import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.core import security
from app.core.errors import ApiError

TEST_KID = "test-kid"
TEST_ISSUER = "https://test.supabase.co/auth/v1"


class _FakeSigningKey:
    def __init__(self, key_id, key):
        self.key_id = key_id
        self.key = key


class _FakeJwksClient:
    def __init__(self, keys):
        self._keys = keys

    def get_signing_keys(self, refresh: bool = False):
        return self._keys


class _ConnectionFailureJwksClient:
    def get_signing_keys(self, refresh: bool = False):
        raise jwt.PyJWKClientConnectionError("connection failed")


class _NoSigningKeysJwksClient:
    def get_signing_keys(self, refresh: bool = False):
        raise jwt.PyJWKClientError("no signing keys")


class _NeverCalledJwksClient:
    def get_signing_keys(self, refresh: bool = False):
        raise AssertionError("JWKS 조회가 호출되면 안 된다(조기 차단 검증용)")


@pytest.fixture
def key_pair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


def _make_token(
    private_key,
    sub=None,
    kid=TEST_KID,
    extra_claims=None,
    omit_claims=None,
    headers_override=None,
):
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub if sub is not None else str(uuid.uuid4()),
        "aud": "authenticated",
        "iss": TEST_ISSUER,
        "exp": now + timedelta(hours=1),
        "iat": now,
    }
    if extra_claims:
        payload.update(extra_claims)
    for claim in omit_claims or []:
        payload.pop(claim, None)

    headers = {}
    if kid is not None:
        headers["kid"] = kid
    if headers_override:
        headers.update(headers_override)

    return jwt.encode(payload, private_key, algorithm="ES256", headers=headers)


def _patch_supabase_url(monkeypatch):
    monkeypatch.setattr(security, "get_supabase_url", lambda: TEST_ISSUER.removesuffix("/auth/v1"))


def _patch_jwks_client(monkeypatch, client):
    monkeypatch.setattr(security, "get_jwks_client", lambda: client)


def test_valid_token_returns_user_id(monkeypatch, key_pair):
    private_key, public_key = key_pair
    expected_user_id = uuid.uuid4()
    token = _make_token(private_key, sub=str(expected_user_id))

    _patch_supabase_url(monkeypatch)
    _patch_jwks_client(monkeypatch, _FakeJwksClient([_FakeSigningKey(TEST_KID, public_key)]))

    user_id = security.verify_access_token(token)
    assert user_id == expected_user_id


def test_expired_token_raises_401(monkeypatch, key_pair):
    private_key, public_key = key_pair
    now = datetime.now(timezone.utc)
    token = _make_token(private_key, extra_claims={"exp": now - timedelta(hours=1)})

    _patch_supabase_url(monkeypatch)
    _patch_jwks_client(monkeypatch, _FakeJwksClient([_FakeSigningKey(TEST_KID, public_key)]))

    with pytest.raises(ApiError) as exc_info:
        security.verify_access_token(token)
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "AUTH_REQUIRED"


def test_tampered_signature_raises_401(monkeypatch, key_pair):
    private_key, _ = key_pair
    other_private_key = ec.generate_private_key(ec.SECP256R1())
    token = _make_token(private_key)

    _patch_supabase_url(monkeypatch)
    # 서명은 private_key로 했지만 검증용 공개키는 다른 키쌍의 것을 반환 -> 서명 불일치
    _patch_jwks_client(
        monkeypatch, _FakeJwksClient([_FakeSigningKey(TEST_KID, other_private_key.public_key())])
    )

    with pytest.raises(ApiError) as exc_info:
        security.verify_access_token(token)
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "AUTH_REQUIRED"


def test_alg_not_es256_raises_401_without_jwks_lookup(monkeypatch):
    # security.py가 헤더 alg를 확인한 뒤 JWKS 조회 전에 거부하는지 검증한다.
    # (HS256 서명 자체의 유효성 검증이 목적이 아니므로 평범한 임의 문자열 secret을 사용한다.)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "aud": "authenticated",
            "iss": TEST_ISSUER,
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        "irrelevant-test-secret-that-is-long-enough",
        algorithm="HS256",
        headers={"kid": TEST_KID},
    )

    _patch_supabase_url(monkeypatch)
    _patch_jwks_client(monkeypatch, _NeverCalledJwksClient())

    with pytest.raises(ApiError) as exc_info:
        security.verify_access_token(token)

    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "AUTH_REQUIRED"


