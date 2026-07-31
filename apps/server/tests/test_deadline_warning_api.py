import uuid
from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.clock import get_current_moment
from app.core.errors import ApiError
from app.core.security import AuthenticatedUser, get_current_user
from app.db.session import get_db
from app.main import app
from app.schemas.task import AcknowledgeRequest
from app.services import deadline_warning_service
from app.services.deadline_warning_service import AcknowledgeResult

SEOUL_TZ = ZoneInfo("Asia/Seoul")

TEST_USER_ID = uuid.uuid4()
TASK_ID_1 = uuid.uuid4()
TASK_ID_2 = uuid.uuid4()
AUTH_HEADERS = {"Authorization": "Bearer irrelevant-because-dependency-is-overridden"}
FIXED_NOW = datetime(2026, 7, 29, 14, 40, tzinfo=SEOUL_TZ)

ENDPOINT = "/api/v1/tasks/deadline-warnings/acknowledge"


def _override_get_current_user():
    return AuthenticatedUser(id=TEST_USER_ID)


def _override_get_db():
    yield None  # 서비스 함수를 monkeypatch로 대체하므로 실제 세션이 필요 없다.


def _override_get_current_moment():
    return FIXED_NOW


@pytest.fixture
def fake_acknowledge(monkeypatch):
    spy = MagicMock()
    monkeypatch.setattr(deadline_warning_service, "acknowledge_deadline_warnings", spy)
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


# ---------------------------------------------------------------------------
# 1~4. 정상 흐름 — 서비스가 돌려준 결과를 그대로 camelCase로 직렬화하는지 확인한다.
# (dedup·동일 acknowledgedAt·이미 확인된 Task 포함 성공 자체는 서비스 단위 테스트에서 검증됨)
# ---------------------------------------------------------------------------


def test_acknowledge_returns_service_result_as_camel_case(authenticated_client, fake_acknowledge):
    fake_acknowledge.return_value = AcknowledgeResult(
        acknowledged_task_ids=[TASK_ID_1, TASK_ID_2], acknowledged_at=FIXED_NOW
    )

    response = authenticated_client.post(
        ENDPOINT,
        json={"taskIds": [str(TASK_ID_1), str(TASK_ID_2)]},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"data"}
    data = body["data"]
    assert set(data.keys()) == {"acknowledgedTaskIds", "acknowledgedAt"}
    assert data["acknowledgedTaskIds"] == [str(TASK_ID_1), str(TASK_ID_2)]
    assert data["acknowledgedAt"] is not None

    fake_acknowledge.assert_called_once()
    call_kwargs = fake_acknowledge.call_args.kwargs
    assert call_kwargs["user_id"] == TEST_USER_ID
    assert call_kwargs["task_ids"] == [TASK_ID_1, TASK_ID_2]
    assert call_kwargs["now"] == FIXED_NOW


def test_acknowledge_forwards_request_order_undeduped_to_service(
    authenticated_client, fake_acknowledge
):
    # dedup은 서비스 책임이므로 라우터는 요청 순서 그대로(중복 포함) 전달해야 한다.
    fake_acknowledge.return_value = AcknowledgeResult(
        acknowledged_task_ids=[TASK_ID_1], acknowledged_at=FIXED_NOW
    )

    authenticated_client.post(
        ENDPOINT,
        json={"taskIds": [str(TASK_ID_1), str(TASK_ID_1)]},
        headers=AUTH_HEADERS,
    )

    call_kwargs = fake_acknowledge.call_args.kwargs
    assert call_kwargs["task_ids"] == [TASK_ID_1, TASK_ID_1]


def test_acknowledge_uses_same_now_for_dependency_and_response(
    authenticated_client, fake_acknowledge
):
    fake_acknowledge.return_value = AcknowledgeResult(
        acknowledged_task_ids=[TASK_ID_1], acknowledged_at=FIXED_NOW
    )

    response = authenticated_client.post(
        ENDPOINT, json={"taskIds": [str(TASK_ID_1)]}, headers=AUTH_HEADERS
    )

    assert response.json()["data"]["acknowledgedAt"] == FIXED_NOW.isoformat()
    assert fake_acknowledge.call_args.kwargs["now"] == FIXED_NOW


# ---------------------------------------------------------------------------
# 5. 빈 배열 -> 422 INVALID_TASK_IDS (서비스가 raise, 라우터는 그대로 전달)
# ---------------------------------------------------------------------------


def test_empty_task_ids_returns_422_invalid_task_ids(authenticated_client, fake_acknowledge):
    fake_acknowledge.side_effect = ApiError(
        422, deadline_warning_service.CODE_INVALID_TASK_IDS, "확인할 Task를 선택해 주세요."
    )

    response = authenticated_client.post(ENDPOINT, json={"taskIds": []}, headers=AUTH_HEADERS)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_TASK_IDS"


