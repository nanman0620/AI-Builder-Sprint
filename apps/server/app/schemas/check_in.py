import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import PlanBlockStatus, PlanPeriod
from app.services.check_in_service import (
    AcknowledgeResult,
    CheckInResultPlanBlock,
    CheckInResultState,
    FinalizingInfo,
)


class FinalizingOut(BaseModel):
    check_in_id: uuid.UUID = Field(alias="checkInId")
    check_date: date = Field(alias="checkDate")
    period: PlanPeriod
    finalization_started_at: datetime = Field(alias="finalizationStartedAt")

    model_config = ConfigDict(populate_by_name=True)


class CheckInResultPlanBlockOut(BaseModel):
    id: uuid.UUID
    display_title: str = Field(alias="displayTitle")
    status: PlanBlockStatus

    model_config = ConfigDict(populate_by_name=True)


class CheckInResultOut(BaseModel):
    id: uuid.UUID
    check_date: date = Field(alias="checkDate")
    period: PlanPeriod
    total_plan_count: int = Field(alias="totalPlanCount")
    completed_plan_count: int = Field(alias="completedPlanCount")
    not_done_plan_count: int = Field(alias="notDonePlanCount")
    score: int
    replan_unplaced_minutes: int = Field(alias="replanUnplacedMinutes")
    finalized_at: datetime = Field(alias="finalizedAt")
    cycle_ended: bool = Field(alias="cycleEnded")
    completed_plans: list[CheckInResultPlanBlockOut] = Field(alias="completedPlans")
    not_done_plans: list[CheckInResultPlanBlockOut] = Field(alias="notDonePlans")

    model_config = ConfigDict(populate_by_name=True)


class AcknowledgeOut(BaseModel):
    target_check_in_id: uuid.UUID = Field(alias="targetCheckInId")
    acknowledged_check_in_ids: list[uuid.UUID] = Field(alias="acknowledgedCheckInIds")
    acknowledged_count: int = Field(alias="acknowledgedCount")
    result_acknowledged_at: datetime = Field(alias="resultAcknowledgedAt")

    model_config = ConfigDict(populate_by_name=True)


class AcknowledgeResponse(BaseModel):
    data: AcknowledgeOut


def to_finalizing_out(info: FinalizingInfo) -> FinalizingOut:
    return FinalizingOut(
        check_in_id=info.check_in_id,
        check_date=info.check_date,
        period=info.period,
        finalization_started_at=info.finalization_started_at,
    )


def _to_result_plan_block_out(block: CheckInResultPlanBlock) -> CheckInResultPlanBlockOut:
    return CheckInResultPlanBlockOut(id=block.id, display_title=block.display_title, status=block.status)


def to_check_in_result_out(state: CheckInResultState) -> CheckInResultOut:
    return CheckInResultOut(
        id=state.id,
        check_date=state.check_date,
        period=state.period,
        total_plan_count=state.total_plan_count,
        completed_plan_count=state.completed_plan_count,
        not_done_plan_count=state.not_done_plan_count,
        score=state.score,
        replan_unplaced_minutes=state.replan_unplaced_minutes,
        finalized_at=state.finalized_at,
        cycle_ended=state.cycle_ended,
        completed_plans=[_to_result_plan_block_out(block) for block in state.completed_plans],
        not_done_plans=[_to_result_plan_block_out(block) for block in state.not_done_plans],
    )


def to_acknowledge_response(result: AcknowledgeResult) -> AcknowledgeResponse:
    return AcknowledgeResponse(
        data=AcknowledgeOut(
            target_check_in_id=result.target_check_in_id,
            acknowledged_check_in_ids=result.acknowledged_check_in_ids,
            acknowledged_count=len(result.acknowledged_check_in_ids),
            result_acknowledged_at=result.result_acknowledged_at,
        )
    )
