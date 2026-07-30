import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.models.enums import PlanPeriod
from app.services import plan_block_service as svc
from tests.support_scheduler import FakeSchedulerSession, make_fixed_schedule

SEOUL = ZoneInfo("Asia/Seoul")


def test_future_period_capacity_is_full_without_fixed_schedule():
    user_id = uuid.uuid4()
    db = FakeSchedulerSession()

    available = svc.compute_period_capacity(
        db,
        user_id=user_id,
        plan_date=date(2026, 7, 30),
        period=PlanPeriod.AFTERNOON,
        is_current_period=False,
        now=datetime(2026, 7, 29, 5, 0, tzinfo=SEOUL),
    )

    assert available == 240


def test_future_period_capacity_subtracts_fixed_schedule_minutes():
    user_id = uuid.uuid4()
    cycle_id = uuid.uuid4()
    # AFTERNOON = 12:00~18:00. 그 중 1시간(60분)이 고정 일정으로 차 있다.
    fs = make_fixed_schedule(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        start_at=datetime(2026, 7, 30, 13, 0, tzinfo=SEOUL),
        end_at=datetime(2026, 7, 30, 14, 0, tzinfo=SEOUL),
    )
    db = FakeSchedulerSession().seed(fs)

    available = svc.compute_period_capacity(
        db,
        user_id=user_id,
        plan_date=date(2026, 7, 30),
        period=PlanPeriod.AFTERNOON,
        is_current_period=False,
        now=datetime(2026, 7, 29, 5, 0, tzinfo=SEOUL),
    )

    assert available == 240 - 60


def test_future_period_capacity_does_not_double_count_overlapping_fixed_schedules():
    user_id = uuid.uuid4()
    cycle_id = uuid.uuid4()
    # 두 고정 일정이 12:30~13:30 구간에서 겹친다 -> 합집합은 12:00~14:00 (120분).
    fs1 = make_fixed_schedule(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        start_at=datetime(2026, 7, 30, 12, 0, tzinfo=SEOUL),
        end_at=datetime(2026, 7, 30, 13, 30, tzinfo=SEOUL),
    )
    fs2 = make_fixed_schedule(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        start_at=datetime(2026, 7, 30, 12, 30, tzinfo=SEOUL),
        end_at=datetime(2026, 7, 30, 14, 0, tzinfo=SEOUL),
    )
    db = FakeSchedulerSession().seed(fs1, fs2)

    available = svc.compute_period_capacity(
        db,
        user_id=user_id,
        plan_date=date(2026, 7, 30),
        period=PlanPeriod.AFTERNOON,
        is_current_period=False,
        now=datetime(2026, 7, 29, 5, 0, tzinfo=SEOUL),
    )

    assert available == 240 - 120


def test_future_period_capacity_ignores_schedules_outside_the_window():
    user_id = uuid.uuid4()
    cycle_id = uuid.uuid4()
    fs = make_fixed_schedule(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        start_at=datetime(2026, 7, 30, 9, 0, tzinfo=SEOUL),
        end_at=datetime(2026, 7, 30, 11, 0, tzinfo=SEOUL),
    )
    db = FakeSchedulerSession().seed(fs)

    available = svc.compute_period_capacity(
        db,
        user_id=user_id,
        plan_date=date(2026, 7, 30),
        period=PlanPeriod.AFTERNOON,  # 12:00~18:00, 위 일정과 겹치지 않음
        is_current_period=False,
        now=datetime(2026, 7, 29, 5, 0, tzinfo=SEOUL),
    )

    assert available == 240


def test_current_period_uses_min_of_limit_and_clock_remaining():
    user_id = uuid.uuid4()
    # AFTERNOON(12:00~18:00) 진행 중, now=17:00 -> 시계상 남은 시간은 60분뿐이라
    # 240분 한도보다 시계 제약이 더 강하다.
    db = FakeSchedulerSession()

    available = svc.compute_period_capacity(
        db,
        user_id=user_id,
        plan_date=date(2026, 7, 30),
        period=PlanPeriod.AFTERNOON,
        is_current_period=True,
        now=datetime(2026, 7, 30, 17, 0, tzinfo=SEOUL),
    )

    assert available == 60


def test_current_period_checked_minutes_reduce_limit_capacity():
    user_id = uuid.uuid4()
    db = FakeSchedulerSession()

    available = svc.compute_period_capacity(
        db,
        user_id=user_id,
        plan_date=date(2026, 7, 30),
        period=PlanPeriod.AFTERNOON,
        is_current_period=True,
        now=datetime(2026, 7, 30, 12, 5, tzinfo=SEOUL),
        checked_minutes=100,
    )

    # remaining_capacity_by_limit = 240-100=140, remaining_clock_available = 355(대략) 중 작은 값
    assert available == 140


def test_current_period_fixed_schedule_after_now_reduces_clock_available():
    user_id = uuid.uuid4()
    cycle_id = uuid.uuid4()
    # now=12:00, AFTERNOON 끝까지(18:00) 360분 중 13:00~14:00(60분)이 고정 일정으로 막혀 있다.
    fs = make_fixed_schedule(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        start_at=datetime(2026, 7, 30, 13, 0, tzinfo=SEOUL),
        end_at=datetime(2026, 7, 30, 14, 0, tzinfo=SEOUL),
    )
    db = FakeSchedulerSession().seed(fs)

    available = svc.compute_period_capacity(
        db,
        user_id=user_id,
        plan_date=date(2026, 7, 30),
        period=PlanPeriod.AFTERNOON,
        is_current_period=True,
        now=datetime(2026, 7, 30, 12, 0, tzinfo=SEOUL),
    )

    # remaining_capacity_by_limit = 240 - 0 - 60 = 180
    # remaining_clock_available = (18:00-12:00=360) - 60 = 300
    assert available == 180


def test_current_period_fixed_schedule_before_now_does_not_reduce_clock_available():
    user_id = uuid.uuid4()
    cycle_id = uuid.uuid4()
    # 고정 일정이 이미 지나간 시간대(now 이전)에만 있으면 남은 시계 시간에는 영향이 없다.
    fs = make_fixed_schedule(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        start_at=datetime(2026, 7, 30, 12, 0, tzinfo=SEOUL),
        end_at=datetime(2026, 7, 30, 12, 30, tzinfo=SEOUL),
    )
    db = FakeSchedulerSession().seed(fs)

    available = svc.compute_period_capacity(
        db,
        user_id=user_id,
        plan_date=date(2026, 7, 30),
        period=PlanPeriod.AFTERNOON,
        is_current_period=True,
        now=datetime(2026, 7, 30, 13, 0, tzinfo=SEOUL),
    )

    # remaining_capacity_by_limit(전체 분기 기준) = 240 - 0 - 30 = 210
    # remaining_clock_available = (18:00-13:00=300) - 0(고정 일정이 now 이전이라 클리핑됨) = 300
    # 둘 중 작은 값
    assert available == 210
