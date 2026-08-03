import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models.check_in import CheckIn
from app.models.enums import PlanBlockStatus, PlanCycleStatus, PlanPeriod, TaskStatus
from app.models.plan_block import PlanBlock
from app.services import check_in_settlement_service as settlement
from app.services import plan_block_service
from tests.support_scheduler import make_cycle, make_plan_block, make_task
from tests.support_settlement import FakeSettlementSession

SEOUL = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 7, 29, 12, 0, 1, tzinfo=SEOUL)
PLAN_DATE = date(2026, 7, 29)


def _setup(*, period=PlanPeriod.MORNING, end_date=date(2026, 8, 4)):
    user_id = uuid.uuid4()
    cycle = make_cycle(
        user_id=user_id,
        start_date=PLAN_DATE,
        end_date=end_date,
        activated_at=datetime(2026, 7, 29, 4, 0, tzinfo=SEOUL),
        ended_at=None,
    )
    target = settlement.SettlementTarget(cycle.id, user_id, PLAN_DATE, period)
    return user_id, cycle, target, FakeSettlementSession().seed(cycle)


@pytest.mark.parametrize(
    ("period", "expected"),
    [
        (PlanPeriod.MORNING, datetime(2026, 7, 29, 12, 0, tzinfo=SEOUL)),
        (PlanPeriod.AFTERNOON, datetime(2026, 7, 29, 18, 0, tzinfo=SEOUL)),
        (PlanPeriod.EVENING, datetime(2026, 7, 30, 4, 0, tzinfo=SEOUL)),
    ],
)
def test_period_end_at(period, expected):
    assert settlement.period_end_at(PLAN_DATE, period) == expected


@pytest.mark.parametrize("period", list(PlanPeriod))
def test_period_closed_at_exact_boundary_but_not_just_before(period):
    end = settlement.period_end_at(PLAN_DATE, period)
    assert settlement.is_period_closed(PLAN_DATE, period, now=end - timedelta(microseconds=1)) is False
    assert settlement.is_period_closed(PLAN_DATE, period, now=end) is True
    assert settlement.is_period_closed(PLAN_DATE, period, now=end + timedelta(microseconds=1)) is True


@pytest.mark.parametrize(
    ("completed", "total", "expected"),
    [(0, 1, 0), (2, 7, 29), (3, 10, 30), (10, 17, 59), (3, 5, 60), (99, 100, 99), (1, 1, 100)],
)
def test_score_boundaries_use_shared_round_half_up(completed, total, expected):
    assert plan_block_service.calculate_plan_percentage(completed, total) == expected


def test_settlement_transitions_blocks_tasks_and_replans_in_two_transactions(monkeypatch):
    user_id, cycle, target, db = _setup()
    completed_task = make_task(
        user_id=user_id,
        plan_cycle_id=cycle.id,
        remaining_minutes=60,
        created_at=NOW,
    )
    remaining_task = make_task(
        user_id=user_id,
        plan_cycle_id=cycle.id,
        remaining_minutes=120,
        created_at=NOW,
    )
    checked = make_plan_block(
        user_id=user_id,
        plan_cycle_id=cycle.id,
        task_id=completed_task.id,
        plan_date=PLAN_DATE,
        period=PlanPeriod.MORNING,
        allocated_minutes=60,
        status=PlanBlockStatus.CHECKED,
        now=NOW,
    )
    planned = make_plan_block(
        user_id=user_id,
        plan_cycle_id=cycle.id,
        task_id=remaining_task.id,
        plan_date=PLAN_DATE,
        period=PlanPeriod.MORNING,
        allocated_minutes=30,
        display_order=1,
        status=PlanBlockStatus.PLANNED,
        now=NOW,
    )
    db.seed(completed_task, remaining_task, checked, planned)
    calls = []

    def fake_schedule(_db, **kwargs):
        calls.append(kwargs)
        return plan_block_service.ScheduleResult([], {}, 17)

    monkeypatch.setattr(plan_block_service, "schedule_plan_blocks", fake_schedule)

    result = settlement.settle_period(db, target, now=NOW)

    check_in = db.all_rows(CheckIn)[0]
    assert result.action == settlement.SettlementAction.FINALIZED
    assert result.check_in_id == check_in.id
    assert db.transaction_count == db.commit_count == 2
    assert db.advisory_lock_keys == [settlement.advisory_lock_key(target)] * 2
    assert checked.status == PlanBlockStatus.COMPLETED
    assert planned.status == PlanBlockStatus.NOT_DONE
    assert checked.check_in_id == planned.check_in_id == check_in.id
    assert completed_task.remaining_minutes == 0
    assert completed_task.status == TaskStatus.COMPLETED
    assert completed_task.completed_at == datetime(2026, 7, 29, 12, 0, tzinfo=SEOUL)
    assert remaining_task.remaining_minutes == 120
    assert check_in.total_plan_count == 2
    assert check_in.completed_plan_count == 1
    assert check_in.score == 50
    assert check_in.replan_unplaced_minutes == 17
    assert check_in.replanned_at == NOW
    assert check_in.finalized_at == NOW
    assert calls == [
        {
            "user_id": user_id,
            "plan_cycle_id": cycle.id,
            "now": datetime(2026, 7, 29, 12, 0, tzinfo=SEOUL),
        }
    ]


