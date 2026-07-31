import uuid
from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.core.clock import get_current_moment
from app.core.errors import ApiError
from app.core.security import AuthenticatedUser, get_current_user
from app.db.session import get_db
from app.main import app
from app.models.enums import SolarRequestPurpose, SolarRequestStatus
from app.models.solar_request import SolarRequest
from app.services import solar_request_service
from app.services.plan_management_service import PlanManagementState, SolarRequestDetail
from app.services.solar_request_service import CreateSolarRequestResult, PlanManagementScreenMode

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
        status=SolarRequestStatus.CHANGE_CONFIRMATION,
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


def _state(request):
    detail = SolarRequestDetail(
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
    return PlanManagementState(
        screen_mode=PlanManagementScreenMode.CHANGE_CONFIRMATION, active_cycle=None, request_detail=detail
    )


def _override_get_current_user():
    return AuthenticatedUser(id=TEST_USER_ID)


def _override_get_db():
    yield None  # create_solar_request를 monkeypatch로 대체하므로 실제 세션이 필요 없다.


def _override_get_current_moment():
    return NOW


@pytest.fixture
def fake_create_solar_request(monkeypatch):
    spy = MagicMock()
    monkeypatch.setattr(solar_request_service, "create_solar_request", spy)
    return spy


@pytest.fixture
def authenticated_client(fake_create_solar_request):
    app.dependency_overrides[get_current_user] = _override_get_current_user
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_moment] = _override_get_current_moment

    yield TestClient(app)

    app.dependency_overrides.clear()


@pytest.fixture
def unauthenticated_client(fake_create_solar_request):
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_moment] = _override_get_current_moment

    yield TestClient(app)

    app.dependency_overrides.clear()


def _valid_body(**overrides):
    body = {"purpose": "NEW_CYCLE", "clientEventId": "evt-1", "message": "새 과제 만들어줘"}
    body.update(overrides)
    return body


def test_missing_authorization_header_returns_401(unauthenticated_client, fake_create_solar_request):
    response = unauthenticated_client.post("/api/v1/solar/requests", json=_valid_body())

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    fake_create_solar_request.assert_not_called()


def test_created_true_returns_201(authenticated_client, fake_create_solar_request):
    request = _request()
    fake_create_solar_request.return_value = CreateSolarRequestResult(state=_state(request), created=True)

    response = authenticated_client.post("/api/v1/solar/requests", json=_valid_body(), headers=AUTH_HEADERS)

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["request"]["id"] == str(REQUEST_ID)
    fake_create_solar_request.assert_called_once_with(
        None,
        user_id=TEST_USER_ID,
        purpose=SolarRequestPurpose.NEW_CYCLE,
        client_event_id="evt-1",
        message="새 과제 만들어줘",
        now=NOW,
    )


def test_created_false_idempotent_replay_returns_200(authenticated_client, fake_create_solar_request):
    request = _request()
    fake_create_solar_request.return_value = CreateSolarRequestResult(state=_state(request), created=False)

    response = authenticated_client.post("/api/v1/solar/requests", json=_valid_body(), headers=AUTH_HEADERS)

    assert response.status_code == 200


@pytest.mark.parametrize(
    "overrides",
    [
        {"message": ""},
        {"message": "   "},
        {"clientEventId": ""},
        {"clientEventId": "   "},
        {"purpose": "NOT_A_PURPOSE"},
    ],
)
def test_invalid_body_returns_400_malformed_request(authenticated_client, fake_create_solar_request, overrides):
    response = authenticated_client.post(
        "/api/v1/solar/requests", json=_valid_body(**overrides), headers=AUTH_HEADERS
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MALFORMED_REQUEST"
    fake_create_solar_request.assert_not_called()


@pytest.mark.parametrize(
    ("status_code", "code"),
    [
        (409, "ACTIVE_CYCLE_EXISTS"),
        (409, "NO_ACTIVE_CYCLE"),
        (409, "ACTIVE_REQUEST_EXISTS"),
        (409, "CYCLE_NOT_ACTIVE"),
        (409, "TARGET_AMBIGUOUS"),
        (503, "SOLAR_UNAVAILABLE"),
    ],
)
def test_api_error_codes_are_mapped_through(authenticated_client, fake_create_solar_request, status_code, code):
    fake_create_solar_request.side_effect = ApiError(status_code, code, "에러 메시지")

    response = authenticated_client.post("/api/v1/solar/requests", json=_valid_body(), headers=AUTH_HEADERS)

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
