from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.check_in import CheckIn
from app.models.enums import PlanBlockStatus, PlanCycleStatus, PlanPeriod, TaskStatus
from app.models.plan_block import PlanBlock
from app.models.planning_cycle import PlanningCycle
from app.models.task import Task
from app.services import plan_block_service

logger = logging.getLogger(__name__)

_SEOUL_TZ = ZoneInfo("Asia/Seoul")
_PERIODS = (PlanPeriod.MORNING, PlanPeriod.AFTERNOON, PlanPeriod.EVENING)
_SETTLEABLE_BLOCK_STATUSES = (PlanBlockStatus.PLANNED, PlanBlockStatus.CHECKED)


@dataclass(frozen=True)
class SettlementTarget:
    plan_cycle_id: uuid.UUID
    user_id: uuid.UUID
    plan_date: date
    period: PlanPeriod


class SettlementAction(str, Enum):
    FINALIZED = "FINALIZED"
    ALREADY_FINALIZED = "ALREADY_FINALIZED"
    NO_BLOCKS = "NO_BLOCKS"
    CYCLE_ENDED_WITHOUT_CHECK_IN = "CYCLE_ENDED_WITHOUT_CHECK_IN"
    CYCLE_NOT_SETTLEABLE = "CYCLE_NOT_SETTLEABLE"


@dataclass(frozen=True)
class SettlementResult:
    target: SettlementTarget
    action: SettlementAction
    check_in_id: uuid.UUID | None = None


def period_end_at(plan_date: date, period: PlanPeriod) -> datetime:
    """논리 날짜·분기의 종료 시각을 Asia/Seoul aware datetime으로 반환한다."""
    if period == PlanPeriod.MORNING:
        return datetime.combine(plan_date, time(12, 0), tzinfo=_SEOUL_TZ)
    if period == PlanPeriod.AFTERNOON:
        return datetime.combine(plan_date, time(18, 0), tzinfo=_SEOUL_TZ)
    next_day = plan_date + timedelta(days=1)
    return datetime.combine(next_day, time(4, 0), tzinfo=_SEOUL_TZ)


def is_period_closed(plan_date: date, period: PlanPeriod, *, now: datetime) -> bool:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now는 timezone-aware datetime이어야 한다.")
    return now.astimezone(_SEOUL_TZ) >= period_end_at(plan_date, period)


