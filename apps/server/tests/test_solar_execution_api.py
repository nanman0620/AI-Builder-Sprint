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
from app.services.solar_request_service import (
    AcknowledgeExecutionResult,
    ExecutionTransitionResult,
    PlanManagementScreenMode,
    SolarExecutionErrorView,
    SolarExecutionView,
)
from app.workers.solar_execution_worker import get_solar_execution_dispatcher

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
        status=SolarRequestStatus.EXECUTING,
        raw_input="테스트 입력",
        current_item_order=None,
        confirmed_at=None,
        execution_started_at=NOW,
        executed_at=None,
        execution_attempt_count=1,
        execution_result=None,
        error_code=None,
        error_message=None,
        result_acknowledged_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
    defaults.update(overrides)
    return SolarRequest(**defaults)


def _override_get_current_user():
    return AuthenticatedUser(id=TEST_USER_ID)


def _override_get_db():
    yield None


def _override_get_current_moment():
    return NOW


class _FakeDispatcher:
    def __init__(self):
        self.registered: list[uuid.UUID] = []

    def register(self, request_id: uuid.UUID) -> None:
        self.registered.append(request_id)


@pytest.fixture
def fake_dispatcher():
    return _FakeDispatcher()


@pytest.fixture
def fake_service(monkeypatch):
    fakes = {
        "execute_solar_request": MagicMock(),
        "retry_solar_request": MagicMock(),
        "get_solar_request_execution": MagicMock(),
        "acknowledge_solar_execution_result": MagicMock(),
    }
    for name, spy in fakes.items():
        monkeypatch.setattr(solar_request_service, name, spy)
    return fakes


@pytest.fixture
def authenticated_client(fake_service, fake_dispatcher):
    app.dependency_overrides[get_current_user] = _override_get_current_user
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_moment] = _override_get_current_moment
    app.dependency_overrides[get_solar_execution_dispatcher] = lambda: fake_dispatcher

    yield TestClient(app)

    app.dependency_overrides.clear()


@pytest.fixture
def unauthenticated_client(fake_service, fake_dispatcher):
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_moment] = _override_get_current_moment
    app.dependency_overrides[get_solar_execution_dispatcher] = lambda: fake_dispatcher

    yield TestClient(app)

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /execute
# ---------------------------------------------------------------------------


def test_execute_success_returns_202(authenticated_client, fake_service, fake_dispatcher):
    fake_service["execute_solar_request"].return_value = ExecutionTransitionResult(
        request=_request(status=SolarRequestStatus.EXECUTING), transitioned=True
    )

    response = authenticated_client.post(f"/api/v1/solar/requests/{REQUEST_ID}/execute", headers=AUTH_HEADERS)

    assert response.status_code == 202
    body = response.json()["data"]
    assert body["requestId"] == str(REQUEST_ID)
    assert body["status"] == "EXECUTING"
    assert body["screenMode"] == "EXECUTING"
    assert body["executionAttemptCount"] == 1
    fake_service["execute_solar_request"].assert_called_once_with(
        None, user_id=TEST_USER_ID, request_id=REQUEST_ID, now=NOW, dispatcher=fake_dispatcher
    )


def test_execute_idempotent_duplicate_still_returns_202(authenticated_client, fake_service):
    """이미 EXECUTING이라 이번 호출이 전이를 일으키지 않아도 202를 유지한다(명세 8-1절, 공개
    응답에 transitioned 같은 신규 필드를 추가하지 않는다)."""
    fake_service["execute_solar_request"].return_value = ExecutionTransitionResult(
        request=_request(status=SolarRequestStatus.EXECUTING), transitioned=False
    )

    response = authenticated_client.post(f"/api/v1/solar/requests/{REQUEST_ID}/execute", headers=AUTH_HEADERS)

    assert response.status_code == 202
    assert "transitioned" not in response.json()["data"]


def test_execute_missing_auth_returns_401(unauthenticated_client, fake_service):
    response = unauthenticated_client.post(f"/api/v1/solar/requests/{REQUEST_ID}/execute")
    assert response.status_code == 401
    fake_service["execute_solar_request"].assert_not_called()


@pytest.mark.parametrize(
    ("status_code", "code"),
    [
        (404, "REQUEST_NOT_FOUND"),
        (409, "INVALID_REQUEST_STATE"),
        (409, "ACTIVE_CYCLE_EXISTS"),
        (409, "CYCLE_NOT_ACTIVE"),
        (409, "SETTLEMENT_IN_PROGRESS"),
        (409, "TARGET_AMBIGUOUS"),
    ],
)
def test_execute_error_codes_mapped_through(authenticated_client, fake_service, status_code, code):
    fake_service["execute_solar_request"].side_effect = ApiError(status_code, code, "에러")
    response = authenticated_client.post(f"/api/v1/solar/requests/{REQUEST_ID}/execute", headers=AUTH_HEADERS)
    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code


def test_execute_dispatcher_dependency_is_injected(authenticated_client, fake_service, fake_dispatcher):
    fake_service["execute_solar_request"].return_value = ExecutionTransitionResult(
        request=_request(status=SolarRequestStatus.EXECUTING), transitioned=True
    )

    authenticated_client.post(f"/api/v1/solar/requests/{REQUEST_ID}/execute", headers=AUTH_HEADERS)

    call = fake_service["execute_solar_request"].call_args
    assert call.kwargs["dispatcher"] is fake_dispatcher


# ---------------------------------------------------------------------------
# GET /execution
# ---------------------------------------------------------------------------


