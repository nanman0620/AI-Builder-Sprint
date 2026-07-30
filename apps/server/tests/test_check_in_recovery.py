import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.models.check_in import CheckIn
from app.models.enums import PlanPeriod
from app.services import check_in_settlement_service as settlement
from tests.support_scheduler import make_cycle
from tests.support_settlement import FakeSettlementSession

SEOUL = ZoneInfo("Asia/Seoul")


def test_recovery_finds_incomplete_and_missing_periods_oldest_first():
    user_id = uuid.uuid4()
    cycle = make_cycle(
        user_id=user_id,
        start_date=date(2026, 7, 29),
        end_date=date(2026, 8, 4),
        activated_at=datetime(2026, 7, 29, 4, 0, tzinfo=SEOUL),
        ended_at=None,
    )
    incomplete = CheckIn(
        id=uuid.uuid4(),
        user_id=user_id,
        plan_cycle_id=cycle.id,
        check_date=date(2026, 7, 29),
        period=PlanPeriod.AFTERNOON,
        finalization_started_at=datetime(2026, 7, 29, 18, 0, tzinfo=SEOUL),
    )
    db = FakeSettlementSession().seed(cycle, incomplete)

    targets = settlement.find_recovery_targets(
        db, now=datetime(2026, 7, 30, 4, 0, tzinfo=SEOUL)
    )

    assert [(target.plan_date, target.period) for target in targets] == [
        (date(2026, 7, 29), PlanPeriod.MORNING),
        (date(2026, 7, 29), PlanPeriod.AFTERNOON),
        (date(2026, 7, 29), PlanPeriod.EVENING),
    ]
    assert targets[1].plan_cycle_id == incomplete.plan_cycle_id


def test_recovery_does_not_report_future_boundary():
    user_id = uuid.uuid4()
    cycle = make_cycle(
        user_id=user_id,
        start_date=date(2026, 7, 29),
        end_date=date(2026, 8, 4),
        activated_at=datetime(2026, 7, 29, 4, 0, tzinfo=SEOUL),
        ended_at=None,
    )
    db = FakeSettlementSession().seed(cycle)

    targets = settlement.find_recovery_targets(
        db, now=datetime(2026, 7, 29, 11, 59, 59, tzinfo=SEOUL)
    )

    assert targets == []


def test_recovery_does_not_load_check_ins_for_cycle_starting_after_latest_closed_period():
    user_id = uuid.uuid4()
    future_cycle = make_cycle(
        user_id=user_id,
        start_date=date(2026, 7, 30),
        end_date=date(2026, 8, 5),
        activated_at=datetime(2026, 7, 30, 4, 0, tzinfo=SEOUL),
        ended_at=None,
    )
    db = FakeSettlementSession().seed(future_cycle)

    targets = settlement.find_recovery_targets(
        db, now=datetime(2026, 7, 30, 3, 59, 59, tzinfo=SEOUL)
    )

    assert targets == []
    # 미완료 CheckIn 조회 + 종료 분기가 존재할 수 있는 ACTIVE cycle 조회까지만 수행한다.
    assert len(db.executed_statements) == 2
    active_cycle_query = db.executed_statements[1]
    assert "planning_cycles.start_date <=" in str(active_cycle_query.whereclause)


def test_recovery_treats_early_morning_as_previous_evening_boundary():
    user_id = uuid.uuid4()
    cycle = make_cycle(
        user_id=user_id,
        start_date=date(2026, 7, 29),
        end_date=date(2026, 8, 4),
        activated_at=datetime(2026, 7, 29, 4, 0, tzinfo=SEOUL),
        ended_at=None,
    )
    db = FakeSettlementSession().seed(cycle)

    before = settlement.find_recovery_targets(
        db, now=datetime(2026, 7, 30, 3, 59, 59, tzinfo=SEOUL)
    )
    at_boundary = settlement.find_recovery_targets(
        db, now=datetime(2026, 7, 30, 4, 0, tzinfo=SEOUL)
    )

    assert (date(2026, 7, 29), PlanPeriod.EVENING) not in {
        (target.plan_date, target.period) for target in before
    }
    assert (date(2026, 7, 29), PlanPeriod.EVENING) in {
        (target.plan_date, target.period) for target in at_boundary
    }


def test_advisory_key_is_stable_and_period_specific():
    target = settlement.SettlementTarget(
        uuid.UUID("00000000-0000-0000-0000-000000000001"),
        uuid.uuid4(),
        date(2026, 7, 29),
        PlanPeriod.MORNING,
    )
    same_identity_other_user = settlement.SettlementTarget(
        target.plan_cycle_id,
        uuid.uuid4(),
        target.plan_date,
        target.period,
    )
    afternoon = settlement.SettlementTarget(
        target.plan_cycle_id,
        target.user_id,
        target.plan_date,
        PlanPeriod.AFTERNOON,
    )
    next_date = settlement.SettlementTarget(
        target.plan_cycle_id,
        target.user_id,
        date(2026, 7, 30),
        target.period,
    )
    other_cycle = settlement.SettlementTarget(
        uuid.UUID("00000000-0000-0000-0000-000000000002"),
        target.user_id,
        target.plan_date,
        target.period,
    )

    assert settlement.advisory_lock_key(target) == settlement.advisory_lock_key(
        same_identity_other_user
    )
    assert settlement.advisory_lock_key(target) != settlement.advisory_lock_key(afternoon)
    assert settlement.advisory_lock_key(target) != settlement.advisory_lock_key(next_date)
    assert settlement.advisory_lock_key(target) != settlement.advisory_lock_key(other_cycle)
