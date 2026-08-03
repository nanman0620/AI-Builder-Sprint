import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.models.enums import PlanBlockStatus, PlanPeriod, TaskStatus
from app.models.fixed_schedule import FixedSchedule
from app.models.plan_block import PlanBlock
from app.models.task import Task
from app.services.plan_block_service import (
    _PERIOD_CAPACITY_MINUTES,
    _compute_cycle_end_at,
    _iter_periods_from,
    _period_window,
    _union_minutes,
    get_active_planning_cycle,
    resolve_period,
    resolve_plan_date,
)

CODE_INVALID_TASK_IDS = "INVALID_TASK_IDS"
CODE_TASK_NOT_FOUND = "TASK_NOT_FOUND"


def _get_candidate_tasks(db: Session, user_id: uuid.UUID) -> list[Task]:
    """ix_tasks_active_deadline 부분 인덱스의 WHERE 조건과 동일하게 후보를 조회한다.

    (status='ACTIVE' AND remaining_minutes>0 AND deadline_at IS NOT NULL
     AND deadline_warning_acknowledged_at IS NULL)
    """
    stmt = select(Task).where(
        Task.user_id == user_id,
        Task.status == TaskStatus.ACTIVE,
        Task.remaining_minutes > 0,
        Task.deadline_at.isnot(None),
        Task.deadline_warning_acknowledged_at.is_(None),
    )
    return list(db.execute(stmt).scalars().all())


def _unfinalized_checked_minutes(
    db: Session, *, task_id: uuid.UUID, plan_date: date, period: PlanPeriod
) -> int:
    """현재 분기의 아직 정산되지 않은(check_in_id IS NULL) CHECKED PlanBlock 시간 합.

    plan_blocks의 status_consistency CHECK가 CHECKED는 항상 check_in_id IS NULL임을
    이미 보장하지만, 의도를 명확히 하기 위해 조건을 그대로 명시한다.
    """
    stmt = select(PlanBlock).where(
        PlanBlock.task_id == task_id,
        PlanBlock.plan_date == plan_date,
        PlanBlock.period == period,
        PlanBlock.status == PlanBlockStatus.CHECKED,
        PlanBlock.check_in_id.is_(None),
    )
    blocks = db.execute(stmt).scalars().all()
    return sum(block.allocated_minutes for block in blocks)


