import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Path, Response
from sqlalchemy.orm import Session

from app.core.clock import get_current_moment
from app.core.security import AuthenticatedUser, get_current_user
from app.db.session import get_db
from app.schemas.plan_management import PlanManagementStateResponse, to_plan_management_state_response
from app.schemas.solar_request import (
    AcknowledgeExecutionResultResponse,
    CreateSolarDecisionBody,
    CreateSolarMessageBody,
    CreateSolarRequestBody,
    ExecuteSolarRequestResponse,
    SolarExecutionResponse,
    to_acknowledge_execution_result_response,
    to_execute_response,
    to_solar_execution_response,
)
from app.services import plan_management_service, solar_request_service
from app.workers.solar_execution_worker import SolarExecutionDispatcher, get_solar_execution_dispatcher

router = APIRouter()


@router.get("/solar/requests/{requestId}", response_model=PlanManagementStateResponse)
def get_solar_request_detail(
    request_id: uuid.UUID = Path(alias="requestId"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlanManagementStateResponse:
    state = plan_management_service.get_solar_request_detail_state(db, current_user.id, request_id)
    return to_plan_management_state_response(state)


@router.post("/solar/requests", response_model=PlanManagementStateResponse)
def create_solar_request(
    body: CreateSolarRequestBody,
    response: Response,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    now: datetime = Depends(get_current_moment),
) -> PlanManagementStateResponse:
    result = solar_request_service.create_solar_request(
        db,
        user_id=current_user.id,
        purpose=body.purpose,
        client_event_id=body.client_event_id,
        message=body.message,
        now=now,
    )
    response.status_code = 201 if result.created else 200
    return to_plan_management_state_response(result.state)


@router.post("/solar/requests/{solarRequestId}/messages", response_model=PlanManagementStateResponse)
def create_solar_message(
    body: CreateSolarMessageBody,
    request_id: uuid.UUID = Path(alias="solarRequestId"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    now: datetime = Depends(get_current_moment),
) -> PlanManagementStateResponse:
    state = solar_request_service.add_solar_message(
        db,
        user_id=current_user.id,
        request_id=request_id,
        client_event_id=body.client_event_id,
        message=body.message,
        now=now,
    )
    return to_plan_management_state_response(state)


@router.post("/solar/requests/{solarRequestId}/decisions", response_model=PlanManagementStateResponse)
def create_solar_decision(
    body: CreateSolarDecisionBody,
    request_id: uuid.UUID = Path(alias="solarRequestId"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    now: datetime = Depends(get_current_moment),
) -> PlanManagementStateResponse:
    state = solar_request_service.add_solar_decision(
        db,
        user_id=current_user.id,
        request_id=request_id,
        client_event_id=body.client_event_id,
        decision=body.decision,
        now=now,
    )
    return to_plan_management_state_response(state)


@router.post("/solar/requests/{solarRequestId}/reopen", response_model=PlanManagementStateResponse)
def reopen_solar_request(
    request_id: uuid.UUID = Path(alias="solarRequestId"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    now: datetime = Depends(get_current_moment),
) -> PlanManagementStateResponse:
    state = solar_request_service.reopen_solar_request(db, user_id=current_user.id, request_id=request_id, now=now)
    return to_plan_management_state_response(state)


@router.delete("/solar/requests/{solarRequestId}", status_code=204)
def delete_solar_request(
    request_id: uuid.UUID = Path(alias="solarRequestId"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    solar_request_service.delete_solar_request(db, user_id=current_user.id, request_id=request_id)
    return Response(status_code=204)


@router.post("/solar/requests/{requestId}/execute", response_model=ExecuteSolarRequestResponse, status_code=202)
def execute_solar_request(
    request_id: uuid.UUID = Path(alias="requestId"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    now: datetime = Depends(get_current_moment),
    dispatcher: SolarExecutionDispatcher = Depends(get_solar_execution_dispatcher),
) -> ExecuteSolarRequestResponse:
    result = solar_request_service.execute_solar_request(
        db, user_id=current_user.id, request_id=request_id, now=now, dispatcher=dispatcher
    )
    return to_execute_response(result)


@router.get("/solar/requests/{requestId}/execution", response_model=SolarExecutionResponse)
def get_solar_request_execution(
    request_id: uuid.UUID = Path(alias="requestId"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SolarExecutionResponse:
    view = solar_request_service.get_solar_request_execution(db, user_id=current_user.id, request_id=request_id)
    return to_solar_execution_response(view)


@router.post("/solar/requests/{requestId}/retry", response_model=ExecuteSolarRequestResponse, status_code=202)
def retry_solar_request(
    request_id: uuid.UUID = Path(alias="requestId"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    now: datetime = Depends(get_current_moment),
    dispatcher: SolarExecutionDispatcher = Depends(get_solar_execution_dispatcher),
) -> ExecuteSolarRequestResponse:
    result = solar_request_service.retry_solar_request(
        db, user_id=current_user.id, request_id=request_id, now=now, dispatcher=dispatcher
    )
    return to_execute_response(result)


@router.post(
    "/solar/requests/{requestId}/acknowledge-result", response_model=AcknowledgeExecutionResultResponse
)
def acknowledge_solar_execution_result(
    request_id: uuid.UUID = Path(alias="requestId"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    now: datetime = Depends(get_current_moment),
) -> AcknowledgeExecutionResultResponse:
    result = solar_request_service.acknowledge_solar_execution_result(
        db, user_id=current_user.id, request_id=request_id, now=now
    )
    return to_acknowledge_execution_result_response(result)
