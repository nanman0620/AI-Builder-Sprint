import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.models.enums import PlanCycleStatus, PlanPeriod, SolarRequestPurpose, SolarRequestStatus
from app.models.planning_cycle import PlanningCycle
from app.models.solar_request import SolarRequest
from app.models.user_profile import UserProfile
from app.services import bootstrap_service, home_service, profile_service, solar_request_service
from app.services.check_in_service import CheckInResultState, FinalizingInfo
from app.services.deadline_warning_service import DeadlineWarningItem, DeadlineWarningNotice
from app.services.plan_block_service import PlanBlockProgress

SEOUL_TZ = ZoneInfo("Asia/Seoul")

USER_ID = uuid.uuid4()
CYCLE_ID = uuid.uuid4()
EMAIL = "test-user@example.com"
NOW = datetime(2026, 7, 30, 14, 0, tzinfo=SEOUL_TZ)


class _NoQuerySession:
    """bootstrap_service는 profile/home/solar_request의 기존 조회 전용 service만 호출해야 하고,
    직접 db.execute/db.begin을 호출하면 안 된다. 직접 호출 시 즉시 실패시켜 검증한다."""

    def begin(self):
        raise AssertionError("bootstrap_service는 db.begin()을 호출하면 안 된다.")

    def execute(self, *args, **kwargs):
        raise AssertionError(
            "bootstrap_service는 기존 service를 거치지 않고 직접 db.execute()를 호출하면 안 된다."
        )


def _make_profile(**overrides):
    defaults = dict(
        id=USER_ID,
        nickname="유림",
        onboarding_completed=True,
        created_at=NOW,
        updated_at=NOW,
    )
    defaults.update(overrides)
    return UserProfile(**defaults)


def _make_cycle(**overrides):
    defaults = dict(
        id=CYCLE_ID,
        user_id=USER_ID,
        start_date=date(2026, 7, 27),
        end_date=date(2026, 8, 2),
        status=PlanCycleStatus.ACTIVE,
        activated_at=datetime(2026, 7, 27, 1, 0, tzinfo=timezone.utc),
        ended_at=None,
    )
    defaults.update(overrides)
    return PlanningCycle(**defaults)


