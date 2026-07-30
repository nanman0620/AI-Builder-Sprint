import uuid
from datetime import date, datetime
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
from app.models.enums import PlanBlockStatus, PlanPeriod
from app.models.plan_block import PlanBlock
from app.schemas.plan_block import CheckStateRequest
from app.services import plan_block_service
from app.services.plan_block_service import PlanBlockCheckStateResult, PlanBlockProgress

SEOUL_TZ = ZoneInfo("Asia/Seoul")

TEST_USER_ID = uuid.uuid4()
TASK_ID = uuid.uuid4()
BLOCK_ID = uuid.uuid4()
AUTH_HEADERS = {"Authorization": "Bearer irrelevant-because-dependency-is-overridden"}
FIXED_NOW = datetime(2026, 7, 30, 14, 10, tzinfo=SEOUL_TZ)


def _make_block(**overrides):
    defaults = dict(
        id=BLOCK_ID,
        user_id=TEST_USER_ID,
        plan_cycle_id=uuid.uuid4(),
        task_id=TASK_ID,
        plan_date=date(2026, 7, 30),
        period=PlanPeriod.AFTERNOON,
        allocated_minutes=60,
        allocated_amount_text="10문제",
        display_title="수학 문제집 2단원 풀기",
        display_order=0,
        status=PlanBlockStatus.CHECKED,
        checked_at=FIXED_NOW,
    )
    defaults.update(overrides)
    return PlanBlock(**defaults)


def _override_get_current_user():
    return AuthenticatedUser(id=TEST_USER_ID)


def _override_get_db():
    yield None  # set_plan_block_check_state를 monkeypatch로 대체하므로 실제 세션이 필요 없다.


def _override_get_current_moment():
    return FIXED_NOW


@pytest.fixture
def fake_set_check_state(monkeypatch):
    spy = MagicMock()
    monkeypatch.setattr(plan_block_service, "set_plan_block_check_state", spy)
    return spy


@pytest.fixture
def authenticated_client(fake_set_check_state):
    app.dependency_overrides[get_current_user] = _override_get_current_user
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_moment] = _override_get_current_moment

    yield TestClient(app)

    app.dependency_overrides.clear()


@pytest.fixture
def unauthenticated_client(fake_set_check_state):
    # get_current_user는 override하지 않고 실제 dependency를 그대로 사용한다.
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_moment] = _override_get_current_moment

    yield TestClient(app)

    app.dependency_overrides.clear()


def test_check_returns_nested_plan_block_and_progress(authenticated_client, fake_set_check_state):
    block = _make_block(status=PlanBlockStatus.CHECKED, checked_at=FIXED_NOW)
    fake_set_check_state.return_value = PlanBlockCheckStateResult(
        plan_block=block,
        progress=PlanBlockProgress(checked_count=2, total_count=3, percentage=67),
    )

    response = authenticated_client.patch(
        f"/api/v1/plan-blocks/{BLOCK_ID}/check-state",
        json={"checked": True},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"data"}
    data = body["data"]
    assert set(data.keys()) == {"planBlock", "progress"}
    assert data["planBlock"]["id"] == str(BLOCK_ID)
    assert data["planBlock"]["taskId"] == str(TASK_ID)
    assert data["planBlock"]["status"] == "CHECKED"
    assert data["planBlock"]["checkedAt"] is not None
    assert data["progress"] == {"checkedCount": 2, "totalCount": 3, "percentage": 67}

    fake_set_check_state.assert_called_once()
    assert fake_set_check_state.call_args.kwargs["checked"] is True
    assert fake_set_check_state.call_args.kwargs["plan_block_id"] == BLOCK_ID
    assert fake_set_check_state.call_args.kwargs["user_id"] == TEST_USER_ID
    assert fake_set_check_state.call_args.kwargs["now"] == FIXED_NOW


