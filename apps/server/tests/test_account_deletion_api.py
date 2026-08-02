"""DELETE /me endpoint 테스트. account_deletion_service.delete_account를 mock하지 않고
실제로 호출해, get_db()/get_current_user()가 이미 열린 트랜잭션을 주지 않는 실제 의존성
구조에서 delete_account의 단독 with db.begin()이 중첩 트랜잭션 오류 없이 동작하는지까지
endpoint 레벨에서 확인한다(단위 테스트는 test_account_deletion_service.py에 있음)."""

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Select
from sqlalchemy.sql.dml import Delete

from app.core.security import AuthenticatedUser, get_current_user
from app.db.session import get_db
from app.main import app
from app.models.user_profile import UserProfile
from app.services import supabase_admin_client

TEST_USER_ID = uuid.uuid4()
AUTH_HEADERS = {"Authorization": "Bearer irrelevant-because-dependency-is-overridden"}


class _FakeResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return self

    def one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeTransaction:
    def __init__(self, session):
        self._session = session

    def __enter__(self):
        if self._session.in_transaction:
            raise RuntimeError("중첩 트랜잭션이 시도됐다.")
        self._session.in_transaction = True
        return self._session

    def __exit__(self, exc_type, exc, tb):
        self._session.in_transaction = False
        return False


class _FakeDb:
    """실제 account_deletion_service.delete_account를 그대로 실행할 수 있는 fake 세션.
    profile 유무에 따라 SELECT ... FOR UPDATE 결과가 갈리고, DELETE 문은 전부 성공한 것으로
    취급한다(순서·스코프는 test_account_deletion_service.py에서 이미 검증함 — 여기서는
    endpoint↔service 연결과 트랜잭션 중첩 여부만 본다)."""

    def __init__(self, *, profile):
        self.in_transaction = False
        self._profile = profile

    def begin(self):
        return _FakeTransaction(self)

    def execute(self, stmt):
        if isinstance(stmt, Select):
            return _FakeResult([self._profile] if self._profile is not None else [])
        if isinstance(stmt, Delete):
            return None
        raise AssertionError(f"예상하지 못한 statement: {stmt!r}")


def _override_get_current_user():
    return AuthenticatedUser(id=TEST_USER_ID)


def _make_profile():
    return UserProfile(id=TEST_USER_ID, nickname="탈퇴예정", onboarding_completed=True)


@pytest.fixture(autouse=True)
def _supabase_config_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")


@pytest.fixture
def mock_delete_auth_user(monkeypatch):
    mock = MagicMock(return_value=None)
    monkeypatch.setattr(supabase_admin_client, "delete_auth_user", mock)
    return mock


def _client_with_db(fake_db, *, authenticated: bool):
    if authenticated:
        app.dependency_overrides[get_current_user] = _override_get_current_user

    def _override_get_db():
        yield fake_db

    app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(app)
    return client


def test_delete_me_returns_204_with_real_service_and_no_nested_transaction_error(
    mock_delete_auth_user,
):
    fake_db = _FakeDb(profile=_make_profile())
    client = _client_with_db(fake_db, authenticated=True)
    try:
        response = client.delete("/api/v1/me", headers=AUTH_HEADERS)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204
    mock_delete_auth_user.assert_called_once_with(TEST_USER_ID)


def test_delete_me_without_authorization_returns_401(mock_delete_auth_user):
    fake_db = _FakeDb(profile=_make_profile())
    client = _client_with_db(fake_db, authenticated=False)
    try:
        response = client.delete("/api/v1/me")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    mock_delete_auth_user.assert_not_called()


def test_delete_me_is_idempotent_on_repeated_call(mock_delete_auth_user):
    """1차 호출로 프로필이 삭제된 뒤 2차 호출해도(프로필 없음) 204가 반복된다."""
    fake_db_first = _FakeDb(profile=_make_profile())
    client = _client_with_db(fake_db_first, authenticated=True)
    try:
        first_response = client.delete("/api/v1/me", headers=AUTH_HEADERS)
    finally:
        app.dependency_overrides.clear()
    assert first_response.status_code == 204

    fake_db_second = _FakeDb(profile=None)  # 이미 삭제된 상태
    client = _client_with_db(fake_db_second, authenticated=True)
    try:
        second_response = client.delete("/api/v1/me", headers=AUTH_HEADERS)
    finally:
        app.dependency_overrides.clear()

    assert second_response.status_code == 204
    assert mock_delete_auth_user.call_count == 2


def test_first_call_db_succeeds_auth_fails_second_call_db_no_targets_auth_retries_succeeds(
    monkeypatch,
):
    """1차 호출: DB 삭제는 성공하지만 Auth 삭제가 실패해 500. 2차 호출: DB 삭제 대상은 이미
    0건이지만 Auth 삭제를 재시도해 성공 → 204."""
    delete_auth_user = MagicMock(side_effect=[RuntimeError("Supabase Auth 삭제가 실패했다: 500"), None])
    monkeypatch.setattr(supabase_admin_client, "delete_auth_user", delete_auth_user)

    fake_db_first = _FakeDb(profile=_make_profile())
    client = _client_with_db(fake_db_first, authenticated=True)
    try:
        first_response = client.delete("/api/v1/me", headers=AUTH_HEADERS)
    finally:
        app.dependency_overrides.clear()
    assert first_response.status_code == 500
    assert first_response.json()["error"]["code"] == "ACCOUNT_AUTH_DELETION_FAILED"

    fake_db_second = _FakeDb(profile=None)  # 1차에서 이미 DB는 삭제됨
    client = _client_with_db(fake_db_second, authenticated=True)
    try:
        second_response = client.delete("/api/v1/me", headers=AUTH_HEADERS)
    finally:
        app.dependency_overrides.clear()

    assert second_response.status_code == 204
    assert delete_auth_user.call_count == 2