def _make_request(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        user_id=USER_ID,
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


def _home_state(
    *, home_mode, active_cycle=None, blocking_notice=None, finalizing=None, check_in_result=None
):
    return home_service.HomeCurrentState(
        home_mode=home_mode,
        server_time=NOW,
        logical_date=date(2026, 7, 30),
        period=PlanPeriod.AFTERNOON,
        active_cycle=active_cycle,
        progress=PlanBlockProgress(checked_count=0, total_count=0, percentage=0)
        if active_cycle
        else None,
        plan_blocks=[],
        blocking_notice=blocking_notice,
        finalizing=finalizing,
        check_in_result=check_in_result,
    )


@pytest.fixture
def patch_dependencies(monkeypatch):
    def _patch(*, profile, email=EMAIL, home_state=None, current_request=None):
        monkeypatch.setattr(profile_service, "get_profile", lambda db, user_id: profile)
        monkeypatch.setattr(profile_service, "get_user_email", lambda db, user_id: email)
        monkeypatch.setattr(
            home_service, "get_home_current_state", lambda db, user_id, *, now: home_state
        )
        monkeypatch.setattr(
            solar_request_service, "get_current_solar_request", lambda db, user_id: current_request
        )

    return _patch


def test_onboarding_not_completed_returns_nickname_creation_and_nulls(patch_dependencies):
    profile = _make_profile(onboarding_completed=False, nickname=None)
    patch_dependencies(profile=profile)

    state = bootstrap_service.get_bootstrap_state(_NoQuerySession(), USER_ID, now=NOW)

    assert state.initial_screen == bootstrap_service.InitialScreen.NICKNAME_CREATION
    assert state.profile.onboarding_completed is False
    assert state.active_cycle is None
    assert state.plan_management_screen_mode is None
    assert state.current_request is None
    assert state.home_state is None


def test_missing_profile_row_is_treated_as_onboarding_not_completed(patch_dependencies):
    patch_dependencies(profile=None)

    state = bootstrap_service.get_bootstrap_state(_NoQuerySession(), USER_ID, now=NOW)

    assert state.initial_screen == bootstrap_service.InitialScreen.NICKNAME_CREATION
    assert state.profile.onboarding_completed is False
    assert state.profile.nickname is None
    assert state.profile.email == EMAIL


def test_missing_email_raises_runtime_error(patch_dependencies):
    patch_dependencies(profile=_make_profile(), email=None)

    with pytest.raises(RuntimeError):
        bootstrap_service.get_bootstrap_state(_NoQuerySession(), USER_ID, now=NOW)


def test_no_active_cycle_uses_home_mode_as_initial_screen(patch_dependencies):
    profile = _make_profile()
    home_state = _home_state(home_mode=home_service.HomeMode.NO_ACTIVE_CYCLE)
    patch_dependencies(profile=profile, home_state=home_state, current_request=None)

    state = bootstrap_service.get_bootstrap_state(_NoQuerySession(), USER_ID, now=NOW)

    assert state.initial_screen == bootstrap_service.InitialScreen.NO_ACTIVE_CYCLE
    assert state.active_cycle is None
    assert (
        state.plan_management_screen_mode
        == solar_request_service.PlanManagementScreenMode.NEW_CYCLE_ENTRY
    )


def test_active_cycle_no_plans_uses_active_cycle_entry_for_plan_management(patch_dependencies):
    profile = _make_profile()
    cycle = _make_cycle()
    home_state = _home_state(home_mode=home_service.HomeMode.NO_PLANS, active_cycle=cycle)
    patch_dependencies(profile=profile, home_state=home_state, current_request=None)

    state = bootstrap_service.get_bootstrap_state(_NoQuerySession(), USER_ID, now=NOW)

    assert state.initial_screen == bootstrap_service.InitialScreen.NO_PLANS
    assert state.active_cycle is cycle
    assert (
        state.plan_management_screen_mode
        == solar_request_service.PlanManagementScreenMode.ACTIVE_CYCLE_ENTRY
    )


def test_in_progress_home_mode_becomes_initial_screen(patch_dependencies):
    profile = _make_profile()
    cycle = _make_cycle()
    home_state = _home_state(home_mode=home_service.HomeMode.IN_PROGRESS, active_cycle=cycle)
    patch_dependencies(profile=profile, home_state=home_state, current_request=None)

    state = bootstrap_service.get_bootstrap_state(_NoQuerySession(), USER_ID, now=NOW)

    assert state.initial_screen == bootstrap_service.InitialScreen.IN_PROGRESS


def test_current_request_overrides_home_driven_initial_screen(patch_dependencies):
    profile = _make_profile()
    cycle = _make_cycle()
    home_state = _home_state(home_mode=home_service.HomeMode.IN_PROGRESS, active_cycle=cycle)
    current_request = _make_request(status=SolarRequestStatus.CHANGE_CONFIRMATION)
    patch_dependencies(
        profile=profile, home_state=home_state, current_request=current_request
    )

    state = bootstrap_service.get_bootstrap_state(_NoQuerySession(), USER_ID, now=NOW)

    assert state.initial_screen == bootstrap_service.InitialScreen.CHANGE_CONFIRMATION
    assert state.current_request is current_request
    # home 캐시는 요청 존재 여부와 무관하게 항상 동기화된다(포그라운드 복귀 캐시 갱신 계약).
    assert state.home_state is home_state
    assert state.active_cycle is cycle


def test_current_request_failed_maps_to_execution_failed_initial_screen(patch_dependencies):
    profile = _make_profile()
    home_state = _home_state(home_mode=home_service.HomeMode.NO_ACTIVE_CYCLE)
    current_request = _make_request(status=SolarRequestStatus.FAILED)
    patch_dependencies(
        profile=profile, home_state=home_state, current_request=current_request
    )

    state = bootstrap_service.get_bootstrap_state(_NoQuerySession(), USER_ID, now=NOW)

    assert state.initial_screen == bootstrap_service.InitialScreen.EXECUTION_FAILED


def test_current_request_completed_unacknowledged_maps_to_execution_success(patch_dependencies):
    profile = _make_profile()
    home_state = _home_state(home_mode=home_service.HomeMode.NO_ACTIVE_CYCLE)
    current_request = _make_request(
        status=SolarRequestStatus.COMPLETED,
        result_acknowledged_at=None,
        execution_started_at=NOW,
        executed_at=NOW,
        execution_attempt_count=1,
        execution_result={},
    )
    patch_dependencies(
        profile=profile, home_state=home_state, current_request=current_request
    )

    state = bootstrap_service.get_bootstrap_state(_NoQuerySession(), USER_ID, now=NOW)

    assert state.initial_screen == bootstrap_service.InitialScreen.EXECUTION_SUCCESS


def test_finalizing_home_mode_becomes_initial_screen(patch_dependencies):
    profile = _make_profile()
    finalizing = FinalizingInfo(
        check_in_id=uuid.uuid4(),
        check_date=date(2026, 7, 30),
        period=PlanPeriod.AFTERNOON,
        finalization_started_at=NOW,
    )
    home_state = _home_state(home_mode=home_service.HomeMode.FINALIZING, finalizing=finalizing)
    patch_dependencies(profile=profile, home_state=home_state, current_request=None)

    state = bootstrap_service.get_bootstrap_state(_NoQuerySession(), USER_ID, now=NOW)

    assert state.initial_screen == bootstrap_service.InitialScreen.FINALIZING
    # 현재 SOLAR 요청이 없어도 home payload는 항상 함께 계산·반환된다.
    assert state.home_state is home_state


def test_check_in_result_home_mode_becomes_initial_screen(patch_dependencies):
    profile = _make_profile()
    result_state = CheckInResultState(
        id=uuid.uuid4(),
        check_date=date(2026, 7, 29),
        period=PlanPeriod.MORNING,
        total_plan_count=3,
        completed_plan_count=2,
        not_done_plan_count=1,
        score=67,
        replan_unplaced_minutes=0,
        finalized_at=NOW,
        cycle_ended=False,
        completed_plans=[],
        not_done_plans=[],
    )
    home_state = _home_state(
        home_mode=home_service.HomeMode.CHECK_IN_RESULT, check_in_result=result_state
    )
    patch_dependencies(profile=profile, home_state=home_state, current_request=None)

    state = bootstrap_service.get_bootstrap_state(_NoQuerySession(), USER_ID, now=NOW)

    assert state.initial_screen == bootstrap_service.InitialScreen.CHECK_IN_RESULT


def test_deadline_warning_overrides_initial_screen_but_keeps_home_mode(patch_dependencies):
    profile = _make_profile()
    cycle = _make_cycle()
    notice = DeadlineWarningNotice(
        items=[
            DeadlineWarningItem(
                task_id=uuid.uuid4(),
                title="과제",
                deadline_at=NOW + timedelta(days=1),
                required_minutes=180,
                available_minutes=120,
                shortage_minutes=60,
                created_at=NOW,
            )
        ]
    )
    home_state = _home_state(
        home_mode=home_service.HomeMode.IN_PROGRESS, active_cycle=cycle, blocking_notice=notice
    )
    patch_dependencies(profile=profile, home_state=home_state, current_request=None)

    state = bootstrap_service.get_bootstrap_state(_NoQuerySession(), USER_ID, now=NOW)

    assert state.initial_screen == bootstrap_service.InitialScreen.DEADLINE_WARNING
    # initialScreen만 DEADLINE_WARNING으로 덮이고 home.homeMode 자체는 그대로 유지된다.
    assert state.home_state.home_mode == home_service.HomeMode.IN_PROGRESS
    assert state.home_state.blocking_notice is notice


def test_current_request_takes_priority_over_deadline_warning(patch_dependencies):
    """현재 SOLAR 요청이 있으면 home의 DEADLINE_WARNING보다 요청 상태가 우선한다."""
    profile = _make_profile()
    notice = DeadlineWarningNotice(
        items=[
            DeadlineWarningItem(
                task_id=uuid.uuid4(),
                title="과제",
                deadline_at=NOW + timedelta(days=1),
                required_minutes=180,
                available_minutes=120,
                shortage_minutes=60,
                created_at=NOW,
            )
        ]
    )
    home_state = _home_state(home_mode=home_service.HomeMode.IN_PROGRESS, blocking_notice=notice)
    current_request = _make_request(status=SolarRequestStatus.FINAL_REVIEW)
    patch_dependencies(
        profile=profile, home_state=home_state, current_request=current_request
    )

    state = bootstrap_service.get_bootstrap_state(_NoQuerySession(), USER_ID, now=NOW)

    assert state.initial_screen == bootstrap_service.InitialScreen.FINAL_REVIEW
    # home payload는 여전히 함께 반환된다(계산 자체는 생략하지 않음).
    assert state.home_state is home_state
