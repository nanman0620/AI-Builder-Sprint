"""supabase_admin_client.delete_auth_user 상태 코드 정책 테스트. conftest.py의 autouse
block_network가 urllib.request.urlopen을 기본 차단하므로, 여기서는 매 테스트마다 명시적으로
monkeypatch해 실제 네트워크를 전혀 타지 않는다."""

import urllib.error
import urllib.request
import uuid
from unittest.mock import MagicMock

import pytest

from app.services import supabase_admin_client

TEST_USER_ID = uuid.uuid4()


class _FakeHTTPResponse:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _http_error(status: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url="irrelevant", code=status, msg="error", hdrs=None, fp=None)


@pytest.fixture(autouse=True)
def _supabase_config_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key-value")


def test_2xx_succeeds_without_retry(monkeypatch):
    urlopen = MagicMock(return_value=_FakeHTTPResponse(204))
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    sleep = MagicMock()

    supabase_admin_client.delete_auth_user(TEST_USER_ID, sleep=sleep)

    assert urlopen.call_count == 1
    sleep.assert_not_called()


def test_404_is_idempotent_success_without_retry(monkeypatch):
    urlopen = MagicMock(side_effect=_http_error(404))
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    sleep = MagicMock()

    supabase_admin_client.delete_auth_user(TEST_USER_ID, sleep=sleep)

    assert urlopen.call_count == 1
    sleep.assert_not_called()


@pytest.mark.parametrize("status", [429, 500, 503])
def test_429_and_5xx_retry_three_times_with_backoff_then_fail(monkeypatch, status):
    urlopen = MagicMock(side_effect=_http_error(status))
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    sleep = MagicMock()

    with pytest.raises(RuntimeError, match=str(status)):
        supabase_admin_client.delete_auth_user(TEST_USER_ID, sleep=sleep)

    assert urlopen.call_count == 3
    assert sleep.call_args_list == [((0.2,),), ((0.5,),)]


def test_network_errors_retry_three_times_with_same_backoff(monkeypatch):
    urlopen = MagicMock(side_effect=urllib.error.URLError("connection refused"))
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    sleep = MagicMock()

    with pytest.raises(RuntimeError, match="네트워크"):
        supabase_admin_client.delete_auth_user(TEST_USER_ID, sleep=sleep)

    assert urlopen.call_count == 3
    assert sleep.call_args_list == [((0.2,),), ((0.5,),)]


def test_other_4xx_fails_immediately_without_retry_or_sleep(monkeypatch):
    urlopen = MagicMock(side_effect=_http_error(400))
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    sleep = MagicMock()

    with pytest.raises(RuntimeError, match="400"):
        supabase_admin_client.delete_auth_user(TEST_USER_ID, sleep=sleep)

    assert urlopen.call_count == 1
    sleep.assert_not_called()


def test_http_error_response_is_closed_on_404(monkeypatch):
    error = _http_error(404)
    error.close = MagicMock(wraps=error.close)
    monkeypatch.setattr(urllib.request, "urlopen", MagicMock(side_effect=error))

    supabase_admin_client.delete_auth_user(TEST_USER_ID, sleep=MagicMock())

    error.close.assert_called_once()


@pytest.mark.parametrize("status,expected_attempts", [(500, 3), (400, 1)])
def test_http_error_response_is_closed_on_every_attempt(monkeypatch, status, expected_attempts):
    error = _http_error(status)
    error.close = MagicMock(wraps=error.close)
    monkeypatch.setattr(urllib.request, "urlopen", MagicMock(side_effect=error))

    with pytest.raises(RuntimeError):
        supabase_admin_client.delete_auth_user(TEST_USER_ID, sleep=MagicMock())

    # 재시도 대상(500)은 시도할 때마다, 재시도 없는 4xx(400)는 1회만 close된다.
    assert error.close.call_count == expected_attempts


def test_request_includes_apikey_and_authorization_headers(monkeypatch):
    captured_request = {}

    def _fake_urlopen(request, timeout=None):
        captured_request["request"] = request
        return _FakeHTTPResponse(204)

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    supabase_admin_client.delete_auth_user(TEST_USER_ID, sleep=MagicMock())

    request = captured_request["request"]
    assert request.get_header("Apikey") == "test-service-role-key-value"
    assert request.get_header("Authorization") == "Bearer test-service-role-key-value"


def test_exception_messages_never_contain_service_role_key_or_headers(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", MagicMock(side_effect=_http_error(500)))

    with pytest.raises(RuntimeError) as exc_info:
        supabase_admin_client.delete_auth_user(TEST_USER_ID, sleep=MagicMock())

    message = str(exc_info.value)
    assert "test-service-role-key-value" not in message
    assert "Bearer" not in message
    assert "Authorization" not in message
