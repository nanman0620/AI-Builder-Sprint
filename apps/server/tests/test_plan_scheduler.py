import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models.enums import AmountSource, PlanPeriod
from app.services import plan_block_service as svc
from tests.support_scheduler import (
    FakeSchedulerSession,
    make_cycle,
    make_fixed_schedule,
    make_task as _make_task,
)

SEOUL = ZoneInfo("Asia/Seoul")


def make_task(**kwargs):
    """기존 단일 날짜 배치 테스트는 당일 마감을 명시해 검증 범위를 고정한다."""
    kwargs.setdefault("deadline_at", datetime(2026, 7, 29, 23, 59, 59, tzinfo=SEOUL))
    return _make_task(**kwargs)


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


def _schedule_structured_amount(
    *, quantity: int, unit: str, period_capacities: tuple[int, ...]
):
    """Create one Task whose blocks have the requested per-period minute capacities."""
    user_id, cycle_id, db = _setup()
    period_starts = (
        datetime(2026, 7, 29, 4, 0, tzinfo=SEOUL),
        datetime(2026, 7, 29, 12, 0, tzinfo=SEOUL),
        datetime(2026, 7, 29, 18, 0, tzinfo=SEOUL),
    )
    fixed_schedules = []
    for capacity, period_start in zip(period_capacities, period_starts):
        occupied_minutes = 240 - capacity
        if occupied_minutes > 0:
            fixed_schedules.append(
                make_fixed_schedule(
                    user_id=user_id,
                    plan_cycle_id=cycle_id,
                    start_at=period_start,
                    end_at=period_start + timedelta(minutes=occupied_minutes),
                )
            )

    task = make_task(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        remaining_minutes=sum(period_capacities),
        title="자료구조 과제",
        amount_text=f"{quantity}{unit}",
        amount_source=AmountSource.USER,
        created_at=_now(),
    )
    db.seed(task, *fixed_schedules)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=_now())
    return task, result


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
    ordered = sorted(
        (
            block
            for block in result.created_blocks
            if block.plan_date == date(2026, 7, 29) and block.period == PlanPeriod.MORNING
        ),
        key=lambda b: b.display_order,
    )
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
        deadline_at=None,
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


# ---------------------------------------------------------------------------
# 분량 배분 fallback (SOLAR 연동 전 제한적 MVP 규칙)
# ---------------------------------------------------------------------------


def test_single_block_full_placement_applies_task_amount_text_fallback():
    user_id, cycle_id, db = _setup()
    task = make_task(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        remaining_minutes=60,
        title="자료구조 과제",
        amount_text="2문제",
        amount_source=AmountSource.USER,
        created_at=_now(),
    )
    db.seed(task)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=_now())

    assert len(result.created_blocks) == 1
    block = result.created_blocks[0]
    assert block.allocated_amount_text == "2문제"
    assert block.display_title == "자료구조 과제 2문제"
    assert result.total_unplaced_minutes == 0


def test_two_blocks_distribute_amount_by_minutes_ratio():
    """예시 1: 3개 / 120분·60분 -> 2개·1개."""
    user_id, cycle_id, db = _setup()
    # MORNING 용량을 120분으로 제한해(04-12시 창에서 120분 고정 일정 점유) 나머지 60분이
    # AFTERNOON으로 넘어가도록 강제한다.
    fixed = make_fixed_schedule(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        start_at=datetime(2026, 7, 29, 8, 0, tzinfo=SEOUL),
        end_at=datetime(2026, 7, 29, 10, 0, tzinfo=SEOUL),
    )
    task = make_task(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        remaining_minutes=180,
        title="한문 과제",
        amount_text="3개",
        amount_source=AmountSource.USER,
        created_at=_now(),
    )
    db.seed(task, fixed)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=_now())

    assert len(result.created_blocks) == 2
    assert result.total_unplaced_minutes == 0
    morning = next(b for b in result.created_blocks if b.period == PlanPeriod.MORNING)
    afternoon = next(b for b in result.created_blocks if b.period == PlanPeriod.AFTERNOON)
    assert morning.allocated_minutes == 120
    assert afternoon.allocated_minutes == 60
    assert morning.allocated_amount_text == "2개"
    assert morning.display_title == "한문 과제 2개"
    assert afternoon.allocated_amount_text == "1개"
    assert afternoon.display_title == "한문 과제 1개"
    # 여러 블록에 Task 전체 amount_text("3개")가 반복 복사되지 않는다.
    assert "3개" not in morning.display_title
    assert "3개" not in afternoon.display_title


