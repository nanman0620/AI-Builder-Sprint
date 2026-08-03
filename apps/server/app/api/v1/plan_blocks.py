import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app.core.clock import get_current_moment
from app.core.security import AuthenticatedUser, get_current_user
from app.db.session import get_db
from app.schemas.plan_block import CheckStateRequest, CheckStateResponse, to_check_state_response
from app.services import plan_block_service

router = APIRouter()


@router.patch("/plan-blocks/{planBlockId}/check-state", response_model=CheckStateResponse)
def update_plan_block_check_state(
    body: CheckStateRequest,
    plan_block_id: uuid.UUID = Path(alias="planBlockId"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    now: datetime = Depends(get_current_moment),
) -> CheckStateResponse:
    result = plan_block_service.set_plan_block_check_state(
        db, user_id=current_user.id, plan_block_id=plan_block_id, checked=body.checked, now=now
    )
    return to_check_state_response(result)