def _compute_available_minutes(
    db: Session,
    *,
    user_id: uuid.UUID,
    plan_cycle_id: uuid.UUID,
    task_id: uuid.UUID,
    now: datetime,
    planning_deadline_at: datetime,
    current_plan_date: date,
    current_period: PlanPeriod,
) -> int:
    """now부터 planning_deadline_at까지 분기별 가용 시간을 합산한다.

    각 분기: windowMinutes(최대 240분, compute_period_capacity와 동일한 분 환산 규칙)
    - 고정 일정 합집합 점유 시간 - 다른 Task에 이미 배정된 PLANNED/CHECKED PlanBlock 시간.
    대상 Task 자신의 PlanBlock은 절대 차감하지 않는다(task_id != 대상 Task로 제외).
    """
    if planning_deadline_at <= now:
        return 0

    end_date = resolve_plan_date(planning_deadline_at)
    total_available = 0

    for plan_date, period in _iter_periods_from(current_plan_date, current_period, end_date):
        period_start, period_end = _period_window(plan_date, period)
        if period_start >= planning_deadline_at:
            break

        window_start = max(now, period_start)
        window_end = min(period_end, planning_deadline_at)
        if window_end <= window_start:
            continue

        window_minutes = min(
            _PERIOD_CAPACITY_MINUTES, int((window_end - window_start).total_seconds() // 60)
        )

        fixed_schedules = (
            db.execute(
                select(FixedSchedule).where(
                    FixedSchedule.user_id == user_id,
                    FixedSchedule.start_at < window_end,
                    FixedSchedule.end_at > window_start,
                )
            )
            .scalars()
            .all()
        )
        fixed_minutes = _union_minutes(
            [(fs.start_at, fs.end_at) for fs in fixed_schedules], window_start, window_end
        )

        other_blocks = (
            db.execute(
                select(PlanBlock).where(
                    PlanBlock.plan_cycle_id == plan_cycle_id,
                    PlanBlock.plan_date == plan_date,
                    PlanBlock.period == period,
                    PlanBlock.task_id != task_id,
                    PlanBlock.status.in_((PlanBlockStatus.PLANNED, PlanBlockStatus.CHECKED)),
                )
            )
            .scalars()
            .all()
        )
        other_minutes = sum(block.allocated_minutes for block in other_blocks)

        total_available += max(0, window_minutes - fixed_minutes - other_minutes)

    return total_available


@dataclass(frozen=True)
class DeadlineWarningItem:
    task_id: uuid.UUID
    title: str
    deadline_at: datetime
    required_minutes: int
    available_minutes: int
    shortage_minutes: int
    created_at: datetime


@dataclass(frozen=True)
class DeadlineWarningNotice:
    items: list[DeadlineWarningItem]


def compute_deadline_warnings(
    db: Session, user_id: uuid.UUID, *, now: datetime
) -> DeadlineWarningNotice | None:
    """마감 임박 경고 blockingNotice.items를 계산한다(DB 명세 18절).

    완전한 조회 전용이며 DB에 어떤 쓰기도 하지 않는다. 활성 cycle이 없거나 경고 대상이
    없으면 None을 반환한다. GET /home/current·bootstrap 연동은 이 함수의 책임이 아니며
    이번 Issue 범위에서는 어떤 라우터도 이 결과를 노출하지 않는다(BE-11에서 연결 예정).
    """
    cycle = get_active_planning_cycle(db, user_id)
    if cycle is None:
        return None

    candidates = _get_candidate_tasks(db, user_id)
    if not candidates:
        return None

    cycle_end_at = _compute_cycle_end_at(cycle)
    current_plan_date = resolve_plan_date(now)
    current_period = resolve_period(now)

    items: list[DeadlineWarningItem] = []
    for task in candidates:
        unfinalized_checked = _unfinalized_checked_minutes(
            db, task_id=task.id, plan_date=current_plan_date, period=current_period
        )
        required_minutes = max(0, task.remaining_minutes - unfinalized_checked)
        if required_minutes <= 0:
            continue

        # 후보 조회 조건상 deadline_at은 항상 nonnull이다.
        planning_deadline_at = min(task.deadline_at, cycle_end_at)
        available_minutes = _compute_available_minutes(
            db,
            user_id=user_id,
            plan_cycle_id=cycle.id,
            task_id=task.id,
            now=now,
            planning_deadline_at=planning_deadline_at,
            current_plan_date=current_plan_date,
            current_period=current_period,
        )
        if required_minutes <= available_minutes:
            continue

        items.append(
            DeadlineWarningItem(
                task_id=task.id,
                title=task.title,
                deadline_at=task.deadline_at,
                required_minutes=required_minutes,
                available_minutes=available_minutes,
                shortage_minutes=required_minutes - available_minutes,
                created_at=task.created_at,
            )
        )

    if not items:
        return None

    items.sort(
        key=lambda item: (item.deadline_at, -item.shortage_minutes, item.created_at, item.task_id)
    )
    return DeadlineWarningNotice(items=items)


@dataclass(frozen=True)
class AcknowledgeResult:
    acknowledged_task_ids: list[uuid.UUID]
    acknowledged_at: datetime


def acknowledge_deadline_warnings(
    db: Session, *, user_id: uuid.UUID, task_ids: Sequence[uuid.UUID], now: datetime
) -> AcknowledgeResult:
    """taskIds 전체의 존재·소유권을 먼저 검증한 뒤 한 트랜잭션에서 동일한 now로 갱신한다.

    dedup은 최초 요청 순서를 유지한다. 존재하지 않거나 타인 소유인 ID가 하나라도 있으면
    (조회된 행 수가 dedup 개수와 다르면) 어떤 Task도 갱신하지 않고 with db.begin()에 의해
    전체 rollback된다. 이미 확인된 Task가 섞여 있어도 오류 없이 동일한 now로 덮어쓴다.
    """
    deduped_ids = list(dict.fromkeys(task_ids))
    if not deduped_ids:
        raise ApiError(422, CODE_INVALID_TASK_IDS, "확인할 Task를 선택해 주세요.")

    with db.begin():
        tasks = (
            db.execute(
                select(Task)
                .where(Task.id.in_(deduped_ids), Task.user_id == user_id)
                .with_for_update()
            )
            .scalars()
            .all()
        )
        if len(tasks) != len(deduped_ids):
            raise ApiError(404, CODE_TASK_NOT_FOUND, "Task를 찾을 수 없어요.")

        for task in tasks:
            task.deadline_warning_acknowledged_at = now
        db.flush()

    return AcknowledgeResult(acknowledged_task_ids=deduped_ids, acknowledged_at=now)
