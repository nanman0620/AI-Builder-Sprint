from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import get_current_moment
from app.models.check_in import CheckIn
from app.models.enums import (
    AmountSource,
    PlanBlockStatus,
    PlanCycleStatus,
    SolarAction,
    SolarEntityType,
    SolarItemStatus,
    SolarRequestPurpose,
    SolarRequestStatus,
    TaskStatus,
)
from app.models.fixed_schedule import FixedSchedule
from app.models.plan_block import PlanBlock
from app.models.planning_cycle import PlanningCycle
from app.models.solar_request import SolarRequest
from app.models.solar_request_item import SolarRequestItem
from app.models.task import Task
from app.services import plan_block_service
from app.services.new_cycle_execution_service import (
    _acquire_user_transaction_lock,
    _create_fixed_schedule_from_item,
    _create_task_from_item,
)

logger = logging.getLogger(__name__)

# API 명세 8-2절/11절에 정의된, 실제 실행 실패에 쓰는 유일한 code다 — NEW_CYCLE과 동일 원칙으로
# execute/retry 사전 검증의 409 code들과는 다른 계층이며, 원본 실패 사유는 절대 이 문구에
# 담기지 않는다(로그에만 남긴다).
CODE_PLAN_EXECUTION_FAILED = "PLAN_EXECUTION_FAILED"
_SAFE_FAILURE_MESSAGE = "실행 중 문제가 발생했어요. 다시 시도해 주세요."

_ALLOWED_TASK_UPDATE_FIELDS = {"title", "deadlineAt", "estimatedMinutes", "remainingMinutes", "amount"}
_ALLOWED_FIXED_SCHEDULE_UPDATE_FIELDS = {"title", "startAt", "endAt"}


