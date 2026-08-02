import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterator, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import ApiError
from app.models.enums import AmountSource, PlanBlockStatus, PlanCycleStatus, PlanPeriod, TaskStatus
from app.models.fixed_schedule import FixedSchedule
from app.models.plan_block import PlanBlock
from app.models.planning_cycle import PlanningCycle
from app.models.task import Task

logger = logging.getLogger(__name__)

_SEOUL_TZ = ZoneInfo("Asia/Seoul")

_PERIOD_ORDER = {
    PlanPeriod.MORNING: 0,
    PlanPeriod.AFTERNOON: 1,
    PlanPeriod.EVENING: 2,
}

# 기존 API 명세(13절) 오류 코드표와 동일한 code를 재사용할 수 있는 경우 그대로 쓴다.
CODE_PLAN_BLOCK_NOT_FOUND = "PLAN_BLOCK_NOT_FOUND"
CODE_PLANNING_CYCLE_NOT_FOUND = "PLANNING_CYCLE_NOT_FOUND"
CODE_INVALID_DATE_RANGE = "INVALID_DATE_RANGE"
CODE_INVALID_REQUEST_STATE = "INVALID_REQUEST_STATE"
# 아래 3개는 명세 13절 표에 없는 신규 code다. 실제 API endpoint를 만드는 후속 Issue에서
# 팀 확인 후 확정한다.
CODE_PLAN_BLOCK_CYCLE_MISMATCH = "PLAN_BLOCK_CYCLE_MISMATCH"
CODE_PLAN_BLOCK_TASK_MISMATCH = "PLAN_BLOCK_TASK_MISMATCH"
CODE_PLAN_BLOCK_RESCHEDULE_NOT_IN_FUTURE = "PLAN_BLOCK_RESCHEDULE_NOT_IN_FUTURE"
# 아래 3개는 명세 11절 오류 코드표에 정의된 공식 code를 그대로 쓴다.
CODE_BLOCK_NOT_IN_CURRENT_PERIOD = "BLOCK_NOT_IN_CURRENT_PERIOD"
CODE_PERIOD_ALREADY_FINALIZED = "PERIOD_ALREADY_FINALIZED"
CODE_INVALID_CHECK_STATE = "INVALID_CHECK_STATE"


