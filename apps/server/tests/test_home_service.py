import uuid
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.models.enums import PlanBlockStatus, PlanCycleStatus, PlanPeriod
from app.models.plan_block import PlanBlock
from app.models.planning_cycle import PlanningCycle
from app.services import home_service

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


class _FakeScalars:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class _FakeResult:
    def __init__(self, *, value=None, items=None):
        self._value = value
        self._items = items

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return _FakeScalars(self._items or [])


class _FakeSession:
    """execute() 호출 순서: 1) 활성 PlanningCycle, 2) (cycle이 있을 때만) 현재 분기 PlanBlock 목록.

    begin()이 호출되면 즉시 실패시켜 get_home_current_state가 완전한 조회 전용으로
    동작하는지(쓰기 트랜잭션을 열지 않는지)를 검증한다.
    """

    def __init__(self, *, cycle, blocks=None):
        self._cycle = cycle
        self._blocks = blocks or []
        self.execute_calls = 0
        self.begin_called = False

    def begin(self):
        self.begin_called = True
        raise AssertionError("get_home_current_state는 db.begin()을 호출하면 안 된다.")

    def execute(self, stmt):
        self.execute_calls += 1
        if self.execute_calls == 1:
            return _FakeResult(value=self._cycle)
        return _FakeResult(items=self._blocks)


def test_no_active_cycle_returns_no_active_cycle_mode():
    fake_db = _FakeSession(cycle=None)

    state = home_service.get_home_current_state(fake_db, USER_ID, now=NOW)

    assert state.home_mode == home_service.HomeMode.NO_ACTIVE_CYCLE
    assert state.active_cycle is None
    assert state.progress is None
    assert state.plan_blocks == []
    # cycle이 없으면 PlanBlock 조회 자체를 하지 않는다.
    assert fake_db.execute_calls == 1


def test_active_cycle_without_blocks_returns_no_plans_mode():
    cycle = _make_cycle()
    fake_db = _FakeSession(cycle=cycle, blocks=[])

    state = home_service.get_home_current_state(fake_db, USER_ID, now=NOW)

    assert state.home_mode == home_service.HomeMode.NO_PLANS
    assert state.active_cycle is cycle
    assert state.progress.checked_count == 0
    assert state.progress.total_count == 0
    assert state.progress.percentage == 0
    assert state.plan_blocks == []


def test_active_cycle_with_blocks_returns_in_progress_mode():
    cycle = _make_cycle()
    b1 = _make_block(status=PlanBlockStatus.CHECKED, display_order=0)
    b2 = _make_block(status=PlanBlockStatus.PLANNED, display_order=1)
    fake_db = _FakeSession(cycle=cycle, blocks=[b1, b2])

    state = home_service.get_home_current_state(fake_db, USER_ID, now=NOW)

    assert state.home_mode == home_service.HomeMode.IN_PROGRESS
    assert state.active_cycle is cycle
    assert state.progress.checked_count == 1
    assert state.progress.total_count == 2
    assert state.progress.percentage == 50
    # home_service는 조회된 순서를 그대로 보존한다(정렬은 쿼리 계층 책임).
    assert state.plan_blocks == [b1, b2]


def test_server_time_echoes_injected_now():
    fake_db = _FakeSession(cycle=None)

    state = home_service.get_home_current_state(fake_db, USER_ID, now=NOW)

    assert state.server_time == NOW


def test_logical_date_before_4am_belongs_to_previous_day():
    early_morning = datetime(2026, 7, 30, 2, 0, tzinfo=SEOUL_TZ)
    fake_db = _FakeSession(cycle=None)

    state = home_service.get_home_current_state(fake_db, USER_ID, now=early_morning)

    assert state.logical_date == date(2026, 7, 29)
    assert state.period == PlanPeriod.EVENING


def test_get_home_current_state_never_opens_write_transaction():
    cycle = _make_cycle()
    fake_db = _FakeSession(cycle=cycle, blocks=[_make_block()])

    home_service.get_home_current_state(fake_db, USER_ID, now=NOW)

    assert fake_db.begin_called is False
