import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.models.enums import AmountSource, PlanPeriod
from app.services import plan_block_service as svc
from tests.support_scheduler import (
    FakeSchedulerSession,
    make_cycle,
    make_fixed_schedule,
    make_task,
)

SEOUL = ZoneInfo("Asia/Seoul")


def _setup_cycle():
    user_id = uuid.uuid4()
    cycle_id = uuid.uuid4()
    cycle = make_cycle(
        user_id=user_id, start_date=date(2026, 8, 2), end_date=date(2026, 8, 8), id=cycle_id
    )
    return user_id, cycle_id, FakeSchedulerSession().seed(cycle)


def _daily_minutes(blocks):
    totals: dict[date, int] = {}
    for block in blocks:
        totals[block.plan_date] = totals.get(block.plan_date, 0) + block.allocated_minutes
    return totals


def test_task_is_evenly_distributed_through_deadline_before_amount_distribution():
    user_id, cycle_id, db = _setup_cycle()
    now = datetime(2026, 8, 2, 4, 0, tzinfo=SEOUL)
    task = make_task(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        remaining_minutes=150,
        deadline_at=datetime(2026, 8, 5, 23, 59, 59, tzinfo=SEOUL),
        title="영어 단어 암기",
        amount_text="300개",
        amount_source=AmountSource.USER,
        created_at=now,
    )
    db.seed(
        task,
        make_fixed_schedule(
            user_id=user_id, plan_cycle_id=cycle_id,
            start_at=datetime(2026, 8, 2, 10, 0, tzinfo=SEOUL),
            end_at=datetime(2026, 8, 2, 12, 0, tzinfo=SEOUL),
        ),
        make_fixed_schedule(
            user_id=user_id, plan_cycle_id=cycle_id,
            start_at=datetime(2026, 8, 2, 12, 0, tzinfo=SEOUL),
            end_at=datetime(2026, 8, 2, 16, 0, tzinfo=SEOUL),
        ),
    )

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=now)
    blocks = sorted(result.created_blocks, key=lambda b: (b.plan_date, b.display_order))

    assert list(_daily_minutes(blocks).values()) == [38, 38, 37, 37]
    assert sum(block.allocated_minutes for block in blocks) == 150
    assert [block.allocated_amount_text for block in blocks] == ["76개", "76개", "74개", "74개"]
    assert all(block.plan_date <= date(2026, 8, 5) for block in blocks)
    assert result.total_unplaced_minutes == 0


def test_daily_quota_shortage_carries_forward_without_using_future_quota_early():
    user_id, cycle_id, db = _setup_cycle()
    now = datetime(2026, 8, 2, 4, 0, tzinfo=SEOUL)
    task = make_task(
        user_id=user_id, plan_cycle_id=cycle_id, remaining_minutes=150,
        deadline_at=datetime(2026, 8, 5, 23, 59, 59, tzinfo=SEOUL), created_at=now,
    )
    db.seed(
        task,
        make_fixed_schedule(
            user_id=user_id, plan_cycle_id=cycle_id,
            start_at=datetime(2026, 8, 2, 4, 0, tzinfo=SEOUL),
            end_at=datetime(2026, 8, 2, 7, 40, tzinfo=SEOUL),
        ),
        make_fixed_schedule(
            user_id=user_id, plan_cycle_id=cycle_id,
            start_at=datetime(2026, 8, 2, 12, 0, tzinfo=SEOUL),
            end_at=datetime(2026, 8, 3, 4, 0, tzinfo=SEOUL),
        ),
    )

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=now)
    assert list(_daily_minutes(result.created_blocks).values()) == [20, 56, 37, 37]
    assert result.total_unplaced_minutes == 0


