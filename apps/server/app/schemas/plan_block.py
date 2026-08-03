import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app.models.enums import PlanBlockStatus, PlanPeriod
from app.models.plan_block import PlanBlock
from app.services.plan_block_service import PlanBlockCheckStateResult, PlanBlockProgress


class PlanBlockOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID = Field(alias="taskId")
    plan_date: date = Field(alias="planDate")
    period: PlanPeriod
    allocated_minutes: int = Field(alias="allocatedMinutes")
    allocated_amount_text: str | None = Field(alias="allocatedAmountText")
    display_title: str = Field(alias="displayTitle")
    display_order: int = Field(alias="displayOrder")
    status: PlanBlockStatus
    checked_at: datetime | None = Field(alias="checkedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class ProgressOut(BaseModel):
    checked_count: int = Field(alias="checkedCount")
    total_count: int = Field(alias="totalCount")
    percentage: int

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class CheckStateRequest(BaseModel):
    checked: StrictBool

    model_config = ConfigDict(extra="forbid")


class CheckStateOut(BaseModel):
    plan_block: PlanBlockOut = Field(alias="planBlock")
    progress: ProgressOut

    model_config = ConfigDict(populate_by_name=True)


class CheckStateResponse(BaseModel):
    data: CheckStateOut


def to_plan_block_out(block: PlanBlock) -> PlanBlockOut:
    return PlanBlockOut(
        id=block.id,
        task_id=block.task_id,
        plan_date=block.plan_date,
        period=block.period,
        allocated_minutes=block.allocated_minutes,
        allocated_amount_text=block.allocated_amount_text,
        display_title=block.display_title,
        display_order=block.display_order,
        status=block.status,
        checked_at=block.checked_at,
    )


def to_progress_out(progress: PlanBlockProgress) -> ProgressOut:
    return ProgressOut(
        checked_count=progress.checked_count,
        total_count=progress.total_count,
        percentage=progress.percentage,
    )


def to_check_state_response(result: PlanBlockCheckStateResult) -> CheckStateResponse:
    return CheckStateResponse(
        data=CheckStateOut(
            plan_block=to_plan_block_out(result.plan_block),
            progress=to_progress_out(result.progress),
        )
    )
