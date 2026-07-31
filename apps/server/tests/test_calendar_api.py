import uuid
from datetime import date, datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.core.clock import get_current_moment
from app.core.security import AuthenticatedUser, get_current_user
from app.db.session import get_db
from app.main import app
from app.models.check_in import CheckIn
from app.models.enums import PlanBlockStatus, PlanPeriod
from app.models.fixed_schedule import FixedSchedule
from app.models.plan_block import PlanBlock
from app.services import calendar_service

SEOUL_TZ = ZoneInfo("Asia/Seoul")
TEST_USER_ID = uuid.uuid4()
FIXED_NOW = datetime(2026, 7, 29, 14, 0, tzinfo=SEOUL_TZ)
AUTH_HEADERS = {"Authorization": "Bearer dependency-is-overridden"}


def _override_get_current_user():
    return AuthenticatedUser(id=TEST_USER_ID)


def _override_get_db():
    yield None


def _override_get_current_moment():
    return FIXED_NOW


@pytest.fixture
def service_spy(monkeypatch):
    spy = MagicMock()
    monkeypatch.setattr(calendar_service, "get_calendar_state", spy)
    return spy


@pytest.fixture
def authenticated_client(service_spy):
    app.dependency_overrides[get_current_user] = _override_get_current_user
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_moment] = _override_get_current_moment
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def unauthenticated_client(service_spy):
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_moment] = _override_get_current_moment
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_state():
    block = PlanBlock(
        id=uuid.uuid4(),
        user_id=TEST_USER_ID,
        plan_cycle_id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        plan_date=date(2026, 7, 29),
        period=PlanPeriod.MORNING,
        allocated_minutes=60,
        allocated_amount_text="2문제",
        display_title="자료구조 2문제",
        display_order=1,
        status=PlanBlockStatus.COMPLETED,
        checked_at=FIXED_NOW,
        check_in_id=uuid.uuid4(),
    )
    check_in = CheckIn(
        id=block.check_in_id,
        user_id=TEST_USER_ID,
        plan_cycle_id=block.plan_cycle_id,
        check_date=date(2026, 7, 29),
        period=PlanPeriod.MORNING,
        total_plan_count=3,
        completed_plan_count=2,
        score=67,
        replan_unplaced_minutes=60,
        finalization_started_at=datetime(2026, 7, 29, 12, 0, tzinfo=SEOUL_TZ),
        finalized_at=datetime(2026, 7, 29, 12, 0, 5, tzinfo=SEOUL_TZ),
    )
    schedule = FixedSchedule(
        id=uuid.uuid4(),
        user_id=TEST_USER_ID,
        plan_cycle_id=block.plan_cycle_id,
        title="알바",
        start_at=datetime(2026, 7, 29, 22, 0, tzinfo=SEOUL_TZ),
        end_at=datetime(2026, 7, 30, 2, 0, tzinfo=SEOUL_TZ),
    )
    segment = calendar_service.FixedScheduleSegment(
        schedule=schedule,
        start_at=schedule.start_at,
        end_at=schedule.end_at,
        segment_start_at=schedule.start_at,
        segment_end_at=schedule.end_at,
    )
    return calendar_service.CalendarState(
        from_date=date(2026, 7, 29),
        to_date=date(2026, 7, 29),
        logical_today=date(2026, 7, 29),
        current_period=PlanPeriod.AFTERNOON,
        days=(
            calendar_service.CalendarDayState(
                date=date(2026, 7, 29),
                periods=(
                    calendar_service.CalendarPeriodState(
                        period=PlanPeriod.MORNING,
                        temporal_state=calendar_service.CalendarTemporalState.PAST,
                        check_in=check_in,
                        plan_blocks=(block,),
                        fixed_schedules=(),
                    ),
                    calendar_service.CalendarPeriodState(
                        period=PlanPeriod.AFTERNOON,
                        temporal_state=calendar_service.CalendarTemporalState.CURRENT,
                        check_in=None,
                        plan_blocks=(),
                        fixed_schedules=(),
                    ),
                    calendar_service.CalendarPeriodState(
                        period=PlanPeriod.EVENING,
                        temporal_state=calendar_service.CalendarTemporalState.FUTURE,
                        check_in=None,
                        plan_blocks=(),
                        fixed_schedules=(segment,),
                    ),
                ),
            ),
        ),
    )


def test_calendar_returns_exact_camel_case_contract(authenticated_client, service_spy):
    service_spy.return_value = _make_state()

    response = authenticated_client.get(
        "/api/v1/calendar?from=2026-07-29&to=2026-07-29", headers=AUTH_HEADERS
    )

    assert response.status_code == 200
    assert set(response.json()) == {"data"}
    data = response.json()["data"]
    assert set(data) == {"from", "to", "logicalToday", "currentPeriod", "days"}
    assert data["from"] == "2026-07-29"
    assert data["to"] == "2026-07-29"
    assert data["logicalToday"] == "2026-07-29"
    assert data["currentPeriod"] == "AFTERNOON"
    assert len(data["days"]) == 1
    assert set(data["days"][0]) == {"date", "periods"}

    morning, afternoon, evening = data["days"][0]["periods"]
    assert [period["period"] for period in (morning, afternoon, evening)] == [
        "MORNING",
        "AFTERNOON",
        "EVENING",
    ]
    expected_period_fields = {
        "period",
        "temporalState",
        "checkIn",
        "planBlocks",
        "fixedSchedules",
    }
    assert all(set(period) == expected_period_fields for period in (morning, afternoon, evening))
    assert set(morning["planBlocks"][0]) == {"id", "displayTitle", "status", "displayOrder"}
    assert set(morning["checkIn"]) == {
        "id",
        "score",
        "totalPlanCount",
        "completedPlanCount",
        "finalizedAt",
    }
    assert set(evening["fixedSchedules"][0]) == {
        "id",
        "title",
        "startAt",
        "endAt",
        "segmentStartAt",
        "segmentEndAt",
    }
    assert morning["checkIn"]["finalizedAt"].endswith("+09:00")
    assert evening["fixedSchedules"][0]["startAt"].endswith("+09:00")
    assert afternoon["checkIn"] is None
    assert afternoon["planBlocks"] == []
    assert afternoon["fixedSchedules"] == []
    assert "emptyReason" not in data

    service_spy.assert_called_once_with(
        None,
        TEST_USER_ID,
        from_date=date(2026, 7, 29),
        to_date=date(2026, 7, 29),
        now=FIXED_NOW,
    )


@pytest.mark.parametrize(
    "query",
    [
        "to=2026-07-29",
        "from=2026-07-29",
        "from=not-a-date&to=2026-07-29",
        "from=2026-07-29&to=2026-02-30",
    ],
)
def test_missing_or_malformed_date_returns_common_400(
    authenticated_client, service_spy, query
):
    response = authenticated_client.get(f"/api/v1/calendar?{query}", headers=AUTH_HEADERS)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MALFORMED_REQUEST"
    service_spy.assert_not_called()


def test_from_after_to_returns_invalid_date_range(authenticated_client, service_spy):
    response = authenticated_client.get(
        "/api/v1/calendar?from=2026-07-30&to=2026-07-29", headers=AUTH_HEADERS
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "INVALID_DATE_RANGE"
    assert error["message"] == "조회 날짜 범위를 확인해 주세요."
    assert error["details"] == {}
    service_spy.assert_not_called()


def test_missing_authorization_returns_auth_required(unauthenticated_client, service_spy):
    response = unauthenticated_client.get(
        "/api/v1/calendar?from=2026-07-29&to=2026-07-29"
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    service_spy.assert_not_called()
