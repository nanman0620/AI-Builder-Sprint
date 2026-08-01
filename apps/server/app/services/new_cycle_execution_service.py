from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import get_current_moment
from app.models.enums import (
    AmountSource,
    EstimateSource,
    PlanCycleStatus,
    SolarAction,
    SolarEntityType,
    SolarItemStatus,
    SolarRequestPurpose,
    SolarRequestStatus,
    TaskStatus,
)
from app.models.fixed_schedule import FixedSchedule
from app.models.planning_cycle import PlanningCycle
from app.models.solar_request import SolarRequest
from app.models.solar_request_item import SolarRequestItem
from app.models.task import Task
from app.services import plan_block_service

# API 명세 8-2절/11절에 정의된, 실제 실행 실패에 쓰는 유일한 code다. execute/retry 사전 검증의
# 409 ACTIVE_CYCLE_EXISTS와는 다른 계층(실행 도중 발견된 실패는 항상 이 code로 DB에 남는다).
CODE_PLAN_EXECUTION_FAILED = "PLAN_EXECUTION_FAILED"


class NewCycleExecutionError(Exception):
    """execute_new_cycle이 실제로 실행을 시도했지만 도메인 로직상 실패했을 때만 raise한다.
    Worker adapter(DefaultExecutor)가 그대로 ExecutionDomainError로 변환한다."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def advisory_lock_key_for_user(user_id: uuid.UUID) -> int:
    """check_in_settlement_service.advisory_lock_key/solar_execution_worker.advisory_lock_key와
    동일한 SHA-256 방식으로 안정적인 signed bigint lock key를 만든다(다른 namespace).

    requestId 기준 advisory lock은 같은 request의 중복 실행만 막을 뿐, 서로 다른 NEW_CYCLE
    요청 두 개가 같은 사용자의 ACTIVE cycle을 동시에 만드는 경쟁은 막지 못한다. 이 키로
    트랜잭션 범위 advisory lock(pg_advisory_xact_lock)을 잡아 그 경쟁을 직렬화한다.
    """
    identity = f"new-cycle-execution:user:{user_id}".encode()
    return int.from_bytes(hashlib.sha256(identity).digest()[:8], "big", signed=True)


def _acquire_user_transaction_lock(db: Session, user_id: uuid.UUID) -> None:
    db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": advisory_lock_key_for_user(user_id)},
    )


def _load_execution_target_items(db: Session, solar_request_id: uuid.UUID) -> list[SolarRequestItem]:
    """요청의 카드 전체를 item_order 순서로 로드하고, 하나라도 실행 가능한 상태가 아니면 아무
    것도 만들지 않고 즉시 실패한다.

    FINAL_REVIEW에 도달한 NEW_CYCLE 요청은 정상적으로는 카드가 전부 READY·action=CREATE지만,
    이 불변식을 "READY만 골라 나머지는 조용히 건너뛰는" 방식으로 확인하면 일부 카드만 Task·
    고정 일정으로 만들고 나머지는 방치한 채 요청을 COMPLETED로 만드는 부분 성공 경로가 생긴다.
    그래서 생성을 시작하기 전에 전체 카드를 검사해 하나라도 어긋나면 RuntimeError로 실패시킨다
    (버그·데이터 손상 신호이지 재시도로 해결되는 도메인 조건이 아니다 — Worker는 이 예외를
    포함해 실행 트랜잭션 안에서 발생한 모든 예외를 rollback 후 FAILED로 기록한다)."""
    stmt = (
        select(SolarRequestItem)
        .where(SolarRequestItem.solar_request_id == solar_request_id)
        .order_by(SolarRequestItem.item_order)
    )
    items = list(db.execute(stmt).scalars().all())
    for item in items:
        if item.status != SolarItemStatus.READY:
            raise RuntimeError(
                f"NEW_CYCLE 카드는 실행 시점에 모두 READY여야 한다 (item_id={item.id}, status={item.status})"
            )
        if item.action != SolarAction.CREATE:
            raise RuntimeError(
                f"NEW_CYCLE 카드는 항상 action=CREATE여야 한다 (item_id={item.id}, action={item.action})"
            )
    return items


def _create_planning_cycle(db: Session, *, user_id: uuid.UUID, now: datetime) -> PlanningCycle:
    """DB 명세 5절: start_date = resolvePlanDate(activated_at), end_date = start_date + 6."""
    start_date = plan_block_service.resolve_plan_date(now)
    cycle = PlanningCycle(
        id=uuid.uuid4(),
        user_id=user_id,
        start_date=start_date,
        end_date=start_date + timedelta(days=6),
        status=PlanCycleStatus.ACTIVE,
        activated_at=now,
        ended_at=None,
    )
    db.add(cycle)
    db.flush()
    return cycle


def _create_task_from_item(
    db: Session, *, item: SolarRequestItem, cycle: PlanningCycle, user_id: uuid.UUID, now: datetime
) -> Task:
    """DB 명세 9절: 최초 생성 시 initial_minutes = estimated_minutes = remaining_minutes. 카드의
    remainingMinutes는 신뢰하지 않고(항상 estimatedMinutes와 같아야 하는 CREATE 불변식이지만),
    estimated_minutes 하나의 값에서 세 컬럼을 모두 계산해 값이 서로 어긋날 여지를 없앤다."""
    payload = item.normalized_payload
    deadline_at = datetime.fromisoformat(payload["deadlineAt"]) if payload.get("deadlineAt") else None
    estimated_minutes = int(payload["estimatedMinutes"])
    amount_source_raw = payload.get("amountSource")
    amount_source = AmountSource(amount_source_raw) if amount_source_raw else AmountSource.UNKNOWN

    task = Task(
        id=uuid.uuid4(),
        user_id=user_id,
        plan_cycle_id=cycle.id,
        source_request_item_id=item.id,
        title=payload["title"],
        deadline_at=deadline_at,
        amount_text=payload.get("amountText") if amount_source != AmountSource.UNKNOWN else None,
        amount_source=amount_source,
        initial_minutes=estimated_minutes,
        estimated_minutes=estimated_minutes,
        estimated_minutes_source=EstimateSource(payload["estimatedMinutesSource"]),
        remaining_minutes=estimated_minutes,
        status=TaskStatus.ACTIVE,
        deadline_warning_acknowledged_at=None,
        completed_at=None,
        cancelled_at=None,
        created_at=now,
        updated_at=now,
    )
    db.add(task)
    return task


def _create_fixed_schedule_from_item(
    db: Session, *, item: SolarRequestItem, cycle: PlanningCycle, user_id: uuid.UUID, now: datetime
) -> FixedSchedule:
    payload = item.normalized_payload
    fixed_schedule = FixedSchedule(
        id=uuid.uuid4(),
        user_id=user_id,
        plan_cycle_id=cycle.id,
        source_request_item_id=item.id,
        title=payload["title"],
        start_at=datetime.fromisoformat(payload["startAt"]),
        end_at=datetime.fromisoformat(payload["endAt"]),
        created_at=now,
        updated_at=now,
    )
    db.add(fixed_schedule)
    return fixed_schedule


def _build_execution_result(*, created_task_count: int, created_fixed_schedule_count: int) -> dict:
    """API 명세 8-2절 응답 예시(NEW_CYCLE COMPLETED)의 exact 8개 key만 채운다 —
    updated/cancelled/deleted 계열은 ACTIVE_CYCLE 실행 전용이라 NEW_CYCLE에서는 항상 0이다.
    taskCount/fixedScheduleCount는 "실행 후 cycle의 현재 총 개수"라 새 cycle에서는 created와
    같다. GET /solar/requests/{id}/execution의 `execution_result: dict | None` 응답 스키마는
    필드를 필터링하지 않고 이 dict를 그대로 직렬화하므로, 명세에 없는 key(cycle id, PlanBlock
    배치 통계 등)를 추가하면 그대로 응답 계약을 벗어난다 — 이번 Issue에서 API 명세·Pydantic
    schema·프론트 타입을 함께 확장하기로 합의된 근거가 없어 8개 key만 유지한다."""
    return {
        "createdTaskCount": created_task_count,
        "updatedTaskCount": 0,
        "cancelledTaskCount": 0,
        "createdFixedScheduleCount": created_fixed_schedule_count,
        "updatedFixedScheduleCount": 0,
        "deletedFixedScheduleCount": 0,
        "taskCount": created_task_count,
        "fixedScheduleCount": created_fixed_schedule_count,
    }


def execute_new_cycle(db: Session, request: SolarRequest) -> None:
    """NEW_CYCLE 하나의 실행 트랜잭션(IMPLEMENTATION_CONTEXT.md 10절). 호출자(Worker의
    _execute_locked)가 이미 연 `with db.begin():` 블록 안에서 호출되어야 한다 — 여기서는
    begin()/commit()을 직접 호출하지 않는다. 성공 시 request.status까지 COMPLETED로 바꾸고
    정상 반환하면 호출자의 트랜잭션이 커밋된다. 실패하면 NewCycleExecutionError만 raise하고,
    그 예외가 with-block을 빠져나가며 지금까지의 모든 변경(cycle/Task/고정 일정/PlanBlock/카드
    상태)이 자동으로 rollback된다.
    """
    if request.purpose != SolarRequestPurpose.NEW_CYCLE:
        raise NewCycleExecutionError(CODE_PLAN_EXECUTION_FAILED, "실행할 수 없는 요청이에요.")

    now = get_current_moment()

    # 서로 다른 NEW_CYCLE 요청 두 개가 같은 사용자에 대해 동시에 EXECUTING에 들어와도, 실제
    # cycle 생성은 이 트랜잭션 범위 lock으로 직렬화된다 — 뒤에 도착한 쪽만 lock 획득 후
    # 재확인에서 도메인 실패로 안전하게 끝난다(uq_planning_cycles_one_active_per_user UNIQUE
    # 위반까지 가지 않는다). 그럼에도 남는 잔여 경쟁(예: lock 획득 방식 변경 등으로 생기는 미래의
    # 회귀)은 아래 IntegrityError 처리로 한 번 더 방어한다 — create_solar_request의 UNIQUE 충돌
    # 처리와 같은 원칙으로 예상 가능한 제약 위반을 도메인 실패로 분류한다. 그 외 이 try 블록
    # 안에서 발생하는 모든 예외(IntegrityError로 분류되지 않는 것 포함)는 이미 열려 있는
    # `with db.begin()` 밖으로 그대로 전파되어 rollback을 보장하며, Worker(DefaultExecutor)가
    # 그 rollback 이후 별도 트랜잭션에서 FAILED로 기록한다 — 여기서 EXECUTING 유지를 노리고
    # 예외를 삼키지 않는다.
    try:
        _acquire_user_transaction_lock(db, request.user_id)

        if plan_block_service.get_active_planning_cycle(db, request.user_id) is not None:
            raise NewCycleExecutionError(CODE_PLAN_EXECUTION_FAILED, "이미 진행 중인 계획 기간이 있어요.")

        # 일부 카드만 생성하고 요청을 COMPLETED로 만드는 부분 성공을 막기 위해, 생성을
        # 시작하기 전에 카드 전체가 실행 가능한 상태인지 먼저 검증한다.
        items = _load_execution_target_items(db, request.id)

        cycle = _create_planning_cycle(db, user_id=request.user_id, now=now)

        created_task_count = 0
        created_fixed_schedule_count = 0
        for item in items:
            if item.entity_type == SolarEntityType.TASK:
                _create_task_from_item(db, item=item, cycle=cycle, user_id=request.user_id, now=now)
                created_task_count += 1
            elif item.entity_type == SolarEntityType.FIXED_SCHEDULE:
                _create_fixed_schedule_from_item(db, item=item, cycle=cycle, user_id=request.user_id, now=now)
                created_fixed_schedule_count += 1
            else:
                # 현재 SolarEntityType은 TASK/FIXED_SCHEDULE 둘뿐이라 정상적으로는 도달할 수
                # 없다. 향후 enum이 늘어나도 이 Worker가 지원하지 않는 카드 유형을 조용히
                # 무시하고 요청을 COMPLETED로 만들지 않도록 명시적으로 실패시킨다.
                raise RuntimeError(
                    f"NEW_CYCLE Worker가 지원하지 않는 카드 유형이다 (item_id={item.id}, entity_type={item.entity_type})"
                )

            item.status = SolarItemStatus.EXECUTED
            item.executed_at = now

        db.flush()

        # schedule_plan_blocks의 반환값(생성된 PlanBlock, 미배치 시간)은 API 명세 8-2절
        # execution_result 8개 key에 없다 — 미배치 시간이 있어도 실행 자체는 실패시키지 않되,
        # 계약 외 필드로 응답에 노출하지 않는다.
        plan_block_service.schedule_plan_blocks(db, user_id=request.user_id, plan_cycle_id=cycle.id, now=now)

        request.status = SolarRequestStatus.COMPLETED
        request.executed_at = now
        request.execution_result = _build_execution_result(
            created_task_count=created_task_count,
            created_fixed_schedule_count=created_fixed_schedule_count,
        )
        db.flush()
    except IntegrityError as exc:
        raise NewCycleExecutionError(
            CODE_PLAN_EXECUTION_FAILED, "실행 중 저장 오류가 발생했어요. 다시 시도해 주세요."
        ) from exc
