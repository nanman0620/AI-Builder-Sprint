import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import PlanBlockStatus, PlanPeriod
from app.services.calendar_service import CalendarState, CalendarTemporalState


class CalendarPlanBlockOut(BaseModel):
    id: uuid.UUID
    display_title: str = Field(alias="displayTitle")
    status: PlanBlockStatus
    display_order: int = Field(alias="displayOrder")

    model_config = ConfigDict(populate_by_name=True)


class CalendarCheckInOut(BaseModel):
    id: uuid.UUID
    score: int
    total_plan_count: int = Field(alias="totalPlanCount")
    completed_plan_count: int = Field(alias="completedPlanCount")
    finalized_at: datetime = Field(alias="finalizedAt")

    model_config = ConfigDict(populate_by_name=True)


class CalendarFixedScheduleOut(BaseModel):
    id: uuid.UUID
    title: str
    start_at: datetime = Field(alias="startAt")
    end_at: datetime = Field(alias="endAt")
    segment_start_at: datetime = Field(alias="segmentStartAt")
    segment_end_at: datetime = Field(alias="segmentEndAt")

    model_config = ConfigDict(populate_by_name=True)


class CalendarPeriodOut(BaseModel):
    period: PlanPeriod
    temporal_state: CalendarTemporalState = Field(alias="temporalState")
    check_in: CalendarCheckInOut | None = Field(alias="checkIn")
    plan_blocks: list[CalendarPlanBlockOut] = Field(alias="planBlocks")
    fixed_schedules: list[CalendarFixedScheduleOut] = Field(alias="fixedSchedules")

    model_config = ConfigDict(populate_by_name=True)


class CalendarDayOut(BaseModel):
    date: date
    periods: list[CalendarPeriodOut]


class CalendarOut(BaseModel):
    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")
    logical_today: date = Field(alias="logicalToday")
    current_period: PlanPeriod = Field(alias="currentPeriod")
    days: list[CalendarDayOut]

    model_config = ConfigDict(populate_by_name=True)


class CalendarResponse(BaseModel):
    data: CalendarOut


def to_calendar_response(state: CalendarState) -> CalendarResponse:
    return CalendarResponse(
        data=CalendarOut(
            from_date=state.from_date,
            to_date=state.to_date,
            logical_today=state.logical_today,
            current_period=state.current_period,
            days=[
                CalendarDayOut(
                    date=day.date,
                    periods=[
                        CalendarPeriodOut(
                            period=period.period,
                            temporal_state=period.temporal_state,
                            check_in=CalendarCheckInOut(
                                id=period.check_in.id,
                                score=period.check_in.score,
                                total_plan_count=period.check_in.total_plan_count,
                                completed_plan_count=period.check_in.completed_plan_count,
                                finalized_at=period.check_in.finalized_at,
                            )
                            if period.check_in
                            else None,
                            plan_blocks=[
                                CalendarPlanBlockOut(
                                    id=block.id,
                                    display_title=block.display_title,
                                    status=block.status,
                                    display_order=block.display_order,
                                )
                                for block in period.plan_blocks
                            ],
                            fixed_schedules=[
                                CalendarFixedScheduleOut(
                                    id=segment.schedule.id,
                                    title=segment.schedule.title,
                                    start_at=segment.start_at,
                                    end_at=segment.end_at,
                                    segment_start_at=segment.segment_start_at,
                                    segment_end_at=segment.segment_end_at,
                                )
                                for segment in period.fixed_schedules
                            ],
                        )
                        for period in day.periods
                    ],
                )
                for day in state.days
            ],
        )
    )
