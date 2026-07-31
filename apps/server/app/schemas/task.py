import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.services.deadline_warning_service import AcknowledgeResult


class AcknowledgeRequest(BaseModel):
    task_ids: list[uuid.UUID] = Field(alias="taskIds")

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class AcknowledgeOut(BaseModel):
    acknowledged_task_ids: list[uuid.UUID] = Field(alias="acknowledgedTaskIds")
    acknowledged_at: datetime = Field(alias="acknowledgedAt")

    model_config = ConfigDict(populate_by_name=True)


class AcknowledgeResponse(BaseModel):
    data: AcknowledgeOut


def to_acknowledge_response(result: AcknowledgeResult) -> AcknowledgeResponse:
    return AcknowledgeResponse(
        data=AcknowledgeOut(
            acknowledged_task_ids=result.acknowledged_task_ids,
            acknowledged_at=result.acknowledged_at,
        )
    )