class ActiveCycleExecutionError(Exception):
    """execute_active_cycle이 실제로 실행을 시도했지만 도메인 로직상 실패했을 때만 raise한다.
    Worker adapter(DefaultExecutor)가 그대로 ExecutionDomainError로 변환한다."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _fail_execution(log_message: str, *args: object) -> None:
    """재검증 실패를 서버 로그에만 원인을 남기고 항상 같은 안전한 문구로 실행을 실패시킨다.

    원본 사유(log_message)는 예외 message에 절대 포함하지 않는다 — DB error_message,
    execution_result, API 응답 어디에도 노출되면 안 된다."""
    logger.warning(log_message, *args)
    raise ActiveCycleExecutionError(CODE_PLAN_EXECUTION_FAILED, _SAFE_FAILURE_MESSAGE)


def _has_unfinalized_check_in(db: Session, plan_cycle_id: uuid.UUID) -> bool:
    """요청 cycle에 한정된 미정산 CheckIn 존재 확인.

    UI/화면용 check_in_service.get_finalizing_info(user_id)는 사용자 단위라 이전에 종료된
    다른 cycle의 비정상 잔존 CheckIn 때문에 현재 ACTIVE cycle 실행까지 잘못 막을 수 있으므로
    재사용하지 않는다 — Worker 재검증은 항상 request.plan_cycle_id 하나에만 한정한다."""
    rows = db.execute(
        select(CheckIn).where(CheckIn.plan_cycle_id == plan_cycle_id, CheckIn.finalized_at.is_(None))
    ).scalars().all()
    return len(rows) > 0


def _has_past_checked_plan_block(
    db: Session, plan_cycle_id: uuid.UUID, current_plan_date, current_period
) -> bool:
    """현재 분기보다 과거인데 아직 CHECKED로 남아 있는 비정상 PlanBlock이 있는지 확인한다.

    정상 흐름에서는 정산 Worker가 분기 종료 시 CHECKED를 COMPLETED/NOT_DONE으로 전환하므로
    존재하면 안 되는 상태다 — 존재한다는 것은 정산이 아직 끝나지 않았거나 멈춰 있다는 신호."""
    rows = db.execute(
        select(PlanBlock).where(
            PlanBlock.plan_cycle_id == plan_cycle_id,
            PlanBlock.status == PlanBlockStatus.CHECKED,
            plan_block_service.plan_block_before(
                PlanBlock.plan_date, PlanBlock.period, current_plan_date, current_period
            ),
        )
    ).scalars().all()
    return len(rows) > 0


def _lock_active_cycle(db: Session, request: SolarRequest) -> PlanningCycle | None:
    """request.plan_cycle_id를 FOR UPDATE로 잠그고, 사용자의 현재 ACTIVE cycle과도 같은지
    재확인한다. 못 찾거나 ACTIVE가 아니거나 다른 cycle로 바뀌었으면 None을 반환한다."""
    cycle = db.execute(
        select(PlanningCycle)
        .where(PlanningCycle.id == request.plan_cycle_id, PlanningCycle.user_id == request.user_id)
        .with_for_update()
    ).scalar_one_or_none()
    if cycle is None or cycle.status != PlanCycleStatus.ACTIVE:
        return None

    current_active = plan_block_service.get_active_planning_cycle(db, request.user_id)
    if current_active is None or current_active.id != cycle.id:
        return None
    return cycle


def _load_items(db: Session, solar_request_id: uuid.UUID) -> list[SolarRequestItem]:
    stmt = (
        select(SolarRequestItem)
        .where(SolarRequestItem.solar_request_id == solar_request_id)
        .order_by(SolarRequestItem.item_order)
    )
    return list(db.execute(stmt).scalars().all())


def _validate_items(items: list[SolarRequestItem]) -> None:
    """카드 전체가 실행 가능한 상태인지, 동일 대상을 두 카드가 가리키지 않는지 확인한다.

    하나라도 어긋나면 아무 것도 만들지 않고 즉시 실패시킨다(NEW_CYCLE의
    _load_execution_target_items와 동일 원칙 — 부분 성공 방지). 이 위반은 정상 도메인
    조건이 아니라 데이터 정합성 버그 신호이므로 RuntimeError로 분류해 DefaultExecutor의
    포괄 예외 처리로 넘긴다."""
    target_counts: dict[tuple[SolarEntityType, uuid.UUID], int] = {}
    for item in items:
        if item.status != SolarItemStatus.READY:
            raise RuntimeError(
                f"ACTIVE_CYCLE 카드는 실행 시점에 모두 READY여야 한다 (item_id={item.id}, status={item.status})"
            )
        if item.action == SolarAction.CREATE:
            continue
        target_id = item.target_task_id if item.entity_type == SolarEntityType.TASK else item.target_fixed_schedule_id
        key = (item.entity_type, target_id)
        target_counts[key] = target_counts.get(key, 0) + 1

    duplicated = [key for key, count in target_counts.items() if count > 1]
    if duplicated:
        raise RuntimeError(f"동일 대상을 둘 이상의 카드가 변경하려 한다: {duplicated}")


def _lock_current_period_plan_blocks(
    db: Session, plan_cycle_id: uuid.UUID, current_plan_date, current_period
) -> list[PlanBlock]:
    """현재 분기의 CHECKED+PLANNED 전체를 한 번에 잠근다.

    CheckIn 정산 Worker의 _locked_settleable_blocks(check_in_settlement_service.py)와
    정확히 같은 필터(status IN (CHECKED, PLANNED))·정렬(display_order, id)을 써서, 두 Worker가
    같은 사용자의 같은 현재 분기 행을 동시에 건드릴 때 역순 대기(deadlock)가 생기지 않도록
    맞춘다. 대상 Task로 필터링하지 않는다 — 비대상 Task의 현재 CHECKED도 함께 잠가 보호한다."""
    return list(
        db.execute(
            select(PlanBlock)
            .where(
                PlanBlock.plan_cycle_id == plan_cycle_id,
                PlanBlock.plan_date == current_plan_date,
                PlanBlock.period == current_period,
                PlanBlock.status.in_((PlanBlockStatus.CHECKED, PlanBlockStatus.PLANNED)),
            )
            .order_by(PlanBlock.display_order, PlanBlock.id)
            .with_for_update()
        )
        .scalars()
        .all()
    )


def _lock_future_planned_blocks(
    db: Session, plan_cycle_id: uuid.UUID, current_plan_date, current_period
) -> list[PlanBlock]:
    """현재 분기 다음부터의 PLANNED만 잠근다(현재 분기는 이미 위 함수가 처리했으므로 제외).

    plan_block_service.plan_block_strictly_after()를 그대로 써서 schedule_plan_blocks()의
    삭제 대상 predicate와 같은 출처를 공유한다."""
    return list(
        db.execute(
            select(PlanBlock)
            .where(
                PlanBlock.plan_cycle_id == plan_cycle_id,
                PlanBlock.status == PlanBlockStatus.PLANNED,
                plan_block_service.plan_block_strictly_after(
                    PlanBlock.plan_date, PlanBlock.period, current_plan_date, current_period
                ),
            )
            .order_by(PlanBlock.id)
            .with_for_update()
        )
        .scalars()
        .all()
    )


def _lock_tasks(
    db: Session, user_id: uuid.UUID, plan_cycle_id: uuid.UUID, task_ids: set[uuid.UUID]
) -> dict[uuid.UUID, Task]:
    if not task_ids:
        return {}
    rows = db.execute(
        select(Task)
        .where(Task.id.in_(sorted(task_ids)), Task.user_id == user_id, Task.plan_cycle_id == plan_cycle_id)
        .order_by(Task.id)
        .with_for_update()
    ).scalars().all()
    return {row.id: row for row in rows}


def _lock_fixed_schedules(
    db: Session, user_id: uuid.UUID, plan_cycle_id: uuid.UUID, fixed_schedule_ids: set[uuid.UUID]
) -> dict[uuid.UUID, FixedSchedule]:
    if not fixed_schedule_ids:
        return {}
    rows = db.execute(
        select(FixedSchedule)
        .where(
            FixedSchedule.id.in_(sorted(fixed_schedule_ids)),
            FixedSchedule.user_id == user_id,
            FixedSchedule.plan_cycle_id == plan_cycle_id,
        )
        .order_by(FixedSchedule.id)
        .with_for_update()
    ).scalars().all()
    return {row.id: row for row in rows}


def _completed_minutes(db: Session, task_id: uuid.UUID) -> int:
    """해당 task_id의 COMPLETED PlanBlock allocated_minutes 합계 — 완료 시간의 유일한 근거.

    estimated_minutes - remaining_minutes는 완료 시간으로 쓰지 않는다(remaining이 estimated
    보다 커지는 것이 정상 상태이기 때문). 집계 함수(SQL SUM) 대신 행을 그대로 읽어 Python에서
    더한다 — 이 서비스가 쓰는 select(Model).where(...) 패턴을 그대로 유지해 fake 테스트
    세션과도 호환된다."""
    rows = db.execute(
        select(PlanBlock).where(PlanBlock.task_id == task_id, PlanBlock.status == PlanBlockStatus.COMPLETED)
    ).scalars().all()
    return sum(block.allocated_minutes for block in rows)


def _apply_task_update(
    db: Session, *, item: SolarRequestItem, task: Task, checked_minutes: int
) -> bool:
    """ACTIVE Task 한 건에 UPDATE 카드를 적용한다. 실질적으로 값이 바뀐 경우에만 True를 반환한다."""
    payload = item.normalized_payload
    update_fields = set(payload.get("_updateFields", []))
    unknown = update_fields - _ALLOWED_TASK_UPDATE_FIELDS
    if unknown:
        _fail_execution("알 수 없는 Task update field: %s item_id=%s", unknown, item.id)

    changed_title = False
    changed_deadline = False
    changed_amount = False
    changed_time = False

    if "title" in update_fields:
        new_title = payload["title"]
        if new_title != task.title:
            task.title = new_title
            changed_title = True

    if "deadlineAt" in update_fields:
        new_deadline = datetime.fromisoformat(payload["deadlineAt"]) if payload.get("deadlineAt") else None
        if new_deadline != task.deadline_at:
            task.deadline_at = new_deadline
            changed_deadline = True

    if "amount" in update_fields:
        # Task 전체/현재 남은 전체 분량(tasks.amount_text)만 바꾼다 — plan_blocks에는 절대
        # 복사하지 않는다. 숫자 파싱이나 비례 계산도 하지 않고 문자열을 그대로 치환한다.
        try:
            new_source = AmountSource(payload["amountSource"])
        except (KeyError, ValueError):
            _fail_execution("알 수 없는 amountSource item_id=%s", item.id)
        new_text = payload.get("amountText")
        if new_source == AmountSource.UNKNOWN and new_text:
            _fail_execution("amountSource=UNKNOWN인데 amountText가 있다 item_id=%s", item.id)
        if new_source in (AmountSource.USER, AmountSource.AI_ESTIMATED) and not (new_text or "").strip():
            _fail_execution("amountSource가 %s인데 amountText가 비어 있다 item_id=%s", new_source, item.id)
        resolved_text = new_text if new_source != AmountSource.UNKNOWN else None
        if (resolved_text, new_source) != (task.amount_text, task.amount_source):
            task.amount_text = resolved_text
            task.amount_source = new_source
            changed_amount = True

    if "estimatedMinutes" in update_fields or "remainingMinutes" in update_fields:
        settled = _completed_minutes(db, task.id)
        total_completed = settled + checked_minutes

        if "remainingMinutes" in update_fields:
            new_remaining = payload["remainingMinutes"]
            if new_remaining < 0:
                _fail_execution("remainingMinutes가 음수다 item_id=%s", item.id)
            calculated_estimated = total_completed + new_remaining
            if "estimatedMinutes" in update_fields and payload["estimatedMinutes"] != calculated_estimated:
                _fail_execution(
                    "estimatedMinutes(%s)와 remainingMinutes 기준 계산값(%s)이 다르다 item_id=%s",
                    payload["estimatedMinutes"],
                    calculated_estimated,
                    item.id,
                )
            new_estimated = calculated_estimated
            stored_remaining = new_remaining + checked_minutes
        else:
            new_estimated = payload["estimatedMinutes"]
            if new_estimated < 1:
                _fail_execution("estimatedMinutes가 1보다 작다 item_id=%s", item.id)
            effective_remaining = new_estimated - settled - checked_minutes
            if effective_remaining < 0:
                _fail_execution("effectiveRemainingMinutes가 음수다 item_id=%s", item.id)
            stored_remaining = effective_remaining + checked_minutes

        if stored_remaining <= 0:
            # ACTIVE Task는 status_consistency CHECK상 remaining_minutes > 0이어야 한다.
            # "이 시점에 완료됨"으로 만드는 것은 CheckIn 정산의 책임이므로 여기서는 실행을
            # 실패시킨다(자동으로 COMPLETED 전환하지 않는다).
            _fail_execution("storedRemainingMinutes가 0 이하다 item_id=%s", item.id)

        if (new_estimated, stored_remaining) != (task.estimated_minutes, task.remaining_minutes):
            task.estimated_minutes = new_estimated
            task.remaining_minutes = stored_remaining
            changed_time = True

    changed = changed_title or changed_deadline or changed_amount or changed_time
    if changed_deadline or changed_time:
        task.deadline_warning_acknowledged_at = None
    return changed


def _apply_task_cancel(*, task: Task, now: datetime) -> None:
    task.status = TaskStatus.CANCELLED
    task.cancelled_at = now
    task.completed_at = None


def _validate_new_fixed_schedule_bounds(
    cycle: PlanningCycle, start_at: datetime, end_at: datetime, now: datetime, item_id: uuid.UUID
) -> None:
    if not start_at < end_at:
        _fail_execution("고정 일정 시작 시각이 종료 시각보다 늦거나 같다 item_id=%s", item_id)
    if not start_at > now:
        _fail_execution("고정 일정 시작 시각이 미래가 아니다 item_id=%s", item_id)
    plan_block_service.validate_fixed_schedule_range(cycle, start_at, end_at)


def _apply_fixed_schedule_update(
    *, item: SolarRequestItem, fixed_schedule: FixedSchedule, cycle: PlanningCycle, now: datetime
) -> bool:
    payload = item.normalized_payload
    update_fields = set(payload.get("_updateFields", []))
    unknown = update_fields - _ALLOWED_FIXED_SCHEDULE_UPDATE_FIELDS
    if unknown:
        _fail_execution("알 수 없는 FixedSchedule update field: %s item_id=%s", unknown, item.id)

    new_title = payload["title"] if "title" in update_fields else fixed_schedule.title
    new_start = (
        datetime.fromisoformat(payload["startAt"]) if "startAt" in update_fields else fixed_schedule.start_at
    )
    new_end = datetime.fromisoformat(payload["endAt"]) if "endAt" in update_fields else fixed_schedule.end_at

    if not new_start < new_end:
        _fail_execution("고정 일정 시작 시각이 종료 시각보다 늦거나 같다 item_id=%s", item.id)
    if not new_start > now:
        _fail_execution("수정 결과 고정 일정 시작 시각이 미래가 아니다 item_id=%s", item.id)
    plan_block_service.validate_fixed_schedule_range(cycle, new_start, new_end)

    changed = (new_title, new_start, new_end) != (
        fixed_schedule.title,
        fixed_schedule.start_at,
        fixed_schedule.end_at,
    )
    if changed:
        fixed_schedule.title = new_title
        fixed_schedule.start_at = new_start
        fixed_schedule.end_at = new_end
        fixed_schedule.updated_at = now
    return changed


def _build_execution_result(
    *,
    created_task_count: int,
    updated_task_count: int,
    cancelled_task_count: int,
    created_fixed_schedule_count: int,
    updated_fixed_schedule_count: int,
    deleted_fixed_schedule_count: int,
    deleted_plan_block_count: int,
    created_plan_block_count: int,
) -> dict:
    """API 명세 8-2절 응답 예시(ACTIVE_CYCLE COMPLETED)의 8개 key만 채운다 — NEW_CYCLE의
    _build_execution_result와 정확히 같은 key 집합, 새 key를 추가하지 않는다."""
    return {
        "createdTaskCount": created_task_count,
        "updatedTaskCount": updated_task_count,
        "cancelledTaskCount": cancelled_task_count,
        "createdFixedScheduleCount": created_fixed_schedule_count,
        "updatedFixedScheduleCount": updated_fixed_schedule_count,
        "deletedFixedScheduleCount": deleted_fixed_schedule_count,
        "deletedPlanBlockCount": deleted_plan_block_count,
        "createdPlanBlockCount": created_plan_block_count,
    }


def execute_active_cycle(db: Session, request: SolarRequest) -> None:
    """ACTIVE_CYCLE 하나의 실행 트랜잭션. 호출자(Worker의 _execute_locked)가 이미 연
    `with db.begin():` 블록 안에서 호출되어야 한다 — 여기서는 begin()/commit()을 직접
    호출하지 않는다. 성공 시 request.status까지 COMPLETED로 바꾸고 정상 반환하면 호출자의
    트랜잭션이 커밋된다. 실패하면 ActiveCycleExecutionError 또는 RuntimeError만 raise하고,
    그 예외가 with-block을 빠져나가며 지금까지의 모든 변경이 자동으로 rollback된다."""
    if request.purpose != SolarRequestPurpose.ACTIVE_CYCLE:
        raise ActiveCycleExecutionError(CODE_PLAN_EXECUTION_FAILED, _SAFE_FAILURE_MESSAGE)

    # now는 이 함수 진입 시 정확히 한 번만 계산하고, 이후 어디서도 get_current_moment()를
    # 다시 호출하지 않는다 — 실행 도중 실제 시계가 분기 경계를 넘어도 기준이 흔들리지 않는다.
    now = get_current_moment()
    current_plan_date = plan_block_service.resolve_plan_date(now)
    current_period = plan_block_service.resolve_period(now)

    try:
        _acquire_user_transaction_lock(db, request.user_id)

        cycle = _lock_active_cycle(db, request)
        if cycle is None:
            _fail_execution(
                "ACTIVE cycle을 찾을 수 없거나 요청의 plan_cycle_id와 다르다 request_id=%s plan_cycle_id=%s",
                request.id,
                request.plan_cycle_id,
            )

        if _has_unfinalized_check_in(db, cycle.id):
            _fail_execution("cycle에 미정산 CheckIn이 있다 cycle_id=%s", cycle.id)

        if _has_past_checked_plan_block(db, cycle.id, current_plan_date, current_period):
            _fail_execution("과거 분기에 CHECKED PlanBlock이 남아 있다 cycle_id=%s", cycle.id)

        items = _load_items(db, request.id)
        _validate_items(items)

        current_period_blocks = _lock_current_period_plan_blocks(
            db, cycle.id, current_plan_date, current_period
        )
        checked_minutes_by_task: dict[uuid.UUID, int] = {}
        current_period_planned_ids: set[uuid.UUID] = set()
        for block in current_period_blocks:
            if block.status == PlanBlockStatus.CHECKED:
                checked_minutes_by_task[block.task_id] = (
                    checked_minutes_by_task.get(block.task_id, 0) + block.allocated_minutes
                )
            elif block.status == PlanBlockStatus.PLANNED:
                current_period_planned_ids.add(block.id)

        future_planned_blocks = _lock_future_planned_blocks(db, cycle.id, current_plan_date, current_period)
        future_planned_ids = {block.id for block in future_planned_blocks}

        locked_delete_candidate_ids = current_period_planned_ids | future_planned_ids

        task_ids = {
            item.target_task_id
            for item in items
            if item.entity_type == SolarEntityType.TASK and item.action != SolarAction.CREATE
        }
        fixed_schedule_ids = {
            item.target_fixed_schedule_id
            for item in items
            if item.entity_type == SolarEntityType.FIXED_SCHEDULE and item.action != SolarAction.CREATE
        }

        tasks_by_id = _lock_tasks(db, request.user_id, cycle.id, task_ids)
        fixed_schedules_by_id = _lock_fixed_schedules(db, request.user_id, cycle.id, fixed_schedule_ids)

        # 최신 상태 재검증 — 요청 생성 당시가 아니라 지금 잠근 결과 기준으로 다시 확인한다.
        for task_id in task_ids:
            task = tasks_by_id.get(task_id)
            if task is None or task.status != TaskStatus.ACTIVE:
                _fail_execution("대상 Task가 없거나 ACTIVE가 아니다 task_id=%s", task_id)
        for fixed_schedule_id in fixed_schedule_ids:
            fixed_schedule = fixed_schedules_by_id.get(fixed_schedule_id)
            if fixed_schedule is None:
                _fail_execution("대상 FixedSchedule이 없다 fixed_schedule_id=%s", fixed_schedule_id)
            elif not fixed_schedule.start_at > now:
                _fail_execution(
                    "대상 FixedSchedule이 이미 시작됐거나 종료됐다 fixed_schedule_id=%s", fixed_schedule_id
                )

        created_task_count = 0
        updated_task_count = 0
        cancelled_task_count = 0
        created_fixed_schedule_count = 0
        updated_fixed_schedule_count = 0
        deleted_fixed_schedule_count = 0

        for item in items:
            if item.entity_type == SolarEntityType.TASK:
                if item.action == SolarAction.CREATE:
                    _create_task_from_item(db, item=item, cycle=cycle, user_id=request.user_id, now=now)
                    created_task_count += 1
                elif item.action == SolarAction.UPDATE:
                    task = tasks_by_id[item.target_task_id]
                    if _apply_task_update(
                        db, item=item, task=task, checked_minutes=checked_minutes_by_task.get(task.id, 0)
                    ):
                        updated_task_count += 1
                elif item.action == SolarAction.DELETE:
                    task = tasks_by_id[item.target_task_id]
                    _apply_task_cancel(task=task, now=now)
                    cancelled_task_count += 1
                else:
                    raise RuntimeError(f"지원하지 않는 action이다 item_id={item.id} action={item.action}")
                item.status = SolarItemStatus.EXECUTED
                item.executed_at = now

            elif item.entity_type == SolarEntityType.FIXED_SCHEDULE:
                if item.action == SolarAction.CREATE:
                    payload = item.normalized_payload
                    start_at = datetime.fromisoformat(payload["startAt"])
                    end_at = datetime.fromisoformat(payload["endAt"])
                    _validate_new_fixed_schedule_bounds(cycle, start_at, end_at, now, item.id)
                    _create_fixed_schedule_from_item(db, item=item, cycle=cycle, user_id=request.user_id, now=now)
                    created_fixed_schedule_count += 1
                    item.status = SolarItemStatus.EXECUTED
                    item.executed_at = now
                elif item.action == SolarAction.UPDATE:
                    fixed_schedule = fixed_schedules_by_id[item.target_fixed_schedule_id]
                    if _apply_fixed_schedule_update(item=item, fixed_schedule=fixed_schedule, cycle=cycle, now=now):
                        updated_fixed_schedule_count += 1
                    item.status = SolarItemStatus.EXECUTED
                    item.executed_at = now
                elif item.action == SolarAction.DELETE:
                    fixed_schedule = fixed_schedules_by_id[item.target_fixed_schedule_id]
                    # target_reference_integrity CHECK를 항상 만족시키기 위해 item을 먼저
                    # EXECUTED로 확정(flush)한 뒤에만 실제로 삭제한다.
                    item.status = SolarItemStatus.EXECUTED
                    item.executed_at = now
                    db.flush()
                    db.delete(fixed_schedule)
                    db.flush()
                    deleted_fixed_schedule_count += 1
                else:
                    raise RuntimeError(f"지원하지 않는 action이다 item_id={item.id} action={item.action}")
            else:
                raise RuntimeError(
                    f"ACTIVE_CYCLE Worker가 지원하지 않는 카드 유형이다 (item_id={item.id}, "
                    f"entity_type={item.entity_type})"
                )

        db.flush()

        # PlanBlock 실제 삭제·생성은 schedule_plan_blocks() 한 곳에서만 수행한다 — 이 서비스는
        # 삭제 대상을 잠그기만 했을 뿐 db.delete(PlanBlock)를 직접 호출하지 않는다.
        schedule_result = plan_block_service.schedule_plan_blocks(
            db, user_id=request.user_id, plan_cycle_id=cycle.id, now=now
        )

        if locked_delete_candidate_ids:
            remaining = db.execute(
                select(PlanBlock).where(PlanBlock.id.in_(locked_delete_candidate_ids))
            ).scalars().all()
            if remaining:
                _fail_execution(
                    "삭제 대상으로 잠갔던 PlanBlock이 %d건 그대로 남아 있다", len(remaining)
                )

        unexecuted = [item for item in items if item.status != SolarItemStatus.EXECUTED]
        if unexecuted:
            raise RuntimeError(f"item이 EXECUTED로 전환되지 않았다: {[item.id for item in unexecuted]}")

        request.status = SolarRequestStatus.COMPLETED
        request.executed_at = now
        request.execution_result = _build_execution_result(
            created_task_count=created_task_count,
            updated_task_count=updated_task_count,
            cancelled_task_count=cancelled_task_count,
            created_fixed_schedule_count=created_fixed_schedule_count,
            updated_fixed_schedule_count=updated_fixed_schedule_count,
            deleted_fixed_schedule_count=deleted_fixed_schedule_count,
            deleted_plan_block_count=len(locked_delete_candidate_ids),
            created_plan_block_count=len(schedule_result.created_blocks),
        )
        db.flush()
    except IntegrityError as exc:
        raise ActiveCycleExecutionError(
            CODE_PLAN_EXECUTION_FAILED, _SAFE_FAILURE_MESSAGE
        ) from exc
