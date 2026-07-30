import uuid
from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.core.errors import ApiError
from app.core.security import AuthenticatedUser, get_current_user
from app.db.session import get_db
from app.main import app
from app.models.enums import SolarRequestPurpose, SolarRequestStatus
from app.models.solar_request import SolarRequest
from app.services import plan_management_service
from app.services.plan_management_service import PlanManagementState, SolarRequestDetail
from app.services.solar_request_service import PlanManagementScreenMode

SEOUL_TZ = ZoneInfo("Asia/Seoul")
TEST_USER_ID = uuid.uuid4()
REQUEST_ID = uuid.uuid4()
NOW = datetime(2026, 7, 30, 14, 0, tzinfo=SEOUL_TZ)
AUTH_HEADERS = {"Authorization": "Bearer irrelevant-because-dependency-is-overridden"}


def _request(**overrides):
    defaults = dict(
        id=REQUEST_ID,
        user_id=TEST_USER_ID,
        plan_cycle_id=None,
        purpose=SolarRequestPurpose.NEW_CYCLE,
        status=SolarRequestStatus.COMPLETED,
        raw_input="테스트 입력",
        current_item_order=None,
        confirmed_at=None,
        execution_started_at=NOW,
        executed_at=NOW,
        execution_attempt_count=1,
        execution_result={},
        error_code=None,
        error_message=None,
        result_acknowledged_at=NOW,
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
    yield None  # get_solar_request_detail_state를 monkeypatch로 대체하므로 실제 세션이 필요 없다.


@pytest.fixture
def fake_get_solar_request_detail_state(monkeypatch):
    spy = MagicMock()
    monkeypatch.setattr(plan_management_service, "get_solar_request_detail_state", spy)
    return spy


@pytest.fixture
def authenticated_client(fake_get_solar_request_detail_state):
    app.dependency_overrides[get_current_user] = _override_get_current_user
    app.dependency_overrides[get_db] = _override_get_db

    yield TestClient(app)

    app.dependency_overrides.clear()


@pytest.fixture
def unauthenticated_client(fake_get_solar_request_detail_state):
    app.dependency_overrides[get_db] = _override_get_db

    yield TestClient(app)

    app.dependency_overrides.clear()


def test_missing_authorization_header_returns_401(
    unauthenticated_client, fake_get_solar_request_detail_state
):
    response = unauthenticated_client.get(f"/api/v1/solar/requests/{REQUEST_ID}")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    fake_get_solar_request_detail_state.assert_not_called()


def test_returns_plan_management_state_envelope(
    authenticated_client, fake_get_solar_request_detail_state
):
    request = _request()
    detail = _request_detail(request)
    fake_get_solar_request_detail_state.return_value = PlanManagementState(
        screen_mode=PlanManagementScreenMode.EXECUTION_SUCCESS, active_cycle=None, request_detail=detail
    )

    response = authenticated_client.get(f"/api/v1/solar/requests/{REQUEST_ID}", headers=AUTH_HEADERS)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["screenMode"] == "EXECUTION_SUCCESS"
    assert data["request"]["id"] == str(REQUEST_ID)
    fake_get_solar_request_detail_state.assert_called_once_with(None, TEST_USER_ID, REQUEST_ID)


def test_not_found_returns_404_request_not_found(
    authenticated_client, fake_get_solar_request_detail_state
):
    fake_get_solar_request_detail_state.side_effect = ApiError(404, "REQUEST_NOT_FOUND", "요청을 찾을 수 없어요.")

    response = authenticated_client.get(f"/api/v1/solar/requests/{REQUEST_ID}", headers=AUTH_HEADERS)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REQUEST_NOT_FOUND"


def test_invalid_uuid_path_param_returns_400():
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(id=TEST_USER_ID)
    app.dependency_overrides[get_db] = lambda: iter([None])
    client = TestClient(app)

    response = client.get("/api/v1/solar/requests/not-a-uuid", headers=AUTH_HEADERS)

    app.dependency_overrides.clear()
    assert response.status_code == 400
