import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.models.check_in import CheckIn
from app.models.enums import PlanBlockStatus, PlanPeriod
from app.models.fixed_schedule import FixedSchedule
from app.models.plan_block import PlanBlock
from app.services import calendar_service

SEOUL_TZ = ZoneInfo("Asia/Seoul")

USER_ID = uuid.uuid4()
OTHER_USER_ID = uuid.uuid4()
CYCLE_ID = uuid.uuid4()
TASK_ID = uuid.uuid4()
NOW = datetime(2026, 7, 30, 14, 0, tzinfo=SEOUL_TZ)


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
        display_title="저장된 실행 단위",
        display_order=0,
        status=PlanBlockStatus.PLANNED,
        checked_at=None,
        check_in_id=None,
    )
    defaults.update(overrides)
    return PlanBlock(**defaults)


def _make_check_in(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        check_date=date(2026, 7, 30),
        period=PlanPeriod.MORNING,
        total_plan_count=2,
        completed_plan_count=0,
        score=0,
        replan_unplaced_minutes=120,
        finalization_started_at=datetime(2026, 7, 30, 12, 0, tzinfo=SEOUL_TZ),
        finalized_at=datetime(2026, 7, 30, 12, 0, 5, tzinfo=SEOUL_TZ),
    )
    defaults.update(overrides)
    return CheckIn(**defaults)


def _make_schedule(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        title="고정 일정",
        start_at=datetime(2026, 7, 30, 10, 0, tzinfo=SEOUL_TZ),
        end_at=datetime(2026, 7, 30, 14, 0, tzinfo=SEOUL_TZ),
    )
    defaults.update(overrides)
    return FixedSchedule(**defaults)


class _FakeScalars:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class _FakeResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return _FakeScalars(self._items)


class _ReadOnlyFakeSession:
    def __init__(self, *, blocks=None, check_ins=None, schedules=None):
        self._results = [blocks or [], check_ins or [], schedules or []]
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)
        return _FakeResult(self._results[len(self.statements) - 1])

    def _reject_write(self, *args, **kwargs):
        raise AssertionError("calendar 조회 service는 DB 쓰기 메서드를 호출하면 안 된다.")

    add = _reject_write
    flush = _reject_write
    commit = _reject_write
    delete = _reject_write
    begin = _reject_write


def _get_period(state, target_date, period):
    day = next(day for day in state.days if day.date == target_date)
    return next(item for item in day.periods if item.period == period)


def test_empty_range_includes_every_day_and_three_ordered_periods():
    db = _ReadOnlyFakeSession()

    state = calendar_service.get_calendar_state(
        db,
        USER_ID,
        from_date=date(2026, 7, 29),
        to_date=date(2026, 7, 31),
        now=NOW,
    )

    assert [day.date for day in state.days] == [
        date(2026, 7, 29),
        date(2026, 7, 30),
        date(2026, 7, 31),
    ]
    for day in state.days:
        assert [period.period for period in day.periods] == [
            PlanPeriod.MORNING,
            PlanPeriod.AFTERNOON,
            PlanPeriod.EVENING,
        ]
        assert all(period.check_in is None for period in day.periods)
        assert all(period.plan_blocks == () for period in day.periods)
        assert all(period.fixed_schedules == () for period in day.periods)


def test_temporal_state_compares_logical_date_and_period():
    db = _ReadOnlyFakeSession()

    state = calendar_service.get_calendar_state(
        db,
        USER_ID,
        from_date=date(2026, 7, 29),
        to_date=date(2026, 7, 31),
        now=NOW,
    )

    assert [period.temporal_state.value for period in state.days[0].periods] == [
        "PAST",
        "PAST",
        "PAST",
    ]
    assert [period.temporal_state.value for period in state.days[1].periods] == [
        "PAST",
        "CURRENT",
        "FUTURE",
    ]
    assert [period.temporal_state.value for period in state.days[2].periods] == [
        "FUTURE",
        "FUTURE",
        "FUTURE",
    ]
    assert state.logical_today == date(2026, 7, 30)
    assert state.current_period == PlanPeriod.AFTERNOON