def test_three_blocks_distribute_amount_by_minutes_ratio():
    """예시 2: 8문제 / 60분·60분·120분 -> 2문제·2문제·4문제."""
    user_id, cycle_id, db = _setup()
    # MORNING·AFTERNOON 용량을 각각 60분으로 제한해(각 창에서 180분씩 고정 일정 점유),
    # 남은 120분이 EVENING으로 넘어가도록 강제한다.
    morning_fixed = make_fixed_schedule(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        start_at=datetime(2026, 7, 29, 6, 0, tzinfo=SEOUL),
        end_at=datetime(2026, 7, 29, 9, 0, tzinfo=SEOUL),
    )
    afternoon_fixed = make_fixed_schedule(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        start_at=datetime(2026, 7, 29, 12, 0, tzinfo=SEOUL),
        end_at=datetime(2026, 7, 29, 15, 0, tzinfo=SEOUL),
    )
    task = make_task(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        remaining_minutes=240,
        title="자료구조 과제",
        amount_text="8문제",
        amount_source=AmountSource.USER,
        created_at=_now(),
    )
    db.seed(task, morning_fixed, afternoon_fixed)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=_now())

    assert len(result.created_blocks) == 3
    assert result.total_unplaced_minutes == 0
    by_period = {b.period: b for b in result.created_blocks}
    assert by_period[PlanPeriod.MORNING].allocated_minutes == 60
    assert by_period[PlanPeriod.AFTERNOON].allocated_minutes == 60
    assert by_period[PlanPeriod.EVENING].allocated_minutes == 120
    assert by_period[PlanPeriod.MORNING].allocated_amount_text == "2문제"
    assert by_period[PlanPeriod.AFTERNOON].allocated_amount_text == "2문제"
    assert by_period[PlanPeriod.EVENING].allocated_amount_text == "4문제"
    total_quantity = sum(
        int(b.allocated_amount_text.removesuffix("문제")) for b in result.created_blocks
    )
    assert total_quantity == 8


def test_remainder_tie_break_is_deterministic_by_chronological_order():
    """예시 4: 5문제 / 60분씩 3개 분기 -> 몫이 모두 동률(1문제)일 때 이른 시간순으로
    나머지 2를 먼저 배정해 2문제·2문제·1문제가 된다."""
    user_id, cycle_id, db = _setup()
    morning_fixed = make_fixed_schedule(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        start_at=datetime(2026, 7, 29, 6, 0, tzinfo=SEOUL),
        end_at=datetime(2026, 7, 29, 9, 0, tzinfo=SEOUL),
    )
    afternoon_fixed = make_fixed_schedule(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        start_at=datetime(2026, 7, 29, 12, 0, tzinfo=SEOUL),
        end_at=datetime(2026, 7, 29, 15, 0, tzinfo=SEOUL),
    )
    task = make_task(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        remaining_minutes=180,
        title="수학 문제",
        amount_text="5문제",
        amount_source=AmountSource.USER,
        created_at=_now(),
    )
    db.seed(task, morning_fixed, afternoon_fixed)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=_now())

    assert len(result.created_blocks) == 3
    by_period = {b.period: b for b in result.created_blocks}
    assert by_period[PlanPeriod.MORNING].allocated_minutes == 60
    assert by_period[PlanPeriod.AFTERNOON].allocated_minutes == 60
    assert by_period[PlanPeriod.EVENING].allocated_minutes == 60
    assert by_period[PlanPeriod.MORNING].allocated_amount_text == "2문제"
    assert by_period[PlanPeriod.AFTERNOON].allocated_amount_text == "2문제"
    assert by_period[PlanPeriod.EVENING].allocated_amount_text == "1문제"


