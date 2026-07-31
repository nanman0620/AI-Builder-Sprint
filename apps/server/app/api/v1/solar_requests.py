import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Path, Response
from sqlalchemy.orm import Session

from app.core.clock import get_current_moment
from app.core.security import AuthenticatedUser, get_current_user
from app.db.session import get_db
from app.schemas.plan_management import PlanManagementStateResponse, to_plan_management_state_response
from app.schemas.solar_request import CreateSolarRequestBody
from app.services import plan_management_service, solar_request_service

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