def test_plan_blocks_are_filtered_by_temporal_state_and_sorted():
    blocks = [
        _make_block(
            plan_date=date(2026, 7, 30),
            period=period,
            status=status,
            display_order=order,
            display_title=f"{period.value}-{status.value}",
        )
        for period in PlanPeriod
        for order, status in enumerate(PlanBlockStatus)
    ]
    # 현재 분기 PLANNED 두 개가 displayOrder 순으로 정렬되는지도 함께 검증한다.
    blocks.append(
        _make_block(
            plan_date=date(2026, 7, 30),
            period=PlanPeriod.AFTERNOON,
            status=PlanBlockStatus.PLANNED,
            display_order=5,
            display_title="저장된 제목 그대로",
        )
    )
    db = _ReadOnlyFakeSession(blocks=blocks)

    state = calendar_service.get_calendar_state(
        db,
        USER_ID,
        from_date=date(2026, 7, 30),
        to_date=date(2026, 7, 30),
        now=NOW,
    )

    morning = _get_period(state, date(2026, 7, 30), PlanPeriod.MORNING)
    afternoon = _get_period(state, date(2026, 7, 30), PlanPeriod.AFTERNOON)
    evening = _get_period(state, date(2026, 7, 30), PlanPeriod.EVENING)
    assert [block.status for block in morning.plan_blocks] == [PlanBlockStatus.COMPLETED]
    assert [block.status for block in afternoon.plan_blocks] == [
        PlanBlockStatus.PLANNED,
        PlanBlockStatus.CHECKED,
        PlanBlockStatus.PLANNED,
    ]
    assert afternoon.plan_blocks[-1].display_title == "저장된 제목 그대로"
    assert [block.status for block in evening.plan_blocks] == [PlanBlockStatus.PLANNED]


def test_past_completed_block_is_not_filtered_by_task_status_join():
    block = _make_block(
        period=PlanPeriod.MORNING,
        status=PlanBlockStatus.COMPLETED,
        display_title="취소된 Task의 과거 완료 스냅숏",
    )
    db = _ReadOnlyFakeSession(blocks=[block])

    state = calendar_service.get_calendar_state(
        db,
        USER_ID,
        from_date=date(2026, 7, 30),
        to_date=date(2026, 7, 30),
        now=NOW,
    )

    assert _get_period(state, date(2026, 7, 30), PlanPeriod.MORNING).plan_blocks == (block,)
    assert "tasks" not in str(db.statements[0]).lower()


def test_only_past_finalized_check_in_is_exposed_and_zero_score_is_preserved():
    past = _make_check_in(score=0, result_acknowledged_at=NOW)
    current = _make_check_in(period=PlanPeriod.AFTERNOON, score=50)
    future = _make_check_in(period=PlanPeriod.EVENING, score=100)
    db = _ReadOnlyFakeSession(check_ins=[past, current, future])

    state = calendar_service.get_calendar_state(
        db,
        USER_ID,
        from_date=date(2026, 7, 30),
        to_date=date(2026, 7, 30),
        now=NOW,
    )

    returned = _get_period(state, date(2026, 7, 30), PlanPeriod.MORNING).check_in
    assert returned is past
    assert returned.score == 0
    assert _get_period(state, date(2026, 7, 30), PlanPeriod.AFTERNOON).check_in is None
    assert _get_period(state, date(2026, 7, 30), PlanPeriod.EVENING).check_in is None


def test_fixed_schedule_is_split_across_periods_without_mutating_original():
    schedule = _make_schedule()
    original_start = schedule.start_at
    original_end = schedule.end_at
    db = _ReadOnlyFakeSession(schedules=[schedule])

    state = calendar_service.get_calendar_state(
        db,
        USER_ID,
        from_date=date(2026, 7, 30),
        to_date=date(2026, 7, 30),
        now=NOW,
    )

    morning = _get_period(state, date(2026, 7, 30), PlanPeriod.MORNING).fixed_schedules[0]
    afternoon = _get_period(state, date(2026, 7, 30), PlanPeriod.AFTERNOON).fixed_schedules[0]
    assert (morning.segment_start_at.hour, morning.segment_end_at.hour) == (10, 12)
    assert (afternoon.segment_start_at.hour, afternoon.segment_end_at.hour) == (12, 14)
    assert morning.start_at == original_start
    assert morning.end_at == original_end
    assert schedule.start_at is original_start
    assert schedule.end_at is original_end


