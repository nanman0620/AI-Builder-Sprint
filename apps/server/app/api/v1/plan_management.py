from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedUser, get_current_user
from app.db.session import get_db
from app.schemas.plan_management import PlanManagementStateResponse, to_plan_management_state_response
from app.services import plan_management_service

router = APIRouter()


@router.get("/plan-management/state", response_model=PlanManagementStateResponse)
def get_plan_management_state(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlanManagementStateResponse:
    state = plan_management_service.get_plan_management_state(db, current_user.id)
    return to_plan_management_state_response(state)
