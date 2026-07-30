import uuid
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.core.config import get_supabase_url
from app.core.errors import ApiError

_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    id: uuid.UUID


@lru_cache(maxsize=1)
def get_jwks_client() -> PyJWKClient:
    supabase_url = get_supabase_url()
    return PyJWKClient(f"{supabase_url}/auth/v1/.well-known/jwks.json")


def _fetch_signing_keys(jwks_client: PyJWKClient, refresh: bool):
    try:
        return jwks_client.get_signing_keys(refresh=refresh)
    except jwt.PyJWKClientConnectionError:
        # JWKS endpoint 네트워크 장애 — 서버/인프라 오류. 401로 위장하지 않는다.
        raise RuntimeError("JWKS endpoint 조회에 실패했다.") from None
    except (jwt.PyJWKClientError, jwt.PyJWKSetError):
        # JWKS 응답이 올바른 JSON 구조가 아니거나(PyJWKSetError) signing key가
        # 하나도 없는 경우(PyJWKClientError) — 클라이언트 토큰 문제가 아니라 서버/인프라 오류.
        raise RuntimeError("JWKS 응답에서 유효한 signing key를 찾을 수 없다.") from None


def _get_signing_key(jwks_client: PyJWKClient, kid: str):
    keys = _fetch_signing_keys(jwks_client, refresh=False)
    matching_key = next((key for key in keys if key.key_id == kid), None)

    if matching_key is None:
        keys = _fetch_signing_keys(jwks_client, refresh=True)
        matching_key = next((key for key in keys if key.key_id == kid), None)

    if matching_key is None:
        # 두 번 모두 정상적인 JWKS를 받았지만 일치하는 kid가 없음 — 클라이언트 토큰 문제
        raise ApiError(401, "AUTH_REQUIRED", "로그인이 필요해요.")

    return matching_key.key


def _extract_user_id(payload: dict) -> uuid.UUID:
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        raise ApiError(401, "AUTH_REQUIRED", "로그인이 필요해요.")
    try:
        return uuid.UUID(sub)
    except ValueError:
        raise ApiError(401, "AUTH_REQUIRED", "로그인이 필요해요.")


def verify_access_token(token: str) -> uuid.UUID:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.exceptions.InvalidTokenError:
        raise ApiError(401, "AUTH_REQUIRED", "로그인이 필요해요.") from None

    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise ApiError(401, "AUTH_REQUIRED", "로그인이 필요해요.")

    alg = header.get("alg")
    if alg != "ES256":
        # jwt.decode(algorithms=["ES256"])를 대체하는 것이 아니라, JWKS 조회 자체를
        # 생략하기 위한 조기 차단이다. decode 단계의 algorithms 고정은 그대로 유지한다.
        raise ApiError(401, "AUTH_REQUIRED", "로그인이 필요해요.")

    jwks_client = get_jwks_client()
    signing_key = _get_signing_key(jwks_client, kid)

    supabase_url = get_supabase_url()
    try:
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["ES256"],
            audience="authenticated",
            issuer=f"{supabase_url}/auth/v1",
            options={"require": ["exp", "sub", "aud", "iss"]},
        )
    except jwt.exceptions.PyJWTError:
        # 만료·서명 불일치·issuer/audience 불일치·비허용 algorithm·필수 claim(exp/sub/aud/iss)
        # 누락 등 전부 포함
        raise ApiError(401, "AUTH_REQUIRED", "로그인이 필요해요.")

    return _extract_user_id(payload)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthenticatedUser:
    if credentials is None or not credentials.credentials.strip():
        raise ApiError(401, "AUTH_REQUIRED", "로그인이 필요해요.")

    user_id = verify_access_token(credentials.credentials)
    return AuthenticatedUser(id=user_id)
