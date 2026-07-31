import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import SolarRequestPurpose, SolarRequestStatus
from app.services.solar_request_service import (
    AcknowledgeExecutionResult,
    ExecutionTransitionResult,
    PlanManagementScreenMode,
    SolarExecutionView,
    resolve_current_request_screen_mode,
)


class CreateSolarRequestBody(BaseModel):
    purpose: SolarRequestPurpose
    client_event_id: str = Field(alias="clientEventId")
    message: str

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("client_event_id", "message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("공백일 수 없다.")
        return value


class CreateSolarMessageBody(BaseModel):
    client_event_id: str = Field(alias="clientEventId")
    message: str

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("client_event_id", "message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("공백일 수 없다.")
        return value


class CreateSolarDecisionBody(BaseModel):
    client_event_id: str = Field(alias="clientEventId")
    decision: str

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("client_event_id")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("공백일 수 없다.")
        return value

    @field_validator("decision")
    @classmethod
    def _valid_decision(cls, value: str) -> str:
        if value not in ("YES", "NO"):
            raise ValueError("decision은 YES 또는 NO여야 한다.")
        return value


# ---------------------------------------------------------------------------
# BE-06 — execute / retry / execution 조회 / acknowledge-result
# ---------------------------------------------------------------------------


class ExecuteSolarRequestOut(BaseModel):
    request_id: uuid.UUID = Field(alias="requestId")
    status: SolarRequestStatus
    screen_mode: PlanManagementScreenMode = Field(alias="screenMode")
    execution_started_at: datetime | None = Field(alias="executionStartedAt")
    execution_attempt_count: int = Field(alias="executionAttemptCount")

    model_config = ConfigDict(populate_by_name=True)


class ExecuteSolarRequestResponse(BaseModel):
    data: ExecuteSolarRequestOut


class SolarExecutionErrorOut(BaseModel):
    code: str
    message: str
    retryable: bool

    model_config = ConfigDict(populate_by_name=True)


class SolarExecutionOut(BaseModel):
    request_id: uuid.UUID = Field(alias="requestId")
    purpose: SolarRequestPurpose
    status: SolarRequestStatus
    screen_mode: PlanManagementScreenMode = Field(alias="screenMode")
    execution_started_at: datetime | None = Field(alias="executionStartedAt")
    execution_attempt_count: int = Field(alias="executionAttemptCount")
    executed_at: datetime | None = Field(alias="executedAt")
    execution_result: dict | None = Field(alias="executionResult")
    error: SolarExecutionErrorOut | None

    model_config = ConfigDict(populate_by_name=True)


class SolarExecutionResponse(BaseModel):
    data: SolarExecutionOut


class AcknowledgeExecutionResultOut(BaseModel):
    request_id: uuid.UUID = Field(alias="requestId")
    result_acknowledged_at: datetime = Field(alias="resultAcknowledgedAt")
    next_plan_management_screen_mode: PlanManagementScreenMode = Field(
        alias="nextPlanManagementScreenMode"
    )

    model_config = ConfigDict(populate_by_name=True)


class AcknowledgeExecutionResultResponse(BaseModel):
    data: AcknowledgeExecutionResultOut


def to_execute_response(result: ExecutionTransitionResult) -> ExecuteSolarRequestResponse:
    request = result.request
    return ExecuteSolarRequestResponse(
        data=ExecuteSolarRequestOut(
            request_id=request.id,
            status=request.status,
            screen_mode=resolve_current_request_screen_mode(request),
            execution_started_at=request.execution_started_at,
            execution_attempt_count=request.execution_attempt_count,
        )
    )


def to_solar_execution_response(view: SolarExecutionView) -> SolarExecutionResponse:
    return SolarExecutionResponse(
        data=SolarExecutionOut(
            request_id=view.request_id,
            purpose=view.purpose,
            status=view.status,
            screen_mode=view.screen_mode,
            execution_started_at=view.execution_started_at,
            execution_attempt_count=view.execution_attempt_count,
            executed_at=view.executed_at,
            execution_result=view.execution_result,
            error=SolarExecutionErrorOut(
                code=view.error.code, message=view.error.message, retryable=view.error.retryable
            )
            if view.error
            else None,
        )
    )


def to_acknowledge_execution_result_response(
    result: AcknowledgeExecutionResult,
) -> AcknowledgeExecutionResultResponse:
    return AcknowledgeExecutionResultResponse(
        data=AcknowledgeExecutionResultOut(
            request_id=result.request_id,
            result_acknowledged_at=result.result_acknowledged_at,
            next_plan_management_screen_mode=result.next_screen_mode,
        )
    )