def test_completed_check_in_is_idempotent_and_does_not_double_decrement(monkeypatch):
    user_id, cycle, target, db = _setup()
    task = make_task(
        user_id=user_id, plan_cycle_id=cycle.id, remaining_minutes=100, created_at=NOW
    )
    block = make_plan_block(
        user_id=user_id,
        plan_cycle_id=cycle.id,
        task_id=task.id,
        plan_date=PLAN_DATE,
        period=PlanPeriod.MORNING,
        allocated_minutes=40,
        status=PlanBlockStatus.CHECKED,
        now=NOW,
    )
    db.seed(task, block)
    monkeypatch.setattr(
        plan_block_service,
        "schedule_plan_blocks",
        lambda *args, **kwargs: plan_block_service.ScheduleResult([], {}, 0),
    )

    first = settlement.settle_period(db, target, now=NOW)
    second = settlement.settle_period(db, target, now=NOW + timedelta(minutes=1))

    assert first.action == settlement.SettlementAction.FINALIZED
    assert second.action == settlement.SettlementAction.ALREADY_FINALIZED
    assert len(db.all_rows(CheckIn)) == 1
    assert task.remaining_minutes == 60


def test_incomplete_check_in_recovers_same_id(monkeypatch):
    user_id, cycle, target, db = _setup()
    task = make_task(
        user_id=user_id, plan_cycle_id=cycle.id, remaining_minutes=30, created_at=NOW
    )
    block = make_plan_block(
        user_id=user_id,
        plan_cycle_id=cycle.id,
        task_id=task.id,
        plan_date=PLAN_DATE,
        period=PlanPeriod.MORNING,
        allocated_minutes=30,
        status=PlanBlockStatus.CHECKED,
        now=NOW,
    )
    existing = CheckIn(
        id=uuid.uuid4(),
        user_id=user_id,
        plan_cycle_id=cycle.id,
        check_date=PLAN_DATE,
        period=PlanPeriod.MORNING,
        finalization_started_at=NOW - timedelta(minutes=5),
    )
    db.seed(task, block, existing)
    monkeypatch.setattr(
        plan_block_service,
        "schedule_plan_blocks",
        lambda *args, **kwargs: plan_block_service.ScheduleResult([], {}, 0),
    )

    result = settlement.settle_period(db, target, now=NOW)

    assert result.check_in_id == existing.id
    assert len(db.all_rows(CheckIn)) == 1
    assert existing.finalized_at == NOW


def test_cancelled_task_remaining_is_decremented_without_reactivation(monkeypatch):
    user_id, cycle, target, db = _setup()
    cancelled_at = NOW - timedelta(days=1)
    task = make_task(
        user_id=user_id,
        plan_cycle_id=cycle.id,
        remaining_minutes=50,
        created_at=NOW,
        status=TaskStatus.CANCELLED,
        cancelled_at=cancelled_at,
    )
    block = make_plan_block(
        user_id=user_id,
        plan_cycle_id=cycle.id,
        task_id=task.id,
        plan_date=PLAN_DATE,
        period=PlanPeriod.MORNING,
        allocated_minutes=20,
        status=PlanBlockStatus.CHECKED,
        now=NOW,
    )
    db.seed(task, block)
    monkeypatch.setattr(
        plan_block_service,
        "schedule_plan_blocks",
        lambda *args, **kwargs: plan_block_service.ScheduleResult([], {}, 0),
    )

    settlement.settle_period(db, target, now=NOW)

    assert task.remaining_minutes == 30
    assert task.status == TaskStatus.CANCELLED
    assert task.cancelled_at == cancelled_at
    assert task.completed_at is None


