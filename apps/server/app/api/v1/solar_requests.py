import uuid

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedUser, get_current_user
from app.db.session import get_db
from app.schemas.plan_management import PlanManagementStateResponse, to_plan_management_state_response
from app.services import plan_management_service

router = APIRouter()


@router.get("/solar/requests/{requestId}", response_model=PlanManagementStateResponse)
def get_solar_request_detail(
    request_id: uuid.UUID = Path(alias="requestId"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlanManagementStateResponse:
    state = plan_management_service.get_solar_request_detail_state(db, current_user.id, request_id)
    return to_plan_management_state_response(state)