def test_cross_midnight_schedule_stays_in_one_logical_evening():
    schedule = _make_schedule(
        start_at=datetime(2026, 7, 30, 22, 0, tzinfo=SEOUL_TZ),
        end_at=datetime(2026, 7, 31, 2, 0, tzinfo=SEOUL_TZ),
    )
    db = _ReadOnlyFakeSession(schedules=[schedule])

    state = calendar_service.get_calendar_state(
        db,
        USER_ID,
        from_date=date(2026, 7, 30),
        to_date=date(2026, 7, 31),
        now=NOW,
    )

    assert len(_get_period(state, date(2026, 7, 30), PlanPeriod.EVENING).fixed_schedules) == 1
    assert _get_period(state, date(2026, 7, 31), PlanPeriod.MORNING).fixed_schedules == ()


def test_three_to_five_schedule_is_split_at_logical_day_boundary():
    schedule = _make_schedule(
        start_at=datetime(2026, 7, 31, 3, 0, tzinfo=SEOUL_TZ),
        end_at=datetime(2026, 7, 31, 5, 0, tzinfo=SEOUL_TZ),
    )
    db = _ReadOnlyFakeSession(schedules=[schedule])

    state = calendar_service.get_calendar_state(
        db,
        USER_ID,
        from_date=date(2026, 7, 30),
        to_date=date(2026, 7, 31),
        now=NOW,
    )

    evening = _get_period(state, date(2026, 7, 30), PlanPeriod.EVENING).fixed_schedules[0]
    morning = _get_period(state, date(2026, 7, 31), PlanPeriod.MORNING).fixed_schedules[0]
    assert (evening.segment_start_at.hour, evening.segment_end_at.hour) == (3, 4)
    assert (morning.segment_start_at.hour, morning.segment_end_at.hour) == (4, 5)


def test_schedules_ending_on_period_boundaries_are_not_duplicated():
    schedules = [
        _make_schedule(
            start_at=datetime(2026, 7, 30, 10, 0, tzinfo=SEOUL_TZ),
            end_at=datetime(2026, 7, 30, 12, 0, tzinfo=SEOUL_TZ),
        ),
        _make_schedule(
            start_at=datetime(2026, 7, 30, 16, 0, tzinfo=SEOUL_TZ),
            end_at=datetime(2026, 7, 30, 18, 0, tzinfo=SEOUL_TZ),
        ),
        _make_schedule(
            start_at=datetime(2026, 7, 31, 2, 0, tzinfo=SEOUL_TZ),
            end_at=datetime(2026, 7, 31, 4, 0, tzinfo=SEOUL_TZ),
        ),
    ]
    db = _ReadOnlyFakeSession(schedules=schedules)

    state = calendar_service.get_calendar_state(
        db,
        USER_ID,
        from_date=date(2026, 7, 30),
        to_date=date(2026, 7, 31),
        now=NOW,
    )

    assert len(_get_period(state, date(2026, 7, 30), PlanPeriod.MORNING).fixed_schedules) == 1
    assert len(_get_period(state, date(2026, 7, 30), PlanPeriod.AFTERNOON).fixed_schedules) == 1
    assert len(_get_period(state, date(2026, 7, 30), PlanPeriod.EVENING).fixed_schedules) == 1
    assert _get_period(state, date(2026, 7, 31), PlanPeriod.MORNING).fixed_schedules == ()


def test_queries_include_user_and_required_range_predicates():
    db = _ReadOnlyFakeSession()

    calendar_service.get_calendar_state(
        db,
        USER_ID,
        from_date=date(2026, 7, 1),
        to_date=date(2026, 8, 10),
        now=NOW,
    )

    block_sql, check_in_sql, schedule_sql = (str(stmt).lower() for stmt in db.statements)
    assert "plan_blocks.user_id" in block_sql
    assert "plan_blocks.plan_date >=" in block_sql
    assert "plan_blocks.plan_date <=" in block_sql
    assert "check_ins.user_id" in check_in_sql
    assert "check_ins.check_date >=" in check_in_sql
    assert "check_ins.check_date <=" in check_in_sql
    assert "check_ins.finalized_at is not null" in check_in_sql
    assert "fixed_schedules.user_id" in schedule_sql
    assert "fixed_schedules.start_at <" in schedule_sql
    assert "fixed_schedules.end_at >" in schedule_sql


def test_service_uses_only_three_selects_and_no_write_methods():
    db = _ReadOnlyFakeSession()

    calendar_service.get_calendar_state(
        db,
        USER_ID,
        from_date=date(2026, 7, 1),
        to_date=date(2026, 8, 10),
        now=NOW,
    )

    assert len(db.statements) == 3
