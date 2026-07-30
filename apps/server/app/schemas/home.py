import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import PlanCycleStatus, PlanPeriod
from app.schemas.plan_block import PlanBlockOut, ProgressOut, to_plan_block_out, to_progress_out
from app.services.home_service import HomeCurrentState, HomeMode


class ActiveCycleOut(BaseModel):
    id: uuid.UUID
    start_date: date = Field(alias="startDate")
    end_date: date = Field(alias="endDate")
    status: PlanCycleStatus
    activated_at: datetime = Field(alias="activatedAt")
    ended_at: datetime | None = Field(alias="endedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class HomeCurrentOut(BaseModel):
    server_time: datetime = Field(alias="serverTime")
    logical_date: date = Field(alias="logicalDate")
    period: PlanPeriod
    home_mode: HomeMode = Field(alias="homeMode")
    blocking_notice: dict | None = Field(default=None, alias="blockingNotice")
    active_cycle: ActiveCycleOut | None = Field(alias="activeCycle")
    progress: ProgressOut | None
    plan_blocks: list[PlanBlockOut] = Field(alias="planBlocks")
    finalizing: dict | None = Field(default=None, alias="finalizing")
    check_in_result: dict | None = Field(default=None, alias="checkInResult")

    model_config = ConfigDict(populate_by_name=True)


class HomeCurrentResponse(BaseModel):
    data: HomeCurrentOut


def to_active_cycle_out(cycle) -> ActiveCycleOut:
    return ActiveCycleOut(
        id=cycle.id,
        start_date=cycle.start_date,
        end_date=cycle.end_date,
        status=cycle.status,
        activated_at=cycle.activated_at,
        ended_at=cycle.ended_at,
    )


def to_home_current_response(state: HomeCurrentState) -> HomeCurrentResponse:
    return HomeCurrentResponse(
        data=HomeCurrentOut(
            server_time=state.server_time,
            logical_date=state.logical_date,
            period=state.period,
            home_mode=state.home_mode,
            active_cycle=to_active_cycle_out(state.active_cycle) if state.active_cycle else None,
            progress=to_progress_out(state.progress) if state.progress else None,
            plan_blocks=[to_plan_block_out(b) for b in state.plan_blocks],
        )
    )
