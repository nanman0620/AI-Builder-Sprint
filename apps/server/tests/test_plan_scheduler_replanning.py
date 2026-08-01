import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.models.enums import AmountSource, PlanBlockStatus, PlanPeriod
from app.models.plan_block import PlanBlock
from app.services import plan_block_service as svc
from tests.support_scheduler import (
    FakeSchedulerSession,
    make_cycle,
    make_plan_block,
    make_task,
)

SEOUL = ZoneInfo("Asia/Seoul")


def _now():
    return datetime(2026, 7, 29, 5, 0, tzinfo=SEOUL)


def _setup():
    user_id = uuid.uuid4()
    cycle_id = uuid.uuid4()
    cycle = make_cycle(
        user_id=user_id, start_date=date(2026, 7, 29), end_date=date(2026, 8, 4), id=cycle_id
    )
    db = FakeSchedulerSession().seed(cycle)
    return user_id, cycle_id, db


def test_checked_block_is_protected_from_deletion():
    user_id, cycle_id, db = _setup()
    task = make_task(user_id=user_id, plan_cycle_id=cycle_id, remaining_minutes=100, created_at=_now())
    checked = make_plan_block(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        task_id=task.id,
        plan_date=date(2026, 7, 29),
        period=PlanPeriod.MORNING,
        allocated_minutes=40,
        status=PlanBlockStatus.CHECKED,
        now=_now(),
    )
    db.seed(task, checked)

    svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=_now())

    assert checked in db.all_rows(PlanBlock)


def test_completed_block_is_protected_from_deletion():
    user_id, cycle_id, db = _setup()
    task = make_task(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        remaining_minutes=0,
        amount_text="3문제",
        amount_source=AmountSource.USER,
        created_at=_now(),
    )
    completed = make_plan_block(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        task_id=task.id,
        plan_date=date(2026, 7, 29),
        period=PlanPeriod.MORNING,
        allocated_minutes=40,
        status=PlanBlockStatus.COMPLETED,
        display_title="완료된 블록",
        now=_now(),
    )
    db.seed(task, completed)

    svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=_now())

    assert completed in db.all_rows(PlanBlock)
    # remaining_minutes=0이라 이번 호출의 배치 대상이 아니며, 과거 COMPLETED의
    # display_title/allocated_amount_text는 새 fallback 규칙과 무관하게 그대로 유지된다.
    assert completed.display_title == "완료된 블록"
    assert completed.allocated_amount_text is None


def test_not_done_block_is_protected_from_deletion():
    user_id, cycle_id, db = _setup()
    task = make_task(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        remaining_minutes=40,
        title="자료구조 과제",
        amount_text="2문제",
        amount_source=AmountSource.USER,
        created_at=_now(),
    )
    not_done = make_plan_block(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        task_id=task.id,
        plan_date=date(2026, 7, 29),
        period=PlanPeriod.MORNING,
        allocated_minutes=40,
        status=PlanBlockStatus.NOT_DONE,
        display_title="미완료 블록",
        now=_now(),
    )
    db.seed(task, not_done)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=_now())

    assert not_done in db.all_rows(PlanBlock)
    # NOT_DONE은 완료된 적이 없는 시도라 CHECKED/COMPLETED 이력에 포함하지 않는다 —
    # 이 Task는 새 블록에 전체 분량을 다시 배분받고, 기존 NOT_DONE 행 자체의 문구는
    # 그대로 유지된다.
    assert not_done.display_title == "미완료 블록"
    assert not_done.allocated_amount_text is None
    new_blocks = [b for b in result.created_blocks if b.task_id == task.id]
    assert len(new_blocks) == 1
    assert new_blocks[0].allocated_amount_text == "2문제"
    assert new_blocks[0].display_title == "자료구조 과제 2문제"


def test_completed_history_keeps_new_blocks_title_only_even_when_task_still_active():
    """예시 8: 과거 COMPLETED가 하나라도 있으면(Task가 아직 진행 중이라도) 이번 신규
    블록 전체가 title-only fallback을 유지한다 — 이미 끝난 몫을 amount_text에서
    차감할 구조가 없기 때문이다."""
    user_id, cycle_id, db = _setup()
    task = make_task(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        remaining_minutes=60,
        title="자료구조 과제",
        amount_text="8문제",
        amount_source=AmountSource.USER,
        created_at=_now(),
    )
    past_completed = make_plan_block(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        task_id=task.id,
        plan_date=date(2026, 7, 28),
        period=PlanPeriod.EVENING,
        allocated_minutes=40,
        status=PlanBlockStatus.COMPLETED,
        display_title="자료구조 과제 3문제",
        allocated_amount_text="3문제",
        now=_now(),
    )
    db.seed(task, past_completed)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=_now())

    new_blocks = [b for b in result.created_blocks if b.task_id == task.id]
    assert len(new_blocks) == 1
    assert new_blocks[0].allocated_amount_text is None
    assert new_blocks[0].display_title == "자료구조 과제"
    # 과거 COMPLETED 저장값은 수정되지 않는다.
    assert past_completed.display_title == "자료구조 과제 3문제"
    assert past_completed.allocated_amount_text == "3문제"


