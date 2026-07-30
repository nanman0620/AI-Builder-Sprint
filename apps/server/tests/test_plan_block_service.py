import uuid
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.core.errors import ApiError
from app.models.enums import PlanBlockStatus, PlanCycleStatus, PlanPeriod
from app.models.plan_block import PlanBlock
from app.models.planning_cycle import PlanningCycle
from app.services import plan_block_service

SEOUL_TZ = ZoneInfo("Asia/Seoul")

USER_ID = uuid.uuid4()
OTHER_USER_ID = uuid.uuid4()
CYCLE_ID = uuid.uuid4()
OTHER_CYCLE_ID = uuid.uuid4()
TASK_ID = uuid.uuid4()
OTHER_TASK_ID = uuid.uuid4()
EXISTING_BLOCK_ID = uuid.uuid4()


def _make_cycle(**overrides):
    defaults = dict(
        id=CYCLE_ID,
        user_id=USER_ID,
        start_date=date(2026, 7, 27),
        end_date=date(2026, 8, 2),
        status=PlanCycleStatus.ACTIVE,
        activated_at=datetime(2026, 7, 27, 1, 0, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return PlanningCycle(**defaults)


def _make_existing_block(**overrides):
    defaults = dict(
        id=EXISTING_BLOCK_ID,
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        task_id=TASK_ID,
        plan_date=date(2026, 7, 28),
        period=PlanPeriod.AFTERNOON,
        allocated_minutes=60,
        allocated_amount_text=None,
        display_title="기존 실행 문구",
        display_order=1,
        status=PlanBlockStatus.PLANNED,
    )
    defaults.update(overrides)
    return PlanBlock(**defaults)


# ---------------------------------------------------------------------------
# resolve_plan_date / resolve_period — 고정 시각으로만 검증(현재 시각 비의존)
# ---------------------------------------------------------------------------


def test_resolve_plan_date_before_4am_belongs_to_previous_day():
    moment = datetime(2026, 7, 29, 2, 0, tzinfo=SEOUL_TZ)
    assert plan_block_service.resolve_plan_date(moment) == date(2026, 7, 28)


def test_resolve_plan_date_at_4am_belongs_to_same_day():
    moment = datetime(2026, 7, 29, 4, 0, tzinfo=SEOUL_TZ)
    assert plan_block_service.resolve_plan_date(moment) == date(2026, 7, 29)


def test_resolve_plan_date_rejects_naive_datetime():
    with pytest.raises(ValueError):
        plan_block_service.resolve_plan_date(datetime(2026, 7, 29, 2, 0))


@pytest.mark.parametrize(
    "hour, expected",
    [
        (4, PlanPeriod.MORNING),
        (11, PlanPeriod.MORNING),
        (12, PlanPeriod.AFTERNOON),
        (17, PlanPeriod.AFTERNOON),
        (18, PlanPeriod.EVENING),
        (23, PlanPeriod.EVENING),
        (0, PlanPeriod.EVENING),
        (3, PlanPeriod.EVENING),
    ],
)
def test_resolve_period_boundaries(hour, expected):
    moment = datetime(2026, 7, 29, hour, 0, tzinfo=SEOUL_TZ)
    assert plan_block_service.resolve_period(moment) == expected


def test_resolve_period_rejects_naive_datetime():
    with pytest.raises(ValueError):
        plan_block_service.resolve_period(datetime(2026, 7, 29, 10, 0))


# ---------------------------------------------------------------------------
# validate_date_in_cycle_range — plan_date/check_date 공용 validator
# ---------------------------------------------------------------------------


def test_validate_date_in_cycle_range_accepts_boundaries():
    cycle = _make_cycle()
    plan_block_service.validate_date_in_cycle_range(cycle, date(2026, 7, 27), field="planDate")
    plan_block_service.validate_date_in_cycle_range(cycle, date(2026, 8, 2), field="planDate")


def test_validate_date_in_cycle_range_rejects_plan_date_outside():
    cycle = _make_cycle()
    with pytest.raises(ApiError) as exc_info:
        plan_block_service.validate_date_in_cycle_range(cycle, date(2026, 8, 3), field="planDate")
    assert exc_info.value.status_code == 422
    assert exc_info.value.code == plan_block_service.CODE_INVALID_DATE_RANGE
    assert exc_info.value.details == {"field": "planDate"}


def test_validate_date_in_cycle_range_rejects_check_date_outside():
    cycle = _make_cycle()
    with pytest.raises(ApiError) as exc_info:
        plan_block_service.validate_date_in_cycle_range(cycle, date(2026, 7, 26), field="checkDate")
    assert exc_info.value.code == plan_block_service.CODE_INVALID_DATE_RANGE
    assert exc_info.value.details == {"field": "checkDate"}


# ---------------------------------------------------------------------------
# validate_fixed_schedule_range
# ---------------------------------------------------------------------------


def test_validate_fixed_schedule_range_accepts_within_cycle():
    cycle = _make_cycle()
    start = datetime(2026, 7, 28, 22, 0, tzinfo=SEOUL_TZ)
    end = datetime(2026, 7, 29, 2, 0, tzinfo=SEOUL_TZ)
    plan_block_service.validate_fixed_schedule_range(cycle, start, end)


def test_validate_fixed_schedule_range_rejects_start_after_end():
    cycle = _make_cycle()
    start = datetime(2026, 7, 28, 10, 0, tzinfo=SEOUL_TZ)
    end = datetime(2026, 7, 28, 9, 0, tzinfo=SEOUL_TZ)
    with pytest.raises(ApiError) as exc_info:
        plan_block_service.validate_fixed_schedule_range(cycle, start, end)
    assert exc_info.value.code == plan_block_service.CODE_INVALID_DATE_RANGE
    assert exc_info.value.details == {"field": "startAt"}


def test_validate_fixed_schedule_range_rejects_start_outside_cycle():
    cycle = _make_cycle()
    start = datetime(2026, 7, 26, 22, 0, tzinfo=SEOUL_TZ)
    end = datetime(2026, 7, 27, 1, 0, tzinfo=SEOUL_TZ)
    with pytest.raises(ApiError) as exc_info:
        plan_block_service.validate_fixed_schedule_range(cycle, start, end)
    assert exc_info.value.details == {"field": "startAt"}


def test_validate_fixed_schedule_range_rejects_end_outside_cycle():
    cycle = _make_cycle()
    start = datetime(2026, 8, 2, 23, 0, tzinfo=SEOUL_TZ)
    end = datetime(2026, 8, 3, 5, 0, tzinfo=SEOUL_TZ)
    with pytest.raises(ApiError) as exc_info:
        plan_block_service.validate_fixed_schedule_range(cycle, start, end)
    assert exc_info.value.details == {"field": "endAt"}


def test_validate_fixed_schedule_range_end_before_4am_still_within_cycle():
    # cycle end_date=8/2, 종료가 8/3 02:00(04:00 이전)이면 8/2 EVENING 범위로 계산되어 허용된다.
    cycle = _make_cycle()
    start = datetime(2026, 8, 2, 22, 0, tzinfo=SEOUL_TZ)
    end = datetime(2026, 8, 3, 2, 0, tzinfo=SEOUL_TZ)
    plan_block_service.validate_fixed_schedule_range(cycle, start, end)


def test_validate_fixed_schedule_range_end_exactly_4am_still_within_cycle():
    # 종료가 정확히 다음 날 04:00이면 그 직전(EVENING 마지막 microsecond)까지가 판단 기준이므로
    # cycle 마지막 날(8/2) EVENING 범위로 허용된다.
    cycle = _make_cycle()
    start = datetime(2026, 8, 2, 22, 0, tzinfo=SEOUL_TZ)
    end = datetime(2026, 8, 3, 4, 0, tzinfo=SEOUL_TZ)
    plan_block_service.validate_fixed_schedule_range(cycle, start, end)


def test_validate_fixed_schedule_range_rejects_naive_start_at():
    cycle = _make_cycle()
    start = datetime(2026, 7, 28, 22, 0)
    end = datetime(2026, 7, 29, 2, 0, tzinfo=SEOUL_TZ)
    with pytest.raises(ValueError):
        plan_block_service.validate_fixed_schedule_range(cycle, start, end)


def test_validate_fixed_schedule_range_rejects_naive_end_at():
    cycle = _make_cycle()
    start = datetime(2026, 7, 28, 22, 0, tzinfo=SEOUL_TZ)
    end = datetime(2026, 7, 29, 2, 0)
    with pytest.raises(ValueError):
        plan_block_service.validate_fixed_schedule_range(cycle, start, end)


def test_validate_fixed_schedule_range_rejects_both_naive():
    cycle = _make_cycle()
    start = datetime(2026, 7, 28, 22, 0)
    end = datetime(2026, 7, 29, 2, 0)
    with pytest.raises(ValueError):
        plan_block_service.validate_fixed_schedule_range(cycle, start, end)


# ---------------------------------------------------------------------------
# validate_reschedule_source — 순수 함수, DB 불필요
# ---------------------------------------------------------------------------


def test_validate_reschedule_source_accepts_valid_future_reschedule():
    original = _make_existing_block()
    plan_block_service.validate_reschedule_source(
        original=original,
        new_user_id=USER_ID,
        new_plan_cycle_id=CYCLE_ID,
        new_task_id=TASK_ID,
        new_plan_date=date(2026, 7, 29),
        new_period=PlanPeriod.MORNING,
    )


def test_validate_reschedule_source_rejects_other_user():
    original = _make_existing_block()
    with pytest.raises(ApiError) as exc_info:
        plan_block_service.validate_reschedule_source(
            original=original,
            new_user_id=OTHER_USER_ID,
            new_plan_cycle_id=CYCLE_ID,
            new_task_id=TASK_ID,
            new_plan_date=date(2026, 7, 29),
            new_period=PlanPeriod.MORNING,
        )
    assert exc_info.value.status_code == 404
    assert exc_info.value.code == plan_block_service.CODE_PLAN_BLOCK_NOT_FOUND


def test_validate_reschedule_source_rejects_cycle_mismatch():
    original = _make_existing_block()
    with pytest.raises(ApiError) as exc_info:
        plan_block_service.validate_reschedule_source(
            original=original,
            new_user_id=USER_ID,
            new_plan_cycle_id=OTHER_CYCLE_ID,
            new_task_id=TASK_ID,
            new_plan_date=date(2026, 7, 29),
            new_period=PlanPeriod.MORNING,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == plan_block_service.CODE_PLAN_BLOCK_CYCLE_MISMATCH


def test_validate_reschedule_source_rejects_task_mismatch():
    original = _make_existing_block()
    with pytest.raises(ApiError) as exc_info:
        plan_block_service.validate_reschedule_source(
            original=original,
            new_user_id=USER_ID,
            new_plan_cycle_id=CYCLE_ID,
            new_task_id=OTHER_TASK_ID,
            new_plan_date=date(2026, 7, 29),
            new_period=PlanPeriod.MORNING,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == plan_block_service.CODE_PLAN_BLOCK_TASK_MISMATCH


def test_validate_reschedule_source_rejects_non_planned_status():
    original = _make_existing_block(status=PlanBlockStatus.CHECKED)
    with pytest.raises(ApiError) as exc_info:
        plan_block_service.validate_reschedule_source(
            original=original,
            new_user_id=USER_ID,
            new_plan_cycle_id=CYCLE_ID,
            new_task_id=TASK_ID,
            new_plan_date=date(2026, 7, 29),
            new_period=PlanPeriod.MORNING,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == plan_block_service.CODE_INVALID_REQUEST_STATE


@pytest.mark.parametrize(
    "new_plan_date, new_period",
    [
        (date(2026, 7, 28), PlanPeriod.AFTERNOON),  # 원본과 완전히 동일한 시점
        (date(2026, 7, 28), PlanPeriod.MORNING),  # 같은 날짜의 더 이른 period
        (date(2026, 7, 27), PlanPeriod.EVENING),  # 과거 날짜
    ],
)
def test_validate_reschedule_source_rejects_past_or_same(new_plan_date, new_period):
    original = _make_existing_block(plan_date=date(2026, 7, 28), period=PlanPeriod.AFTERNOON)
    with pytest.raises(ApiError) as exc_info:
        plan_block_service.validate_reschedule_source(
            original=original,
            new_user_id=USER_ID,
            new_plan_cycle_id=CYCLE_ID,
            new_task_id=TASK_ID,
            new_plan_date=new_plan_date,
            new_period=new_period,
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.code == plan_block_service.CODE_PLAN_BLOCK_RESCHEDULE_NOT_IN_FUTURE


# ---------------------------------------------------------------------------
# get_active_planning_cycle
# ---------------------------------------------------------------------------


class _FakeSingleQuerySession:
    """execute() 1회 호출로 scalar_one_or_none() 결과를 돌려주는 최소 fake."""

    def __init__(self, value):
        self._value = value
        self.last_statement = None

    def execute(self, stmt):
        self.last_statement = stmt
        return _FakeResult(self._value)


def test_get_active_planning_cycle_returns_cycle_when_exists():
    cycle = _make_cycle()
    fake_db = _FakeSingleQuerySession(cycle)

    result = plan_block_service.get_active_planning_cycle(fake_db, USER_ID)

    assert result is cycle


def test_get_active_planning_cycle_returns_none_when_missing():
    fake_db = _FakeSingleQuerySession(None)

    result = plan_block_service.get_active_planning_cycle(fake_db, USER_ID)

    assert result is None


def test_get_active_planning_cycle_query_filters_by_user_and_active_status():
    fake_db = _FakeSingleQuerySession(None)

    plan_block_service.get_active_planning_cycle(fake_db, USER_ID)

    sql = str(fake_db.last_statement)
    assert "planning_cycles.user_id" in sql
    assert "planning_cycles.status" in sql


# ---------------------------------------------------------------------------
# list_current_period_plan_blocks
# ---------------------------------------------------------------------------


class _FakeScalarsResult:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class _FakeListResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return _FakeScalarsResult(self._items)


class _FakeListQuerySession:
    """execute() 1회 호출로 scalars().all() 결과를 돌려주는 최소 fake."""

    def __init__(self, items):
        self._items = items
        self.last_statement = None

    def execute(self, stmt):
        self.last_statement = stmt
        return _FakeListResult(self._items)


def test_list_current_period_plan_blocks_query_conditions():
    fake_db = _FakeListQuerySession([])

    plan_block_service.list_current_period_plan_blocks(
        fake_db,
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        plan_date=date(2026, 7, 30),
        period=PlanPeriod.AFTERNOON,
    )

    sql = str(fake_db.last_statement)
    assert "plan_blocks.user_id" in sql
    assert "plan_blocks.plan_cycle_id" in sql
    assert "plan_blocks.plan_date" in sql
    assert "plan_blocks.period" in sql
    assert "plan_blocks.status IN" in sql
    assert "ORDER BY plan_blocks.display_order" in sql


def test_list_current_period_plan_blocks_returns_items_in_query_order():
    b1 = _make_existing_block(id=uuid.uuid4(), display_order=0)
    b2 = _make_existing_block(id=uuid.uuid4(), display_order=1)
    fake_db = _FakeListQuerySession([b1, b2])

    result = plan_block_service.list_current_period_plan_blocks(
        fake_db,
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        plan_date=date(2026, 7, 30),
        period=PlanPeriod.AFTERNOON,
    )

    assert result == [b1, b2]


# ---------------------------------------------------------------------------
# compute_plan_block_progress
# ---------------------------------------------------------------------------


def test_compute_plan_block_progress_empty_list_is_zero():
    result = plan_block_service.compute_plan_block_progress([])

    assert result == plan_block_service.PlanBlockProgress(
        checked_count=0, total_count=0, percentage=0
    )


@pytest.mark.parametrize(
    "checked, total, expected_percentage",
    [
        (1, 8, 13),  # 12.5 -> ROUND_HALF_UP -> 13 (명세 9절 예시와 동일)
        (2, 3, 67),  # 66.66... -> 67 (명세 9절 예시와 동일)
        (5, 7, 71),  # 71.42... -> 71 (명세 9절 예시와 동일)
        (1, 2, 50),
        (0, 5, 0),
        (5, 5, 100),
    ],
)
def test_compute_plan_block_progress_rounds_half_up(checked, total, expected_percentage):
    blocks = [
        _make_existing_block(id=uuid.uuid4(), status=PlanBlockStatus.CHECKED)
        for _ in range(checked)
    ] + [
        _make_existing_block(id=uuid.uuid4(), status=PlanBlockStatus.PLANNED)
        for _ in range(total - checked)
    ]

    result = plan_block_service.compute_plan_block_progress(blocks)

    assert result.checked_count == checked
    assert result.total_count == total
    assert result.percentage == expected_percentage


# ---------------------------------------------------------------------------
# reschedule_plan_block — 트랜잭션 오케스트레이션. Fake Session으로 begin()의
# 커밋/롤백 호출 여부만 검증하는 단위 테스트이며, 실제 PostgreSQL rollback을
# 검증하는 통합 테스트가 아니다(후속 작업으로 남김).
# ---------------------------------------------------------------------------


class _TransactionRecorder:
    def __init__(self):
        self.committed = False
        self.rolled_back = False


class _FakeTransaction:
    def __init__(self, recorder: _TransactionRecorder):
        self._recorder = recorder

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._recorder.committed = True
        else:
            self._recorder.rolled_back = True
        return False  # 예외를 삼키지 않고 그대로 호출자에게 전달한다.


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeSession:
    """SELECT(1회차: PlanBlock, 2회차: PlanningCycle) → delete → flush → add → flush
    호출 순서를 그대로 모사하는 최소 fake. 실제 SQL은 실행하지 않는다."""

    def __init__(self, *, existing_block, cycle, fail_on_second_flush=False):
        self._existing_block = existing_block
        self._cycle = cycle
        self._execute_calls = 0
        self._fail_on_second_flush = fail_on_second_flush
        self.deleted = []
        self.added = []
        self.flush_calls = 0
        self.for_update_seen = False
        self.recorder = _TransactionRecorder()

    def begin(self):
        return _FakeTransaction(self.recorder)

    def execute(self, stmt):
        self._execute_calls += 1
        if self._execute_calls == 1:
            self.for_update_seen = "FOR UPDATE" in str(stmt).upper()
            return _FakeResult(self._existing_block)
        return _FakeResult(self._cycle)

    def delete(self, obj):
        self.deleted.append(obj)

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        self.flush_calls += 1
        if self._fail_on_second_flush and self.flush_calls == 2:
            raise RuntimeError("simulated failure during second flush")

    def refresh(self, obj):
        pass


def _reschedule(fake_db, **overrides):
    kwargs = dict(
        user_id=USER_ID,
        existing_block_id=EXISTING_BLOCK_ID,
        plan_date=date(2026, 7, 29),
        period=PlanPeriod.AFTERNOON,
        allocated_minutes=90,
        allocated_amount_text="2문제",
        display_title="새 실행 문구",
        display_order=2,
    )
    kwargs.update(overrides)
    return plan_block_service.reschedule_plan_block(fake_db, **kwargs)


def test_reschedule_plan_block_success_deletes_old_and_creates_new():
    existing = _make_existing_block()
    cycle = _make_cycle()
    fake_db = _FakeSession(existing_block=existing, cycle=cycle)

    result = _reschedule(fake_db)

    assert fake_db.deleted == [existing]
    assert len(fake_db.added) == 1
    assert fake_db.added[0] is result
    assert result.rescheduled_from_block_id is None
    assert result.status == PlanBlockStatus.PLANNED
    assert result.plan_date == date(2026, 7, 29)
    assert result.period == PlanPeriod.AFTERNOON
    assert result.plan_cycle_id == CYCLE_ID
    assert result.task_id == TASK_ID
    assert result.display_title == "새 실행 문구"
    assert fake_db.for_update_seen is True
    assert fake_db.flush_calls == 2
    assert fake_db.recorder.committed is True
    assert fake_db.recorder.rolled_back is False


def test_reschedule_plan_block_rejects_missing_or_other_user_block():
    cycle = _make_cycle()
    fake_db = _FakeSession(existing_block=None, cycle=cycle)

    with pytest.raises(ApiError) as exc_info:
        _reschedule(fake_db)

    assert exc_info.value.code == plan_block_service.CODE_PLAN_BLOCK_NOT_FOUND
    assert fake_db.deleted == []
    assert fake_db.added == []
    assert fake_db.recorder.rolled_back is True
    assert fake_db.recorder.committed is False


def test_reschedule_plan_block_rejects_plan_date_outside_cycle():
    existing = _make_existing_block()
    cycle = _make_cycle()
    fake_db = _FakeSession(existing_block=existing, cycle=cycle)

    with pytest.raises(ApiError) as exc_info:
        _reschedule(fake_db, plan_date=date(2026, 8, 10))

    assert exc_info.value.code == plan_block_service.CODE_INVALID_DATE_RANGE
    assert fake_db.deleted == []
    assert fake_db.added == []
    assert fake_db.recorder.rolled_back is True
    assert fake_db.recorder.committed is False


def test_reschedule_plan_block_rolls_back_on_second_flush_failure():
    """중간 실패 rollback: delete + 1차 flush + add까지 실행된 뒤 2차 flush에서
    예외가 발생하면 rolled_back=True, committed=False, 예외가 호출자에게 재전달됨을 확인한다.
    Fake Session은 실제 DB 상태를 복원하지 않으므로 이는 트랜잭션 오케스트레이션(호출 순서·
    커밋/롤백 분기) 단위 테스트이며, 실제 PostgreSQL rollback 통합 테스트는 후속 작업이다.
    """
    existing = _make_existing_block()
    cycle = _make_cycle()
    fake_db = _FakeSession(existing_block=existing, cycle=cycle, fail_on_second_flush=True)

    with pytest.raises(RuntimeError):
        _reschedule(fake_db)

    assert fake_db.deleted == [existing]
    assert len(fake_db.added) == 1
    assert fake_db.flush_calls == 2
    assert fake_db.recorder.rolled_back is True
    assert fake_db.recorder.committed is False


# ---------------------------------------------------------------------------
# set_plan_block_check_state — 소유권·활성 cycle·날짜·분기·정산·상태 전이 검증과
# 진행률 재계산까지 하나의 트랜잭션으로 처리하는지 확인한다.
# ---------------------------------------------------------------------------

CHECK_STATE_NOW = datetime(2026, 7, 30, 14, 0, tzinfo=SEOUL_TZ)
CHECK_STATE_PLAN_DATE = date(2026, 7, 30)
CHECK_STATE_PERIOD = PlanPeriod.AFTERNOON


class _CheckStateFakeSession:
    """execute() 호출 순서: 1) PlanBlock(FOR UPDATE), 2) 활성 PlanningCycle,
    3) (검증 통과 시에만) 현재 분기 PlanBlock 목록. flush/refresh는 in-memory 객체를
    그대로 쓰므로 아무 것도 하지 않는다."""

    def __init__(self, *, block, cycle, current_blocks=()):
        self._block = block
        self._cycle = cycle
        self._current_blocks = list(current_blocks)
        self._execute_calls = 0
        self.for_update_seen = False
        self.recorder = _TransactionRecorder()

    def begin(self):
        return _FakeTransaction(self.recorder)

    def execute(self, stmt):
        self._execute_calls += 1
        if self._execute_calls == 1:
            self.for_update_seen = "FOR UPDATE" in str(stmt).upper()
            return _FakeResult(self._block)
        if self._execute_calls == 2:
            return _FakeResult(self._cycle)
        return _FakeListResult(self._current_blocks)

    def flush(self):
        pass

    def refresh(self, obj):
        pass


def _set_check_state(fake_db, **overrides):
    kwargs = dict(
        user_id=USER_ID,
        plan_block_id=EXISTING_BLOCK_ID,
        checked=True,
        now=CHECK_STATE_NOW,
    )
    kwargs.update(overrides)
    return plan_block_service.set_plan_block_check_state(fake_db, **kwargs)


def test_set_plan_block_check_state_planned_to_checked_success():
    block = _make_existing_block(
        status=PlanBlockStatus.PLANNED, plan_date=CHECK_STATE_PLAN_DATE, period=CHECK_STATE_PERIOD
    )
    cycle = _make_cycle()
    fake_db = _CheckStateFakeSession(block=block, cycle=cycle, current_blocks=[block])

    result = _set_check_state(fake_db, checked=True)

    assert result.plan_block.status == PlanBlockStatus.CHECKED
    assert result.plan_block.checked_at == CHECK_STATE_NOW
    assert fake_db.for_update_seen is True
    assert fake_db.recorder.committed is True
    assert fake_db.recorder.rolled_back is False


def test_set_plan_block_check_state_checked_to_planned_success():
    block = _make_existing_block(
        status=PlanBlockStatus.CHECKED,
        checked_at=CHECK_STATE_NOW,
        plan_date=CHECK_STATE_PLAN_DATE,
        period=CHECK_STATE_PERIOD,
    )
    cycle = _make_cycle()
    fake_db = _CheckStateFakeSession(block=block, cycle=cycle, current_blocks=[block])

    result = _set_check_state(fake_db, checked=False)

    assert result.plan_block.status == PlanBlockStatus.PLANNED
    assert result.plan_block.checked_at is None


def test_set_plan_block_check_state_sets_checked_at_when_checking():
    block = _make_existing_block(
        status=PlanBlockStatus.PLANNED,
        checked_at=None,
        plan_date=CHECK_STATE_PLAN_DATE,
        period=CHECK_STATE_PERIOD,
    )
    cycle = _make_cycle()
    fake_db = _CheckStateFakeSession(block=block, cycle=cycle, current_blocks=[block])

    result = _set_check_state(fake_db, checked=True)

    assert result.plan_block.checked_at == CHECK_STATE_NOW


def test_set_plan_block_check_state_clears_checked_at_when_unchecking():
    block = _make_existing_block(
        status=PlanBlockStatus.CHECKED,
        checked_at=CHECK_STATE_NOW,
        plan_date=CHECK_STATE_PLAN_DATE,
        period=CHECK_STATE_PERIOD,
    )
    cycle = _make_cycle()
    fake_db = _CheckStateFakeSession(block=block, cycle=cycle, current_blocks=[block])

    result = _set_check_state(fake_db, checked=False)

    assert result.plan_block.checked_at is None


def test_set_plan_block_check_state_rejects_missing_block():
    cycle = _make_cycle()
    fake_db = _CheckStateFakeSession(block=None, cycle=cycle)

    with pytest.raises(ApiError) as exc_info:
        _set_check_state(fake_db)

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == plan_block_service.CODE_PLAN_BLOCK_NOT_FOUND
    assert fake_db.recorder.rolled_back is True
    assert fake_db.recorder.committed is False


def test_set_plan_block_check_state_rejects_no_active_cycle():
    block = _make_existing_block(plan_date=CHECK_STATE_PLAN_DATE, period=CHECK_STATE_PERIOD)
    fake_db = _CheckStateFakeSession(block=block, cycle=None)

    with pytest.raises(ApiError) as exc_info:
        _set_check_state(fake_db)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == plan_block_service.CODE_BLOCK_NOT_IN_CURRENT_PERIOD


def test_set_plan_block_check_state_rejects_cycle_mismatch():
    block = _make_existing_block(
        plan_cycle_id=OTHER_CYCLE_ID, plan_date=CHECK_STATE_PLAN_DATE, period=CHECK_STATE_PERIOD
    )
    cycle = _make_cycle()  # id=CYCLE_ID
    fake_db = _CheckStateFakeSession(block=block, cycle=cycle)

    with pytest.raises(ApiError) as exc_info:
        _set_check_state(fake_db)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == plan_block_service.CODE_BLOCK_NOT_IN_CURRENT_PERIOD


def test_set_plan_block_check_state_rejects_date_mismatch():
    block = _make_existing_block(plan_date=date(2026, 7, 29), period=CHECK_STATE_PERIOD)
    cycle = _make_cycle()
    fake_db = _CheckStateFakeSession(block=block, cycle=cycle)

    with pytest.raises(ApiError) as exc_info:
        _set_check_state(fake_db)

    assert exc_info.value.code == plan_block_service.CODE_BLOCK_NOT_IN_CURRENT_PERIOD


def test_set_plan_block_check_state_rejects_period_mismatch():
    block = _make_existing_block(plan_date=CHECK_STATE_PLAN_DATE, period=PlanPeriod.MORNING)
    cycle = _make_cycle()
    fake_db = _CheckStateFakeSession(block=block, cycle=cycle)

    with pytest.raises(ApiError) as exc_info:
        _set_check_state(fake_db)

    assert exc_info.value.code == plan_block_service.CODE_BLOCK_NOT_IN_CURRENT_PERIOD


def test_set_plan_block_check_state_rejects_already_finalized():
    block = _make_existing_block(
        status=PlanBlockStatus.COMPLETED,
        checked_at=CHECK_STATE_NOW,
        check_in_id=uuid.uuid4(),
        plan_date=CHECK_STATE_PLAN_DATE,
        period=CHECK_STATE_PERIOD,
    )
    cycle = _make_cycle()
    fake_db = _CheckStateFakeSession(block=block, cycle=cycle)

    with pytest.raises(ApiError) as exc_info:
        _set_check_state(fake_db, checked=False)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == plan_block_service.CODE_PERIOD_ALREADY_FINALIZED


def test_set_plan_block_check_state_rejects_checking_when_not_planned():
    block = _make_existing_block(
        status=PlanBlockStatus.CHECKED,
        checked_at=CHECK_STATE_NOW,
        plan_date=CHECK_STATE_PLAN_DATE,
        period=CHECK_STATE_PERIOD,
    )
    cycle = _make_cycle()
    fake_db = _CheckStateFakeSession(block=block, cycle=cycle)

    with pytest.raises(ApiError) as exc_info:
        _set_check_state(fake_db, checked=True)

    assert exc_info.value.status_code == 422
    assert exc_info.value.code == plan_block_service.CODE_INVALID_CHECK_STATE


def test_set_plan_block_check_state_rejects_unchecking_when_not_checked():
    block = _make_existing_block(
        status=PlanBlockStatus.PLANNED, plan_date=CHECK_STATE_PLAN_DATE, period=CHECK_STATE_PERIOD
    )
    cycle = _make_cycle()
    fake_db = _CheckStateFakeSession(block=block, cycle=cycle)

    with pytest.raises(ApiError) as exc_info:
        _set_check_state(fake_db, checked=False)

    assert exc_info.value.status_code == 422
    assert exc_info.value.code == plan_block_service.CODE_INVALID_CHECK_STATE


def test_set_plan_block_check_state_recomputes_progress_after_change():
    target = _make_existing_block(
        status=PlanBlockStatus.PLANNED, plan_date=CHECK_STATE_PLAN_DATE, period=CHECK_STATE_PERIOD
    )
    other_checked = _make_existing_block(
        id=uuid.uuid4(),
        status=PlanBlockStatus.CHECKED,
        plan_date=CHECK_STATE_PLAN_DATE,
        period=CHECK_STATE_PERIOD,
    )
    cycle = _make_cycle()
    # 재조회 시점에는 target도 CHECKED로 반영된 상태로 돌아온다고 가정한다(같은 in-memory 객체).
    fake_db = _CheckStateFakeSession(
        block=target, cycle=cycle, current_blocks=[target, other_checked]
    )

    result = _set_check_state(fake_db, checked=True)

    assert result.progress.total_count == 2
    assert result.progress.checked_count == 2
    assert result.progress.percentage == 100


def test_set_plan_block_check_state_rolls_back_on_validation_error():
    block = _make_existing_block(plan_date=date(2026, 7, 1), period=CHECK_STATE_PERIOD)
    cycle = _make_cycle()
    fake_db = _CheckStateFakeSession(block=block, cycle=cycle)

    with pytest.raises(ApiError):
        _set_check_state(fake_db)

    assert fake_db.recorder.rolled_back is True
    assert fake_db.recorder.committed is False
