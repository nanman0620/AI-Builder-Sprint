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
    return PlanManagementState(screen_mode=PlanManagementScreenMode.COLLECTING, active_cycle=None, request_detail=detail)


def _override_get_current_user():
    return AuthenticatedUser(id=TEST_USER_ID)


def _override_get_db():
    yield None


def _override_get_current_moment():
    return NOW


@pytest.fixture
def fake_service(monkeypatch):
    fakes = {
        "add_solar_message": MagicMock(),
        "add_solar_decision": MagicMock(),
        "reopen_solar_request": MagicMock(),
        "delete_solar_request": MagicMock(),
    }
    for name, spy in fakes.items():
        monkeypatch.setattr(solar_request_service, name, spy)
    return fakes


@pytest.fixture
def authenticated_client(fake_service):
    app.dependency_overrides[get_current_user] = _override_get_current_user
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_moment] = _override_get_current_moment

    yield TestClient(app)

    app.dependency_overrides.clear()


@pytest.fixture
def unauthenticated_client(fake_service):
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_moment] = _override_get_current_moment

    yield TestClient(app)

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /messages
# ---------------------------------------------------------------------------


def test_messages_success_returns_200(authenticated_client, fake_service):
    fake_service["add_solar_message"].return_value = _state(_request())

    response = authenticated_client.post(
        f"/api/v1/solar/requests/{REQUEST_ID}/messages",
        json={"clientEventId": "evt-1", "message": "8월 1일까지야"},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    fake_service["add_solar_message"].assert_called_once_with(
        None, user_id=TEST_USER_ID, request_id=REQUEST_ID, client_event_id="evt-1", message="8월 1일까지야", now=NOW
    )


def test_messages_missing_auth_returns_401(unauthenticated_client, fake_service):
    response = unauthenticated_client.post(
        f"/api/v1/solar/requests/{REQUEST_ID}/messages",
        json={"clientEventId": "evt-1", "message": "내용"},
    )
    assert response.status_code == 401
    fake_service["add_solar_message"].assert_not_called()


@pytest.mark.parametrize("overrides", [{"message": ""}, {"message": "   "}, {"clientEventId": ""}])
def test_messages_blank_body_returns_400(authenticated_client, fake_service, overrides):
    body = {"clientEventId": "evt-1", "message": "내용"}
    body.update(overrides)
    response = authenticated_client.post(
        f"/api/v1/solar/requests/{REQUEST_ID}/messages", json=body, headers=AUTH_HEADERS
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MALFORMED_REQUEST"
    fake_service["add_solar_message"].assert_not_called()


@pytest.mark.parametrize(
    ("status_code", "code"),
    [(404, "REQUEST_NOT_FOUND"), (409, "INVALID_REQUEST_STATE"), (409, "TARGET_AMBIGUOUS"), (503, "SOLAR_UNAVAILABLE")],
)
def test_messages_error_codes_mapped_through(authenticated_client, fake_service, status_code, code):
    fake_service["add_solar_message"].side_effect = ApiError(status_code, code, "에러")
    response = authenticated_client.post(
        f"/api/v1/solar/requests/{REQUEST_ID}/messages",
        json={"clientEventId": "evt-1", "message": "내용"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code


# ---------------------------------------------------------------------------
# POST /decisions
# ---------------------------------------------------------------------------


def test_decisions_success_returns_200(authenticated_client, fake_service):
    fake_service["add_solar_decision"].return_value = _state(_request(status=SolarRequestStatus.FINAL_REVIEW))

    response = authenticated_client.post(
        f"/api/v1/solar/requests/{REQUEST_ID}/decisions",
        json={"clientEventId": "evt-2", "decision": "NO"},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    fake_service["add_solar_decision"].assert_called_once_with(
        None, user_id=TEST_USER_ID, request_id=REQUEST_ID, client_event_id="evt-2", decision="NO", now=NOW
    )


def test_decisions_invalid_value_returns_400(authenticated_client, fake_service):
    response = authenticated_client.post(
        f"/api/v1/solar/requests/{REQUEST_ID}/decisions",
        json={"clientEventId": "evt-2", "decision": "MAYBE"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 400
    fake_service["add_solar_decision"].assert_not_called()


def test_decisions_conflict_mapped_through(authenticated_client, fake_service):
    fake_service["add_solar_decision"].side_effect = ApiError(409, "INVALID_REQUEST_STATE", "에러")
    response = authenticated_client.post(
        f"/api/v1/solar/requests/{REQUEST_ID}/decisions",
        json={"clientEventId": "evt-2", "decision": "YES"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_REQUEST_STATE"


# ---------------------------------------------------------------------------
# POST /reopen
# ---------------------------------------------------------------------------


def test_reopen_success_returns_200(authenticated_client, fake_service):
    fake_service["reopen_solar_request"].return_value = _state(_request(status=SolarRequestStatus.CHANGE_INPUT))

    response = authenticated_client.post(f"/api/v1/solar/requests/{REQUEST_ID}/reopen", headers=AUTH_HEADERS)

    assert response.status_code == 200
    fake_service["reopen_solar_request"].assert_called_once_with(None, user_id=TEST_USER_ID, request_id=REQUEST_ID, now=NOW)


def test_reopen_invalid_state_mapped_through(authenticated_client, fake_service):
    fake_service["reopen_solar_request"].side_effect = ApiError(409, "INVALID_REQUEST_STATE", "에러")
    response = authenticated_client.post(f"/api/v1/solar/requests/{REQUEST_ID}/reopen", headers=AUTH_HEADERS)
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# DELETE /solar/requests/{id}
# ---------------------------------------------------------------------------


def test_delete_success_returns_204(authenticated_client, fake_service):
    fake_service["delete_solar_request"].return_value = None

    response = authenticated_client.delete(f"/api/v1/solar/requests/{REQUEST_ID}", headers=AUTH_HEADERS)

    assert response.status_code == 204
    assert response.content == b""
    fake_service["delete_solar_request"].assert_called_once_with(None, user_id=TEST_USER_ID, request_id=REQUEST_ID)


def test_delete_not_found_mapped_through(authenticated_client, fake_service):
    fake_service["delete_solar_request"].side_effect = ApiError(404, "REQUEST_NOT_FOUND", "에러")
    response = authenticated_client.delete(f"/api/v1/solar/requests/{REQUEST_ID}", headers=AUTH_HEADERS)
    assert response.status_code == 404


def test_delete_invalid_state_mapped_through(authenticated_client, fake_service):
    fake_service["delete_solar_request"].side_effect = ApiError(409, "INVALID_REQUEST_STATE", "에러")
    response = authenticated_client.delete(f"/api/v1/solar/requests/{REQUEST_ID}", headers=AUTH_HEADERS)
    assert response.status_code == 409
