from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.clock import get_current_moment
from app.core.security import AuthenticatedUser, get_current_user
from app.db.session import get_db
from app.schemas.home import HomeCurrentResponse, to_home_current_response
from app.services import home_service

router = APIRouter()


@router.get("/home/current", response_model=HomeCurrentResponse)
def get_home_current(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    now: datetime = Depends(get_current_moment),
) -> HomeCurrentResponse:
    state = home_service.get_home_current_state(db, current_user.id, now=now)
    return to_home_current_response(state)