def latest_closed_period(now: datetime) -> tuple[date, PlanPeriod]:
    """현재 시각까지 종료된 가장 최근 논리 날짜·분기를 반환한다."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now는 timezone-aware datetime이어야 한다.")
    local = now.astimezone(_SEOUL_TZ)
    if local.hour < 4:
        return local.date() - timedelta(days=1), PlanPeriod.AFTERNOON
    if local.hour < 12:
        return local.date() - timedelta(days=1), PlanPeriod.EVENING
    if local.hour < 18:
        return local.date(), PlanPeriod.MORNING
    return local.date(), PlanPeriod.AFTERNOON


def advisory_lock_key(target: SettlementTarget) -> int:
    """프로세스별 hash() 대신 SHA-256으로 안정적인 signed bigint lock key를 만든다."""
    identity = (
        f"check-in-settlement:{target.plan_cycle_id}:{target.plan_date.isoformat()}:"
        f"{target.period.value}"
    ).encode()
    return int.from_bytes(hashlib.sha256(identity).digest()[:8], "big", signed=True)


def _acquire_period_transaction_lock(db: Session, target: SettlementTarget) -> None:
    db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": advisory_lock_key(target)},
    )


def _locked_cycle(db: Session, target: SettlementTarget) -> PlanningCycle | None:
    return db.execute(
        select(PlanningCycle)
        .where(
            PlanningCycle.id == target.plan_cycle_id,
            PlanningCycle.user_id == target.user_id,
        )
        .with_for_update()
    ).scalar_one_or_none()


def _locked_check_in(db: Session, target: SettlementTarget) -> CheckIn | None:
    return db.execute(
        select(CheckIn)
        .where(
            CheckIn.plan_cycle_id == target.plan_cycle_id,
            CheckIn.user_id == target.user_id,
            CheckIn.check_date == target.plan_date,
            CheckIn.period == target.period,
        )
        .with_for_update()
    ).scalar_one_or_none()


def _locked_settleable_blocks(db: Session, target: SettlementTarget) -> list[PlanBlock]:
    return list(
        db.execute(
            select(PlanBlock)
            .where(
                PlanBlock.plan_cycle_id == target.plan_cycle_id,
                PlanBlock.user_id == target.user_id,
                PlanBlock.plan_date == target.plan_date,
                PlanBlock.period == target.period,
                PlanBlock.status.in_(_SETTLEABLE_BLOCK_STATUSES),
            )
            .order_by(PlanBlock.display_order, PlanBlock.id)
            .with_for_update()
        )
        .scalars()
        .all()
    )


def _is_last_evening(cycle: PlanningCycle, target: SettlementTarget) -> bool:
    return target.plan_date == cycle.end_date and target.period == PlanPeriod.EVENING


def _end_cycle_without_check_in(
    db: Session, cycle: PlanningCycle, target: SettlementTarget
) -> SettlementResult:
    cycle_end_at = period_end_at(target.plan_date, target.period)
    active_tasks = list(
        db.execute(
            select(Task)
            .where(
                Task.plan_cycle_id == cycle.id,
                Task.user_id == target.user_id,
                Task.status == TaskStatus.ACTIVE,
                Task.remaining_minutes > 0,
            )
            .with_for_update()
        )
        .scalars()
        .all()
    )
    for task in active_tasks:
        task.status = TaskStatus.CANCELLED
        task.cancelled_at = cycle_end_at
        task.completed_at = None

    if cycle.status == PlanCycleStatus.ACTIVE:
        cycle.status = PlanCycleStatus.ENDED
        cycle.ended_at = cycle_end_at
    db.flush()
    logger.info(
        "check-in cycle ended without blocks cycle_id=%s plan_date=%s period=%s",
        target.plan_cycle_id,
        target.plan_date,
        target.period.value,
    )
    return SettlementResult(target, SettlementAction.CYCLE_ENDED_WITHOUT_CHECK_IN)


def _start_or_resume_settlement(
    db: Session, target: SettlementTarget, *, now: datetime
) -> SettlementResult | uuid.UUID:
    """첫 트랜잭션에서 CheckIn 생성만 확정하거나 기존 미완료 행을 선택한다."""
    with db.begin():
        _acquire_period_transaction_lock(db, target)
        cycle = _locked_cycle(db, target)
        if cycle is None or not (cycle.start_date <= target.plan_date <= cycle.end_date):
            return SettlementResult(target, SettlementAction.CYCLE_NOT_SETTLEABLE)

        check_in = _locked_check_in(db, target)
        if check_in is not None:
            if check_in.finalized_at is not None:
                logger.info(
                    "check-in settlement skipped finalized check_in_id=%s", check_in.id
                )
                return SettlementResult(
                    target, SettlementAction.ALREADY_FINALIZED, check_in.id
                )
            logger.info("check-in settlement recovery check_in_id=%s", check_in.id)
            return check_in.id

        if cycle.status != PlanCycleStatus.ACTIVE:
            return SettlementResult(target, SettlementAction.CYCLE_NOT_SETTLEABLE)

        blocks = _locked_settleable_blocks(db, target)
        if not blocks:
            if _is_last_evening(cycle, target):
                return _end_cycle_without_check_in(db, cycle, target)
            return SettlementResult(target, SettlementAction.NO_BLOCKS)

        check_in = CheckIn(
            id=uuid.uuid4(),
            user_id=target.user_id,
            plan_cycle_id=target.plan_cycle_id,
            check_date=target.plan_date,
            period=target.period,
            finalization_started_at=now,
        )
        db.add(check_in)
        db.flush()
        logger.info(
            "check-in finalizing started check_in_id=%s cycle_id=%s plan_date=%s period=%s",
            check_in.id,
            target.plan_cycle_id,
            target.plan_date,
            target.period.value,
        )
        return check_in.id


def _settle_tasks(
    db: Session,
    *,
    target: SettlementTarget,
    completed_minutes_by_task: dict[uuid.UUID, int],
    logical_end_at: datetime,
) -> None:
    if not completed_minutes_by_task:
        return

    tasks = list(
        db.execute(
            select(Task)
            .where(
                Task.id.in_(tuple(completed_minutes_by_task)),
                Task.plan_cycle_id == target.plan_cycle_id,
                Task.user_id == target.user_id,
            )
            .with_for_update()
        )
        .scalars()
        .all()
    )
    for task in tasks:
        if task.status == TaskStatus.COMPLETED:
            continue
        remaining = max(0, task.remaining_minutes - completed_minutes_by_task[task.id])
        task.remaining_minutes = remaining
        if task.status == TaskStatus.ACTIVE and remaining == 0:
            task.status = TaskStatus.COMPLETED
            task.completed_at = logical_end_at
            task.cancelled_at = None
        elif task.status == TaskStatus.ACTIVE:
            task.completed_at = None
            task.cancelled_at = None
        # CANCELLED Task는 남은 시간만 반영하고 상태·기존 cancelled_at을 유지한다.


def _cancel_remaining_tasks_and_end_cycle(
    db: Session,
    *,
    cycle: PlanningCycle,
    target: SettlementTarget,
    logical_end_at: datetime,
) -> None:
    active_tasks = list(
        db.execute(
            select(Task)
            .where(
                Task.plan_cycle_id == target.plan_cycle_id,
                Task.user_id == target.user_id,
                Task.status == TaskStatus.ACTIVE,
                Task.remaining_minutes > 0,
            )
            .with_for_update()
        )
        .scalars()
        .all()
    )
    for task in active_tasks:
        task.status = TaskStatus.CANCELLED
        task.cancelled_at = logical_end_at
        task.completed_at = None
    if cycle.status == PlanCycleStatus.ACTIVE:
        cycle.status = PlanCycleStatus.ENDED
        cycle.ended_at = logical_end_at


def _finalize_settlement(
    db: Session,
    target: SettlementTarget,
    check_in_id: uuid.UUID,
    *,
    now: datetime,
) -> SettlementResult:
    """두 번째 트랜잭션에서 실제 정산·재계획·최종화를 원자적으로 처리한다."""
    with db.begin():
        _acquire_period_transaction_lock(db, target)
        cycle = _locked_cycle(db, target)
        check_in = _locked_check_in(db, target)
        if cycle is None or check_in is None or check_in.id != check_in_id:
            raise RuntimeError("정산 대상 cycle 또는 CheckIn을 찾을 수 없다.")
        if check_in.finalized_at is not None:
            return SettlementResult(
                target, SettlementAction.ALREADY_FINALIZED, check_in.id
            )

        blocks = _locked_settleable_blocks(db, target)
        if not blocks:
            raise RuntimeError("미완료 CheckIn에 정산 가능한 PlanBlock이 없다.")

        logical_end_at = period_end_at(target.plan_date, target.period)
        completed_minutes_by_task: dict[uuid.UUID, int] = {}
        completed_count = 0
        for block in blocks:
            if block.status == PlanBlockStatus.CHECKED:
                block.status = PlanBlockStatus.COMPLETED
                completed_count += 1
                completed_minutes_by_task[block.task_id] = (
                    completed_minutes_by_task.get(block.task_id, 0)
                    + block.allocated_minutes
                )
            else:
                block.status = PlanBlockStatus.NOT_DONE
            block.check_in_id = check_in.id

        _settle_tasks(
            db,
            target=target,
            completed_minutes_by_task=completed_minutes_by_task,
            logical_end_at=logical_end_at,
        )
        db.flush()

        total_count = len(blocks)
        check_in.total_plan_count = total_count
        check_in.completed_plan_count = completed_count
        check_in.score = plan_block_service.calculate_plan_percentage(
            completed_count, total_count
        )

        if _is_last_evening(cycle, target):
            _cancel_remaining_tasks_and_end_cycle(
                db,
                cycle=cycle,
                target=target,
                logical_end_at=logical_end_at,
            )
            check_in.replan_unplaced_minutes = 0
            logger.info("check-in last cycle ended cycle_id=%s", cycle.id)
        else:
            schedule_result = plan_block_service.schedule_plan_blocks(
                db,
                user_id=target.user_id,
                plan_cycle_id=target.plan_cycle_id,
                now=logical_end_at,
            )
            check_in.replan_unplaced_minutes = schedule_result.total_unplaced_minutes
            check_in.replanned_at = now

        check_in.finalized_at = now
        db.flush()

    logger.info(
        "check-in settlement completed check_in_id=%s cycle_id=%s plan_date=%s period=%s",
        check_in_id,
        target.plan_cycle_id,
        target.plan_date,
        target.period.value,
    )
    return SettlementResult(target, SettlementAction.FINALIZED, check_in_id)


def settle_period(
    db: Session, target: SettlementTarget, *, now: datetime
) -> SettlementResult:
    """CheckIn 생성 커밋과 실제 정산 커밋을 분리해 한 분기를 멱등 정산한다."""
    logger.info(
        "check-in settlement started cycle_id=%s plan_date=%s period=%s",
        target.plan_cycle_id,
        target.plan_date,
        target.period.value,
    )
    started = _start_or_resume_settlement(db, target, now=now)
    if isinstance(started, SettlementResult):
        return started
    return _finalize_settlement(db, target, started, now=now)


def find_recovery_targets(db: Session, *, now: datetime) -> list[SettlementTarget]:
    """미완료 CheckIn과 종료 시각이 지난 CheckIn 없는 분기를 오래된 순으로 찾는다."""
    incomplete = list(
        db.execute(
            select(CheckIn)
            .where(CheckIn.finalized_at.is_(None))
            .order_by(CheckIn.finalization_started_at, CheckIn.id)
        )
        .scalars()
        .all()
    )
    targets: dict[tuple[uuid.UUID, date, PlanPeriod], SettlementTarget] = {
        (row.plan_cycle_id, row.check_date, row.period): SettlementTarget(
            row.plan_cycle_id, row.user_id, row.check_date, row.period
        )
        for row in incomplete
    }

    latest_closed_date, _ = latest_closed_period(now)
    active_cycles = list(
        db.execute(
            select(PlanningCycle)
            .where(
                PlanningCycle.status == PlanCycleStatus.ACTIVE,
                PlanningCycle.start_date <= latest_closed_date,
            )
            .order_by(PlanningCycle.start_date, PlanningCycle.id)
        )
        .scalars()
        .all()
    )
    if active_cycles:
        cycle_ids = tuple(cycle.id for cycle in active_cycles)
        existing_check_ins = list(
            db.execute(
                select(CheckIn).where(
                    CheckIn.plan_cycle_id.in_(cycle_ids),
                    CheckIn.check_date <= latest_closed_date,
                )
            )
            .scalars()
            .all()
        )
        existing_keys = {
            (row.plan_cycle_id, row.check_date, row.period) for row in existing_check_ins
        }
        for cycle in active_cycles:
            current_date = cycle.start_date
            scan_end_date = min(cycle.end_date, latest_closed_date)
            while current_date <= scan_end_date:
                for period in _PERIODS:
                    key = (cycle.id, current_date, period)
                    if key not in existing_keys and is_period_closed(
                        current_date, period, now=now
                    ):
                        targets[key] = SettlementTarget(
                            cycle.id, cycle.user_id, current_date, period
                        )
                current_date += timedelta(days=1)

    ordered = sorted(
        targets.values(),
        key=lambda target: (
            period_end_at(target.plan_date, target.period),
            str(target.plan_cycle_id),
        ),
    )
    logger.info("check-in recovery scan target_count=%d", len(ordered))
    return ordered


def find_targets_for_period(
    db: Session, *, plan_date: date, period: PlanPeriod
) -> list[SettlementTarget]:
    cycles = list(
        db.execute(
            select(PlanningCycle)
            .where(
                PlanningCycle.status == PlanCycleStatus.ACTIVE,
                PlanningCycle.start_date <= plan_date,
                PlanningCycle.end_date >= plan_date,
            )
            .order_by(PlanningCycle.id)
        )
        .scalars()
        .all()
    )
    return [
        SettlementTarget(cycle.id, cycle.user_id, plan_date, period)
        for cycle in cycles
    ]
