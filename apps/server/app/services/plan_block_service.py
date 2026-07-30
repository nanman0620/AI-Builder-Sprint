import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.models.enums import PlanBlockStatus, PlanPeriod
from app.models.plan_block import PlanBlock
from app.models.planning_cycle import PlanningCycle

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
