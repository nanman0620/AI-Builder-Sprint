import uuid
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

from sqlalchemy.orm import Session

from app.models.enums import PlanPeriod
from app.models.plan_block import PlanBlock
from app.models.planning_cycle import PlanningCycle
from app.services import check_in_service, deadline_warning_service
from app.services.check_in_service import CheckInResultState, FinalizingInfo
from app.services.deadline_warning_service import DeadlineWarningNotice
from app.services.plan_block_service import (
    PlanBlockProgress,
    compute_plan_block_progress,
    get_active_planning_cycle,
    list_current_period_plan_blocks,
    resolve_period,
    resolve_plan_date,
)


class HomeMode(str, Enum):
    FINALIZING = "FINALIZING"
    CHECK_IN_RESULT = "CHECK_IN_RESULT"
    NO_ACTIVE_CYCLE = "NO_ACTIVE_CYCLE"
    NO_PLANS = "NO_PLANS"
    IN_PROGRESS = "IN_PROGRESS"


@dataclass(frozen=True)
class HomeCurrentState:
    home_mode: HomeMode
    server_time: datetime
    logical_date: date
    period: PlanPeriod
    active_cycle: PlanningCycle | None
    progress: PlanBlockProgress | None
    plan_blocks: list[PlanBlock]
    blocking_notice: DeadlineWarningNotice | None = None
    finalizing: FinalizingInfo | None = None
    check_in_result: CheckInResultState | None = None


def get_home_current_state(db: Session, user_id: uuid.UUID, *, now: datetime) -> HomeCurrentState:
    """현재 사용자의 논리 날짜·분기 기준 홈 표시 상태를 우선순위대로 계산한다.

    완전한 조회 전용이며 DB에 어떤 쓰기도 하지 않는다(db.begin()을 호출하지 않음).

    표시 우선순위(명세 8절): FINALIZING > CHECK_IN_RESULT > DEADLINE_WARNING(기본 상태
    위의 blockingNotice) > NO_ACTIVE_CYCLE > NO_PLANS > IN_PROGRESS. DEADLINE_WARNING은
    homeMode가 아니므로 FINALIZING/CHECK_IN_RESULT일 때는 계산하지 않는다.
    """
    plan_date = resolve_plan_date(now)
    period = resolve_period(now)

    finalizing = check_in_service.get_finalizing_info(db, user_id)
    if finalizing is not None:
        return HomeCurrentState(
            home_mode=HomeMode.FINALIZING,
            server_time=now,
            logical_date=plan_date,
            period=period,
            active_cycle=get_active_planning_cycle(db, user_id),
            progress=None,
            plan_blocks=[],
            blocking_notice=None,
            finalizing=finalizing,
            check_in_result=None,
        )

    check_in_result = check_in_service.get_check_in_result_state(db, user_id)
    if check_in_result is not None:
        return HomeCurrentState(
            home_mode=HomeMode.CHECK_IN_RESULT,
            server_time=now,
            logical_date=plan_date,
            period=period,
            active_cycle=get_active_planning_cycle(db, user_id),
            progress=None,
            plan_blocks=[],
            blocking_notice=None,
            finalizing=None,
            check_in_result=check_in_result,
        )

    cycle = get_active_planning_cycle(db, user_id)
    if cycle is None:
        return HomeCurrentState(
            home_mode=HomeMode.NO_ACTIVE_CYCLE,
            server_time=now,
            logical_date=plan_date,
            period=period,
            active_cycle=None,
            progress=None,
            plan_blocks=[],
        )

    blocks = list_current_period_plan_blocks(
        db, user_id=user_id, plan_cycle_id=cycle.id, plan_date=plan_date, period=period
    )
    blocking_notice = deadline_warning_service.compute_deadline_warnings(db, user_id, now=now)

    if not blocks:
        return HomeCurrentState(
            home_mode=HomeMode.NO_PLANS,
            server_time=now,
            logical_date=plan_date,
            period=period,
            active_cycle=cycle,
            progress=PlanBlockProgress(checked_count=0, total_count=0, percentage=0),
            plan_blocks=[],
            blocking_notice=blocking_notice,
        )

    progress = compute_plan_block_progress(blocks)
    return HomeCurrentState(
        home_mode=HomeMode.IN_PROGRESS,
        server_time=now,
        logical_date=plan_date,
        period=period,
        active_cycle=cycle,
        progress=progress,
        plan_blocks=blocks,
        blocking_notice=blocking_notice,
    )
