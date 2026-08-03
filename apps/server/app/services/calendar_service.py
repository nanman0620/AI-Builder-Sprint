import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.check_in import CheckIn
from app.models.enums import PlanBlockStatus, PlanPeriod
from app.models.fixed_schedule import FixedSchedule
from app.models.plan_block import PlanBlock
from app.services.plan_block_service import resolve_period, resolve_plan_date

_SEOUL_TZ = ZoneInfo("Asia/Seoul")

_PERIODS = (PlanPeriod.MORNING, PlanPeriod.AFTERNOON, PlanPeriod.EVENING)
_PERIOD_ORDER = {period: index for index, period in enumerate(_PERIODS)}
_VISIBLE_PLAN_BLOCK_STATUSES = {
    "PAST": {PlanBlockStatus.COMPLETED},
    "CURRENT": {PlanBlockStatus.PLANNED, PlanBlockStatus.CHECKED},
    "FUTURE": {PlanBlockStatus.PLANNED},
}


class CalendarTemporalState(str, Enum):
    PAST = "PAST"
    CURRENT = "CURRENT"
    FUTURE = "FUTURE"


@dataclass(frozen=True)
class FixedScheduleSegment:
    schedule: FixedSchedule
    start_at: datetime
    end_at: datetime
    segment_start_at: datetime
    segment_end_at: datetime


@dataclass(frozen=True)
class CalendarPeriodState:
    period: PlanPeriod
    temporal_state: CalendarTemporalState
    check_in: CheckIn | None
    plan_blocks: tuple[PlanBlock, ...]
    fixed_schedules: tuple[FixedScheduleSegment, ...]


@dataclass(frozen=True)
class CalendarDayState:
    date: date
    periods: tuple[CalendarPeriodState, ...]


@dataclass(frozen=True)
class CalendarState:
    from_date: date
    to_date: date
    logical_today: date
    current_period: PlanPeriod
    days: tuple[CalendarDayState, ...]


def list_calendar_plan_blocks(
    db: Session, *, user_id: uuid.UUID, from_date: date, to_date: date
) -> list[PlanBlock]:
    stmt = (
        select(PlanBlock)
        .where(
            PlanBlock.user_id == user_id,
            PlanBlock.plan_date >= from_date,
            PlanBlock.plan_date <= to_date,
        )
        .order_by(
            PlanBlock.plan_date,
            PlanBlock.period,
            PlanBlock.display_order,
            PlanBlock.id,
        )
    )
    return list(db.execute(stmt).scalars().all())


def list_calendar_check_ins(
    db: Session, *, user_id: uuid.UUID, from_date: date, to_date: date
) -> list[CheckIn]:
    stmt = (
        select(CheckIn)
        .where(
            CheckIn.user_id == user_id,
            CheckIn.check_date >= from_date,
            CheckIn.check_date <= to_date,
            CheckIn.finalized_at.is_not(None),
        )
        .order_by(CheckIn.check_date, CheckIn.period, CheckIn.id)
    )
    return list(db.execute(stmt).scalars().all())


def list_calendar_fixed_schedules(
    db: Session, *, user_id: uuid.UUID, query_start: datetime, query_end: datetime
) -> list[FixedSchedule]:
    stmt = (
        select(FixedSchedule)
        .where(
            FixedSchedule.user_id == user_id,
            FixedSchedule.start_at < query_end,
            FixedSchedule.end_at > query_start,
        )
        .order_by(FixedSchedule.start_at, FixedSchedule.id)
    )
    return list(db.execute(stmt).scalars().all())


def _period_window(plan_date: date, period: PlanPeriod) -> tuple[datetime, datetime]:
    if period == PlanPeriod.MORNING:
        return (
            datetime.combine(plan_date, time(4), tzinfo=_SEOUL_TZ),
            datetime.combine(plan_date, time(12), tzinfo=_SEOUL_TZ),
        )
    if period == PlanPeriod.AFTERNOON:
        return (
            datetime.combine(plan_date, time(12), tzinfo=_SEOUL_TZ),
            datetime.combine(plan_date, time(18), tzinfo=_SEOUL_TZ),
        )
    return (
        datetime.combine(plan_date, time(18), tzinfo=_SEOUL_TZ),
        datetime.combine(plan_date + timedelta(days=1), time(4), tzinfo=_SEOUL_TZ),
    )