# ---------------------------------------------------------------------------
# 6. UUID 형식 오류 -> 400 MALFORMED_REQUEST (Pydantic validation, 서비스 호출 안 됨)
# ---------------------------------------------------------------------------


def test_malformed_uuid_returns_400_and_does_not_call_service(
    authenticated_client, fake_acknowledge
):
    response = authenticated_client.post(
        ENDPOINT, json={"taskIds": ["not-a-uuid"]}, headers=AUTH_HEADERS
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MALFORMED_REQUEST"
    fake_acknowledge.assert_not_called()


# ---------------------------------------------------------------------------
# 7~9. 존재하지 않는 ID / 타인 소유 ID / 혼합 -> 404 TASK_NOT_FOUND (전체 rollback은 서비스 테스트에서 검증)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "description",
    ["nonexistent_id", "other_users_id", "mixed_valid_and_invalid"],
)
def test_invalid_task_id_returns_404_task_not_found(
    authenticated_client, fake_acknowledge, description
):
    fake_acknowledge.side_effect = ApiError(
        404, deadline_warning_service.CODE_TASK_NOT_FOUND, "Task를 찾을 수 없어요."
    )

    response = authenticated_client.post(
        ENDPOINT,
        json={"taskIds": [str(TASK_ID_1), str(TASK_ID_2)]},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TASK_NOT_FOUND"


# ---------------------------------------------------------------------------
# 10. 미인증 -> 401 AUTH_REQUIRED
# ---------------------------------------------------------------------------


def test_missing_authorization_header_returns_401(unauthenticated_client, fake_acknowledge):
    response = unauthenticated_client.post(ENDPOINT, json={"taskIds": [str(TASK_ID_1)]})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    fake_acknowledge.assert_not_called()


# ---------------------------------------------------------------------------
# 11. extra field 금지
# ---------------------------------------------------------------------------


def test_extra_field_is_rejected_with_400(authenticated_client, fake_acknowledge):
    response = authenticated_client.post(
        ENDPOINT,
        json={"taskIds": [str(TASK_ID_1)], "extra": "nope"},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MALFORMED_REQUEST"
    fake_acknowledge.assert_not_called()


def test_missing_task_ids_field_is_rejected_with_400(authenticated_client, fake_acknowledge):
    response = authenticated_client.post(ENDPOINT, json={}, headers=AUTH_HEADERS)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MALFORMED_REQUEST"
    fake_acknowledge.assert_not_called()


# ---------------------------------------------------------------------------
# AcknowledgeRequest 스키마 단위 테스트 — 라우트를 거치지 않고 Pydantic validation만 확인.
# ---------------------------------------------------------------------------


def test_acknowledge_request_accepts_task_ids_by_alias():
    request = AcknowledgeRequest.model_validate({"taskIds": [str(TASK_ID_1)]})
    assert request.task_ids == [TASK_ID_1]


def test_acknowledge_request_rejects_extra_field():
    with pytest.raises(ValidationError):
        AcknowledgeRequest.model_validate({"taskIds": [str(TASK_ID_1)], "extra": "nope"})


def test_acknowledge_request_accepts_empty_list_pydantic_level():
    # 빈 배열 자체는 Pydantic 단계에서 막지 않는다 — 422 INVALID_TASK_IDS는 서비스 책임이다.
    request = AcknowledgeRequest.model_validate({"taskIds": []})
    assert request.task_ids == []


# ---------------------------------------------------------------------------
# 12. OpenAPI 계약 — camelCase request/response 노출 확인.
# ---------------------------------------------------------------------------


def test_openapi_exposes_camel_case_request_and_response():
    schema = app.openapi()
    paths = schema["paths"]

    assert ENDPOINT in paths
    operation = paths[ENDPOINT]["post"]

    request_schema_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    request_schema_name = request_schema_ref.split("/")[-1]
    request_schema = schema["components"]["schemas"][request_schema_name]
    assert "taskIds" in request_schema["properties"]
    assert "task_ids" not in request_schema["properties"]

    response_schema_ref = operation["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    response_schema_name = response_schema_ref.split("/")[-1]
    response_schema = schema["components"]["schemas"][response_schema_name]
    data_ref = response_schema["properties"]["data"]["$ref"]
    data_schema_name = data_ref.split("/")[-1]
    data_schema = schema["components"]["schemas"][data_schema_name]
    assert "acknowledgedTaskIds" in data_schema["properties"]
    assert "acknowledgedAt" in data_schema["properties"]
    assert "acknowledged_task_ids" not in data_schema["properties"]
