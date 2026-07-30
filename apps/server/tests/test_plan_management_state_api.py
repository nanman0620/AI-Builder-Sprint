import uuid
from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.core.security import AuthenticatedUser, get_current_user
from app.db.session import get_db
from app.main import app
from app.models.enums import PlanCycleStatus, SolarRequestPurpose, SolarRequestStatus
from app.models.planning_cycle import PlanningCycle
from app.models.solar_request import SolarRequest
from app.services import plan_management_service
from app.services.plan_management_service import PlanManagementState, SolarRequestDetail
from app.services.solar_request_service import PlanManagementScreenMode

SEOUL_TZ = ZoneInfo("Asia/Seoul")
TEST_USER_ID = uuid.uuid4()
CYCLE_ID = uuid.uuid4()
NOW = datetime(2026, 7, 30, 14, 0, tzinfo=SEOUL_TZ)
AUTH_HEADERS = {"Authorization": "Bearer irrelevant-because-dependency-is-overridden"}


def _cycle(**overrides):
    defaults = dict(
        id=CYCLE_ID,
        user_id=TEST_USER_ID,
        start_date=NOW.date(),
        end_date=NOW.date(),
        status=PlanCycleStatus.ACTIVE,
        activated_at=NOW,
        ended_at=None,
    )
    defaults.update(overrides)
    return PlanningCycle(**defaults)


def _request(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        user_id=TEST_USER_ID,
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
        created_at=NOW,
        updated_at=NOW,
    )
    defaults.update(overrides)
    return SolarRequest(**defaults)


def _request_detail(request):
    return SolarRequestDetail(
        request=request,
        messages=[],
        items=[],
        current_question=None,
        quick_replies=[],
        input_placeholder=None,
        pending_item_id=None,
        decision_prompt=None,
        review_summary=None,
        execution=None,
    )


def _override_get_current_user():
    return AuthenticatedUser(id=TEST_USER_ID)


def _override_get_db():
    yield None  # get_plan_management_state를 monkeypatch로 대체하므로 실제 세션이 필요 없다.


@pytest.fixture
def fake_get_plan_management_state(monkeypatch):
    spy = MagicMock()
    monkeypatch.setattr(plan_management_service, "get_plan_management_state", spy)
    return spy


@pytest.fixture
def authenticated_client(fake_get_plan_management_state):
    app.dependency_overrides[get_current_user] = _override_get_current_user
    app.dependency_overrides[get_db] = _override_get_db

    yield TestClient(app)

    app.dependency_overrides.clear()


@pytest.fixture
def unauthenticated_client(fake_get_plan_management_state):
    app.dependency_overrides[get_db] = _override_get_db

    yield TestClient(app)

    app.dependency_overrides.clear()


def test_missing_authorization_header_returns_401(unauthenticated_client, fake_get_plan_management_state):
    response = unauthenticated_client.get("/api/v1/plan-management/state")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    fake_get_plan_management_state.assert_not_called()


def test_no_request_no_active_cycle_returns_new_cycle_entry(
    authenticated_client, fake_get_plan_management_state
):
    fake_get_plan_management_state.return_value = PlanManagementState(
        screen_mode=PlanManagementScreenMode.NEW_CYCLE_ENTRY, active_cycle=None, request_detail=None
    )

    response = authenticated_client.get("/api/v1/plan-management/state", headers=AUTH_HEADERS)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data == {"screenMode": "NEW_CYCLE_ENTRY", "activeCycle": None, "request": None}
    fake_get_plan_management_state.assert_called_once_with(None, TEST_USER_ID)


def test_no_request_with_active_cycle_returns_active_cycle_entry(
    authenticated_client, fake_get_plan_management_state
):
    cycle = _cycle()
    fake_get_plan_management_state.return_value = PlanManagementState(
        screen_mode=PlanManagementScreenMode.ACTIVE_CYCLE_ENTRY, active_cycle=cycle, request_detail=None
    )

    response = authenticated_client.get("/api/v1/plan-management/state", headers=AUTH_HEADERS)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["screenMode"] == "ACTIVE_CYCLE_ENTRY"
    assert data["activeCycle"]["id"] == str(CYCLE_ID)
    assert data["request"] is None


def test_current_request_returns_full_detail_envelope(
    authenticated_client, fake_get_plan_management_state
):
    request = _request(status=SolarRequestStatus.CHANGE_CONFIRMATION)
    detail = _request_detail(request)
    fake_get_plan_management_state.return_value = PlanManagementState(
        screen_mode=PlanManagementScreenMode.CHANGE_CONFIRMATION, active_cycle=None, request_detail=detail
    )

    response = authenticated_client.get("/api/v1/plan-management/state", headers=AUTH_HEADERS)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["screenMode"] == "CHANGE_CONFIRMATION"
    assert data["request"]["id"] == str(request.id)
    assert data["request"]["messages"] == []
    assert data["request"]["requestItems"] == []
    assert data["request"]["currentQuestion"] is None
    assert data["request"]["quickReplies"] == []
    assert data["request"]["reviewSummary"] is None
    assert data["request"]["execution"] is None