def test_replanning_failure_leaves_committed_incomplete_check_in(monkeypatch):
    user_id, cycle, target, db = _setup()
    task = make_task(
        user_id=user_id, plan_cycle_id=cycle.id, remaining_minutes=30, created_at=NOW
    )
    block = make_plan_block(
        user_id=user_id,
        plan_cycle_id=cycle.id,
        task_id=task.id,
        plan_date=PLAN_DATE,
        period=PlanPeriod.MORNING,
        allocated_minutes=30,
        status=PlanBlockStatus.PLANNED,
        now=NOW,
    )
    db.seed(task, block)

    def fail_replan(*args, **kwargs):
        raise RuntimeError("expected replan failure")

    monkeypatch.setattr(plan_block_service, "schedule_plan_blocks", fail_replan)

    with pytest.raises(RuntimeError, match="expected replan failure"):
        settlement.settle_period(db, target, now=NOW)

    check_ins = db.all_rows(CheckIn)
    assert len(check_ins) == 1
    assert check_ins[0].finalized_at is None
    assert db.commit_count == 1
    assert db.rollback_count == 1


def test_general_period_without_blocks_creates_no_check_in(monkeypatch):
    _, _, target, db = _setup()
    schedule = monkeypatch.setattr(
        plan_block_service,
        "schedule_plan_blocks",
        lambda *args, **kwargs: pytest.fail("PlanBlock 없는 일반 분기는 재계획하면 안 된다."),
    )

    result = settlement.settle_period(db, target, now=NOW)

    assert schedule is None
    assert result.action == settlement.SettlementAction.NO_BLOCKS
    assert db.all_rows(CheckIn) == []


def test_last_evening_without_blocks_ends_cycle_and_cancels_tasks_without_check_in():
    user_id, cycle, target, db = _setup(
        period=PlanPeriod.EVENING, end_date=PLAN_DATE
    )
    task = make_task(
        user_id=user_id, plan_cycle_id=cycle.id, remaining_minutes=25, created_at=NOW
    )
    db.seed(task)
    end = settlement.period_end_at(PLAN_DATE, PlanPeriod.EVENING)

    result = settlement.settle_period(db, target, now=end + timedelta(minutes=10))

    assert result.action == settlement.SettlementAction.CYCLE_ENDED_WITHOUT_CHECK_IN
    assert db.all_rows(CheckIn) == []
    assert task.status == TaskStatus.CANCELLED
    assert task.cancelled_at == end
    assert cycle.status == PlanCycleStatus.ENDED
    assert cycle.ended_at == end


def test_last_evening_with_blocks_finalizes_then_ends_without_replanning(monkeypatch):
    user_id, cycle, target, db = _setup(
        period=PlanPeriod.EVENING, end_date=PLAN_DATE
    )
    done_task = make_task(
        user_id=user_id, plan_cycle_id=cycle.id, remaining_minutes=20, created_at=NOW
    )
    remaining_task = make_task(
        user_id=user_id, plan_cycle_id=cycle.id, remaining_minutes=50, created_at=NOW
    )
    block = make_plan_block(
        user_id=user_id,
        plan_cycle_id=cycle.id,
        task_id=done_task.id,
        plan_date=PLAN_DATE,
        period=PlanPeriod.EVENING,
        allocated_minutes=20,
        status=PlanBlockStatus.CHECKED,
        now=NOW,
    )
    db.seed(done_task, remaining_task, block)
    monkeypatch.setattr(
        plan_block_service,
        "schedule_plan_blocks",
        lambda *args, **kwargs: pytest.fail("마지막 EVENING은 재계획하면 안 된다."),
    )
    finished_at = settlement.period_end_at(PLAN_DATE, PlanPeriod.EVENING) + timedelta(minutes=5)

    result = settlement.settle_period(db, target, now=finished_at)

    check_in = db.all_rows(CheckIn)[0]
    assert result.action == settlement.SettlementAction.FINALIZED
    assert done_task.status == TaskStatus.COMPLETED
    assert remaining_task.status == TaskStatus.CANCELLED
    assert remaining_task.cancelled_at == settlement.period_end_at(
        PLAN_DATE, PlanPeriod.EVENING
    )
    assert cycle.status == PlanCycleStatus.ENDED
    assert check_in.replan_unplaced_minutes == 0
    assert check_in.replanned_at is None
