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
from app.services import check_in_service
from app.services.check_in_service import AcknowledgeResult

SEOUL_TZ = ZoneInfo("Asia/Seoul")

TEST_USER_ID = uuid.uuid4()
TARGET_ID = uuid.uuid4()
OLDER_ID = uuid.uuid4()
AUTH_HEADERS = {"Authorization": "Bearer irrelevant-because-dependency-is-overridden"}
FIXED_NOW = datetime(2026, 7, 29, 14, 45, tzinfo=SEOUL_TZ)

ENDPOINT = f"/api/v1/check-ins/{TARGET_ID}/acknowledge"


def _override_get_current_user():
    return AuthenticatedUser(id=TEST_USER_ID)


def _override_get_db():
    yield None  # 서비스 함수를 monkeypatch로 대체하므로 실제 세션이 필요 없다.


def _override_get_current_moment():
    return FIXED_NOW


@pytest.fixture
def fake_acknowledge(monkeypatch):
    spy = MagicMock()
    monkeypatch.setattr(check_in_service, "acknowledge_check_in", spy)
    return spy


@pytest.fixture
def authenticated_client(fake_acknowledge):
    app.dependency_overrides[get_current_user] = _override_get_current_user
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_moment] = _override_get_current_moment

    yield TestClient(app)

    app.dependency_overrides.clear()


@pytest.fixture
def unauthenticated_client(fake_acknowledge):
    # get_current_user는 override하지 않고 실제 dependency를 그대로 사용한다.
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_moment] = _override_get_current_moment

    yield TestClient(app)

    app.dependency_overrides.clear()


def test_acknowledge_returns_service_result_as_camel_case(authenticated_client, fake_acknowledge):
    fake_acknowledge.return_value = AcknowledgeResult(
        target_check_in_id=TARGET_ID,
        acknowledged_check_in_ids=[OLDER_ID, TARGET_ID],
        result_acknowledged_at=FIXED_NOW,
    )

    response = authenticated_client.post(ENDPOINT, headers=AUTH_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"data"}
    data = body["data"]
    assert set(data.keys()) == {
        "targetCheckInId",
        "acknowledgedCheckInIds",
        "acknowledgedCount",
        "resultAcknowledgedAt",
    }
    assert data["targetCheckInId"] == str(TARGET_ID)
    assert data["acknowledgedCheckInIds"] == [str(OLDER_ID), str(TARGET_ID)]
    assert data["acknowledgedCount"] == 2
    assert data["resultAcknowledgedAt"] is not None

    fake_acknowledge.assert_called_once()
    call_kwargs = fake_acknowledge.call_args.kwargs
    assert call_kwargs["user_id"] == TEST_USER_ID
    assert call_kwargs["check_in_id"] == TARGET_ID
    assert call_kwargs["now"] == FIXED_NOW


def test_acknowledge_request_body_not_required(authenticated_client, fake_acknowledge):
    fake_acknowledge.return_value = AcknowledgeResult(
        target_check_in_id=TARGET_ID,
        acknowledged_check_in_ids=[TARGET_ID],
        result_acknowledged_at=FIXED_NOW,
    )

    # body를 아예 보내지 않아도(POST without json) 정상 처리돼야 한다.
    response = authenticated_client.post(ENDPOINT, headers=AUTH_HEADERS)

    assert response.status_code == 200


def test_acknowledge_target_only_count_is_one(authenticated_client, fake_acknowledge):
    fake_acknowledge.return_value = AcknowledgeResult(
        target_check_in_id=TARGET_ID,
        acknowledged_check_in_ids=[TARGET_ID],
        result_acknowledged_at=FIXED_NOW,
    )

    response = authenticated_client.post(ENDPOINT, headers=AUTH_HEADERS)

    data = response.json()["data"]
    assert data["acknowledgedCheckInIds"] == [str(TARGET_ID)]
    assert data["acknowledgedCount"] == 1


def test_acknowledge_missing_check_in_returns_404(authenticated_client, fake_acknowledge):
    fake_acknowledge.side_effect = ApiError(
        404, check_in_service.CODE_CHECK_IN_NOT_FOUND, "CheckIn을 찾을 수 없어요."
    )

    response = authenticated_client.post(ENDPOINT, headers=AUTH_HEADERS)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CHECK_IN_NOT_FOUND"


def test_acknowledge_other_users_check_in_returns_404(authenticated_client, fake_acknowledge):
    """타인 소유와 존재하지 않는 경우를 서버가 구분하지 않으므로 동일한 404 코드를 반환한다."""
    fake_acknowledge.side_effect = ApiError(
        404, check_in_service.CODE_CHECK_IN_NOT_FOUND, "CheckIn을 찾을 수 없어요."
    )

    response = authenticated_client.post(ENDPOINT, headers=AUTH_HEADERS)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CHECK_IN_NOT_FOUND"


def test_acknowledge_unfinalized_check_in_returns_409(authenticated_client, fake_acknowledge):
    fake_acknowledge.side_effect = ApiError(
        409, check_in_service.CODE_INVALID_REQUEST_STATE, "정산이 끝나지 않은 결과예요."
    )

    response = authenticated_client.post(ENDPOINT, headers=AUTH_HEADERS)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_REQUEST_STATE"


def test_missing_authorization_header_returns_401(unauthenticated_client, fake_acknowledge):
    response = unauthenticated_client.post(ENDPOINT)

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "AUTH_REQUIRED"

    fake_acknowledge.assert_not_called()


def test_acknowledge_duplicate_call_returns_existing_result_acknowledged_at(
    authenticated_client, fake_acknowledge
):
    original_ack_at = datetime(2026, 7, 29, 14, 45, tzinfo=SEOUL_TZ)
    fake_acknowledge.return_value = AcknowledgeResult(
        target_check_in_id=TARGET_ID,
        acknowledged_check_in_ids=[OLDER_ID, TARGET_ID],
        result_acknowledged_at=original_ack_at,
    )

    response = authenticated_client.post(ENDPOINT, headers=AUTH_HEADERS)

    data = response.json()["data"]
    assert data["resultAcknowledgedAt"] == original_ack_at.isoformat()
    assert data["acknowledgedCheckInIds"] == [str(OLDER_ID), str(TARGET_ID)]
