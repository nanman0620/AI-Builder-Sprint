import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import PlanCycleStatus, PlanPeriod
from app.schemas.check_in import (
    CheckInResultOut,
    FinalizingOut,
    to_check_in_result_out,
    to_finalizing_out,
)
from app.schemas.plan_block import PlanBlockOut, ProgressOut, to_plan_block_out, to_progress_out
from app.services.deadline_warning_service import DeadlineWarningNotice
from app.services.home_service import HomeCurrentState, HomeMode


class ActiveCycleOut(BaseModel):
    id: uuid.UUID
    start_date: date = Field(alias="startDate")
    end_date: date = Field(alias="endDate")
    status: PlanCycleStatus
    activated_at: datetime = Field(alias="activatedAt")
    ended_at: datetime | None = Field(alias="endedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class DeadlineWarningItemOut(BaseModel):
    task_id: uuid.UUID = Field(alias="taskId")
    title: str
    deadline_at: datetime = Field(alias="deadlineAt")
    required_minutes: int = Field(alias="requiredMinutes")
    available_minutes: int = Field(alias="availableMinutes")
    shortage_minutes: int = Field(alias="shortageMinutes")

    model_config = ConfigDict(populate_by_name=True)


class BlockingNoticeOut(BaseModel):
    type: Literal["DEADLINE_WARNING"] = "DEADLINE_WARNING"
    items: list[DeadlineWarningItemOut]

    model_config = ConfigDict(populate_by_name=True)


class HomeCurrentOut(BaseModel):
    server_time: datetime = Field(alias="serverTime")
    logical_date: date = Field(alias="logicalDate")
    period: PlanPeriod
    home_mode: HomeMode = Field(alias="homeMode")
    blocking_notice: BlockingNoticeOut | None = Field(default=None, alias="blockingNotice")
    active_cycle: ActiveCycleOut | None = Field(alias="activeCycle")
    progress: ProgressOut | None
    plan_blocks: list[PlanBlockOut] = Field(alias="planBlocks")
    finalizing: FinalizingOut | None = Field(default=None)
    check_in_result: CheckInResultOut | None = Field(default=None, alias="checkInResult")

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


def to_blocking_notice_out(notice: DeadlineWarningNotice) -> BlockingNoticeOut:
    return BlockingNoticeOut(
        items=[
            DeadlineWarningItemOut(
                task_id=item.task_id,
                title=item.title,
                deadline_at=item.deadline_at,
                required_minutes=item.required_minutes,
                available_minutes=item.available_minutes,
                shortage_minutes=item.shortage_minutes,
            )
            for item in notice.items
        ]
    )


def to_home_current_response(state: HomeCurrentState) -> HomeCurrentResponse:
    return HomeCurrentResponse(
        data=HomeCurrentOut(
            server_time=state.server_time,
            logical_date=state.logical_date,
            period=state.period,
            home_mode=state.home_mode,
            blocking_notice=to_blocking_notice_out(state.blocking_notice)
            if state.blocking_notice
            else None,
            active_cycle=to_active_cycle_out(state.active_cycle) if state.active_cycle else None,
            progress=to_progress_out(state.progress) if state.progress else None,
            plan_blocks=[to_plan_block_out(b) for b in state.plan_blocks],
            finalizing=to_finalizing_out(state.finalizing) if state.finalizing else None,
            check_in_result=to_check_in_result_out(state.check_in_result)
            if state.check_in_result
            else None,
        )
    )
