from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.clock import get_current_moment
from app.core.security import AuthenticatedUser, get_current_user
from app.db.session import get_db
from app.schemas.task import AcknowledgeRequest, AcknowledgeResponse, to_acknowledge_response
from app.services import deadline_warning_service

router = APIRouter()


@router.post("/tasks/deadline-warnings/acknowledge", response_model=AcknowledgeResponse)
def acknowledge_deadline_warnings(
    body: AcknowledgeRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    now: datetime = Depends(get_current_moment),
) -> AcknowledgeResponse:
    result = deadline_warning_service.acknowledge_deadline_warnings(
        db, user_id=current_user.id, task_ids=body.task_ids, now=now
    )
    return to_acknowledge_response(result)