def _resolve_temporal_state(
    plan_date: date,
    period: PlanPeriod,
    *,
    logical_today: date,
    current_period: PlanPeriod,
) -> CalendarTemporalState:
    point = (plan_date, _PERIOD_ORDER[period])
    current = (logical_today, _PERIOD_ORDER[current_period])
    if point < current:
        return CalendarTemporalState.PAST
    if point > current:
        return CalendarTemporalState.FUTURE
    return CalendarTemporalState.CURRENT


def _iter_dates(from_date: date, to_date: date):
    current = from_date
    while current <= to_date:
        yield current
        current += timedelta(days=1)


def get_calendar_state(
    db: Session,
    user_id: uuid.UUID,
    *,
    from_date: date,
    to_date: date,
    now: datetime,
) -> CalendarState:
    logical_today = resolve_plan_date(now)
    current_period = resolve_period(now)
    query_start = datetime.combine(from_date, time(4), tzinfo=_SEOUL_TZ)
    query_end = datetime.combine(to_date + timedelta(days=1), time(4), tzinfo=_SEOUL_TZ)

    plan_blocks = list_calendar_plan_blocks(
        db, user_id=user_id, from_date=from_date, to_date=to_date
    )
    check_ins = list_calendar_check_ins(
        db, user_id=user_id, from_date=from_date, to_date=to_date
    )
    fixed_schedules = list_calendar_fixed_schedules(
        db, user_id=user_id, query_start=query_start, query_end=query_end
    )

    blocks_by_period: dict[tuple[date, PlanPeriod], list[PlanBlock]] = {}
    for block in plan_blocks:
        blocks_by_period.setdefault((block.plan_date, block.period), []).append(block)

    check_ins_by_period = {
        (check_in.check_date, check_in.period): check_in for check_in in check_ins
    }

    days = []
    for plan_date in _iter_dates(from_date, to_date):
        periods = []
        for period in _PERIODS:
            temporal_state = _resolve_temporal_state(
                plan_date,
                period,
                logical_today=logical_today,
                current_period=current_period,
            )
            visible_statuses = _VISIBLE_PLAN_BLOCK_STATUSES[temporal_state.value]
            visible_blocks = tuple(
                sorted(
                    (
                        block
                        for block in blocks_by_period.get((plan_date, period), [])
                        if block.status in visible_statuses
                    ),
                    key=lambda block: (block.display_order, str(block.id)),
                )
            )

            check_in = (
                check_ins_by_period.get((plan_date, period))
                if temporal_state == CalendarTemporalState.PAST
                else None
            )

            period_start, period_end = _period_window(plan_date, period)
            segments = []
            for schedule in fixed_schedules:
                start_at = schedule.start_at.astimezone(_SEOUL_TZ)
                end_at = schedule.end_at.astimezone(_SEOUL_TZ)
                if start_at < period_end and end_at > period_start:
                    segments.append(
                        FixedScheduleSegment(
                            schedule=schedule,
                            start_at=start_at,
                            end_at=end_at,
                            segment_start_at=max(start_at, period_start),
                            segment_end_at=min(end_at, period_end),
                        )
                    )
            segments.sort(key=lambda segment: (segment.segment_start_at, str(segment.schedule.id)))

            periods.append(
                CalendarPeriodState(
                    period=period,
                    temporal_state=temporal_state,
                    check_in=check_in,
                    plan_blocks=visible_blocks,
                    fixed_schedules=tuple(segments),
                )
            )
        days.append(CalendarDayState(date=plan_date, periods=tuple(periods)))

    return CalendarState(
        from_date=from_date,
        to_date=to_date,
        logical_today=logical_today,
        current_period=current_period,
        days=tuple(days),
    )
