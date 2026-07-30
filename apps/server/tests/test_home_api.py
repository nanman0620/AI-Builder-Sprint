import uuid
from datetime import date, datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.core.clock import get_current_moment
from app.core.security import AuthenticatedUser, get_current_user
from app.db.session import get_db
from app.main import app
from app.models.enums import PlanBlockStatus, PlanCycleStatus, PlanPeriod
from app.models.plan_block import PlanBlock
from app.models.planning_cycle import PlanningCycle
from app.services import home_service
from app.services.plan_block_service import PlanBlockProgress

SEOUL_TZ = ZoneInfo("Asia/Seoul")

TEST_USER_ID = uuid.uuid4()
CYCLE_ID = uuid.uuid4()
TASK_ID = uuid.uuid4()
BLOCK_ID = uuid.uuid4()
AUTH_HEADERS = {"Authorization": "Bearer irrelevant-because-dependency-is-overridden"}

FIXED_NOW = datetime(2026, 7, 30, 14, 10, tzinfo=SEOUL_TZ)


def _make_cycle(**overrides):
    defaults = dict(
        id=CYCLE_ID,
        user_id=TEST_USER_ID,
        start_date=date(2026, 7, 27),
        end_date=date(2026, 8, 2),
        status=PlanCycleStatus.ACTIVE,
        activated_at=datetime(2026, 7, 27, 10, 0, tzinfo=SEOUL_TZ),
        ended_at=None,
    )
    defaults.update(overrides)
    return PlanningCycle(**defaults)


def _make_block(**overrides):
    defaults = dict(
        id=BLOCK_ID,
        user_id=TEST_USER_ID,
        plan_cycle_id=CYCLE_ID,
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
    yield None  # home_service.get_home_current_state를 monkeypatch로 대체하므로 실제 세션이 필요 없다.


def _override_get_current_moment():
    return FIXED_NOW


@pytest.fixture
def fake_get_home_current_state(monkeypatch):
    spy = MagicMock()
    monkeypatch.setattr(home_service, "get_home_current_state", spy)
    return spy


@pytest.fixture
def authenticated_client(fake_get_home_current_state):
    app.dependency_overrides[get_current_user] = _override_get_current_user
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_moment] = _override_get_current_moment

    yield TestClient(app)

    app.dependency_overrides.clear()


@pytest.fixture
def unauthenticated_client(fake_get_home_current_state):
    # get_current_user는 override하지 않고 실제 dependency를 그대로 사용한다.
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_moment] = _override_get_current_moment

    yield TestClient(app)

    app.dependency_overrides.clear()


def test_no_active_cycle_returns_full_envelope_with_nulls(
    authenticated_client, fake_get_home_current_state
):
    fake_get_home_current_state.return_value = home_service.HomeCurrentState(
        home_mode=home_service.HomeMode.NO_ACTIVE_CYCLE,
        server_time=FIXED_NOW,
        logical_date=date(2026, 7, 30),
        period=PlanPeriod.AFTERNOON,
        active_cycle=None,
        progress=None,
        plan_blocks=[],
    )

    response = authenticated_client.get("/api/v1/home/current", headers=AUTH_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"data"}
    data = body["data"]
    assert set(data.keys()) == {
        "serverTime",
        "logicalDate",
        "period",
        "homeMode",
        "blockingNotice",
        "activeCycle",
        "progress",
        "planBlocks",
        "finalizing",
        "checkInResult",
    }
    assert data["homeMode"] == "NO_ACTIVE_CYCLE"
    assert data["logicalDate"] == "2026-07-30"
    assert data["period"] == "AFTERNOON"
    assert data["activeCycle"] is None
    assert data["progress"] is None
    assert data["planBlocks"] == []
    assert data["blockingNotice"] is None
    assert data["finalizing"] is None
    assert data["checkInResult"] is None

    fake_get_home_current_state.assert_called_once()
    _, called_user_id = fake_get_home_current_state.call_args.args
    assert called_user_id == TEST_USER_ID
    assert fake_get_home_current_state.call_args.kwargs["now"] == FIXED_NOW


def test_no_plans_returns_active_cycle_and_zero_progress(
    authenticated_client, fake_get_home_current_state
):
    cycle = _make_cycle()
    fake_get_home_current_state.return_value = home_service.HomeCurrentState(
        home_mode=home_service.HomeMode.NO_PLANS,
        server_time=FIXED_NOW,
        logical_date=date(2026, 7, 30),
        period=PlanPeriod.AFTERNOON,
        active_cycle=cycle,
        progress=PlanBlockProgress(checked_count=0, total_count=0, percentage=0),
        plan_blocks=[],
    )

    response = authenticated_client.get("/api/v1/home/current", headers=AUTH_HEADERS)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["homeMode"] == "NO_PLANS"
    assert data["activeCycle"] == {
        "id": str(CYCLE_ID),
        "startDate": "2026-07-27",
        "endDate": "2026-08-02",
        "status": "ACTIVE",
        "activatedAt": "2026-07-27T10:00:00+09:00",
        "endedAt": None,
    }
    assert data["progress"] == {"checkedCount": 0, "totalCount": 0, "percentage": 0}
    assert data["planBlocks"] == []


def test_in_progress_returns_progress_and_plan_blocks_with_task_id(
    authenticated_client, fake_get_home_current_state
):
    cycle = _make_cycle()
    block = _make_block()
    fake_get_home_current_state.return_value = home_service.HomeCurrentState(
        home_mode=home_service.HomeMode.IN_PROGRESS,
        server_time=FIXED_NOW,
        logical_date=date(2026, 7, 30),
        period=PlanPeriod.AFTERNOON,
        active_cycle=cycle,
        progress=PlanBlockProgress(checked_count=1, total_count=1, percentage=100),
        plan_blocks=[block],
    )

    response = authenticated_client.get("/api/v1/home/current", headers=AUTH_HEADERS)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["homeMode"] == "IN_PROGRESS"
    assert data["progress"] == {"checkedCount": 1, "totalCount": 1, "percentage": 100}
    assert len(data["planBlocks"]) == 1
    block_json = data["planBlocks"][0]
    assert block_json["id"] == str(BLOCK_ID)
    assert block_json["taskId"] == str(TASK_ID)
    assert block_json["planDate"] == "2026-07-30"
    assert block_json["period"] == "AFTERNOON"
    assert block_json["allocatedMinutes"] == 60
    assert block_json["allocatedAmountText"] == "10문제"
    assert block_json["displayTitle"] == "수학 문제집 2단원 풀기"
    assert block_json["displayOrder"] == 0
    assert block_json["status"] == "CHECKED"
    assert block_json["checkedAt"] is not None


def test_server_time_has_plus_nine_hour_offset(authenticated_client, fake_get_home_current_state):
    fake_get_home_current_state.return_value = home_service.HomeCurrentState(
        home_mode=home_service.HomeMode.NO_ACTIVE_CYCLE,
        server_time=FIXED_NOW,
        logical_date=date(2026, 7, 30),
        period=PlanPeriod.AFTERNOON,
        active_cycle=None,
        progress=None,
        plan_blocks=[],
    )

    response = authenticated_client.get("/api/v1/home/current", headers=AUTH_HEADERS)

    server_time = datetime.fromisoformat(response.json()["data"]["serverTime"])
    assert server_time.utcoffset() is not None
    assert server_time.utcoffset().total_seconds() == 9 * 3600


def test_missing_authorization_header_returns_401(unauthenticated_client, fake_get_home_current_state):
    response = unauthenticated_client.get("/api/v1/home/current")

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "AUTH_REQUIRED"

    fake_get_home_current_state.assert_not_called()
