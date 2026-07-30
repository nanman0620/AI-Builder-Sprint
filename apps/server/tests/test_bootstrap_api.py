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
from app.models.enums import PlanCycleStatus, PlanPeriod, SolarRequestPurpose, SolarRequestStatus
from app.models.planning_cycle import PlanningCycle
from app.models.solar_request import SolarRequest
from app.services import bootstrap_service, home_service
from app.services.bootstrap_service import BootstrapProfile, BootstrapState, InitialScreen
from app.services.plan_block_service import PlanBlockProgress
from app.services.solar_request_service import PlanManagementScreenMode

SEOUL_TZ = ZoneInfo("Asia/Seoul")

TEST_USER_ID = uuid.uuid4()
CYCLE_ID = uuid.uuid4()
FIXED_NOW = datetime(2026, 7, 30, 14, 10, tzinfo=SEOUL_TZ)
AUTH_HEADERS = {"Authorization": "Bearer irrelevant-because-dependency-is-overridden"}


def _profile(**overrides):
    defaults = dict(
        id=TEST_USER_ID, email="test-user@example.com", nickname="유림", onboarding_completed=True
    )
    defaults.update(overrides)
    return BootstrapProfile(**defaults)


def _cycle(**overrides):
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


def _home_state(*, home_mode, active_cycle=None):
    return home_service.HomeCurrentState(
        home_mode=home_mode,
        server_time=FIXED_NOW,
        logical_date=date(2026, 7, 30),
        period=PlanPeriod.AFTERNOON,
        active_cycle=active_cycle,
        progress=PlanBlockProgress(checked_count=0, total_count=0, percentage=0)
        if active_cycle
        else None,
        plan_blocks=[],
    )


def _solar_request(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        user_id=TEST_USER_ID,
        plan_cycle_id=None,
        purpose=SolarRequestPurpose.NEW_CYCLE,
        status=SolarRequestStatus.COLLECTING,
        raw_input="테스트 입력",
        current_item_order=None,
        confirmed_at=None,
        execution_started_at=None,
        executed_at=None,
        execution_attempt_count=0,
        execution_result=None,
        error_code=None,
        error_message=None,
        result_acknowledged_at=None,
    )
    defaults.update(overrides)
    return SolarRequest(**defaults)


def _override_get_current_user():
    return AuthenticatedUser(id=TEST_USER_ID)


def _override_get_db():
    yield None  # bootstrap_service.get_bootstrap_state를 monkeypatch로 대체하므로 실제 세션이 필요 없다.


def _override_get_current_moment():
    return FIXED_NOW


@pytest.fixture
def fake_get_bootstrap_state(monkeypatch):
    spy = MagicMock()
    monkeypatch.setattr(bootstrap_service, "get_bootstrap_state", spy)
    return spy


@pytest.fixture
def authenticated_client(fake_get_bootstrap_state):
    app.dependency_overrides[get_current_user] = _override_get_current_user
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_moment] = _override_get_current_moment

    yield TestClient(app)

    app.dependency_overrides.clear()


@pytest.fixture
def unauthenticated_client(fake_get_bootstrap_state):
    # get_current_user는 override하지 않고 실제 dependency를 그대로 사용한다.
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_moment] = _override_get_current_moment

    yield TestClient(app)

    app.dependency_overrides.clear()


def test_missing_authorization_header_returns_401(
    unauthenticated_client, fake_get_bootstrap_state
):
    response = unauthenticated_client.get("/api/v1/bootstrap")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    fake_get_bootstrap_state.assert_not_called()


def test_onboarding_not_completed_returns_nickname_creation_with_nulls(
    authenticated_client, fake_get_bootstrap_state
):
    fake_get_bootstrap_state.return_value = BootstrapState(
        server_time=FIXED_NOW,
        profile=_profile(onboarding_completed=False, nickname=None),
        initial_screen=InitialScreen.NICKNAME_CREATION,
        active_cycle=None,
        plan_management_screen_mode=None,
        current_request=None,
        home_state=None,
    )

    response = authenticated_client.get("/api/v1/bootstrap", headers=AUTH_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"data"}
    data = body["data"]
    assert data["initialScreen"] == "NICKNAME_CREATION"
    assert data["profile"]["onboardingCompleted"] is False
    assert data["profile"]["nickname"] is None
    assert data["activeCycle"] is None
    assert data["planManagement"] is None
    assert data["home"] is None

    fake_get_bootstrap_state.assert_called_once()
    _, called_user_id = fake_get_bootstrap_state.call_args.args
    assert called_user_id == TEST_USER_ID
    assert fake_get_bootstrap_state.call_args.kwargs["now"] == FIXED_NOW