def test_get_execution_executing_returns_no_error(authenticated_client, fake_service):
    fake_service["get_solar_request_execution"].return_value = SolarExecutionView(
        request_id=REQUEST_ID,
        purpose=SolarRequestPurpose.ACTIVE_CYCLE,
        status=SolarRequestStatus.EXECUTING,
        screen_mode=PlanManagementScreenMode.EXECUTING,
        execution_started_at=NOW,
        execution_attempt_count=1,
        executed_at=None,
        execution_result=None,
        error=None,
    )

    response = authenticated_client.get(f"/api/v1/solar/requests/{REQUEST_ID}/execution", headers=AUTH_HEADERS)

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["status"] == "EXECUTING"
    assert body["error"] is None
    fake_service["get_solar_request_execution"].assert_called_once_with(
        None, user_id=TEST_USER_ID, request_id=REQUEST_ID
    )


def test_get_execution_failed_returns_error_block(authenticated_client, fake_service):
    fake_service["get_solar_request_execution"].return_value = SolarExecutionView(
        request_id=REQUEST_ID,
        purpose=SolarRequestPurpose.ACTIVE_CYCLE,
        status=SolarRequestStatus.FAILED,
        screen_mode=PlanManagementScreenMode.EXECUTION_FAILED,
        execution_started_at=NOW,
        execution_attempt_count=1,
        executed_at=None,
        execution_result=None,
        error=SolarExecutionErrorView(code="PLAN_EXECUTION_FAILED", message="실패", retryable=True),
    )

    response = authenticated_client.get(f"/api/v1/solar/requests/{REQUEST_ID}/execution", headers=AUTH_HEADERS)

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["status"] == "FAILED"
    assert body["error"] == {"code": "PLAN_EXECUTION_FAILED", "message": "실패", "retryable": True}


def test_get_execution_not_found_returns_404(authenticated_client, fake_service):
    fake_service["get_solar_request_execution"].side_effect = ApiError(404, "REQUEST_NOT_FOUND", "에러")
    response = authenticated_client.get(f"/api/v1/solar/requests/{REQUEST_ID}/execution", headers=AUTH_HEADERS)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REQUEST_NOT_FOUND"


def test_get_execution_missing_auth_returns_401(unauthenticated_client, fake_service):
    response = unauthenticated_client.get(f"/api/v1/solar/requests/{REQUEST_ID}/execution")
    assert response.status_code == 401
    fake_service["get_solar_request_execution"].assert_not_called()


# ---------------------------------------------------------------------------
# POST /retry
# ---------------------------------------------------------------------------


def test_retry_success_returns_202(authenticated_client, fake_service):
    fake_service["retry_solar_request"].return_value = ExecutionTransitionResult(
        request=_request(status=SolarRequestStatus.EXECUTING, execution_attempt_count=2), transitioned=True
    )

    response = authenticated_client.post(f"/api/v1/solar/requests/{REQUEST_ID}/retry", headers=AUTH_HEADERS)

    assert response.status_code == 202
    assert response.json()["data"]["executionAttemptCount"] == 2


def test_retry_invalid_state_mapped_through(authenticated_client, fake_service):
    fake_service["retry_solar_request"].side_effect = ApiError(409, "INVALID_REQUEST_STATE", "에러")
    response = authenticated_client.post(f"/api/v1/solar/requests/{REQUEST_ID}/retry", headers=AUTH_HEADERS)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_REQUEST_STATE"


def test_retry_missing_auth_returns_401(unauthenticated_client, fake_service):
    response = unauthenticated_client.post(f"/api/v1/solar/requests/{REQUEST_ID}/retry")
    assert response.status_code == 401
    fake_service["retry_solar_request"].assert_not_called()


# ---------------------------------------------------------------------------
# POST /acknowledge-result
# ---------------------------------------------------------------------------


def test_acknowledge_result_success_returns_200(authenticated_client, fake_service):
    fake_service["acknowledge_solar_execution_result"].return_value = AcknowledgeExecutionResult(
        request_id=REQUEST_ID,
        result_acknowledged_at=NOW,
        next_screen_mode=PlanManagementScreenMode.ACTIVE_CYCLE_ENTRY,
    )

    response = authenticated_client.post(
        f"/api/v1/solar/requests/{REQUEST_ID}/acknowledge-result", headers=AUTH_HEADERS
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["requestId"] == str(REQUEST_ID)
    assert body["nextPlanManagementScreenMode"] == "ACTIVE_CYCLE_ENTRY"
    fake_service["acknowledge_solar_execution_result"].assert_called_once_with(
        None, user_id=TEST_USER_ID, request_id=REQUEST_ID, now=NOW
    )


def test_acknowledge_result_invalid_state_mapped_through(authenticated_client, fake_service):
    fake_service["acknowledge_solar_execution_result"].side_effect = ApiError(409, "INVALID_REQUEST_STATE", "에러")
    response = authenticated_client.post(
        f"/api/v1/solar/requests/{REQUEST_ID}/acknowledge-result", headers=AUTH_HEADERS
    )
    assert response.status_code == 409


def test_acknowledge_result_not_found_returns_404(authenticated_client, fake_service):
    fake_service["acknowledge_solar_execution_result"].side_effect = ApiError(404, "REQUEST_NOT_FOUND", "에러")
    response = authenticated_client.post(
        f"/api/v1/solar/requests/{REQUEST_ID}/acknowledge-result", headers=AUTH_HEADERS
    )
    assert response.status_code == 404


def test_acknowledge_result_missing_auth_returns_401(unauthenticated_client, fake_service):
    response = unauthenticated_client.post(f"/api/v1/solar/requests/{REQUEST_ID}/acknowledge-result")
    assert response.status_code == 401
    fake_service["acknowledge_solar_execution_result"].assert_not_called()
