from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.clock import get_current_moment
from app.core.errors import ApiError
from app.core.security import AuthenticatedUser, get_current_user
from app.db.session import get_db
from app.schemas.calendar import CalendarResponse, to_calendar_response
from app.services import calendar_service

router = APIRouter()


@router.get("/calendar", response_model=CalendarResponse)
def get_calendar(
    from_date: Annotated[date, Query(alias="from")],
    to_date: Annotated[date, Query(alias="to")],
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    now: datetime = Depends(get_current_moment),
) -> CalendarResponse:
    if from_date > to_date:
        raise ApiError(422, "INVALID_DATE_RANGE", "조회 날짜 범위를 확인해 주세요.")

    state = calendar_service.get_calendar_state(
        db,
        current_user.id,
        from_date=from_date,
        to_date=to_date,
        now=now,
    )
    return to_calendar_response(state)
