import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app.core.clock import get_current_moment
from app.core.security import AuthenticatedUser, get_current_user
from app.db.session import get_db
from app.schemas.check_in import AcknowledgeResponse, to_acknowledge_response
from app.services import check_in_service

router = APIRouter()


@router.post("/check-ins/{checkInId}/acknowledge", response_model=AcknowledgeResponse)
def acknowledge_check_in(
    check_in_id: uuid.UUID = Path(alias="checkInId"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    now: datetime = Depends(get_current_moment),
) -> AcknowledgeResponse:
    result = check_in_service.acknowledge_check_in(
        db, user_id=current_user.id, check_in_id=check_in_id, now=now
    )
    return to_acknowledge_response(result)
