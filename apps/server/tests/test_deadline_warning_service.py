"""deadline_warning_service 단위 테스트.

이 서비스는 begin()을 소유하는 acknowledge_deadline_warnings와, 조회만 하는
compute_deadline_warnings를 모두 제공한다. 두 경로 모두 지원하는 전용 in-memory
Fake Session(_DeadlineWarningFakeSession)을 이 파일에서만 사용한다(다른 테스트 파일의
FakeSchedulerSession은 is_()/isnot()/in_() 절을 지원하지 않아 이 서비스의 쿼리를
그대로 평가할 수 없다 — tests/support_scheduler.py는 건드리지 않고 이 파일에 로컬로
확장된 평가기를 둔다).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.sql import operators as sa_operators
from sqlalchemy.sql.elements import BindParameter, BooleanClauseList, Null

from app.core.errors import ApiError
from app.models.enums import PlanBlockStatus, PlanCycleStatus, PlanPeriod, TaskStatus
from app.services import deadline_warning_service as svc
from tests.support_scheduler import make_cycle, make_fixed_schedule, make_plan_block, make_task

SEOUL = ZoneInfo("Asia/Seoul")


# ---------------------------------------------------------------------------
# 범용 WHERE절 평가기 — tests/support_scheduler.py의 것보다 넓게 eq/ne/gt/lt/is_/
# isnot/in_op/and_/or_를 지원한다.
# ---------------------------------------------------------------------------


def _resolve_scalar(side, obj):
    if isinstance(side, BindParameter):
        return side.value
    if isinstance(side, Null):
        return None
    key = getattr(side, "key", None)
    if key is not None and hasattr(obj, key):
        return getattr(obj, key)
    raise AssertionError(f"평가할 수 없는 피연산자입니다: {side!r}")


def _eval_clause(clause, obj) -> bool:
    if isinstance(clause, BooleanClauseList):
        results = [_eval_clause(sub, obj) for sub in clause.clauses]
        if clause.operator is sa_operators.and_:
            return all(results)
        if clause.operator is sa_operators.or_:
            return any(results)
        raise AssertionError(f"지원하지 않는 불리언 연산자입니다: {clause.operator}")

    op = clause.operator
    left = _resolve_scalar(clause.left, obj)

    if op is sa_operators.in_op or op is sa_operators.not_in_op:
        right = clause.right
        values = right.value if isinstance(right, BindParameter) else right
        member = left in values
        return member if op is sa_operators.in_op else not member

    if op is sa_operators.is_:
        return left is None
    if op is sa_operators.is_not:
        return left is not None

    right = _resolve_scalar(clause.right, obj)
    return bool(op(left, right))


class _FakeScalars:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)


class _FakeExecResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return _FakeScalars(self._rows)

    def scalar_one_or_none(self):
        if not self._rows:
            return None
        if len(self._rows) > 1:
            raise AssertionError("scalar_one_or_none()에 두 건 이상의 행이 매칭되었습니다.")
        return self._rows[0]


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
        return False


class _DeadlineWarningFakeSession:
    """add/delete 없이 select(WHERE 평가) + with_for_update 감지 + begin()/flush()만 지원."""

    def __init__(self):
        self._rows: dict[type, list] = {}
        self.recorder = _TransactionRecorder()
        self.flush_calls = 0
        self.for_update_seen = False

    def seed(self, *objects):
        for obj in objects:
            self._rows.setdefault(type(obj), []).append(obj)
        return self

    def execute(self, stmt):
        if "FOR UPDATE" in str(stmt).upper():
            self.for_update_seen = True
        entity = stmt.column_descriptions[0]["entity"]
        candidates = list(self._rows.get(entity, []))
        whereclause = stmt.whereclause
        if whereclause is not None:
            candidates = [obj for obj in candidates if _eval_clause(whereclause, obj)]
        return _FakeExecResult(candidates)

    def begin(self):
        return _FakeTransaction(self.recorder)

    def flush(self):
        self.flush_calls += 1


# ---------------------------------------------------------------------------
# 공통 fixture 데이터
# ---------------------------------------------------------------------------

USER_ID = uuid.uuid4()
OTHER_USER_ID = uuid.uuid4()
CYCLE_ID = uuid.uuid4()
TASK_ID = uuid.uuid4()
OTHER_TASK_ID = uuid.uuid4()

CYCLE_START = date(2026, 7, 27)
CYCLE_END = date(2026, 8, 2)  # start + 6 = cycle_is_exactly_seven_days CHECK과 일치
# cycle_end_at = end_date 다음날 04:00 Asia/Seoul
CYCLE_END_AT = datetime(2026, 8, 3, 4, 0, tzinfo=SEOUL)

NOW = datetime(2026, 7, 29, 14, 10, tzinfo=SEOUL)  # AFTERNOON(12-18), plan_date=2026-07-29
CURRENT_PLAN_DATE = date(2026, 7, 29)
CURRENT_PERIOD = PlanPeriod.AFTERNOON


def _cycle(**overrides):
    fields = dict(
        id=CYCLE_ID,
        user_id=USER_ID,
        start_date=CYCLE_START,
        end_date=CYCLE_END,
        status=PlanCycleStatus.ACTIVE,
        activated_at=datetime(2026, 7, 27, 5, 0, tzinfo=SEOUL),
    )
    fields.update(overrides)
    return make_cycle(**fields)


def _task(**overrides):
    fields = dict(
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        remaining_minutes=100,
        deadline_at=datetime(2026, 7, 31, 23, 59, 59, tzinfo=SEOUL),
        created_at=datetime(2026, 7, 27, 6, 0, tzinfo=SEOUL),
        id=TASK_ID,
    )
    fields.update(overrides)
    return make_task(**fields)


# ---------------------------------------------------------------------------
# 1. 경고 후보 필터 — _get_candidate_tasks
# ---------------------------------------------------------------------------


def test_candidate_query_includes_only_active_deadline_remaining_unacknowledged():
    ok = _task(id=uuid.uuid4())
    not_active = _task(id=uuid.uuid4(), status=TaskStatus.CANCELLED, cancelled_at=NOW)
    no_deadline = _task(id=uuid.uuid4(), deadline_at=None)
    already_acknowledged = _task(id=uuid.uuid4(), deadline_warning_acknowledged_at=NOW)
    zero_remaining = _task(id=uuid.uuid4(), remaining_minutes=0)
    other_user = _task(id=uuid.uuid4(), user_id=OTHER_USER_ID)

    db = _DeadlineWarningFakeSession().seed(
        ok, not_active, no_deadline, already_acknowledged, zero_remaining, other_user
    )

    candidates = svc._get_candidate_tasks(db, USER_ID)

    assert [t.id for t in candidates] == [ok.id]


# ---------------------------------------------------------------------------
# 2~4. 미정산 CHECKED 차감 — _unfinalized_checked_minutes
# ---------------------------------------------------------------------------


def test_unfinalized_checked_minutes_sums_current_period_checked_block():
    block = make_plan_block(
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        task_id=TASK_ID,
        plan_date=CURRENT_PLAN_DATE,
        period=CURRENT_PERIOD,
        allocated_minutes=45,
        status=PlanBlockStatus.CHECKED,
        now=NOW,
    )
    db = _DeadlineWarningFakeSession().seed(block)

    minutes = svc._unfinalized_checked_minutes(
        db, task_id=TASK_ID, plan_date=CURRENT_PLAN_DATE, period=CURRENT_PERIOD
    )

    assert minutes == 45


def test_unfinalized_checked_minutes_ignores_other_period_checked_block():
    other_period_block = make_plan_block(
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        task_id=TASK_ID,
        plan_date=CURRENT_PLAN_DATE,
        period=PlanPeriod.EVENING,  # 현재 분기(AFTERNOON)가 아님
        allocated_minutes=45,
        status=PlanBlockStatus.CHECKED,
        now=NOW,
    )
    db = _DeadlineWarningFakeSession().seed(other_period_block)

    minutes = svc._unfinalized_checked_minutes(
        db, task_id=TASK_ID, plan_date=CURRENT_PLAN_DATE, period=CURRENT_PERIOD
    )

    assert minutes == 0


def test_unfinalized_checked_minutes_ignores_completed_block():
    completed_block = make_plan_block(
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        task_id=TASK_ID,
        plan_date=CURRENT_PLAN_DATE,
        period=CURRENT_PERIOD,
        allocated_minutes=45,
        status=PlanBlockStatus.COMPLETED,  # 정산 완료(check_in_id nonnull)
        now=NOW,
    )
    db = _DeadlineWarningFakeSession().seed(completed_block)

    minutes = svc._unfinalized_checked_minutes(
        db, task_id=TASK_ID, plan_date=CURRENT_PLAN_DATE, period=CURRENT_PERIOD
    )

    assert minutes == 0


def test_required_minutes_subtracts_unfinalized_checked_in_full_flow():
    cycle = _cycle()
    # 마감을 바짝 붙여 availableMinutes를 작게 만들어야 shortage가 발생해 items에 포함된다.
    tight_deadline = NOW + timedelta(minutes=20)
    task = _task(remaining_minutes=100, deadline_at=tight_deadline)
    checked_block = make_plan_block(
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        task_id=TASK_ID,
        plan_date=CURRENT_PLAN_DATE,
        period=CURRENT_PERIOD,
        allocated_minutes=40,
        status=PlanBlockStatus.CHECKED,
        now=NOW,
    )
    db = _DeadlineWarningFakeSession().seed(cycle, task, checked_block)

    notice = svc.compute_deadline_warnings(db, USER_ID, now=NOW)

    # effective_remaining = 100 - 40 = 60 = requiredMinutes
    assert notice is not None
    assert notice.items[0].required_minutes == 60


# ---------------------------------------------------------------------------
# 5~6. 배치용 마감 = min(deadline_at, cycle_end_at)
# ---------------------------------------------------------------------------


def test_planning_deadline_uses_real_deadline_when_earlier_than_cycle_end():
    cycle = _cycle()
    real_deadline = datetime(2026, 7, 29, 15, 0, tzinfo=SEOUL)  # cycle_end_at보다 이름
    task = _task(deadline_at=real_deadline, remaining_minutes=1000)
    db = _DeadlineWarningFakeSession().seed(cycle, task)

    notice = svc.compute_deadline_warnings(db, USER_ID, now=NOW)

    # NOW(14:10)~real_deadline(15:00) = 50분만 가용 -> availableMinutes는 50을 넘지 않는다.
    assert notice is not None
    assert notice.items[0].available_minutes <= 50


def test_planning_deadline_uses_cycle_end_when_earlier_than_real_deadline():
    cycle = _cycle()
    far_future_deadline = datetime(2026, 12, 31, 23, 59, 59, tzinfo=SEOUL)
    task = _task(deadline_at=far_future_deadline, remaining_minutes=100000)
    db = _DeadlineWarningFakeSession().seed(cycle, task)

    available = svc._compute_available_minutes(
        db,
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        task_id=TASK_ID,
        now=NOW,
        planning_deadline_at=min(far_future_deadline, CYCLE_END_AT),
        current_plan_date=CURRENT_PLAN_DATE,
        current_period=CURRENT_PERIOD,
    )
    # cycle_end_at(2026-08-03 04:00)까지만 계산되고 그 이후는 포함되지 않는다.
    # 매우 큰 remaining_minutes를 요구해도 availableMinutes가 유한해야 한다(= cycle 종료 사용).
    assert available < 100000


# ---------------------------------------------------------------------------
# 7~8. 현재 분기 now clip / 마지막 분기 planningDeadlineAt clip
# ---------------------------------------------------------------------------


def test_current_period_window_is_clipped_by_now():
    # AFTERNOON(12:00~18:00) 전체가 아니라 now(14:10)부터만 계산되어야 한다.
    planning_deadline_at = datetime(2026, 7, 29, 18, 0, tzinfo=SEOUL)  # 현재 분기 끝
    db = _DeadlineWarningFakeSession().seed(_cycle())

    available = svc._compute_available_minutes(
        db,
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        task_id=TASK_ID,
        now=NOW,
        planning_deadline_at=planning_deadline_at,
        current_plan_date=CURRENT_PLAN_DATE,
        current_period=CURRENT_PERIOD,
    )

    # 14:10~18:00 = 230분 (240분 상한 이내이므로 그대로)
    assert available == 230


def test_last_period_window_is_clipped_by_planning_deadline_at():
    planning_deadline_at = datetime(2026, 7, 29, 15, 0, tzinfo=SEOUL)  # 현재 분기 도중
    db = _DeadlineWarningFakeSession().seed(_cycle())

    available = svc._compute_available_minutes(
        db,
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        task_id=TASK_ID,
        now=NOW,
        planning_deadline_at=planning_deadline_at,
        current_plan_date=CURRENT_PLAN_DATE,
        current_period=CURRENT_PERIOD,
    )

    # 14:10~15:00 = 50분
    assert available == 50


# ---------------------------------------------------------------------------
# 9. 분기당 최대 240분
# ---------------------------------------------------------------------------


def test_full_future_period_is_capped_at_240_minutes():
    # 다음날 MORNING(04:00~12:00) = 480분 실제 길이지만 240분 상한 적용.
    planning_deadline_at = datetime(2026, 7, 30, 12, 0, tzinfo=SEOUL)
    db = _DeadlineWarningFakeSession().seed(_cycle())

    available = svc._compute_available_minutes(
        db,
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        task_id=TASK_ID,
        now=NOW,
        planning_deadline_at=planning_deadline_at,
        current_plan_date=CURRENT_PLAN_DATE,
        current_period=CURRENT_PERIOD,
    )

    # 오늘 AFTERNOON(14:10~18:00=230) + EVENING(18:00~익일04:00=최대240) + 익일 MORNING(04:00~12:00, 상한 240 -> deadline 12:00에서 잘림)
    # 여기서는 상한 검증이 핵심이므로 각 분기가 240을 절대 넘지 않는지 별도 계산으로 확인한다.
    period_start, period_end = svc._period_window(date(2026, 7, 30), PlanPeriod.MORNING)
    assert period_end - period_start == timedelta(hours=8)  # 실제 길이는 480분
    assert available <= 230 + 240 + 240


def test_single_future_period_alone_is_exactly_240_when_unobstructed():
    plan_date = date(2026, 7, 30)
    period = PlanPeriod.MORNING
    period_start, period_end = svc._period_window(plan_date, period)
    db = _DeadlineWarningFakeSession()

    available = svc._compute_available_minutes(
        db,
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        task_id=TASK_ID,
        now=period_start,
        planning_deadline_at=period_end,
        current_plan_date=plan_date,
        current_period=period,
    )

    assert available == 240


# ---------------------------------------------------------------------------
# 10. 고정 일정 합집합
# ---------------------------------------------------------------------------


def test_overlapping_fixed_schedules_are_deducted_as_union_once():
    plan_date = date(2026, 7, 30)
    period = PlanPeriod.MORNING
    period_start, period_end = svc._period_window(plan_date, period)
    # 04:00~05:30 과 05:00~06:00 이 겹침 -> 합집합 04:00~06:00 = 120분
    fs1 = make_fixed_schedule(
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        start_at=period_start,
        end_at=period_start + timedelta(hours=1, minutes=30),
    )
    fs2 = make_fixed_schedule(
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        start_at=period_start + timedelta(hours=1),
        end_at=period_start + timedelta(hours=2),
    )
    db = _DeadlineWarningFakeSession().seed(fs1, fs2)

    available = svc._compute_available_minutes(
        db,
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        task_id=TASK_ID,
        now=period_start,
        planning_deadline_at=period_end,
        current_plan_date=plan_date,
        current_period=period,
    )

    assert available == 240 - 120


# ---------------------------------------------------------------------------
# 11~13. 다른 Task PlanBlock 차감 / 완료 상태 제외 / 자기 자신 제외
# ---------------------------------------------------------------------------


def test_other_task_planned_and_checked_blocks_are_deducted():
    plan_date = date(2026, 7, 30)
    period = PlanPeriod.MORNING
    period_start, period_end = svc._period_window(plan_date, period)
    planned = make_plan_block(
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        task_id=OTHER_TASK_ID,
        plan_date=plan_date,
        period=period,
        allocated_minutes=50,
        status=PlanBlockStatus.PLANNED,
    )
    checked = make_plan_block(
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        task_id=OTHER_TASK_ID,
        plan_date=plan_date,
        period=period,
        allocated_minutes=30,
        status=PlanBlockStatus.CHECKED,
        now=period_start,
        display_order=1,
    )
    db = _DeadlineWarningFakeSession().seed(planned, checked)

    available = svc._compute_available_minutes(
        db,
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        task_id=TASK_ID,
        now=period_start,
        planning_deadline_at=period_end,
        current_plan_date=plan_date,
        current_period=period,
    )

    assert available == 240 - 50 - 30


def test_other_task_completed_and_not_done_blocks_are_not_deducted():
    plan_date = date(2026, 7, 30)
    period = PlanPeriod.MORNING
    period_start, period_end = svc._period_window(plan_date, period)
    completed = make_plan_block(
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        task_id=OTHER_TASK_ID,
        plan_date=plan_date,
        period=period,
        allocated_minutes=50,
        status=PlanBlockStatus.COMPLETED,
        now=period_start,
    )
    not_done = make_plan_block(
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        task_id=OTHER_TASK_ID,
        plan_date=plan_date,
        period=period,
        allocated_minutes=30,
        status=PlanBlockStatus.NOT_DONE,
        now=period_start,
        display_order=1,
    )
    db = _DeadlineWarningFakeSession().seed(completed, not_done)

    available = svc._compute_available_minutes(
        db,
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        task_id=TASK_ID,
        now=period_start,
        planning_deadline_at=period_end,
        current_plan_date=plan_date,
        current_period=period,
    )

    assert available == 240


def test_target_tasks_own_block_is_never_deducted():
    plan_date = date(2026, 7, 30)
    period = PlanPeriod.MORNING
    period_start, period_end = svc._period_window(plan_date, period)
    own_block = make_plan_block(
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        task_id=TASK_ID,  # 경고 대상 Task 자신
        plan_date=plan_date,
        period=period,
        allocated_minutes=80,
        status=PlanBlockStatus.PLANNED,
    )
    db = _DeadlineWarningFakeSession().seed(own_block)

    available = svc._compute_available_minutes(
        db,
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        task_id=TASK_ID,
        now=period_start,
        planning_deadline_at=period_end,
        current_plan_date=plan_date,
        current_period=period,
    )

    assert available == 240


# ---------------------------------------------------------------------------
# 14~15. 마감 경과 / 경고 제외 임계값
# ---------------------------------------------------------------------------


def test_available_minutes_is_zero_when_planning_deadline_already_passed():
    cycle = _cycle()
    past_deadline = NOW - timedelta(hours=1)
    task = _task(deadline_at=past_deadline, remaining_minutes=10)
    db = _DeadlineWarningFakeSession().seed(cycle, task)

    notice = svc.compute_deadline_warnings(db, USER_ID, now=NOW)

    assert notice is not None
    assert notice.items[0].available_minutes == 0
    assert notice.items[0].required_minutes == 10
    assert notice.items[0].shortage_minutes == 10


def test_task_excluded_when_required_not_greater_than_available():
    cycle = _cycle()
    # 마감이 충분히 멀어 availableMinutes가 확실히 requiredMinutes보다 크다.
    task = _task(deadline_at=datetime(2026, 8, 2, 23, 59, 59, tzinfo=SEOUL), remaining_minutes=10)
    db = _DeadlineWarningFakeSession().seed(cycle, task)

    notice = svc.compute_deadline_warnings(db, USER_ID, now=NOW)

    assert notice is None


def test_task_excluded_when_required_minutes_is_zero():
    cycle = _cycle()
    task = _task(remaining_minutes=40)
    checked_block = make_plan_block(
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        task_id=TASK_ID,
        plan_date=CURRENT_PLAN_DATE,
        period=CURRENT_PERIOD,
        allocated_minutes=40,  # remaining과 동일 -> effective_remaining = 0
        status=PlanBlockStatus.CHECKED,
        now=NOW,
    )
    db = _DeadlineWarningFakeSession().seed(cycle, task, checked_block)

    notice = svc.compute_deadline_warnings(db, USER_ID, now=NOW)

    assert notice is None


# ---------------------------------------------------------------------------
# 16~17. items 배열 형태 / 정렬
# ---------------------------------------------------------------------------


def test_single_warning_is_still_returned_as_items_list():
    cycle = _cycle()
    task = _task(deadline_at=NOW - timedelta(minutes=1), remaining_minutes=30)
    db = _DeadlineWarningFakeSession().seed(cycle, task)

    notice = svc.compute_deadline_warnings(db, USER_ID, now=NOW)

    assert notice is not None
    assert isinstance(notice.items, list)
    assert len(notice.items) == 1


def test_items_are_sorted_by_deadline_then_shortage_then_created_then_id():
    cycle = _cycle()

    # 마감이 이미 지난 두 Task(availableMinutes=0)로 shortage=requiredMinutes를 그대로 통제한다.
    early_deadline = NOW - timedelta(minutes=1)
    late_deadline = NOW - timedelta(minutes=1) + timedelta(days=1)

    # 같은 deadline, shortage 다름 -> shortage 큰 것 먼저
    task_a = _task(
        id=uuid.uuid4(),
        deadline_at=early_deadline,
        remaining_minutes=100,
        created_at=datetime(2026, 7, 27, 6, 0, tzinfo=SEOUL),
    )
    task_b = _task(
        id=uuid.uuid4(),
        deadline_at=early_deadline,
        remaining_minutes=50,
        created_at=datetime(2026, 7, 27, 6, 0, tzinfo=SEOUL),
    )
    # 같은 deadline, 같은 shortage -> created_at 이른 것 먼저
    task_c = _task(
        id=uuid.uuid4(),
        deadline_at=early_deadline,
        remaining_minutes=50,
        created_at=datetime(2026, 7, 26, 6, 0, tzinfo=SEOUL),
    )
    # 다른(더 늦은) deadline -> 항상 뒤로
    task_d = _task(
        id=uuid.uuid4(),
        deadline_at=late_deadline,
        remaining_minutes=999,
        created_at=datetime(2026, 7, 25, 6, 0, tzinfo=SEOUL),
    )

    db = _DeadlineWarningFakeSession().seed(cycle, task_a, task_b, task_c, task_d)

    notice = svc.compute_deadline_warnings(db, USER_ID, now=NOW)

    assert notice is not None
    ordered_ids = [item.task_id for item in notice.items]
    # 같은 deadline이면 shortage 큰 순(a=100 먼저), shortage가 같으면 created_at 이른 순(c<b).
    assert ordered_ids == [task_a.id, task_c.id, task_b.id, task_d.id]


# ---------------------------------------------------------------------------
# 18. 활성 cycle 없음
# ---------------------------------------------------------------------------


def test_returns_none_when_no_active_cycle():
    ended_cycle = _cycle(status=PlanCycleStatus.ENDED, ended_at=NOW)
    task = _task()
    db = _DeadlineWarningFakeSession().seed(ended_cycle, task)

    notice = svc.compute_deadline_warnings(db, USER_ID, now=NOW)

    assert notice is None


def test_returns_none_when_no_candidates():
    cycle = _cycle()
    db = _DeadlineWarningFakeSession().seed(cycle)

    notice = svc.compute_deadline_warnings(db, USER_ID, now=NOW)

    assert notice is None


# ---------------------------------------------------------------------------
# acknowledge_deadline_warnings — 검증·트랜잭션
# ---------------------------------------------------------------------------


def _acknowledge_task(**overrides):
    fields = dict(id=uuid.uuid4(), user_id=USER_ID)
    fields.update(overrides)
    return _task(**fields)


def test_acknowledge_updates_all_tasks_with_same_now():
    task1 = _acknowledge_task()
    task2 = _acknowledge_task()
    db = _DeadlineWarningFakeSession().seed(task1, task2)
    ack_at = datetime(2026, 7, 29, 14, 40, tzinfo=SEOUL)

    result = svc.acknowledge_deadline_warnings(
        db, user_id=USER_ID, task_ids=[task1.id, task2.id], now=ack_at
    )

    assert result.acknowledged_task_ids == [task1.id, task2.id]
    assert result.acknowledged_at == ack_at
    assert task1.deadline_warning_acknowledged_at == ack_at
    assert task2.deadline_warning_acknowledged_at == ack_at
    assert db.for_update_seen is True
    assert db.recorder.committed is True
    assert db.recorder.rolled_back is False


def test_acknowledge_dedupes_ids_preserving_first_occurrence_order():
    task1 = _acknowledge_task()
    task2 = _acknowledge_task()
    db = _DeadlineWarningFakeSession().seed(task1, task2)

    result = svc.acknowledge_deadline_warnings(
        db, user_id=USER_ID, task_ids=[task1.id, task2.id, task1.id], now=NOW
    )

    assert result.acknowledged_task_ids == [task1.id, task2.id]


def test_acknowledge_succeeds_when_already_acknowledged_task_included():
    already = _acknowledge_task(deadline_warning_acknowledged_at=NOW - timedelta(days=1))
    db = _DeadlineWarningFakeSession().seed(already)
    ack_at = NOW

    result = svc.acknowledge_deadline_warnings(
        db, user_id=USER_ID, task_ids=[already.id], now=ack_at
    )

    assert result.acknowledged_task_ids == [already.id]
    assert already.deadline_warning_acknowledged_at == ack_at


def test_acknowledge_rejects_empty_task_ids_with_422():
    db = _DeadlineWarningFakeSession()

    with pytest.raises(ApiError) as exc_info:
        svc.acknowledge_deadline_warnings(db, user_id=USER_ID, task_ids=[], now=NOW)

    assert exc_info.value.status_code == 422
    assert exc_info.value.code == svc.CODE_INVALID_TASK_IDS
    assert db.recorder.committed is False


def test_acknowledge_rejects_nonexistent_task_id_with_404_and_rolls_back():
    task1 = _acknowledge_task()
    missing_id = uuid.uuid4()
    db = _DeadlineWarningFakeSession().seed(task1)

    with pytest.raises(ApiError) as exc_info:
        svc.acknowledge_deadline_warnings(
            db, user_id=USER_ID, task_ids=[task1.id, missing_id], now=NOW
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == svc.CODE_TASK_NOT_FOUND
    assert db.recorder.rolled_back is True
    assert db.recorder.committed is False
    assert task1.deadline_warning_acknowledged_at is None  # 부분 갱신 없음


def test_acknowledge_rejects_other_users_task_with_404_and_rolls_back():
    own_task = _acknowledge_task()
    other_task = _acknowledge_task(user_id=OTHER_USER_ID)
    db = _DeadlineWarningFakeSession().seed(own_task, other_task)

    with pytest.raises(ApiError) as exc_info:
        svc.acknowledge_deadline_warnings(
            db, user_id=USER_ID, task_ids=[own_task.id, other_task.id], now=NOW
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == svc.CODE_TASK_NOT_FOUND
    assert db.recorder.rolled_back is True
    assert own_task.deadline_warning_acknowledged_at is None