def _require_aware(moment: datetime, *, param_name: str) -> None:
    """naive datetime은 실행 환경의 로컬 timezone에 따라 결과가 달라질 수 있으므로 거부한다."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(f"{param_name}은(는) timezone-aware datetime이어야 한다.")


def resolve_plan_date(moment: datetime) -> date:
    """Asia/Seoul 기준 논리 날짜. 00:00~03:59:59는 전날 EVENING에 포함되므로 전날로 계산한다."""
    _require_aware(moment, param_name="moment")
    local = moment.astimezone(_SEOUL_TZ)
    if local.hour < 4:
        return (local - timedelta(days=1)).date()
    return local.date()


def resolve_period(moment: datetime) -> PlanPeriod:
    """Asia/Seoul 기준 논리 분기. MORNING 04-11, AFTERNOON 12-17, EVENING 18-03(다음날)."""
    _require_aware(moment, param_name="moment")
    hour = moment.astimezone(_SEOUL_TZ).hour
    if 4 <= hour < 12:
        return PlanPeriod.MORNING
    if 12 <= hour < 18:
        return PlanPeriod.AFTERNOON
    return PlanPeriod.EVENING


def _is_strictly_later(
    date_a: date, period_a: PlanPeriod, date_b: date, period_b: PlanPeriod
) -> bool:
    """(date_a, period_a)가 (date_b, period_b)보다 미래 시점인지."""
    if date_a != date_b:
        return date_a > date_b
    return _PERIOD_ORDER[period_a] > _PERIOD_ORDER[period_b]


def validate_date_in_cycle_range(cycle: PlanningCycle, target_date: date, *, field: str) -> None:
    """plan_date/check_date류가 cycle 범위 안인지 검증하는 재사용 가능한 validator.

    이번 Issue에서는 PlanBlock 재계획 흐름에만 실제로 연결되어 있다. CheckIn·FixedSchedule을
    생성·수정하는 서비스는 아직 없으므로 이 함수를 호출하는 쓰기 경로가 없고,
    해당 두 엔티티의 날짜 무결성이 서비스 계층에서 실제로 보장되는 상태는 아니다.
    """
    if not (cycle.start_date <= target_date <= cycle.end_date):
        raise ApiError(
            422,
            CODE_INVALID_DATE_RANGE,
            "선택한 날짜가 계획 범위를 벗어났어요.",
            details={"field": field},
        )


def validate_fixed_schedule_range(cycle: PlanningCycle, start_at: datetime, end_at: datetime) -> None:
    """fixed_schedules 시작·종료가 cycle 범위 안인지 검증하는 재사용 가능한 validator.

    validate_date_in_cycle_range와 마찬가지로 아직 어떤 쓰기 경로에도 연결되지 않았다.
    """
    _require_aware(start_at, param_name="start_at")
    _require_aware(end_at, param_name="end_at")

    if not start_at < end_at:
        raise ApiError(
            422,
            CODE_INVALID_DATE_RANGE,
            "시작 시각은 종료 시각보다 빨라야 해요.",
            details={"field": "startAt"},
        )

    start_plan_date = resolve_plan_date(start_at)
    # 04:00처럼 정확히 분기 경계에서 끝나는 일정이 다음 논리 날짜를 점유한 것으로
    # 잘못 계산되지 않도록 종료 시각에서 아주 작은 값을 뺀 시점으로 판단한다.
    end_plan_date = resolve_plan_date(end_at - timedelta(microseconds=1))

    if not (cycle.start_date <= start_plan_date <= cycle.end_date):
        raise ApiError(
            422,
            CODE_INVALID_DATE_RANGE,
            "고정 일정 시작 시각이 계획 범위를 벗어났어요.",
            details={"field": "startAt"},
        )
    if not (cycle.start_date <= end_plan_date <= cycle.end_date):
        raise ApiError(
            422,
            CODE_INVALID_DATE_RANGE,
            "고정 일정 종료 시각이 계획 범위를 벗어났어요.",
            details={"field": "endAt"},
        )


def validate_reschedule_source(
    *,
    original: PlanBlock,
    new_user_id: uuid.UUID,
    new_plan_cycle_id: uuid.UUID,
    new_task_id: uuid.UUID,
    new_plan_date: date,
    new_period: PlanPeriod,
) -> None:
    """삭제·대체될 기존 PlanBlock이 재계획 가능한 대상인지 검증하는 순수 함수.

    DB 조회 없이 이미 확보된 original 객체와 새 PlanBlock의 목표 필드 값만으로 판단하므로
    단위 테스트에서 실제 세션 없이 직접 호출할 수 있다.

    신규 행의 rescheduled_from_block_id는 저장하지 않으므로(계보 보존 제외, 후속 스키마
    검토 대상) 자기참조 검증은 포함하지 않는다.
    """
    if original.user_id != new_user_id:
        # 존재하지 않는 경우와 동일하게 취급한다(타인 리소스 존재 여부 비노출 원칙).
        raise ApiError(404, CODE_PLAN_BLOCK_NOT_FOUND, "PlanBlock을 찾을 수 없어요.")

    if original.plan_cycle_id != new_plan_cycle_id:
        raise ApiError(
            409, CODE_PLAN_BLOCK_CYCLE_MISMATCH, "재배치 원본이 같은 계획 주기에 속하지 않아요."
        )

    if original.task_id != new_task_id:
        raise ApiError(
            409, CODE_PLAN_BLOCK_TASK_MISMATCH, "재배치 원본이 같은 할 일에 속하지 않아요."
        )

    if original.status != PlanBlockStatus.PLANNED:
        raise ApiError(409, CODE_INVALID_REQUEST_STATE, "재계획할 수 없는 상태예요.")

    if not _is_strictly_later(new_plan_date, new_period, original.plan_date, original.period):
        raise ApiError(
            422,
            CODE_PLAN_BLOCK_RESCHEDULE_NOT_IN_FUTURE,
            "재배치는 원본보다 미래 시점이어야 해요.",
        )


def get_owned_plan_block(
    db: Session, plan_block_id: uuid.UUID, user_id: uuid.UUID, *, for_update: bool = False
) -> PlanBlock:
    stmt = select(PlanBlock).where(PlanBlock.id == plan_block_id, PlanBlock.user_id == user_id)
    if for_update:
        stmt = stmt.with_for_update()
    block = db.execute(stmt).scalar_one_or_none()
    if block is None:
        raise ApiError(404, CODE_PLAN_BLOCK_NOT_FOUND, "PlanBlock을 찾을 수 없어요.")
    return block


def get_owned_planning_cycle(
    db: Session, plan_cycle_id: uuid.UUID, user_id: uuid.UUID
) -> PlanningCycle:
    cycle = db.execute(
        select(PlanningCycle).where(
            PlanningCycle.id == plan_cycle_id, PlanningCycle.user_id == user_id
        )
    ).scalar_one_or_none()
    if cycle is None:
        raise ApiError(404, CODE_PLANNING_CYCLE_NOT_FOUND, "계획 주기를 찾을 수 없어요.")
    return cycle


def get_active_planning_cycle(db: Session, user_id: uuid.UUID) -> PlanningCycle | None:
    """사용자의 현재 ACTIVE PlanningCycle을 조회한다. 없으면 None.

    사용자당 ACTIVE cycle은 partial UNIQUE index(uq_planning_cycles_one_active_per_user)로
    DB가 최대 1개만 존재함을 보장하므로 scalar_one_or_none()을 그대로 쓴다.
    """
    return db.execute(
        select(PlanningCycle).where(
            PlanningCycle.user_id == user_id, PlanningCycle.status == PlanCycleStatus.ACTIVE
        )
    ).scalar_one_or_none()


def list_current_period_plan_blocks(
    db: Session,
    *,
    user_id: uuid.UUID,
    plan_cycle_id: uuid.UUID,
    plan_date: date,
    period: PlanPeriod,
) -> list[PlanBlock]:
    """현재 분기에 홈에 표시할 PlanBlock 목록을 표시 순서대로 조회한다.

    PLANNED/CHECKED만 포함한다(COMPLETED/NOT_DONE은 정산 완료 상태이므로 제외).
    홈 조회와 check-state 변경 후 진행률 재계산에서 공통으로 사용한다.
    """
    stmt = (
        select(PlanBlock)
        .where(
            PlanBlock.user_id == user_id,
            PlanBlock.plan_cycle_id == plan_cycle_id,
            PlanBlock.plan_date == plan_date,
            PlanBlock.period == period,
            PlanBlock.status.in_((PlanBlockStatus.PLANNED, PlanBlockStatus.CHECKED)),
        )
        .order_by(PlanBlock.display_order)
    )
    return list(db.execute(stmt).scalars().all())


@dataclass(frozen=True)
class PlanBlockProgress:
    checked_count: int
    total_count: int
    percentage: int


def calculate_plan_percentage(completed_count: int, total_count: int) -> int:
    """PlanBlock 개수 비율을 Decimal + ROUND_HALF_UP으로 정수화한다."""
    if total_count <= 0:
        return 0
    return int(
        (Decimal(completed_count) * 100 / Decimal(total_count)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def compute_plan_block_progress(blocks: Sequence[PlanBlock]) -> PlanBlockProgress:
    """PLANNED/CHECKED PlanBlock 목록으로부터 진행률을 계산한다.

    percentage는 Decimal + ROUND_HALF_UP으로 반올림한다(명세 9절 CheckIn 점수 계산과 동일 방식).
    """
    total = len(blocks)
    checked = sum(1 for block in blocks if block.status == PlanBlockStatus.CHECKED)
    if total == 0:
        return PlanBlockProgress(checked_count=0, total_count=0, percentage=0)

    percentage = calculate_plan_percentage(checked, total)
    return PlanBlockProgress(checked_count=checked, total_count=total, percentage=percentage)


def reschedule_plan_block(
    db: Session,
    *,
    user_id: uuid.UUID,
    existing_block_id: uuid.UUID,
    plan_date: date,
    period: PlanPeriod,
    allocated_minutes: int,
    allocated_amount_text: str | None,
    display_title: str,
    display_order: int,
    plan_cycle_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
) -> PlanBlock:
    """기존 PLANNED PlanBlock을 삭제하고 변경된 내용으로 새 PlanBlock을 생성한다.

    핵심 필드(task_id/plan_cycle_id/plan_date/period/allocated_minutes/
    allocated_amount_text/display_title/display_order)는 기존 행을 UPDATE하지 않는다.
    체크·정산처럼 상태 필드(status/checked_at/check_in_id)만 바꾸는 동작은 이 함수가
    아닌 별도 함수의 책임이며, 이 함수는 그런 부분 업데이트를 수행하지 않는다.

    rescheduled_from_block_id는 항상 None으로 생성한다. plan_blocks.rescheduled_from_block_id는
    ON DELETE SET NULL (rescheduled_from_block_id)로 plan_blocks.id를 참조하므로, 삭제될 기존
    행의 ID를 신규 행에 보존할 수 없다(먼저 삭제하면 FK 위반, 나중에 삭제하면 방금 만든 신규
    행의 값이 다시 NULL로 되돌아감). 계보 보존은 이번 Issue 범위에서 제외하며 후속 스키마
    검토 대상이다.

    모든 조회·검증·삭제·생성을 하나의 트랜잭션 안에서 수행한다. 기존 PlanBlock은
    SELECT ... FOR UPDATE로 잠가 동일 행에 대한 동시 재계획을 방지한다. 트랜잭션 도중
    예외가 발생하면 with db.begin()에 의해 전체가 rollback된다.
    """
    with db.begin():
        existing = get_owned_plan_block(db, existing_block_id, user_id, for_update=True)

        resolved_plan_cycle_id = plan_cycle_id or existing.plan_cycle_id
        resolved_task_id = task_id or existing.task_id

        cycle = get_owned_planning_cycle(db, resolved_plan_cycle_id, user_id)

        validate_reschedule_source(
            original=existing,
            new_user_id=user_id,
            new_plan_cycle_id=resolved_plan_cycle_id,
            new_task_id=resolved_task_id,
            new_plan_date=plan_date,
            new_period=period,
        )
        validate_date_in_cycle_range(cycle, plan_date, field="planDate")

        db.delete(existing)
        db.flush()

        new_block = PlanBlock(
            id=uuid.uuid4(),
            user_id=user_id,
            plan_cycle_id=resolved_plan_cycle_id,
            task_id=resolved_task_id,
            plan_date=plan_date,
            period=period,
            allocated_minutes=allocated_minutes,
            allocated_amount_text=allocated_amount_text,
            display_title=display_title,
            display_order=display_order,
            status=PlanBlockStatus.PLANNED,
            rescheduled_from_block_id=None,
        )
        db.add(new_block)
        db.flush()

    return new_block


@dataclass(frozen=True)
class PlanBlockCheckStateResult:
    plan_block: PlanBlock
    progress: PlanBlockProgress


def set_plan_block_check_state(
    db: Session,
    *,
    user_id: uuid.UUID,
    plan_block_id: uuid.UUID,
    checked: bool,
    now: datetime,
) -> PlanBlockCheckStateResult:
    """현재 분기 PlanBlock의 체크 상태를 변경하고, 변경 후 진행률을 함께 반환한다.

    동시 요청으로 상태가 꼬이지 않도록 대상 행을 SELECT ... FOR UPDATE로 잠근 뒤
    같은 트랜잭션 안에서 검증·UPDATE·진행률 재계산을 모두 수행한다.
    """
    with db.begin():
        block = get_owned_plan_block(db, plan_block_id, user_id, for_update=True)
        cycle = get_active_planning_cycle(db, user_id)

        current_plan_date = resolve_plan_date(now)
        current_period = resolve_period(now)

        if (
            cycle is None
            or block.plan_cycle_id != cycle.id
            or block.plan_date != current_plan_date
            or block.period != current_period
        ):
            raise ApiError(
                409,
                CODE_BLOCK_NOT_IN_CURRENT_PERIOD,
                "현재 분기의 계획만 체크할 수 있어요.",
            )

        if block.check_in_id is not None:
            # check_in_id가 있으면 status_consistency 제약상 COMPLETED/NOT_DONE이며 정산이 끝난 상태다.
            raise ApiError(409, CODE_PERIOD_ALREADY_FINALIZED, "이미 정산이 끝난 계획이에요.")

        if checked:
            if block.status != PlanBlockStatus.PLANNED:
                raise ApiError(422, CODE_INVALID_CHECK_STATE, "체크할 수 없는 상태예요.")
            block.status = PlanBlockStatus.CHECKED
            block.checked_at = now
        else:
            if block.status != PlanBlockStatus.CHECKED:
                raise ApiError(422, CODE_INVALID_CHECK_STATE, "체크를 해제할 수 없는 상태예요.")
            block.status = PlanBlockStatus.PLANNED
            block.checked_at = None

        db.flush()
        db.refresh(block)

        current_blocks = list_current_period_plan_blocks(
            db,
            user_id=user_id,
            plan_cycle_id=cycle.id,
            plan_date=current_plan_date,
            period=current_period,
        )
        progress = compute_plan_block_progress(current_blocks)

    return PlanBlockCheckStateResult(plan_block=block, progress=progress)


# ---------------------------------------------------------------------------
# PlanBlock 자동 배치 및 재계획 엔진 (Issue #39)
# ---------------------------------------------------------------------------

_PERIOD_ORDER_LIST = [PlanPeriod.MORNING, PlanPeriod.AFTERNOON, PlanPeriod.EVENING]
_PERIOD_START_HOUR = {PlanPeriod.MORNING: 4, PlanPeriod.AFTERNOON: 12, PlanPeriod.EVENING: 18}
_PERIOD_DURATION_HOURS = {PlanPeriod.MORNING: 8, PlanPeriod.AFTERNOON: 6, PlanPeriod.EVENING: 10}
_PERIOD_CAPACITY_MINUTES = 240
_FAR_FUTURE = datetime.max.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# plan_date+period 위치 비교 SQL predicate — ACTIVE_CYCLE Worker(과거 CHECKED 존재 확인,
# 미래 PLANNED 잠금)와 이 파일의 schedule_plan_blocks() 삭제 대상 계산이 공유하는
# 유일한 출처. _PERIOD_ORDER_LIST 하나에서만 분기 순서를 파생시켜, 두 곳이 서로 다른
# 분기 순서 정의를 갖는 drift를 구조적으로 차단한다.
# ---------------------------------------------------------------------------


def _period_rank_case(period_column: ColumnElement) -> ColumnElement:
    """PlanPeriod 컬럼을 0(MORNING)~2(EVENING) 정수 순위로 변환하는 SQL CASE 식."""
    return case(
        {period: rank for rank, period in enumerate(_PERIOD_ORDER_LIST)},
        value=period_column,
    )


def plan_block_before(
    plan_date_column: ColumnElement,
    period_column: ColumnElement,
    reference_date: date,
    reference_period: PlanPeriod,
) -> ColumnElement:
    """(plan_date, period)가 (reference_date, reference_period)보다 과거인지 판별하는 SQL 조건."""
    reference_rank = _PERIOD_ORDER_LIST.index(reference_period)
    return or_(
        plan_date_column < reference_date,
        and_(plan_date_column == reference_date, _period_rank_case(period_column) < reference_rank),
    )


def plan_block_at_or_after(
    plan_date_column: ColumnElement,
    period_column: ColumnElement,
    reference_date: date,
    reference_period: PlanPeriod,
) -> ColumnElement:
    """(plan_date, period)가 (reference_date, reference_period) 이후(포함)인지 판별하는 SQL 조건."""
    reference_rank = _PERIOD_ORDER_LIST.index(reference_period)
    return or_(
        plan_date_column > reference_date,
        and_(plan_date_column == reference_date, _period_rank_case(period_column) >= reference_rank),
    )


def plan_block_strictly_after(
    plan_date_column: ColumnElement,
    period_column: ColumnElement,
    reference_date: date,
    reference_period: PlanPeriod,
) -> ColumnElement:
    """(plan_date, period)가 (reference_date, reference_period)보다 미래(경계 제외)인지 판별하는 SQL 조건."""
    reference_rank = _PERIOD_ORDER_LIST.index(reference_period)
    return or_(
        plan_date_column > reference_date,
        and_(plan_date_column == reference_date, _period_rank_case(period_column) > reference_rank),
    )


def _period_window(plan_date: date, period: PlanPeriod) -> tuple[datetime, datetime]:
    """plan_date+period의 실제 시각 구간 [start, end)를 반환한다."""
    start_hour = _PERIOD_START_HOUR[period]
    start = datetime(plan_date.year, plan_date.month, plan_date.day, start_hour, 0, tzinfo=_SEOUL_TZ)
    end = start + timedelta(hours=_PERIOD_DURATION_HOURS[period])
    return start, end


def _iter_periods_from(
    start_date: date, start_period: PlanPeriod, end_date: date
) -> Iterator[tuple[date, PlanPeriod]]:
    """start_date/start_period부터 end_date의 EVENING까지 시간순으로 (날짜, 분기)를 순회한다."""
    current_date = start_date
    idx = _PERIOD_ORDER_LIST.index(start_period)
    while current_date <= end_date:
        while idx < len(_PERIOD_ORDER_LIST):
            yield current_date, _PERIOD_ORDER_LIST[idx]
            idx += 1
        idx = 0
        current_date += timedelta(days=1)


def _union_minutes(
    intervals: Sequence[tuple[datetime, datetime]], window_start: datetime, window_end: datetime
) -> int:
    """intervals를 [window_start, window_end)로 자른 뒤 합집합 구간의 총 분 수를 계산한다.

    여러 구간이 겹쳐도 겹치는 부분을 한 번만 계산한다(중복 차감 방지).
    """
    clipped: list[tuple[datetime, datetime]] = []
    for start, end in intervals:
        clipped_start = max(start, window_start)
        clipped_end = min(end, window_end)
        if clipped_start < clipped_end:
            clipped.append((clipped_start, clipped_end))

    if not clipped:
        return 0

    clipped.sort(key=lambda interval: interval[0])
    total_minutes = 0
    merged_start, merged_end = clipped[0]
    for start, end in clipped[1:]:
        if start <= merged_end:
            merged_end = max(merged_end, end)
        else:
            total_minutes += int((merged_end - merged_start).total_seconds() // 60)
            merged_start, merged_end = start, end
    total_minutes += int((merged_end - merged_start).total_seconds() // 60)
    return total_minutes


def _compute_cycle_end_at(cycle: PlanningCycle) -> datetime:
    """cycle_end_at = end_date 다음 날 04:00 Asia/Seoul."""
    next_day = cycle.end_date + timedelta(days=1)
    return datetime(next_day.year, next_day.month, next_day.day, 4, 0, tzinfo=_SEOUL_TZ)


def _compute_planning_deadline_at(task: Task, cycle_end_at: datetime) -> datetime | None:
    """배치용 마감. 실제 마감(deadline_at)과 cycle 종료 시각 중 빠른 시각. 마감 모름은 None."""
    if task.deadline_at is None:
        return None
    return min(task.deadline_at, cycle_end_at)


def _compute_task_allocation_end_at(task: Task, cycle_end_at: datetime) -> datetime:
    """Task가 실제로 시간을 사용할 수 있는 exclusive upper bound.

    deadline이 없는 legacy Task는 cycle 끝까지 배치한다. deadline이 있으면 실제 시각과
    cycle 끝 중 빠른 시각을 사용해 deadline 이후 분을 배치하지 않는다.
    """
    return min(task.deadline_at, cycle_end_at) if task.deadline_at is not None else cycle_end_at


def compute_period_capacity(
    db: Session,
    *,
    user_id: uuid.UUID,
    plan_date: date,
    period: PlanPeriod,
    is_current_period: bool,
    now: datetime,
    checked_minutes: int = 0,
    capacity_end_at: datetime | None = None,
) -> int:
    """미래/현재 분기의 신규 PLANNED 배치 가능 분을 계산한다(명세 11절 분기 용량 제약).

    - 미래 분기: max(0, 240 - 고정일정 합집합)
    - 현재 분기: min(remaining_capacity_by_limit, remaining_clock_available_minutes)
    """
    window_start, full_window_end = _period_window(plan_date, period)
    window_end = min(full_window_end, capacity_end_at) if capacity_end_at is not None else full_window_end
    if window_end <= window_start:
        return 0

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
    intervals = [(fs.start_at, fs.end_at) for fs in fixed_schedules]

    if not is_current_period:
        occupied = _union_minutes(intervals, window_start, window_end)
        window_minutes = int((window_end - window_start).total_seconds() // 60)
        return max(0, min(_PERIOD_CAPACITY_MINUTES, window_minutes) - occupied)

    full_period_occupied = _union_minutes(intervals, window_start, window_end)
    window_minutes = int((window_end - window_start).total_seconds() // 60)
    remaining_capacity_by_limit = max(
        0, min(_PERIOD_CAPACITY_MINUTES, window_minutes) - checked_minutes - full_period_occupied
    )

    clock_start = max(now, window_start)
    remaining_clock_minutes = max(0, int((window_end - clock_start).total_seconds() // 60))
    future_occupied = _union_minutes(intervals, clock_start, window_end)
    remaining_clock_available_minutes = max(0, remaining_clock_minutes - future_occupied)

    return min(remaining_capacity_by_limit, remaining_clock_available_minutes)


def _build_fallback_display_title(task: Task) -> str:
    """SOLAR 연동 전까지 사용하는 임시 fallback이다.

    명세는 display_title을 "제목+분량+시간을 기계적으로 연결한 계산값이 아니라 SOLAR가
    실행 단위에 맞게 확정하는 표시 문구"로 규정한다. 이 Issue는 SOLAR 자연어 분석을
    제외 범위로 두므로, 그 대체 문구를 만들어내지 않고 task.title을 그대로 사용한다.
    실제 SOLAR 연동 시 이 함수를 교체해야 한다.
    """
    return task.title


# "3개"/"8문제"처럼 공백 없는 양의 정수+단위 형식만 인식한다. "문제 5개"(단위가 앞),
# "약 3개"(수식어), "2~3개"(범위), "0개"/"-3개"(선행 0·부호), "3개 정도"(꼬리말)처럼
# 숫자·단위를 안전하게 분리할 수 없는 형식은 모두 매치되지 않는다.
_AMOUNT_TEXT_PATTERN = re.compile(r"^\s*([1-9]\d*)\s*([^\d\s]+)\s*$")


def _parse_amount_quantity(amount_text: str) -> tuple[int, str] | None:
    match = _AMOUNT_TEXT_PATTERN.match(amount_text)
    if match is None:
        return None
    return int(match.group(1)), match.group(2)


def _apply_amount_distribution_fallback(
    created_blocks: list[PlanBlock],
    tasks_by_id: dict[uuid.UUID, Task],
    unplaced_minutes: dict[uuid.UUID, int],
    tasks_with_checked_or_completed_history: set[uuid.UUID],
) -> None:
    """SOLAR가 PlanBlock별 분량을 결정하기 전까지 쓰는 제한적 MVP fallback.

    Task.amount_text는 항상 "Task 전체 분량"이며, 이미 CHECKED/COMPLETED된 몫이 그
    전체 중 얼마였는지 계산할 별도 구조가 없다(시간 비율로 역산하지 않는다). 그래서
    해당 Task에 CHECKED 또는 COMPLETED PlanBlock이 하나라도 존재하면 이번 신규 블록에
    분량을 배정하지 않는다(NOT_DONE은 완료되지 않은 시도라 이력에서 제외한다). 마찬가지로
    이번 호출에서 Task의 필요 시간을 다 배치하지 못했다면(unplaced_minutes > 0) 지금
    만든 블록들이 Task 전체를 대표하지 않으므로 배정하지 않는다.

    위 조건을 통과하고 amount_text가 "3개"처럼 명확한 정수+단위로 파싱되며 그 수량이
    이번에 생성된 블록 수 이상일 때만, allocated_minutes 비율 기준 largest remainder
    방식으로 정수 수량을 배분한다(정수 연산만 사용해 항상 같은 결과를 재현한다). 조건을
    하나라도 만족하지 못하면 그 Task의 신규 블록 전체를 기존 title-only fallback으로
    남겨 둔다 — 일부 블록만 분량을 배정하는 혼합 상태는 만들지 않는다.
    """
    blocks_by_task: dict[uuid.UUID, list[PlanBlock]] = {}
    for block in created_blocks:
        blocks_by_task.setdefault(block.task_id, []).append(block)

    for task_id, blocks in blocks_by_task.items():
        if unplaced_minutes.get(task_id, 0) != 0:
            continue
        if task_id in tasks_with_checked_or_completed_history:
            continue

        task = tasks_by_id[task_id]
        if task.amount_text is None:
            continue
        parsed = _parse_amount_quantity(task.amount_text)
        if parsed is None:
            continue
        quantity, unit = parsed
        if quantity < len(blocks):
            continue

        ordered_blocks = sorted(
            blocks, key=lambda b: (b.plan_date, _PERIOD_ORDER[b.period], b.display_order)
        )
        total_minutes = sum(b.allocated_minutes for b in ordered_blocks)
        if total_minutes <= 0:
            logger.warning(
                "PlanBlock amount distribution fallback: non-positive total minutes "
                "task_id=%s block_count=%d",
                task_id,
                len(ordered_blocks),
            )
            continue

        shares = [(quantity * b.allocated_minutes) // total_minutes for b in ordered_blocks]
        remainders = [(quantity * b.allocated_minutes) % total_minutes for b in ordered_blocks]
        leftover = quantity - sum(shares)

        priority = sorted(range(len(ordered_blocks)), key=lambda i: (-remainders[i], i))
        for i in priority[:leftover]:
            shares[i] += 1

        # Preserve every already-positive largest-remainder result. Only distributions that
        # contain a zero are recalculated with one guaranteed unit per block; the remaining
        # quantity uses the same minute ratio and deterministic remainder tie-break.
        if any(count == 0 for count in shares):
            remaining_quantity = quantity - len(ordered_blocks)
            extra_shares = [
                (remaining_quantity * b.allocated_minutes) // total_minutes
                for b in ordered_blocks
            ]
            extra_remainders = [
                (remaining_quantity * b.allocated_minutes) % total_minutes
                for b in ordered_blocks
            ]
            extra_leftover = remaining_quantity - sum(extra_shares)
            extra_priority = sorted(
                range(len(ordered_blocks)), key=lambda i: (-extra_remainders[i], i)
            )
            for i in extra_priority[:extra_leftover]:
                extra_shares[i] += 1
            shares = [1 + count for count in extra_shares]

        valid_distribution = (
            len(shares) == len(ordered_blocks)
            and sum(shares) == quantity
            and all(count >= 1 for count in shares)
        )
        if not valid_distribution:
            logger.warning(
                "PlanBlock amount distribution fallback: invariant violation "
                "task_id=%s quantity=%d block_count=%d",
                task_id,
                quantity,
                len(ordered_blocks),
            )
            for block in ordered_blocks:
                block.allocated_amount_text = None
                block.display_title = _build_fallback_display_title(task)
            continue

        for block, count in zip(ordered_blocks, shares):
            block.allocated_amount_text = f"{count}{unit}"
            block.display_title = f"{task.title} {count}{unit}"


@dataclass(frozen=True)
class ScheduleResult:
    created_blocks: list[PlanBlock]
    # task_id -> cycle 종료까지 배치하지 못한 분. 마감 임박 경고의 shortage_minutes(명세 18절)와는
    # 다른 개념이며, 이 값은 "현재 시점부터 cycle 끝까지 용량이 부족해 배치하지 못한 총 시간"이다.
    unplaced_minutes: dict[uuid.UUID, int]
    total_unplaced_minutes: int


def _task_priority_key(task: Task, cycle_end_at: datetime):
    planning_deadline_at = _compute_planning_deadline_at(task, cycle_end_at)
    # 마감을 모르는 Task(None)는 항상 마감이 있는 Task보다 낮은 우선순위(뒤)로 정렬된다.
    # 동순위 tie-break는 명세에 명시되어 있지 않아 created_at → id 순으로 결정적으로 고정한다.
    return (
        planning_deadline_at is None,
        planning_deadline_at or _FAR_FUTURE,
        task.created_at,
        task.id,
    )


def _distribute_daily_quotas(effective_need: int, eligible_dates: list[date]) -> dict[date, int]:
    """오래된 날짜부터 integer remainder를 1분씩 부여한 균등 quota."""
    if effective_need <= 0 or not eligible_dates:
        return {}
    base, remainder = divmod(effective_need, len(eligible_dates))
    quotas = {
        plan_date: base + (1 if index < remainder else 0)
        for index, plan_date in enumerate(eligible_dates)
    }
    assert sum(quotas.values()) == effective_need
    return quotas


def _select_evenly_spaced_target_dates(
    eligible_dates: list[date], target_date_count: int
) -> list[date]:
    """Select deterministic, increasing dates spread across the planning horizon."""
    if target_date_count <= 0 or not eligible_dates:
        return []
    bounded_count = min(target_date_count, len(eligible_dates))
    selected = [
        eligible_dates[(order * len(eligible_dates)) // bounded_count]
        for order in range(bounded_count)
    ]
    assert len(selected) == len(set(selected)) == bounded_count
    return selected


def _build_task_daily_quotas(
    *,
    task: Task,
    effective_need: int,
    eligible_dates: list[date],
    has_completed_amount_history: bool,
) -> dict[date, int]:
    """Build base quotas and optional forward-only capacity expansion dates.

    A canonical positive integer amount limits the base dates. Dates after the last
    base target receive zero quota so they open only when forward carry remains.
    """
    if effective_need <= 0 or not eligible_dates:
        return {}
    parsed_amount = (
        _parse_amount_quantity(task.amount_text)
        if task.amount_text is not None and task.amount_source != AmountSource.UNKNOWN
        else None
    )
    if parsed_amount is None or has_completed_amount_history:
        return _distribute_daily_quotas(effective_need, eligible_dates)

    quantity, _unit = parsed_amount
    target_dates = _select_evenly_spaced_target_dates(
        eligible_dates, min(quantity, len(eligible_dates))
    )
    quotas = _distribute_daily_quotas(effective_need, target_dates)
    last_target_index = eligible_dates.index(target_dates[-1])
    for expansion_date in eligible_dates[last_target_index + 1:]:
        quotas[expansion_date] = 0
    return quotas


def schedule_plan_blocks(
    db: Session,
    *,
    user_id: uuid.UUID,
    plan_cycle_id: uuid.UUID,
    now: datetime,
) -> ScheduleResult:
    """최초 계획 생성과 재계획에서 공통으로 사용하는 PlanBlock 자동 배치 서비스.

    호출자(NEW_CYCLE/ACTIVE_CYCLE 실행, CheckIn Worker)가 이미 열어 둔 외부 트랜잭션
    안에서 호출되어야 한다. 이 함수는 db.begin()이나 commit을 절대 호출하지 않으며
    add/delete/flush만 수행한다. 실패 시 rollback 여부는 호출자의 트랜잭션 책임이다.

    재계획 보호 규칙: 과거 COMPLETED/NOT_DONE과 현재 분기 CHECKED는 건드리지 않는다.
    현재 분기의 미체크 PLANNED와 미래 PLANNED만 먼저 삭제하고 flush한 뒤, 남은 행(보호된
    CHECKED 등)만 반영된 상태에서 용량을 계산한다. 현재 분기에 특정 Task의 CHECKED
    PlanBlock이 남아 있으면 그 Task는 같은 분기에 새로 배치하지 않고, 남은 필요 시간은
    다음 분기부터 배치한다.
    """
    cycle = get_owned_planning_cycle(db, plan_cycle_id, user_id)

    current_plan_date = resolve_plan_date(now)
    current_period = resolve_period(now)

    # 1. 재계획 대상(현재 분기 미체크 PLANNED + 미래 PLANNED)을 먼저 삭제하고 flush한다.
    #    날짜·분기 경계 판별은 plan_block_at_or_after() SQL predicate 하나로만 수행한다 —
    #    ACTIVE_CYCLE Worker의 과거 CHECKED 확인·미래 PLANNED 잠금과 동일한 출처를 공유한다.
    removable_blocks = (
        db.execute(
            select(PlanBlock).where(
                PlanBlock.user_id == user_id,
                PlanBlock.plan_cycle_id == plan_cycle_id,
                PlanBlock.status == PlanBlockStatus.PLANNED,
                plan_block_at_or_after(PlanBlock.plan_date, PlanBlock.period, current_plan_date, current_period),
            )
        )
        .scalars()
        .all()
    )
    for block in removable_blocks:
        db.delete(block)
    db.flush()

    # 2. 배치 대상 Task 조회 및 우선순위 정렬
    tasks = (
        db.execute(
            select(Task).where(
                Task.user_id == user_id,
                Task.plan_cycle_id == plan_cycle_id,
                Task.status == TaskStatus.ACTIVE,
                Task.remaining_minutes > 0,
            )
        )
        .scalars()
        .all()
    )

    cycle_end_at = _compute_cycle_end_at(cycle)

    remaining_needs: dict[uuid.UUID, int] = {}
    has_current_checked: dict[uuid.UUID, bool] = {}
    for task in tasks:
        # (task_id, plan_date, period)는 UNIQUE 제약이므로 최대 1건만 존재한다.
        current_checked_blocks = (
            db.execute(
                select(PlanBlock).where(
                    PlanBlock.task_id == task.id,
                    PlanBlock.plan_cycle_id == plan_cycle_id,
                    PlanBlock.plan_date == current_plan_date,
                    PlanBlock.period == current_period,
                    PlanBlock.status == PlanBlockStatus.CHECKED,
                )
            )
            .scalars()
            .all()
        )
        unfinalized_checked_minutes = sum(block.allocated_minutes for block in current_checked_blocks)
        remaining_needs[task.id] = max(0, task.remaining_minutes - unfinalized_checked_minutes)
        has_current_checked[task.id] = unfinalized_checked_minutes > 0

    ordered_tasks = sorted(tasks, key=lambda task: _task_priority_key(task, cycle_end_at))

    task_ids = {task.id for task in tasks}
    tasks_with_checked_or_completed_history: set[uuid.UUID] = set()
    if task_ids:
        history_blocks = (
            db.execute(
                select(PlanBlock).where(
                    PlanBlock.task_id.in_(task_ids),
                    PlanBlock.status.in_([PlanBlockStatus.CHECKED, PlanBlockStatus.COMPLETED]),
                )
            )
            .scalars()
            .all()
        )
        tasks_with_checked_or_completed_history = {block.task_id for block in history_blocks}

    periods_by_date: dict[date, list[PlanPeriod]] = {}
    for plan_date, period in _iter_periods_from(current_plan_date, current_period, cycle.end_date):
        periods_by_date.setdefault(plan_date, []).append(period)

    checked_minutes_cache: dict[tuple[date, PlanPeriod], int] = {}

    def _checked_minutes_for(plan_date: date, period: PlanPeriod) -> int:
        key = (plan_date, period)
        if key not in checked_minutes_cache:
            if plan_date != current_plan_date or period != current_period:
                checked_minutes_cache[key] = 0
            else:
                rows = (
                    db.execute(
                        select(PlanBlock).where(
                            PlanBlock.plan_cycle_id == plan_cycle_id,
                            PlanBlock.plan_date == plan_date,
                            PlanBlock.period == period,
                            PlanBlock.status == PlanBlockStatus.CHECKED,
                        )
                    )
                    .scalars()
                    .all()
                )
                checked_minutes_cache[key] = sum(block.allocated_minutes for block in rows)
        return checked_minutes_cache[key]

    allocation_end_by_task = {
        task.id: _compute_task_allocation_end_at(task, cycle_end_at) for task in ordered_tasks
    }
    daily_quotas_by_task: dict[uuid.UUID, dict[date, int]] = {}
    for task in ordered_tasks:
        allocation_end_at = allocation_end_by_task[task.id]
        eligible_dates: list[date] = []
        for plan_date, periods in periods_by_date.items():
            raw_date_capacity = 0
            for period in periods:
                is_current = plan_date == current_plan_date and period == current_period
                if is_current and has_current_checked.get(task.id):
                    continue
                raw_date_capacity += compute_period_capacity(
                    db,
                    user_id=user_id,
                    plan_date=plan_date,
                    period=period,
                    is_current_period=is_current,
                    now=now,
                    checked_minutes=_checked_minutes_for(plan_date, period),
                    capacity_end_at=allocation_end_at,
                )
            if raw_date_capacity > 0:
                eligible_dates.append(plan_date)
        daily_quotas_by_task[task.id] = _build_task_daily_quotas(
            task=task,
            effective_need=remaining_needs.get(task.id, 0),
            eligible_dates=eligible_dates,
            has_completed_amount_history=task.id in tasks_with_checked_or_completed_history,
        )

    # 3. 날짜별 quota와 순방향 carry를 지키며, 날짜 안에서는 기존 period/task 순서로 배치
    next_display_order: dict[tuple[date, PlanPeriod], int] = {}

    def _reserve_display_order(plan_date: date, period: PlanPeriod) -> int:
        key = (plan_date, period)
        if key not in next_display_order:
            existing_blocks = (
                db.execute(
                    select(PlanBlock).where(
                        PlanBlock.plan_cycle_id == plan_cycle_id,
                        PlanBlock.plan_date == plan_date,
                        PlanBlock.period == period,
                    )
                )
                .scalars()
                .all()
            )
            existing_orders = [block.display_order for block in existing_blocks]
            next_display_order[key] = 0 if not existing_orders else max(existing_orders) + 1
        order = next_display_order[key]
        next_display_order[key] += 1
        return order

    created_blocks: list[PlanBlock] = []

    daily_carry = {task.id: 0 for task in ordered_tasks}
    for plan_date, periods in periods_by_date.items():
        daily_targets: dict[uuid.UUID, int] = {}
        daily_allocated = {task.id: 0 for task in ordered_tasks}
        for task in ordered_tasks:
            quota = daily_quotas_by_task[task.id].get(plan_date)
            if quota is not None:
                daily_targets[task.id] = min(
                    remaining_needs.get(task.id, 0), quota + daily_carry[task.id]
                )

        for period in periods:
            is_current = plan_date == current_plan_date and period == current_period
            checked_minutes = _checked_minutes_for(plan_date, period)
            available = compute_period_capacity(
                db,
                user_id=user_id,
                plan_date=plan_date,
                period=period,
                is_current_period=is_current,
                now=now,
                checked_minutes=checked_minutes,
            )
            if available < 1:
                continue

            newly_allocated_in_period = 0
            for task in ordered_tasks:
                if available < 1:
                    break
                need = remaining_needs.get(task.id, 0)
                daily_remaining = daily_targets.get(task.id, 0) - daily_allocated[task.id]
                if need <= 0 or daily_remaining <= 0:
                    continue
                if is_current and has_current_checked.get(task.id):
                    continue

                before_deadline_capacity = compute_period_capacity(
                    db,
                    user_id=user_id,
                    plan_date=plan_date,
                    period=period,
                    is_current_period=is_current,
                    now=now,
                    checked_minutes=checked_minutes,
                    capacity_end_at=allocation_end_by_task[task.id],
                )
                task_available = min(
                    available, max(0, before_deadline_capacity - newly_allocated_in_period)
                )
                if task_available < 1:
                    continue

                allocate = min(need, daily_remaining, task_available)
                if allocate < 1:
                    continue

                new_block = PlanBlock(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    plan_cycle_id=plan_cycle_id,
                    task_id=task.id,
                    plan_date=plan_date,
                    period=period,
                    allocated_minutes=allocate,
                    allocated_amount_text=None,
                    display_title=_build_fallback_display_title(task),
                    display_order=_reserve_display_order(plan_date, period),
                    status=PlanBlockStatus.PLANNED,
                    rescheduled_from_block_id=None,
                )
                db.add(new_block)
                created_blocks.append(new_block)

                remaining_needs[task.id] = need - allocate
                daily_allocated[task.id] += allocate
                newly_allocated_in_period += allocate
                available -= allocate

        for task in ordered_tasks:
            if task.id in daily_targets:
                daily_carry[task.id] = daily_targets[task.id] - daily_allocated[task.id]

    db.flush()

    unplaced_minutes = {task_id: need for task_id, need in remaining_needs.items() if need > 0}
    total_unplaced_minutes = sum(unplaced_minutes.values())

    # 4. 분량 배분 fallback: CHECKED/COMPLETED 이력이 있는 Task는 amount_text가 이미
    #    "Task 전체 분량"을 가리키지 않게 되므로(그 중 얼마가 끝났는지 계산할 구조가 없음)
    #    이번 신규 블록에서 제외한다. NOT_DONE은 완료된 적이 없으므로 이력에 포함하지 않는다.
    tasks_by_id = {task.id: task for task in tasks}
    _apply_amount_distribution_fallback(
        created_blocks,
        tasks_by_id,
        unplaced_minutes,
        tasks_with_checked_or_completed_history,
    )

    return ScheduleResult(
        created_blocks=created_blocks,
        unplaced_minutes=unplaced_minutes,
        total_unplaced_minutes=total_unplaced_minutes,
    )
