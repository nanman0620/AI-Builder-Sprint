from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.clock import get_current_moment
from app.core.security import AuthenticatedUser, get_current_user
from app.db.session import get_db
from app.schemas.bootstrap import BootstrapResponse, to_bootstrap_response
from app.services import bootstrap_service

router = APIRouter()


@router.get("/bootstrap", response_model=BootstrapResponse)
def get_bootstrap(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    now: datetime = Depends(get_current_moment),
) -> BootstrapResponse:
    state = bootstrap_service.get_bootstrap_state(db, current_user.id, now=now)
    return to_bootstrap_response(state)
