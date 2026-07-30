import uuid
from datetime import datetime, timezone

import pytest

from app.core.errors import ApiError
from app.models.enums import SolarRequestPurpose, SolarRequestStatus
from app.models.solar_request import SolarRequest
from app.services import solar_request_service

USER_ID = uuid.uuid4()


def _make_request(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        user_id=USER_ID,
        plan_cycle_id=None,
        purpose=SolarRequestPurpose.NEW_CYCLE,
        status=SolarRequestStatus.COLLECTING,
        raw_input="테스트 입력",
        current_item_order=None,
        confirmed_at=None,
        execution_started_at=None,
        executed_at=None,
        execution_attempt_count=0,
        execution_result=None,
        error_code=None,
        error_message=None,
        result_acknowledged_at=None,
    )
    defaults.update(overrides)
    return SolarRequest(**defaults)


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeSession:
    """execute() 1회 호출로 scalar_one_or_none() 결과를 돌려주는 최소 fake."""

    def __init__(self, value):
        self._value = value
        self.last_statement = None

    def execute(self, stmt):
        self.last_statement = stmt
        return _FakeResult(self._value)


# ---------------------------------------------------------------------------
# get_current_solar_request
# ---------------------------------------------------------------------------


def test_get_current_solar_request_query_conditions():
    fake_db = _FakeSession(None)

    solar_request_service.get_current_solar_request(fake_db, USER_ID)

    sql = str(fake_db.last_statement)
    assert "solar_requests.user_id" in sql
    assert "solar_requests.status IN" in sql
    assert "solar_requests.result_acknowledged_at IS NULL" in sql


def test_get_current_solar_request_returns_the_row_the_session_gives_back():
    request = _make_request(status=SolarRequestStatus.COLLECTING)
    fake_db = _FakeSession(request)

    result = solar_request_service.get_current_solar_request(fake_db, USER_ID)

    assert result is request


def test_get_current_solar_request_returns_none_when_no_row():
    fake_db = _FakeSession(None)

    result = solar_request_service.get_current_solar_request(fake_db, USER_ID)

    assert result is None


# ---------------------------------------------------------------------------
# resolve_current_request_screen_mode
# ---------------------------------------------------------------------------


def test_resolve_current_request_screen_mode_maps_each_in_progress_status():
    expected = {
        SolarRequestStatus.COLLECTING: solar_request_service.PlanManagementScreenMode.COLLECTING,
        SolarRequestStatus.CHANGE_CONFIRMATION: (
            solar_request_service.PlanManagementScreenMode.CHANGE_CONFIRMATION
        ),
        SolarRequestStatus.CHANGE_INPUT: (
            solar_request_service.PlanManagementScreenMode.CHANGE_INPUT
        ),
        SolarRequestStatus.FINAL_REVIEW: (
            solar_request_service.PlanManagementScreenMode.FINAL_REVIEW
        ),
        SolarRequestStatus.EXECUTING: solar_request_service.PlanManagementScreenMode.EXECUTING,
        SolarRequestStatus.FAILED: (
            solar_request_service.PlanManagementScreenMode.EXECUTION_FAILED
        ),
    }

    for status, screen_mode in expected.items():
        request = _make_request(status=status)
        assert solar_request_service.resolve_current_request_screen_mode(request) == screen_mode


def test_resolve_current_request_screen_mode_maps_completed_to_execution_success():
    request = _make_request(
        status=SolarRequestStatus.COMPLETED,
        result_acknowledged_at=None,
        execution_started_at=datetime(2026, 7, 29, 14, 20, tzinfo=timezone.utc),
        executed_at=datetime(2026, 7, 29, 14, 20, 5, tzinfo=timezone.utc),
        execution_attempt_count=1,
        execution_result={},
    )

    result = solar_request_service.resolve_current_request_screen_mode(request)

    assert result == solar_request_service.PlanManagementScreenMode.EXECUTION_SUCCESS


# ---------------------------------------------------------------------------
# resolve_no_request_screen_mode
# ---------------------------------------------------------------------------


def test_resolve_no_request_screen_mode_with_active_cycle():
    result = solar_request_service.resolve_no_request_screen_mode(has_active_cycle=True)

    assert result == solar_request_service.PlanManagementScreenMode.ACTIVE_CYCLE_ENTRY


def test_resolve_no_request_screen_mode_without_active_cycle():
    result = solar_request_service.resolve_no_request_screen_mode(has_active_cycle=False)

    assert result == solar_request_service.PlanManagementScreenMode.NEW_CYCLE_ENTRY


# ---------------------------------------------------------------------------
# get_owned_solar_request
# ---------------------------------------------------------------------------


def test_get_owned_solar_request_query_conditions():
    fake_db = _FakeSession(None)
    request_id = uuid.uuid4()

    with pytest.raises(ApiError):
        solar_request_service.get_owned_solar_request(fake_db, request_id, USER_ID)

    sql = str(fake_db.last_statement)
    assert "solar_requests.id" in sql
    assert "solar_requests.user_id" in sql


def test_get_owned_solar_request_returns_the_row():
    request = _make_request(status=SolarRequestStatus.COMPLETED, result_acknowledged_at=None)
    fake_db = _FakeSession(request)

    result = solar_request_service.get_owned_solar_request(fake_db, request.id, USER_ID)

    assert result is request


def test_get_owned_solar_request_raises_404_when_missing():
    fake_db = _FakeSession(None)

    with pytest.raises(ApiError) as exc_info:
        solar_request_service.get_owned_solar_request(fake_db, uuid.uuid4(), USER_ID)

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "REQUEST_NOT_FOUND"