def test_zero_capacity_date_is_excluded_from_daily_quota_dates():
    user_id, cycle_id, db = _setup_cycle()
    now = datetime(2026, 8, 2, 4, 0, tzinfo=SEOUL)
    task = make_task(
        user_id=user_id, plan_cycle_id=cycle_id, remaining_minutes=150,
        deadline_at=datetime(2026, 8, 5, 23, 59, 59, tzinfo=SEOUL), created_at=now,
    )
    db.seed(
        task,
        make_fixed_schedule(
            user_id=user_id, plan_cycle_id=cycle_id,
            start_at=datetime(2026, 8, 3, 4, 0, tzinfo=SEOUL),
            end_at=datetime(2026, 8, 4, 4, 0, tzinfo=SEOUL),
        ),
    )

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=now)
    assert _daily_minutes(result.created_blocks) == {
        date(2026, 8, 2): 50, date(2026, 8, 4): 50, date(2026, 8, 5): 50,
    }


def test_exact_deadline_and_past_deadline_leave_unusable_minutes_unplaced():
    user_id, cycle_id, db = _setup_cycle()
    now = datetime(2026, 8, 2, 19, 0, tzinfo=SEOUL)
    exact = make_task(
        user_id=user_id, plan_cycle_id=cycle_id, remaining_minutes=180,
        deadline_at=datetime(2026, 8, 2, 20, 0, tzinfo=SEOUL), created_at=now, title="exact",
    )
    past = make_task(
        user_id=user_id, plan_cycle_id=cycle_id, remaining_minutes=30,
        deadline_at=datetime(2026, 8, 2, 18, 0, tzinfo=SEOUL), created_at=now, title="past",
    )
    db.seed(exact, past)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=now)
    exact_blocks = [block for block in result.created_blocks if block.task_id == exact.id]
    assert [(block.plan_date, block.period, block.allocated_minutes) for block in exact_blocks] == [
        (date(2026, 8, 2), PlanPeriod.EVENING, 60)
    ]
    assert result.unplaced_minutes[exact.id] == 120
    assert result.unplaced_minutes[past.id] == 30


def test_deadline_outside_cycle_uses_cycle_end_as_allocation_horizon():
    user_id, cycle_id, db = _setup_cycle()
    now = datetime(2026, 8, 2, 4, 0, tzinfo=SEOUL)
    task = make_task(
        user_id=user_id, plan_cycle_id=cycle_id, remaining_minutes=70,
        deadline_at=datetime(2026, 8, 31, 23, 59, 59, tzinfo=SEOUL), created_at=now,
    )
    db.seed(task)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=now)
    assert list(_daily_minutes(result.created_blocks).values()) == [10] * 7
    assert max(block.plan_date for block in result.created_blocks) == date(2026, 8, 8)


def test_task_priority_is_preserved_while_daily_targets_limit_capacity_use():
    user_id, cycle_id, db = _setup_cycle()
    now = datetime(2026, 8, 2, 5, 0, tzinfo=SEOUL)
    urgent = make_task(
        user_id=user_id, plan_cycle_id=cycle_id, remaining_minutes=120,
        deadline_at=datetime(2026, 8, 3, 23, 59, 59, tzinfo=SEOUL),
        created_at=datetime(2026, 8, 2, 1, 0, tzinfo=SEOUL), title="urgent",
    )
    later = make_task(
        user_id=user_id, plan_cycle_id=cycle_id, remaining_minutes=240,
        deadline_at=datetime(2026, 8, 5, 23, 59, 59, tzinfo=SEOUL),
        created_at=datetime(2026, 8, 2, 1, 0, tzinfo=SEOUL), title="later",
    )
    db.seed(
        urgent,
        later,
        make_fixed_schedule(
            user_id=user_id, plan_cycle_id=cycle_id,
            start_at=datetime(2026, 8, 2, 4, 0, tzinfo=SEOUL),
            end_at=datetime(2026, 8, 2, 6, 20, tzinfo=SEOUL),
        ),
        make_fixed_schedule(
            user_id=user_id, plan_cycle_id=cycle_id,
            start_at=datetime(2026, 8, 2, 12, 0, tzinfo=SEOUL),
            end_at=datetime(2026, 8, 3, 4, 0, tzinfo=SEOUL),
        ),
    )

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=now)
    first_day = sorted(
        (block for block in result.created_blocks if block.plan_date == date(2026, 8, 2)),
        key=lambda block: block.display_order,
    )
    assert [(block.task_id, block.allocated_minutes) for block in first_day] == [
        (urgent.id, 60), (later.id, 40),
    ]
    later_daily = _daily_minutes([b for b in result.created_blocks if b.task_id == later.id])
    assert later_daily[date(2026, 8, 3)] == 80


