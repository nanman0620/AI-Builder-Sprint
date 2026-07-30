import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import ANY, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.security import AuthenticatedUser, get_current_user
from app.db.session import get_db
from app.main import app
from app.models.user_profile import UserProfile
from app.services import profile_service

TEST_USER_ID = uuid.uuid4()
OTHER_USER_ID = uuid.uuid4()
TEST_EMAIL = "profile-user@example.com"
CREATED_AT = datetime(2026, 7, 30, 9, 0, tzinfo=timezone.utc)
UPDATED_AT = datetime(2026, 7, 30, 9, 10, tzinfo=timezone.utc)
AUTH_HEADERS = {"Authorization": "Bearer irrelevant-because-dependency-is-overridden"}


class _FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeDb:
    def begin(self):
        return _FakeTransaction()


def _make_profile(**overrides):
    defaults = dict(
        id=TEST_USER_ID,
        nickname="유림",
        onboarding_completed=True,
        created_at=CREATED_AT,
        updated_at=UPDATED_AT,
    )
    defaults.update(overrides)
    return UserProfile(**defaults)


def _override_get_current_user():
    return AuthenticatedUser(id=TEST_USER_ID)


def _override_get_db():
    yield _FakeDb()


@pytest.fixture
def profile_dependencies(monkeypatch):
    get_profile = MagicMock(return_value=_make_profile())
    get_email = MagicMock(return_value=TEST_EMAIL)
    update_nickname = MagicMock(return_value=_make_profile(updated_at=UPDATED_AT + timedelta(minutes=5)))
    monkeypatch.setattr(profile_service, "get_profile", get_profile)
    monkeypatch.setattr(profile_service, "get_user_email", get_email)
    monkeypatch.setattr(profile_service, "update_nickname", update_nickname)
    return get_profile, get_email, update_nickname


@pytest.fixture
def authenticated_client(profile_dependencies):
    app.dependency_overrides[get_current_user] = _override_get_current_user
    app.dependency_overrides[get_db] = _override_get_db

    yield TestClient(app)

    app.dependency_overrides.clear()


@pytest.fixture
def unauthenticated_client(profile_dependencies):
    app.dependency_overrides[get_db] = _override_get_db

    yield TestClient(app)

    app.dependency_overrides.clear()


def test_get_me_returns_authenticated_users_profile_and_auth_email(
    authenticated_client, profile_dependencies
):
    get_profile, get_email, _ = profile_dependencies

    response = authenticated_client.get("/api/v1/me", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json() == {
        "data": {
            "id": str(TEST_USER_ID),
            "email": TEST_EMAIL,
            "nickname": "유림",
            "onboardingCompleted": True,
            "createdAt": CREATED_AT.isoformat().replace("+00:00", "Z"),
            "updatedAt": UPDATED_AT.isoformat().replace("+00:00", "Z"),
        }
    }
    get_profile.assert_called_once_with(ANY, TEST_USER_ID)
    get_email.assert_called_once_with(ANY, TEST_USER_ID)


def test_get_me_returns_404_when_profile_is_missing(authenticated_client, profile_dependencies):
    get_profile, get_email, _ = profile_dependencies
    get_profile.return_value = None

    response = authenticated_client.get("/api/v1/me", headers=AUTH_HEADERS)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROFILE_NOT_FOUND"
    get_email.assert_not_called()


def test_get_me_without_authorization_returns_401(unauthenticated_client, profile_dependencies):
    get_profile, get_email, _ = profile_dependencies

    response = unauthenticated_client.get("/api/v1/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    get_profile.assert_not_called()
    get_email.assert_not_called()


def test_get_me_never_uses_another_users_id(authenticated_client, profile_dependencies):
    get_profile, _, _ = profile_dependencies
    get_profile.side_effect = lambda db, user_id: (
        _make_profile() if user_id == TEST_USER_ID else _make_profile(id=OTHER_USER_ID)
    )

    response = authenticated_client.get("/api/v1/me", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["data"]["id"] == str(TEST_USER_ID)
    assert get_profile.call_args.args[1] == TEST_USER_ID


def test_patch_profile_trims_nickname_and_returns_latest_profile(
    authenticated_client, profile_dependencies
):
    _, get_email, update_nickname = profile_dependencies
    latest_updated_at = UPDATED_AT + timedelta(minutes=5)
    update_nickname.return_value = _make_profile(
        nickname="새 닉네임", updated_at=latest_updated_at
    )

    response = authenticated_client.patch(
        "/api/v1/me/profile",
        json={"nickname": "  새 닉네임  "},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["data"]["nickname"] == "새 닉네임"
    assert response.json()["data"]["updatedAt"] == latest_updated_at.isoformat().replace(
        "+00:00", "Z"
    )
    update_nickname.assert_called_once_with(ANY, TEST_USER_ID, "새 닉네임")
    get_email.assert_called_once_with(ANY, TEST_USER_ID)


def test_patch_profile_rejects_blank_nickname_without_writing(
    authenticated_client, profile_dependencies
):
    _, _, update_nickname = profile_dependencies

    response = authenticated_client.patch(
        "/api/v1/me/profile", json={"nickname": "   "}, headers=AUTH_HEADERS
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_NICKNAME"
    update_nickname.assert_not_called()


def test_patch_profile_rejects_extra_fields(authenticated_client, profile_dependencies):
    _, _, update_nickname = profile_dependencies

    response = authenticated_client.patch(
        "/api/v1/me/profile",
        json={"nickname": "유림", "email": "changed@example.com"},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MALFORMED_REQUEST"
    update_nickname.assert_not_called()


def test_patch_profile_without_authorization_returns_401(
    unauthenticated_client, profile_dependencies
):
    _, _, update_nickname = profile_dependencies

    response = unauthenticated_client.patch(
        "/api/v1/me/profile", json={"nickname": "유림"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    update_nickname.assert_not_called()


def test_patch_profile_returns_404_when_profile_is_missing(
    authenticated_client, profile_dependencies
):
    _, get_email, update_nickname = profile_dependencies
    update_nickname.return_value = None

    response = authenticated_client.patch(
        "/api/v1/me/profile", json={"nickname": "유림"}, headers=AUTH_HEADERS
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROFILE_NOT_FOUND"
    get_email.assert_not_called()