def test_no_active_cycle_returns_full_envelope(authenticated_client, fake_get_bootstrap_state):
    home_state = _home_state(home_mode=home_service.HomeMode.NO_ACTIVE_CYCLE)
    fake_get_bootstrap_state.return_value = BootstrapState(
        server_time=FIXED_NOW,
        profile=_profile(),
        initial_screen=InitialScreen.NO_ACTIVE_CYCLE,
        active_cycle=None,
        plan_management_screen_mode=PlanManagementScreenMode.NEW_CYCLE_ENTRY,
        current_request=None,
        home_state=home_state,
    )

    response = authenticated_client.get("/api/v1/bootstrap", headers=AUTH_HEADERS)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["initialScreen"] == "NO_ACTIVE_CYCLE"
    assert data["activeCycle"] is None
    assert data["planManagement"] == {
        "screenMode": "NEW_CYCLE_ENTRY",
        "activeCycle": None,
        "request": None,
    }
    assert data["home"]["homeMode"] == "NO_ACTIVE_CYCLE"
    assert data["profile"] == {
        "id": str(TEST_USER_ID),
        "email": "test-user@example.com",
        "nickname": "유림",
        "onboardingCompleted": True,
    }


def test_active_cycle_no_plans_returns_active_cycle_entry(
    authenticated_client, fake_get_bootstrap_state
):
    cycle = _cycle()
    home_state = _home_state(home_mode=home_service.HomeMode.NO_PLANS, active_cycle=cycle)
    fake_get_bootstrap_state.return_value = BootstrapState(
        server_time=FIXED_NOW,
        profile=_profile(),
        initial_screen=InitialScreen.NO_PLANS,
        active_cycle=cycle,
        plan_management_screen_mode=PlanManagementScreenMode.ACTIVE_CYCLE_ENTRY,
        current_request=None,
        home_state=home_state,
    )

    response = authenticated_client.get("/api/v1/bootstrap", headers=AUTH_HEADERS)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["initialScreen"] == "NO_PLANS"
    expected_cycle = {
        "id": str(CYCLE_ID),
        "startDate": "2026-07-27",
        "endDate": "2026-08-02",
        "status": "ACTIVE",
        "activatedAt": "2026-07-27T10:00:00+09:00",
        "endedAt": None,
    }
    assert data["activeCycle"] == expected_cycle
    assert data["planManagement"]["screenMode"] == "ACTIVE_CYCLE_ENTRY"
    assert data["planManagement"]["activeCycle"] == expected_cycle
    assert data["planManagement"]["request"] is None
    assert data["home"]["activeCycle"] == expected_cycle


def test_current_request_populates_plan_management_summary_and_overrides_initial_screen(
    authenticated_client, fake_get_bootstrap_state
):
    home_state = _home_state(home_mode=home_service.HomeMode.NO_ACTIVE_CYCLE)
    request = _solar_request(status=SolarRequestStatus.CHANGE_CONFIRMATION)
    fake_get_bootstrap_state.return_value = BootstrapState(
        server_time=FIXED_NOW,
        profile=_profile(),
        initial_screen=InitialScreen.CHANGE_CONFIRMATION,
        active_cycle=None,
        plan_management_screen_mode=PlanManagementScreenMode.CHANGE_CONFIRMATION,
        current_request=request,
        home_state=home_state,
    )

    response = authenticated_client.get("/api/v1/bootstrap", headers=AUTH_HEADERS)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["initialScreen"] == "CHANGE_CONFIRMATION"
    # home 캐시는 SOLAR 요청 존재 여부와 무관하게 항상 동기화된다.
    assert data["home"]["homeMode"] == "NO_ACTIVE_CYCLE"
    assert data["planManagement"]["screenMode"] == "CHANGE_CONFIRMATION"
    assert data["planManagement"]["request"] == {
        "id": str(request.id),
        "purpose": "NEW_CYCLE",
        "status": "CHANGE_CONFIRMATION",
        "resultAcknowledgedAt": None,
    }


def test_server_time_has_plus_nine_hour_offset(authenticated_client, fake_get_bootstrap_state):
    fake_get_bootstrap_state.return_value = BootstrapState(
        server_time=FIXED_NOW,
        profile=_profile(onboarding_completed=False, nickname=None),
        initial_screen=InitialScreen.NICKNAME_CREATION,
        active_cycle=None,
        plan_management_screen_mode=None,
        current_request=None,
        home_state=None,
    )

    response = authenticated_client.get("/api/v1/bootstrap", headers=AUTH_HEADERS)

    server_time = datetime.fromisoformat(response.json()["data"]["serverTime"])
    assert server_time.utcoffset() is not None
    assert server_time.utcoffset().total_seconds() == 9 * 3600