def test_checked_history_keeps_new_block_title_only_and_checked_block_unchanged():
    """예시 7: 기존 CHECKED("한문 과제 1개")가 있으면 Task.amount_text가 "3개"여도
    신규 블록에 다시 배분하지 않는다."""
    user_id, cycle_id, db = _setup()
    task = make_task(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        remaining_minutes=90,
        title="한문 과제",
        amount_text="3개",
        amount_source=AmountSource.USER,
        created_at=_now(),
    )
    checked = make_plan_block(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        task_id=task.id,
        plan_date=date(2026, 7, 29),
        period=PlanPeriod.MORNING,
        allocated_minutes=30,
        status=PlanBlockStatus.CHECKED,
        display_title="한문 과제 1개",
        allocated_amount_text="1개",
        now=_now(),
    )
    db.seed(task, checked)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=_now())

    new_blocks = [b for b in result.created_blocks if b.task_id == task.id]
    assert len(new_blocks) == 1
    assert new_blocks[0].period == PlanPeriod.AFTERNOON
    assert new_blocks[0].allocated_amount_text is None
    assert new_blocks[0].display_title == "한문 과제"
    # 기존 CHECKED 블록은 모든 필드가 그대로 유지된다.
    assert checked.display_title == "한문 과제 1개"
    assert checked.allocated_amount_text == "1개"
    assert checked.status == PlanBlockStatus.CHECKED


def test_current_period_unchecked_planned_is_deleted_and_recreated():
    user_id, cycle_id, db = _setup()
    task = make_task(user_id=user_id, plan_cycle_id=cycle_id, remaining_minutes=100, created_at=_now())
    stale_current = make_plan_block(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        task_id=task.id,
        plan_date=date(2026, 7, 29),
        period=PlanPeriod.MORNING,
        allocated_minutes=30,
        status=PlanBlockStatus.PLANNED,
        now=_now(),
    )
    db.seed(task, stale_current)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=_now())

    assert stale_current not in db.all_rows(PlanBlock)
    morning_blocks = [b for b in result.created_blocks if b.period == PlanPeriod.MORNING]
    assert len(morning_blocks) == 1
    assert morning_blocks[0].allocated_minutes == 100  # 스케줄러가 남은 필요량 전체를 다시 배치


def test_future_planned_is_deleted_and_recreated():
    user_id, cycle_id, db = _setup()
    task = make_task(user_id=user_id, plan_cycle_id=cycle_id, remaining_minutes=50, created_at=_now())
    stale_future = make_plan_block(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        task_id=task.id,
        plan_date=date(2026, 7, 30),
        period=PlanPeriod.EVENING,
        allocated_minutes=50,
        status=PlanBlockStatus.PLANNED,
        now=_now(),
    )
    db.seed(task, stale_future)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=_now())

    assert stale_future not in db.all_rows(PlanBlock)
    # 현재 분기(MORNING)부터 다시 그리디 배치되므로 EVENING이 아니라 MORNING에 재배치된다.
    assert any(b.period == PlanPeriod.MORNING and b.allocated_minutes == 50 for b in result.created_blocks)


def test_task_with_current_period_checked_block_skips_current_period_and_uses_effective_remaining():
    user_id, cycle_id, db = _setup()
    task = make_task(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        remaining_minutes=150,
        title="자료구조 과제",
        amount_text="6문제",
        amount_source=AmountSource.USER,
        created_at=_now(),
    )
    checked = make_plan_block(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        task_id=task.id,
        plan_date=date(2026, 7, 29),
        period=PlanPeriod.MORNING,
        allocated_minutes=60,
        status=PlanBlockStatus.CHECKED,
        display_title="체크된 블록",
        now=_now(),
    )
    db.seed(task, checked)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=_now())

    # 현재 분기(MORNING)에는 이 Task의 신규 블록이 생기지 않는다.
    assert all(
        not (b.task_id == task.id and b.period == PlanPeriod.MORNING) for b in result.created_blocks
    )
    # effective_remaining = 150 - 60(CHECKED) = 90, 다음 분기(AFTERNOON)부터 배치된다.
    afternoon_blocks = [
        b for b in result.created_blocks if b.task_id == task.id and b.period == PlanPeriod.AFTERNOON
    ]
    assert len(afternoon_blocks) == 1
    assert afternoon_blocks[0].allocated_minutes == 90
    assert result.total_unplaced_minutes == 0
    # 신규 블록은 이번 호출에서 Task당 1개·전량 배치이지만, 이 Task에 CHECKED 이력이
    # 있어 이 블록이 Task 전체 분량을 대표하지 않으므로 title-only fallback을 유지한다.
    assert afternoon_blocks[0].allocated_amount_text is None
    assert afternoon_blocks[0].display_title == "자료구조 과제"
    # 보존된 CHECKED 블록 자체의 문구도 그대로 유지된다.
    assert checked.display_title == "체크된 블록"
    assert checked.allocated_amount_text is None


def test_display_order_continues_after_protected_block_in_same_period():
    user_id, cycle_id, db = _setup()
    task_checked = make_task(
        user_id=user_id, plan_cycle_id=cycle_id, remaining_minutes=60, created_at=_now(), title="checked-task"
    )
    task_new = make_task(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        remaining_minutes=30,
        created_at=_now(),
        title="new-task",
    )
    checked = make_plan_block(
        user_id=user_id,
        plan_cycle_id=cycle_id,
        task_id=task_checked.id,
        plan_date=date(2026, 7, 29),
        period=PlanPeriod.MORNING,
        allocated_minutes=60,
        status=PlanBlockStatus.CHECKED,
        display_order=0,
        now=_now(),
    )
    db.seed(task_checked, task_new, checked)

    result = svc.schedule_plan_blocks(db, user_id=user_id, plan_cycle_id=cycle_id, now=_now())

    morning_new_blocks = [
        b for b in result.created_blocks if b.task_id == task_new.id and b.period == PlanPeriod.MORNING
    ]
    assert len(morning_new_blocks) == 1
    assert morning_new_blocks[0].display_order == 1  # 기존 CHECKED(0) 다음부터 배정

    all_orders = [checked.display_order] + [b.display_order for b in morning_new_blocks]
    assert len(all_orders) == len(set(all_orders))