def test_missing_authorization_header_raises_401():
    with pytest.raises(ApiError) as exc_info:
        security.get_current_user(credentials=None)
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "AUTH_REQUIRED"


def test_empty_bearer_token_raises_401():
    from fastapi.security import HTTPAuthorizationCredentials

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="   ")
    with pytest.raises(ApiError) as exc_info:
        security.get_current_user(credentials=credentials)
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "AUTH_REQUIRED"


@pytest.mark.parametrize(
    "extra_claims, omit_claims",
    [
        ({}, ["sub"]),
        ({"sub": 12345}, None),
        ({"sub": ""}, None),
        ({"sub": "not-a-uuid"}, None),
    ],
)
def test_invalid_sub_raises_401(monkeypatch, key_pair, extra_claims, omit_claims):
    private_key, public_key = key_pair
    token = _make_token(private_key, extra_claims=extra_claims, omit_claims=omit_claims)

    _patch_supabase_url(monkeypatch)
    _patch_jwks_client(monkeypatch, _FakeJwksClient([_FakeSigningKey(TEST_KID, public_key)]))

    with pytest.raises(ApiError) as exc_info:
        security.verify_access_token(token)
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "AUTH_REQUIRED"


def test_missing_exp_raises_401(monkeypatch, key_pair):
    private_key, public_key = key_pair
    token = _make_token(private_key, omit_claims=["exp"])

    _patch_supabase_url(monkeypatch)
    _patch_jwks_client(monkeypatch, _FakeJwksClient([_FakeSigningKey(TEST_KID, public_key)]))

    with pytest.raises(ApiError) as exc_info:
        security.verify_access_token(token)
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "AUTH_REQUIRED"


def test_missing_kid_raises_401(monkeypatch, key_pair):
    private_key, _ = key_pair
    token = _make_token(private_key, kid=None)

    _patch_supabase_url(monkeypatch)
    _patch_jwks_client(monkeypatch, _NeverCalledJwksClient())

    with pytest.raises(ApiError) as exc_info:
        security.verify_access_token(token)
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "AUTH_REQUIRED"


def test_kid_not_string_raises_401_without_jwks_lookup(monkeypatch):
    # 숫자형 kid는 jwt.encode() 단계에서 문제를 일으킬 수 있으므로,
    # get_unverified_header()를 직접 monkeypatch해 숫자형 kid 헤더를 반환하게 만든다.
    monkeypatch.setattr(
        security.jwt,
        "get_unverified_header",
        lambda token: {"alg": "ES256", "kid": 12345},
    )
    _patch_jwks_client(monkeypatch, _NeverCalledJwksClient())

    with pytest.raises(ApiError) as exc_info:
        security.verify_access_token("synthetic-token")

    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "AUTH_REQUIRED"


def test_malformed_token_raises_401(monkeypatch):
    _patch_supabase_url(monkeypatch)
    _patch_jwks_client(monkeypatch, _NeverCalledJwksClient())

    with pytest.raises(ApiError) as exc_info:
        security.verify_access_token("not-a-jwt")
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "AUTH_REQUIRED"


def test_no_matching_kid_after_refresh_raises_401(monkeypatch, key_pair):
    private_key, public_key = key_pair
    token = _make_token(private_key, kid="unknown-kid")

    _patch_supabase_url(monkeypatch)
    # refresh=False, refresh=True 모두 다른 kid만 반환 -> 두 번 다 불일치
    _patch_jwks_client(monkeypatch, _FakeJwksClient([_FakeSigningKey(TEST_KID, public_key)]))

    with pytest.raises(ApiError) as exc_info:
        security.verify_access_token(token)
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "AUTH_REQUIRED"


def test_jwks_network_failure_is_server_error_not_401(monkeypatch, key_pair):
    private_key, _ = key_pair
    token = _make_token(private_key)

    _patch_supabase_url(monkeypatch)
    _patch_jwks_client(monkeypatch, _ConnectionFailureJwksClient())

    with pytest.raises(RuntimeError):
        security.verify_access_token(token)


def test_jwks_no_signing_keys_is_server_error_not_401(monkeypatch, key_pair):
    private_key, _ = key_pair
    token = _make_token(private_key)

    _patch_supabase_url(monkeypatch)
    _patch_jwks_client(monkeypatch, _NoSigningKeysJwksClient())

    with pytest.raises(RuntimeError):
        security.verify_access_token(token)
