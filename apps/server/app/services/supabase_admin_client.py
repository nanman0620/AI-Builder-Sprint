"""Supabase Auth Admin API 연동. solar_client.py와 동일하게 동기 `urllib.request`만 쓴다 —
이 저장소는 동기 SQLAlchemy Session·FastAPI 동기 endpoint(threadpool 실행) 구조라
블로킹 호출을 그대로 써도 메인 이벤트 루프를 막지 않는다.

호출부(`account_deletion_service.delete_account`)는 우리 DB 트랜잭션이 커밋된 뒤에만
이 함수를 호출한다 — Auth 삭제가 실패해도 이미 앱 데이터는 삭제된 상태이므로, 여기서는
service-role key·Authorization 헤더 값·응답 원문을 로그·예외 메시지 어디에도 남기지 않는다.
"""

import time
import urllib.error
import urllib.request
from collections.abc import Callable
import uuid

from app.core.config import get_supabase_service_role_key, get_supabase_url

_MAX_ATTEMPTS = 3  # 최초 1회 + 재시도 2회
_TIMEOUT_SECONDS = 5
# 1차 실패 후 0.2초, 2차 실패 후 0.5초. len은 _MAX_ATTEMPTS - 1과 같아야 한다.
_RETRY_DELAYS_SECONDS = (0.2, 0.5)


def delete_auth_user(user_id: uuid.UUID, *, sleep: Callable[[float], None] = time.sleep) -> None:
    """DELETE {SUPABASE_URL}/auth/v1/admin/users/{user_id}.

    - 2xx: 성공.
    - 404: 이미 삭제된 것으로 간주해 성공 처리(멱등). 재시도·지연 없음.
    - 429·5xx: 재시도 대상(최대 _MAX_ATTEMPTS회, 실패 사이에 _RETRY_DELAYS_SECONDS만큼 대기).
    - 그 외 4xx: 재시도해도 해결되지 않는 클라이언트 오류이므로 즉시 실패.
    - 네트워크 오류(URLError/TimeoutError/OSError): 429·5xx와 동일하게 재시도.

    `sleep`은 테스트에서 실제로 대기하지 않도록 주입할 수 있다.
    """
    supabase_url = get_supabase_url()
    service_role_key = get_supabase_service_role_key()

    request = urllib.request.Request(
        f"{supabase_url}/auth/v1/admin/users/{user_id}",
        headers={
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
        },
        method="DELETE",
    )

    for attempt in range(_MAX_ATTEMPTS):
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS):
                return  # 2xx
        except urllib.error.HTTPError as exc:
            # HTTPError는 URLError의 하위 클래스라서 반드시 URLError보다 먼저 잡는다.
            # HTTPError도 file-like 응답 객체이므로 상태 확인 후 반드시 close한다.
            try:
                status = exc.code
            finally:
                exc.close()

            if status == 404:
                return  # 이미 삭제됨 — 멱등 성공

            if status == 429 or 500 <= status < 600:
                if attempt == _MAX_ATTEMPTS - 1:
                    raise RuntimeError(
                        f"Supabase Auth 삭제가 재시도 후에도 실패했다: {status}"
                    ) from None
                sleep(_RETRY_DELAYS_SECONDS[attempt])
                continue

            # 그 외 4xx: 재시도해도 해결되지 않는 클라이언트 오류
            raise RuntimeError(f"Supabase Auth 삭제가 실패했다: {status}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == _MAX_ATTEMPTS - 1:
                raise RuntimeError("Supabase Auth 삭제 호출이 네트워크 오류로 실패했다.") from None
            sleep(_RETRY_DELAYS_SECONDS[attempt])
            continue