@pytest.mark.parametrize(
    ("quantity", "unit", "period_capacities", "expected_counts"),
    [
        pytest.param(2, "문제", (30, 210), (1, 1), id="reported-30-210-regression"),
        pytest.param(2, "페이지", (1, 239), (1, 1), id="extreme-two-block-ratio"),
        pytest.param(3, "개", (1, 1, 238), (1, 1, 1), id="multiple-zero-shares"),
        pytest.param(4, "문제", (1, 1, 238), (1, 1, 2), id="minimums-plus-remainder"),
        pytest.param(3, "페이지", (1, 1, 238), (1, 1, 1), id="quantity-equals-block-count"),
        pytest.param(5, "문제", (60, 60, 60), (2, 2, 1), id="existing-positive-result"),
    ],
)
def test_amount_distribution_never_assigns_zero_and_preserves_quantity(
    quantity, unit, period_capacities, expected_counts
):
    task, result = _schedule_structured_amount(
        quantity=quantity,
        unit=unit,
        period_capacities=period_capacities,
    )

    ordered = sorted(
        result.created_blocks,
        key=lambda block: (block.plan_date, block.display_order),
    )
    actual_counts = tuple(
        int(block.allocated_amount_text.removesuffix(unit)) for block in ordered
    )

    assert tuple(block.allocated_minutes for block in ordered) == period_capacities
    assert actual_counts == expected_counts
    assert sum(actual_counts) == quantity
    assert all(count >= 1 for count in actual_counts)
    assert all(block.allocated_amount_text != f"0{unit}" for block in ordered)
    assert [block.display_title for block in ordered] == [
        f"{task.title} {count}{unit}" for count in expected_counts
    ]


def test_quantity_less_than_block_count_keeps_all_blocks_title_only():
    """예시 5: 전체 수량(2개)보다 신규 블록 수(3개)가 많으면 0개를 만들지 않고
    Task의 신규 블록 전체를 title-only fallback으로 유지한다."""
    user_id, cycle_id, db = _setup()
    morning_fixed = make_fixed_schedule(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        start_at=datetime(2026, 7, 29, 6, 0, tzinfo=SEOUL),
        end_at=datetime(2026, 7, 29, 9, 0, tzinfo=SEOUL),
    )
    afternoon_fixed = make_fixed_schedule(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        start_at=datetime(2026, 7, 29, 12, 0, tzinfo=SEOUL),
        end_at=datetime(2026, 7, 29, 15, 0, tzinfo=SEOUL),
    )
    task = make_task(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        remaining_minutes=180,
        title="한문 과제",
        amount_text="2개",
        amount_source=AmountSource.USER,
        created_at=_now(),
    )
    db.seed(task, morning_fixed, afternoon_fixed)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=_now())

    assert len(result.created_blocks) == 3
    for block in result.created_blocks:
        assert block.allocated_amount_text is None
        assert block.display_title == "한문 과제"


def test_single_block_with_leftover_unplaced_keeps_title_only_fallback():
    user_id = uuid.uuid4()
    cycle_id = uuid.uuid4()
    # cycle이 당일 하루뿐이고 now가 마지막 분기(EVENING)이므로 이번 호출에서는 분기가
    # 1개만 순회되어, 남는 시간이 있어도 신규 블록은 정확히 1개만 생성된다.
    cycle = make_cycle(
        user_id=user_id, start_date=date(2026, 7, 29), end_date=date(2026, 7, 29), id=cycle_id
    )
    db = FakeSchedulerSession().seed(cycle)
    now = datetime(2026, 7, 29, 19, 0, tzinfo=SEOUL)
    task = make_task(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        remaining_minutes=300,
        title="자료구조 과제",
        amount_text="6문제",
        amount_source=AmountSource.USER,
        created_at=now,
    )
    db.seed(task)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=now)

    assert len(result.created_blocks) == 1
    block = result.created_blocks[0]
    assert block.allocated_minutes == 240
    assert result.unplaced_minutes[task.id] == 60
    assert block.allocated_amount_text is None
    assert block.display_title == "자료구조 과제"


def test_single_block_without_amount_text_keeps_title_only_fallback():
    user_id, cycle_id, db = _setup()
    task = make_task(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        remaining_minutes=60,
        title="산책",
        created_at=_now(),
    )
    db.seed(task)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=_now())

    assert len(result.created_blocks) == 1
    block = result.created_blocks[0]
    assert block.allocated_amount_text is None
    assert block.display_title == "산책"


def test_single_block_with_blank_amount_text_keeps_title_only_fallback():
    user_id, cycle_id, db = _setup()
    task = make_task(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        remaining_minutes=60,
        title="산책",
        amount_text="   ",
        amount_source=AmountSource.USER,
        created_at=_now(),
    )
    db.seed(task)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=_now())

    assert len(result.created_blocks) == 1
    block = result.created_blocks[0]
    assert block.allocated_amount_text is None
    assert block.display_title == "산책"