def test_daily_quota_integer_remainder_is_assigned_to_earliest_dates():
    dates = [date(2026, 8, day) for day in range(2, 6)]
    assert svc._distribute_daily_quotas(150, dates) == dict(zip(dates, [38, 38, 37, 37]))
    assert svc._distribute_daily_quotas(2, dates) == dict(zip(dates, [1, 1, 0, 0]))


def test_two_problems_use_two_evenly_spaced_dates_across_six_eligible_dates():
    user_id, cycle_id, db = _setup_cycle()
    now = datetime(2026, 8, 2, 4, 0, tzinfo=SEOUL)
    task = make_task(
        user_id=user_id, plan_cycle_id=cycle_id, remaining_minutes=240,
        deadline_at=datetime(2026, 8, 7, 23, 59, 59, tzinfo=SEOUL),
        title="운영체제 과제", amount_text="2문제", amount_source=AmountSource.USER,
        created_at=now,
    )
    db.seed(task)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=now)
    blocks = sorted(result.created_blocks, key=lambda block: block.plan_date)

    assert [block.plan_date for block in blocks] == [date(2026, 8, 2), date(2026, 8, 5)]
    assert [block.allocated_minutes for block in blocks] == [120, 120]
    assert [block.allocated_amount_text for block in blocks] == ["1문제", "1문제"]
    assert sum(block.allocated_minutes for block in blocks) == 240
    assert result.total_unplaced_minutes == 0


def test_three_problems_use_three_evenly_spaced_dates_across_seven_eligible_dates():
    user_id, cycle_id, db = _setup_cycle()
    now = datetime(2026, 8, 2, 4, 0, tzinfo=SEOUL)
    task = make_task(
        user_id=user_id, plan_cycle_id=cycle_id, remaining_minutes=300,
        deadline_at=datetime(2026, 8, 8, 23, 59, 59, tzinfo=SEOUL),
        title="알고리즘 문제", amount_text="3문제", amount_source=AmountSource.USER,
        created_at=now,
    )
    db.seed(task)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=now)
    blocks = sorted(result.created_blocks, key=lambda block: block.plan_date)

    assert [block.plan_date for block in blocks] == [
        date(2026, 8, 2), date(2026, 8, 4), date(2026, 8, 6),
    ]
    assert [block.allocated_minutes for block in blocks] == [100, 100, 100]
    assert [block.allocated_amount_text for block in blocks] == ["1문제"] * 3
    assert result.total_unplaced_minutes == 0


def test_quantity_larger_than_horizon_keeps_all_eligible_dates():
    user_id, cycle_id, db = _setup_cycle()
    now = datetime(2026, 8, 2, 4, 0, tzinfo=SEOUL)
    task = make_task(
        user_id=user_id, plan_cycle_id=cycle_id, remaining_minutes=400,
        deadline_at=datetime(2026, 8, 5, 23, 59, 59, tzinfo=SEOUL),
        title="연습 문제", amount_text="10문제", amount_source=AmountSource.USER,
        created_at=now,
    )
    db.seed(task)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=now)
    blocks = sorted(result.created_blocks, key=lambda block: block.plan_date)

    assert [block.plan_date for block in blocks] == [date(2026, 8, day) for day in range(2, 6)]
    assert [block.allocated_minutes for block in blocks] == [100] * 4
    assert [block.allocated_amount_text for block in blocks] == ["3문제", "3문제", "2문제", "2문제"]


def test_capacity_shortage_opens_only_minimum_dates_after_last_target():
    user_id, cycle_id, db = _setup_cycle()
    now = datetime(2026, 8, 2, 4, 0, tzinfo=SEOUL)
    task = make_task(
        user_id=user_id, plan_cycle_id=cycle_id, remaining_minutes=900,
        deadline_at=datetime(2026, 8, 7, 23, 59, 59, tzinfo=SEOUL),
        title="긴 과제", amount_text="1문제", amount_source=AmountSource.USER,
        created_at=now,
    )
    db.seed(task)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=now)

    assert sorted({block.plan_date for block in result.created_blocks}) == [
        date(2026, 8, 2), date(2026, 8, 3),
    ]
    assert sum(block.allocated_minutes for block in result.created_blocks) == 900
    assert result.total_unplaced_minutes == 0
    assert all(block.allocated_amount_text is None for block in result.created_blocks)


