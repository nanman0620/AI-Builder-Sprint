import uuid
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

from sqlalchemy.orm import Session

from app.models.enums import PlanPeriod
from app.models.plan_block import PlanBlock
from app.models.planning_cycle import PlanningCycle
from app.services.plan_block_service import (
    PlanBlockProgress,
    compute_plan_block_progress,
    get_active_planning_cycle,
    list_current_period_plan_blocks,
    resolve_period,
    resolve_plan_date,
)


class HomeMode(str, Enum):
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


def get_home_current_state(db: Session, user_id: uuid.UUID, *, now: datetime) -> HomeCurrentState:
    """현재 사용자의 논리 날짜·분기 기준 홈 상태를 계산한다.

    완전한 조회 전용이며 DB에 어떤 쓰기도 하지 않는다(db.begin()을 호출하지 않음).
    이번 Issue 범위에서는 NO_ACTIVE_CYCLE/NO_PLANS/IN_PROGRESS 세 상태만 계산한다.
    """
    plan_date = resolve_plan_date(now)
    period = resolve_period(now)

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
    if not blocks:
        return HomeCurrentState(
            home_mode=HomeMode.NO_PLANS,
            server_time=now,
            logical_date=plan_date,
            period=period,
            active_cycle=cycle,
            progress=PlanBlockProgress(checked_count=0, total_count=0, percentage=0),
            plan_blocks=[],
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
    )
