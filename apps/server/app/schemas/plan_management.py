import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    SolarAction,
    SolarEntityType,
    SolarItemStatus,
    SolarMessageKind,
    SolarMessageRole,
    SolarRequestPurpose,
    SolarRequestStatus,
)
from app.schemas.home import ActiveCycleOut, to_active_cycle_out
from app.services.plan_management_service import PlanManagementState, SolarRequestDetail
from app.services.solar_request_service import PlanManagementScreenMode


class QuickReplyOut(BaseModel):
    value: str
    label: str

    model_config = ConfigDict(populate_by_name=True)


class DecisionPromptOut(BaseModel):
    message: str
    options: list[QuickReplyOut]

    model_config = ConfigDict(populate_by_name=True)


class CurrentQuestionOut(BaseModel):
    item_id: uuid.UUID = Field(alias="itemId")
    field: str
    message: str

    model_config = ConfigDict(populate_by_name=True)


class PendingQuestionOut(BaseModel):
    field: str
    message: str
    attempt_count: int = Field(alias="attemptCount")

    model_config = ConfigDict(populate_by_name=True)


class ExecutionErrorOut(BaseModel):
    code: str
    message: str
    retryable: bool

    model_config = ConfigDict(populate_by_name=True)


class ExecutionOut(BaseModel):
    execution_started_at: datetime | None = Field(alias="executionStartedAt")
    execution_attempt_count: int = Field(alias="executionAttemptCount")
    executed_at: datetime | None = Field(alias="executedAt")
    execution_result: dict | None = Field(alias="executionResult")
    error: ExecutionErrorOut | None

    model_config = ConfigDict(populate_by_name=True)


class SolarMessageOut(BaseModel):
    id: uuid.UUID
    sequence_no: int = Field(alias="sequenceNo")
    role: SolarMessageRole
    kind: SolarMessageKind
    content: str
    metadata: dict
    created_at: datetime = Field(alias="createdAt")

    model_config = ConfigDict(populate_by_name=True)


class SolarRequestItemOut(BaseModel):
    id: uuid.UUID
    item_order: int = Field(alias="itemOrder")
    action: SolarAction
    action_label: str = Field(alias="actionLabel")
    entity_type: SolarEntityType = Field(alias="entityType")
    entity_label: str = Field(alias="entityLabel")
    status: SolarItemStatus
    status_label: str = Field(alias="statusLabel")
    raw_line_text: str = Field(alias="rawLineText")
    title: str
    summary_text: str = Field(alias="summaryText")
    normalized_payload: dict | None = Field(alias="normalizedPayload")
    missing_fields: list[str] = Field(alias="missingFields")
    pending_question: PendingQuestionOut | None = Field(alias="pendingQuestion")
    target_entity_id: uuid.UUID | None = Field(alias="targetEntityId")
    # 구조가 명세에 확정되어 있지 않아(3-4 예시가 null) 이번 Issue에서는 항상 null이다.
    target_snapshot: None = Field(alias="targetSnapshot")

    model_config = ConfigDict(populate_by_name=True)


class SolarRequestDetailOut(BaseModel):
    id: uuid.UUID
    purpose: SolarRequestPurpose
    status: SolarRequestStatus
    raw_input: str = Field(alias="rawInput")
    current_item_order: int | None = Field(alias="currentItemOrder")
    messages: list[SolarMessageOut]
    request_items: list[SolarRequestItemOut] = Field(alias="requestItems")
    current_question: CurrentQuestionOut | None = Field(alias="currentQuestion")
    quick_replies: list[QuickReplyOut] = Field(alias="quickReplies")
    input_placeholder: str | None = Field(alias="inputPlaceholder")
    pending_item_id: uuid.UUID | None = Field(alias="pendingItemId")
    decision_prompt: DecisionPromptOut | None = Field(alias="decisionPrompt")
    review_summary: None = Field(alias="reviewSummary")
    execution: ExecutionOut | None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True)


class PlanManagementStateOut(BaseModel):
    screen_mode: PlanManagementScreenMode = Field(alias="screenMode")
    active_cycle: ActiveCycleOut | None = Field(alias="activeCycle")
    request: SolarRequestDetailOut | None

    model_config = ConfigDict(populate_by_name=True)


class PlanManagementStateResponse(BaseModel):
    data: PlanManagementStateOut


def _to_solar_message_out(message) -> SolarMessageOut:
    metadata = message.message_metadata
    return SolarMessageOut(
        id=message.id,
        sequence_no=message.sequence_no,
        role=message.role,
        kind=message.kind,
        content=message.content,
        metadata=metadata if isinstance(metadata, dict) else {},
        created_at=message.created_at,
    )


def _to_solar_request_item_out(detail) -> SolarRequestItemOut:
    item = detail.item
    return SolarRequestItemOut(
        id=item.id,
        item_order=item.item_order,
        action=item.action,
        action_label=detail.action_label,
        entity_type=item.entity_type,
        entity_label=detail.entity_label,
        status=item.status,
        status_label=detail.status_label,
        raw_line_text=item.raw_line_text,
        title=detail.title,
        summary_text=detail.summary_text,
        normalized_payload=item.normalized_payload if isinstance(item.normalized_payload, dict) else None,
        missing_fields=item.missing_fields if isinstance(item.missing_fields, list) else [],
        pending_question=PendingQuestionOut(
            field=detail.pending_question.field,
            message=detail.pending_question.message,
            attempt_count=detail.pending_question.attempt_count,
        )
        if detail.pending_question
        else None,
        target_entity_id=detail.target_entity_id,
        target_snapshot=None,
    )


def _to_execution_out(execution) -> ExecutionOut | None:
    if execution is None:
        return None
    return ExecutionOut(
        execution_started_at=execution.execution_started_at,
        execution_attempt_count=execution.execution_attempt_count,
        executed_at=execution.executed_at,
        execution_result=execution.execution_result,
        error=ExecutionErrorOut(
            code=execution.error.code, message=execution.error.message, retryable=execution.error.retryable
        )
        if execution.error
        else None,
    )


def _to_solar_request_detail_out(detail: SolarRequestDetail) -> SolarRequestDetailOut:
    request = detail.request
    return SolarRequestDetailOut(
        id=request.id,
        purpose=request.purpose,
        status=request.status,
        raw_input=request.raw_input,
        current_item_order=request.current_item_order,
        messages=[_to_solar_message_out(m) for m in detail.messages],
        request_items=[_to_solar_request_item_out(item) for item in detail.items],
        current_question=CurrentQuestionOut(
            item_id=detail.current_question.item_id,
            field=detail.current_question.field,
            message=detail.current_question.message,
        )
        if detail.current_question
        else None,
        quick_replies=[QuickReplyOut(value=q.value, label=q.label) for q in detail.quick_replies],
        input_placeholder=detail.input_placeholder,
        pending_item_id=detail.pending_item_id,
        decision_prompt=DecisionPromptOut(
            message=detail.decision_prompt.message,
            options=[QuickReplyOut(value=o.value, label=o.label) for o in detail.decision_prompt.options],
        )
        if detail.decision_prompt
        else None,
        review_summary=None,
        execution=_to_execution_out(detail.execution),
        created_at=request.created_at,
        updated_at=request.updated_at,
    )


def to_plan_management_state_response(state: PlanManagementState) -> PlanManagementStateResponse:
    return PlanManagementStateResponse(
        data=PlanManagementStateOut(
            screen_mode=state.screen_mode,
            active_cycle=to_active_cycle_out(state.active_cycle) if state.active_cycle else None,
            request=_to_solar_request_detail_out(state.request_detail) if state.request_detail else None,
        )
    )