def test_unknown_canonical_amount_does_not_limit_deadline_distribution_dates():
    user_id, cycle_id, db = _setup_cycle()
    now = datetime(2026, 8, 2, 4, 0, tzinfo=SEOUL)
    task = make_task(
        user_id=user_id, plan_cycle_id=cycle_id, remaining_minutes=60,
        deadline_at=datetime(2026, 8, 7, 23, 59, 59, tzinfo=SEOUL),
        amount_text="2문제", amount_source=AmountSource.UNKNOWN, created_at=now,
    )
    db.seed(task)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=now)

    assert _daily_minutes(result.created_blocks) == {
        date(2026, 8, day): 10 for day in range(2, 8)
    }
    assert all(block.allocated_amount_text is None for block in result.created_blocks)


def test_target_date_selection_is_deterministic_increasing_and_in_range():
    dates = [date(2026, 8, day) for day in range(2, 8)]
    assert svc._select_evenly_spaced_target_dates(dates, 2) == [dates[0], dates[3]]
    assert svc._select_evenly_spaced_target_dates(dates, 3) == [dates[0], dates[2], dates[4]]


@pytest.mark.parametrize(("quantity", "unit"), [(2, "페이지"), (3, "개"), (4, "단원")])
def test_target_date_limit_reuses_canonical_amount_parser_for_any_unit(quantity, unit):
    user_id, cycle_id, db = _setup_cycle()
    now = datetime(2026, 8, 2, 4, 0, tzinfo=SEOUL)
    task = make_task(
        user_id=user_id, plan_cycle_id=cycle_id, remaining_minutes=quantity * 60,
        deadline_at=datetime(2026, 8, 7, 23, 59, 59, tzinfo=SEOUL),
        amount_text=f"{quantity}{unit}", amount_source=AmountSource.USER, created_at=now,
    )
    db.seed(task)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=now)

    assert len({block.plan_date for block in result.created_blocks}) == quantity
    assert sum(int(block.allocated_amount_text.removesuffix(unit)) for block in result.created_blocks) == quantity
    assert all(not block.allocated_amount_text.startswith("0") for block in result.created_blocks)


def test_shortage_carries_to_next_selected_date_then_opens_one_expansion_date():
    user_id, cycle_id, db = _setup_cycle()
    now = datetime(2026, 8, 2, 4, 0, tzinfo=SEOUL)
    task = make_task(
        user_id=user_id, plan_cycle_id=cycle_id, remaining_minutes=1500,
        deadline_at=datetime(2026, 8, 7, 23, 59, 59, tzinfo=SEOUL),
        amount_text="2문제", amount_source=AmountSource.USER, created_at=now,
    )
    db.seed(task)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=now)

    assert _daily_minutes(result.created_blocks) == {
        date(2026, 8, 2): 720,
        date(2026, 8, 5): 720,
        date(2026, 8, 6): 60,
    }
    assert result.total_unplaced_minutes == 0


def test_completed_amount_history_keeps_all_eligible_dates_in_time_distribution():
    user_id, cycle_id, _db = _setup_cycle()
    now = datetime(2026, 8, 2, 4, 0, tzinfo=SEOUL)
    task = make_task(
        user_id=user_id, plan_cycle_id=cycle_id, remaining_minutes=60,
        amount_text="2문제", amount_source=AmountSource.USER, created_at=now,
    )
    dates = [date(2026, 8, day) for day in range(2, 8)]

    quotas = svc._build_task_daily_quotas(
        task=task,
        effective_need=60,
        eligible_dates=dates,
        has_completed_amount_history=True,
    )

    assert quotas == {plan_date: 10 for plan_date in dates}