def test_uncheck_returns_planned_status_and_null_checked_at(
    authenticated_client, fake_set_check_state
):
    block = _make_block(status=PlanBlockStatus.PLANNED, checked_at=None)
    fake_set_check_state.return_value = PlanBlockCheckStateResult(
        plan_block=block,
        progress=PlanBlockProgress(checked_count=0, total_count=1, percentage=0),
    )

    response = authenticated_client.patch(
        f"/api/v1/plan-blocks/{BLOCK_ID}/check-state",
        json={"checked": False},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["planBlock"]["status"] == "PLANNED"
    assert data["planBlock"]["checkedAt"] is None
    assert fake_set_check_state.call_args.kwargs["checked"] is False


@pytest.mark.parametrize(
    "code, status_code",
    [
        ("PLAN_BLOCK_NOT_FOUND", 404),
        ("BLOCK_NOT_IN_CURRENT_PERIOD", 409),
        ("PERIOD_ALREADY_FINALIZED", 409),
        ("INVALID_CHECK_STATE", 422),
    ],
)
def test_service_errors_are_mapped_to_expected_status_and_code(
    authenticated_client, fake_set_check_state, code, status_code
):
    fake_set_check_state.side_effect = ApiError(status_code, code, "오류 메시지")

    response = authenticated_client.patch(
        f"/api/v1/plan-blocks/{BLOCK_ID}/check-state",
        json={"checked": True},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code


def test_missing_authorization_header_returns_401(unauthenticated_client, fake_set_check_state):
    response = unauthenticated_client.patch(
        f"/api/v1/plan-blocks/{BLOCK_ID}/check-state", json={"checked": True}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    fake_set_check_state.assert_not_called()


# ---------------------------------------------------------------------------
# checked는 StrictBool이어야 한다 — "true" 문자열, 1, null, 필드 누락 모두
# 200으로 성공 처리되지 않고 400 MALFORMED_REQUEST여야 한다.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"checked": "true"},
        {"checked": 1},
        {"checked": None},
        {},
    ],
)
def test_non_strict_bool_checked_returns_400(authenticated_client, fake_set_check_state, body):
    response = authenticated_client.patch(
        f"/api/v1/plan-blocks/{BLOCK_ID}/check-state", json=body, headers=AUTH_HEADERS
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MALFORMED_REQUEST"
    fake_set_check_state.assert_not_called()


def test_extra_field_is_rejected_with_400(authenticated_client, fake_set_check_state):
    response = authenticated_client.patch(
        f"/api/v1/plan-blocks/{BLOCK_ID}/check-state",
        json={"checked": True, "extra": "nope"},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MALFORMED_REQUEST"
    fake_set_check_state.assert_not_called()


# ---------------------------------------------------------------------------
# CheckStateRequest 스키마 단위 테스트 — 라우트를 거치지 않고 Pydantic validation만 확인.
# ---------------------------------------------------------------------------


def test_check_state_request_accepts_strict_bool():
    assert CheckStateRequest(checked=True).checked is True
    assert CheckStateRequest(checked=False).checked is False


@pytest.mark.parametrize("invalid_value", ["true", 1, None])
def test_check_state_request_rejects_non_strict_bool(invalid_value):
    with pytest.raises(ValidationError):
        CheckStateRequest(checked=invalid_value)


# ---------------------------------------------------------------------------
# OpenAPI 계약 — 경로가 명세 표현(/plan-blocks/{planBlockId}/check-state) 그대로 노출되고,
# 내부 snake_case 파라미터명이 아니라 planBlockId가 외부에 노출되는지 확인한다.
# ---------------------------------------------------------------------------


def test_openapi_exposes_camel_case_path_and_uuid_param():
    schema = app.openapi()
    paths = schema["paths"]

    assert "/api/v1/plan-blocks/{planBlockId}/check-state" in paths
    assert "/api/v1/plan-blocks/{plan_block_id}/check-state" not in paths

    operation = paths["/api/v1/plan-blocks/{planBlockId}/check-state"]["patch"]
    path_params = [p for p in operation["parameters"] if p["in"] == "path"]
    assert len(path_params) == 1

    param = path_params[0]
    assert param["name"] == "planBlockId"
    assert param["required"] is True
    assert param["schema"]["type"] == "string"
    assert param["schema"]["format"] == "uuid"
