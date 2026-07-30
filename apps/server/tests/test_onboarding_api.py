import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import me as me_module
from app.core.security import AuthenticatedUser, get_current_user
from app.db.session import get_db
from app.main import app
from app.models.user_profile import UserProfile

TEST_USER_ID = uuid.uuid4()
TEST_EMAIL = "test-user@example.com"
AUTH_HEADERS = {"Authorization": "Bearer irrelevant-because-dependency-is-overridden"}


class _FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDb:
    def __init__(self, email=TEST_EMAIL):
        self.email = email

    def begin(self):
        return _FakeTransaction()

    def execute(self, *args, **kwargs):
        return _FakeResult(self.email)


def _override_get_current_user():
    return AuthenticatedUser(id=TEST_USER_ID)


def _override_get_db():
    yield _FakeDb()


@pytest.fixture
def fake_upsert(monkeypatch):
    now = datetime.now(timezone.utc)

    def _upsert(db, user_id, nickname):
        return UserProfile(
            id=user_id,
            nickname=nickname,
            onboarding_completed=True,
            created_at=now,
            updated_at=now,
        )

    spy = MagicMock(wraps=_upsert)
    monkeypatch.setattr(me_module, "upsert_onboarding_profile", spy)
    return spy


@pytest.fixture
def authenticated_client(fake_upsert):
    app.dependency_overrides[get_current_user] = _override_get_current_user
    app.dependency_overrides[get_db] = _override_get_db

    yield TestClient(app)

    app.dependency_overrides.clear()


@pytest.fixture
def unauthenticated_client(fake_upsert):
    # get_current_user는 override하지 않고 실제 dependency를 그대로 사용한다.
    # Authorization 헤더가 없으면 verify_access_token/JWKS에 도달하기 전에
    # get_current_user 자체에서 401을 반환하므로 네트워크나 SUPABASE_URL이 필요 없다.
    app.dependency_overrides[get_db] = _override_get_db

    yield TestClient(app)

    app.dependency_overrides.clear()


def test_creates_new_profile_and_returns_envelope(authenticated_client, fake_upsert):
    response = authenticated_client.put(
        "/api/v1/me/onboarding", json={"nickname": "유림"}, headers=AUTH_HEADERS
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"data"}
    data = body["data"]
    assert data["id"] == str(TEST_USER_ID)
    assert data["email"] == TEST_EMAIL
    assert data["nickname"] == "유림"
    assert data["onboardingCompleted"] is True
    assert "createdAt" in data
    assert "updatedAt" in data

    fake_upsert.assert_called_once()
    _, called_user_id, called_nickname = fake_upsert.call_args.args
    assert called_user_id == TEST_USER_ID
    assert called_nickname == "유림"


def test_updates_existing_profile_with_trimmed_nickname(authenticated_client, fake_upsert):
    response = authenticated_client.put(
        "/api/v1/me/onboarding", json={"nickname": "  유림  "}, headers=AUTH_HEADERS
    )

    assert response.status_code == 200
    assert response.json()["data"]["nickname"] == "유림"

    _, _, called_nickname = fake_upsert.call_args.args
    assert called_nickname == "유림"


def test_blank_nickname_returns_422_and_no_db_write(authenticated_client, fake_upsert):
    response = authenticated_client.put(
        "/api/v1/me/onboarding", json={"nickname": "   "}, headers=AUTH_HEADERS
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "INVALID_NICKNAME"
    assert body["error"]["message"] == "닉네임을 입력해 주세요."
    assert body["error"]["details"] == {}
    assert "traceId" in body["error"]

    fake_upsert.assert_not_called()


def test_missing_nickname_returns_400_and_no_db_write(authenticated_client, fake_upsert):
    response = authenticated_client.put(
        "/api/v1/me/onboarding", json={}, headers=AUTH_HEADERS
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "MALFORMED_REQUEST"
    assert body["error"]["message"] == "요청 형식이 올바르지 않아요."

    fake_upsert.assert_not_called()


def test_non_string_nickname_returns_400_and_no_db_write(authenticated_client, fake_upsert):
    response = authenticated_client.put(
        "/api/v1/me/onboarding", json={"nickname": 12345}, headers=AUTH_HEADERS
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MALFORMED_REQUEST"

    fake_upsert.assert_not_called()


def test_extra_field_is_rejected_with_400_and_no_db_write(authenticated_client, fake_upsert):
    response = authenticated_client.put(
        "/api/v1/me/onboarding",
        json={"nickname": "유림", "userId": str(uuid.uuid4())},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MALFORMED_REQUEST"

    fake_upsert.assert_not_called()


def test_malformed_json_returns_400_and_no_db_write(authenticated_client, fake_upsert):
    response = authenticated_client.put(
        "/api/v1/me/onboarding",
        content=b"{not valid json",
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MALFORMED_REQUEST"

    fake_upsert.assert_not_called()


def test_missing_body_returns_400_and_no_db_write(authenticated_client, fake_upsert):
    response = authenticated_client.put(
        "/api/v1/me/onboarding",
        content=b"",
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MALFORMED_REQUEST"

    fake_upsert.assert_not_called()


def test_missing_authorization_header_returns_401_and_no_db_write(
    unauthenticated_client, fake_upsert
):
    response = unauthenticated_client.put("/api/v1/me/onboarding", json={"nickname": "유림"})

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "AUTH_REQUIRED"

    fake_upsert.assert_not_called()
