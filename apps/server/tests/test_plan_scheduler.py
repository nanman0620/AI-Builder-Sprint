import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.models.enums import PlanPeriod
from app.services import plan_block_service as svc
from tests.support_scheduler import FakeSchedulerSession, make_cycle, make_task

SEOUL = ZoneInfo("Asia/Seoul")


def _now():
    return datetime(2026, 7, 29, 5, 0, tzinfo=SEOUL)


def _setup(*, tasks=(), extra_rows=()):
    user_id = uuid.uuid4()
    cycle_id = uuid.uuid4()
    cycle = make_cycle(
        user_id=user_id, start_date=date(2026, 7, 29), end_date=date(2026, 8, 4), id=cycle_id
    )
    db = FakeSchedulerSession().seed(cycle, *tasks, *extra_rows)
    return user_id, cycle_id, db


def test_schedule_plan_blocks_never_opens_or_commits_a_transaction():
    task = None
    user_id, cycle_id, db = _setup()
    task = make_task(
        user_id=user_id, plan_cycle_id=cycle_id, remaining_minutes=60, created_at=_now()
    )
    db.seed(task)

    # begin()/commit()을 직접 호출하지 않는 것은 물론, 정상 실행 자체가 이를 유발하지 않아야 한다.
    svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=_now())

    with pytest.raises(AssertionError):
        db.begin()
    with pytest.raises(AssertionError):
        db.commit()


def test_single_task_is_placed_in_current_period():
    user_id, cycle_id, db = _setup()
    task = make_task(
        user_id=user_id, plan_cycle_id=cycle_id, remaining_minutes=60, created_at=_now()
    )
    db.seed(task)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=_now())

    assert len(result.created_blocks) == 1
    block = result.created_blocks[0]
    assert block.plan_date == date(2026, 7, 29)
    assert block.period == PlanPeriod.MORNING
    assert block.allocated_minutes == 60
    assert block.task_id == task.id
    assert block.display_title == task.title
    assert block.allocated_amount_text is None
    assert result.total_unplaced_minutes == 0


def test_priority_orders_by_planning_deadline_then_created_at_then_id():
    """마감이 이른 Task가 먼저 배치된다. 마감이 없는 Task는 항상 마지막이다.

    동순위 tie-break는 created_at -> id 순으로 결정적으로 고정한다(구현 규칙으로 허용됨).
    """
    user_id, cycle_id, db = _setup()
    # 세 Task를 각기 다른 우선순위 조건으로 구성한다.
    urgent = make_task(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        remaining_minutes=10,
        deadline_at=datetime(2026, 7, 29, 6, 0, tzinfo=SEOUL),
        created_at=datetime(2026, 7, 29, 1, 0, tzinfo=SEOUL),
        title="urgent",
    )
    no_deadline_older = make_task(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        remaining_minutes=10,
        deadline_at=None,
        created_at=datetime(2026, 7, 29, 1, 0, tzinfo=SEOUL),
        title="no-deadline-older",
    )
    no_deadline_newer = make_task(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        remaining_minutes=10,
        deadline_at=None,
        created_at=datetime(2026, 7, 29, 2, 0, tzinfo=SEOUL),
        title="no-deadline-newer",
    )
    db.seed(urgent, no_deadline_older, no_deadline_newer)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=_now())

    # 모두 같은 분기(MORNING)에 들어갈 만큼 용량이 충분하므로 display_order 순서가 배치 순서다.
    ordered = sorted(result.created_blocks, key=lambda b: b.display_order)
    assert [b.task_id for b in ordered] == [urgent.id, no_deadline_older.id, no_deadline_newer.id]


def test_priority_tie_break_uses_created_at_then_id_when_deadlines_equal():
    user_id, cycle_id, db = _setup()
    same_deadline = datetime(2026, 7, 30, 4, 0, tzinfo=SEOUL)
    same_created_at = datetime(2026, 7, 29, 1, 0, tzinfo=SEOUL)

    task_a = make_task(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        remaining_minutes=5,
        deadline_at=same_deadline,
        created_at=same_created_at,
        title="a",
    )
    task_b = make_task(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        remaining_minutes=5,
        deadline_at=same_deadline,
        created_at=same_created_at,
        title="b",
    )
    # id로만 tie-break되도록 강제 정렬해 비교한다.
    ordered_ids = sorted([task_a.id, task_b.id])
    db.seed(task_a, task_b)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=_now())

    ordered = sorted(result.created_blocks, key=lambda b: b.display_order)
    assert [b.task_id for b in ordered] == ordered_ids


def test_no_duplicate_display_order_within_same_period():
    user_id, cycle_id, db = _setup()
    tasks = [
        make_task(
            user_id=user_id,
            plan_cycle_id=cycle_id,
            remaining_minutes=10,
            created_at=datetime(2026, 7, 29, i, 0, tzinfo=SEOUL),
            title=f"task-{i}",
        )
        for i in range(1, 5)
    ]
    db.seed(*tasks)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=_now())

    by_period: dict[tuple, list[int]] = {}
    for block in result.created_blocks:
        by_period.setdefault((block.plan_date, block.period), []).append(block.display_order)
    for orders in by_period.values():
        assert len(orders) == len(set(orders))


def test_at_most_one_block_per_task_date_period():
    user_id, cycle_id, db = _setup()
    task = make_task(
        user_id=user_id, plan_cycle_id=cycle_id, remaining_minutes=500, created_at=_now()
    )
    db.seed(task)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=_now())

    seen = set()
    for block in result.created_blocks:
        key = (block.task_id, block.plan_date, block.period)
        assert key not in seen
        seen.add(key)


def test_unplaced_minutes_when_cycle_capacity_is_exhausted():
    user_id, cycle_id, db = _setup()
    # 7일짜리 cycle(29일 MORNING ~ 8/4 EVENING)의 총 용량(240*3*7=5040분)을 초과하는 Task.
    total_cycle_capacity = 240 * 3 * 7
    huge_task = make_task(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        remaining_minutes=total_cycle_capacity + 500,
        created_at=_now(),
    )
    db.seed(huge_task)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=_now())

    placed_total = sum(b.allocated_minutes for b in result.created_blocks)
    assert placed_total == total_cycle_capacity
    assert result.unplaced_minutes[huge_task.id] == 500
    assert result.total_unplaced_minutes == 500


def test_task_with_zero_remaining_minutes_is_not_scheduled():
    user_id, cycle_id, db = _setup()
    task = make_task(
        user_id=user_id, plan_cycle_id=cycle_id, remaining_minutes=0, created_at=_now()
    )
    db.seed(task)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=_now())

    assert result.created_blocks == []
    assert result.total_unplaced_minutes == 0
