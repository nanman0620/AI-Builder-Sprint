import uuid
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.models.enums import PlanBlockStatus, PlanCycleStatus, PlanPeriod
from app.models.plan_block import PlanBlock
from app.models.planning_cycle import PlanningCycle
from app.services import home_service
from tests.support_check_in import FakeCheckInSession

SEOUL_TZ = ZoneInfo("Asia/Seoul")

USER_ID = uuid.uuid4()
CYCLE_ID = uuid.uuid4()
TASK_ID = uuid.uuid4()

NOW = datetime(2026, 7, 30, 14, 0, tzinfo=SEOUL_TZ)


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


def _make_block(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        task_id=TASK_ID,
        plan_date=date(2026, 7, 30),
        period=PlanPeriod.AFTERNOON,
        allocated_minutes=60,
        allocated_amount_text=None,
        display_title="테스트 계획",
        display_order=0,
        status=PlanBlockStatus.PLANNED,
        checked_at=None,
    )
    defaults.update(overrides)
    return PlanBlock(**defaults)


def _fake_db(*rows):
    """조회 전용 서비스 검증용 Fake. db.begin()을 호출하면 즉시 실패한다."""
    return FakeCheckInSession(forbid_begin=True).seed(*rows)


def test_no_active_cycle_returns_no_active_cycle_mode():
    fake_db = _fake_db()

    state = home_service.get_home_current_state(fake_db, USER_ID, now=NOW)

    assert state.home_mode == home_service.HomeMode.NO_ACTIVE_CYCLE
    assert state.active_cycle is None
    assert state.progress is None
    assert state.plan_blocks == []
    assert state.blocking_notice is None
    assert state.finalizing is None
    assert state.check_in_result is None


def test_active_cycle_without_blocks_returns_no_plans_mode():
    cycle = _make_cycle()
    fake_db = _fake_db(cycle)

    state = home_service.get_home_current_state(fake_db, USER_ID, now=NOW)

    assert state.home_mode == home_service.HomeMode.NO_PLANS
    assert state.active_cycle is cycle
    assert state.progress.checked_count == 0
    assert state.progress.total_count == 0
    assert state.progress.percentage == 0
    assert state.plan_blocks == []
    # 경고 대상 Task가 없으므로 BE-10 서비스를 그대로 통과시켜도 자연스럽게 None이다.
    assert state.blocking_notice is None


def test_active_cycle_with_blocks_returns_in_progress_mode():
    cycle = _make_cycle()
    b1 = _make_block(status=PlanBlockStatus.CHECKED, display_order=0)
    b2 = _make_block(status=PlanBlockStatus.PLANNED, display_order=1)
    fake_db = _fake_db(cycle, b1, b2)

    state = home_service.get_home_current_state(fake_db, USER_ID, now=NOW)

    assert state.home_mode == home_service.HomeMode.IN_PROGRESS
    assert state.active_cycle is cycle
    assert state.progress.checked_count == 1
    assert state.progress.total_count == 2
    assert state.progress.percentage == 50
    assert state.plan_blocks == [b1, b2]
    assert state.blocking_notice is None


def test_server_time_echoes_injected_now():
    fake_db = _fake_db()

    state = home_service.get_home_current_state(fake_db, USER_ID, now=NOW)

    assert state.server_time == NOW


def test_logical_date_before_4am_belongs_to_previous_day():
    early_morning = datetime(2026, 7, 30, 2, 0, tzinfo=SEOUL_TZ)
    fake_db = _fake_db()

    state = home_service.get_home_current_state(fake_db, USER_ID, now=early_morning)

    assert state.logical_date == date(2026, 7, 29)
    assert state.period == PlanPeriod.EVENING


def test_get_home_current_state_never_opens_write_transaction():
    cycle = _make_cycle()
    fake_db = _fake_db(cycle, _make_block())

    home_service.get_home_current_state(fake_db, USER_ID, now=NOW)

    # _fake_db는 forbid_begin=True이므로 begin()이 호출되면 이 호출 자체가 실패한다.
    # 예외 없이 끝났다는 것 자체가 db.begin()이 호출되지 않았다는 증거다.
