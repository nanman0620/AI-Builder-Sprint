import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models.enums import PlanBlockStatus, PlanPeriod, TaskStatus
from app.models.plan_block import PlanBlock
from app.services import active_cycle_execution_service as svc
from app.services import plan_block_service
from tests.support_active_cycle_execution import (
    FakeActiveCycleDB,
    make_active_cycle_request,
    make_cycle,
    make_plan_block,
    make_task,
    make_task_cancel_item,
    make_task_update_item,
    make_task_update_payload,
)

SEOUL = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 7, 29, 10, 0, tzinfo=SEOUL)  # MORNING, plan_date=2026-07-29
CURRENT_DATE = date(2026, 7, 29)
CURRENT_PERIOD = PlanPeriod.MORNING
FUTURE_DATE = date(2026, 7, 30)


@pytest.fixture(autouse=True)
def _fixed_now(monkeypatch):
    monkeypatch.setattr(svc, "get_current_moment", lambda: NOW)


def _setup(*extra_rows):
    user_id = uuid.uuid4()
    cycle = make_cycle(user_id=user_id, start_date=CURRENT_DATE, end_date=CURRENT_DATE + timedelta(days=6))
    request = make_active_cycle_request(user_id=user_id, plan_cycle_id=cycle.id, now=NOW)
    db = FakeActiveCycleDB().seed(cycle, request, *extra_rows)
    session = db()
    return user_id, cycle, request, db, session


def _title_update_item(user_id, request_id, task):
    return make_task_update_item(
        user_id=user_id, solar_request_id=request_id, item_order=1, target_task_id=task.id,
        payload=make_task_update_payload(title="바뀐 제목", estimated_minutes=task.estimated_minutes,
                                          remaining_minutes=task.remaining_minutes),
        update_fields=["title"],
    )


# ---------------------------------------------------------------------------
# 보호 범위
# ---------------------------------------------------------------------------


def test_current_checked_preserved_for_non_target_task():
    user_id, cycle, request, db, session = _setup()
    target_task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60, created_at=NOW)
    other_task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60, created_at=NOW)
    other_checked = make_plan_block(
        user_id=user_id, plan_cycle_id=cycle.id, task_id=other_task.id, plan_date=CURRENT_DATE, period=CURRENT_PERIOD,
        allocated_minutes=45, status=PlanBlockStatus.CHECKED, display_title="other task title",
        allocated_amount_text=None, now=NOW,
    )
    item = _title_update_item(user_id, request.id, target_task)
    db.seed(target_task, other_task, other_checked, item)

    snapshot = dict(other_checked.__dict__)

    with session.begin():
        svc.execute_active_cycle(session, request)

    assert other_checked in db.all_rows(PlanBlock)
    for key in ("status", "checked_at", "allocated_minutes", "display_title", "allocated_amount_text", "display_order"):
        assert getattr(other_checked, key) == snapshot[key], key


def test_past_completed_and_not_done_preserved():
    user_id, cycle, request, db, session = _setup()
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60, created_at=NOW)
    past_completed = make_plan_block(
        user_id=user_id, plan_cycle_id=cycle.id, task_id=task.id, plan_date=CURRENT_DATE - timedelta(days=1),
        period=PlanPeriod.EVENING, allocated_minutes=30, status=PlanBlockStatus.COMPLETED, now=NOW,
    )
    past_not_done = make_plan_block(
        user_id=user_id, plan_cycle_id=cycle.id, task_id=task.id, plan_date=CURRENT_DATE - timedelta(days=1),
        period=PlanPeriod.AFTERNOON, allocated_minutes=20, status=PlanBlockStatus.NOT_DONE, now=NOW,
    )
    item = _title_update_item(user_id, request.id, task)
    db.seed(task, past_completed, past_not_done, item)

    with session.begin():
        svc.execute_active_cycle(session, request)

    rows = db.all_rows(PlanBlock)
    assert past_completed in rows
    assert past_not_done in rows
    assert past_completed.status == PlanBlockStatus.COMPLETED
    assert past_not_done.status == PlanBlockStatus.NOT_DONE


def test_current_unchecked_planned_deleted_and_recreated():
    user_id, cycle, request, db, session = _setup()
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60, created_at=NOW)
    stale_planned = make_plan_block(
        user_id=user_id, plan_cycle_id=cycle.id, task_id=task.id, plan_date=CURRENT_DATE, period=CURRENT_PERIOD,
        allocated_minutes=60, status=PlanBlockStatus.PLANNED, now=NOW,
    )
    item = _title_update_item(user_id, request.id, task)
    db.seed(task, stale_planned, item)

    with session.begin():
        svc.execute_active_cycle(session, request)

    rows = db.all_rows(PlanBlock)
    assert stale_planned not in rows
    assert any(block.task_id == task.id and block.status == PlanBlockStatus.PLANNED for block in rows)
    assert request.execution_result["deletedPlanBlockCount"] == 1
    assert request.execution_result["createdPlanBlockCount"] >= 1


def test_future_planned_deleted_and_recreated():
    user_id, cycle, request, db, session = _setup()
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60, created_at=NOW)
    future_planned = make_plan_block(
        user_id=user_id, plan_cycle_id=cycle.id, task_id=task.id, plan_date=FUTURE_DATE, period=PlanPeriod.MORNING,
        allocated_minutes=60, status=PlanBlockStatus.PLANNED, now=NOW,
    )
    item = _title_update_item(user_id, request.id, task)
    db.seed(task, future_planned, item)

    with session.begin():
        svc.execute_active_cycle(session, request)

    rows = db.all_rows(PlanBlock)
    assert future_planned not in rows
    assert any(block.task_id == task.id and block.status == PlanBlockStatus.PLANNED for block in rows)
    assert request.execution_result["deletedPlanBlockCount"] == 1


def test_deleted_and_created_count_accuracy():
    user_id, cycle, request, db, session = _setup()
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=300, remaining_minutes=300, created_at=NOW)
    current_planned = make_plan_block(
        user_id=user_id, plan_cycle_id=cycle.id, task_id=task.id, plan_date=CURRENT_DATE, period=CURRENT_PERIOD,
        allocated_minutes=60, status=PlanBlockStatus.PLANNED, now=NOW,
    )
    future_planned = make_plan_block(
        user_id=user_id, plan_cycle_id=cycle.id, task_id=task.id, plan_date=FUTURE_DATE, period=PlanPeriod.MORNING,
        allocated_minutes=60, status=PlanBlockStatus.PLANNED, now=NOW,
    )
    item = _title_update_item(user_id, request.id, task)
    db.seed(task, current_planned, future_planned, item)

    with session.begin():
        svc.execute_active_cycle(session, request)

    rows = db.all_rows(PlanBlock)
    assert request.execution_result["deletedPlanBlockCount"] == 2
    created_rows = [b for b in rows if b.task_id == task.id]
    assert request.execution_result["createdPlanBlockCount"] == len(created_rows)


def test_post_delete_verification_fails_execution_when_row_remains(monkeypatch):
    """schedule_plan_blocks()가 잠갔던 삭제 대상을 실제로 지우지 못하면(가정된 drift),
    조용히 성공 처리하지 않고 전체 실행을 실패시켜야 한다."""
    user_id, cycle, request, db, session = _setup()
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60, created_at=NOW)
    stale_planned = make_plan_block(
        user_id=user_id, plan_cycle_id=cycle.id, task_id=task.id, plan_date=CURRENT_DATE, period=CURRENT_PERIOD,
        allocated_minutes=60, status=PlanBlockStatus.PLANNED, now=NOW,
    )
    item = _title_update_item(user_id, request.id, task)
    db.seed(task, stale_planned, item)

    def _noop_schedule(db_arg, *, user_id, plan_cycle_id, now):
        return plan_block_service.ScheduleResult(created_blocks=[], unplaced_minutes={}, total_unplaced_minutes=0)

    monkeypatch.setattr(svc.plan_block_service, "schedule_plan_blocks", _noop_schedule)

    with pytest.raises(svc.ActiveCycleExecutionError):
        with session.begin():
            svc.execute_active_cycle(session, request)


# ---------------------------------------------------------------------------
# 분량과 PlanBlock 표시 범위 분리
# ---------------------------------------------------------------------------


def test_new_planned_uses_task_amount_text_when_single_block_fully_placed():
    """Task가 이번 재계획에서 신규 블록 1개로 남김없이 배치되면(보존된 CHECKED도 없으면)
    그 블록이 Task 전체 분량을 대표하므로 SOLAR 연동 전 제한적 MVP fallback으로
    title+amount_text를 쓴다."""
    user_id, cycle, request, db, session = _setup()
    task = make_task(
        user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60,
        title="자료구조", amount_text="3문제", created_at=NOW,
    )
    payload = make_task_update_payload(estimated_minutes=60, remaining_minutes=60, amount_text="2문제", amount_source="USER")
    item = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id,
        payload=payload, update_fields=["amount"],
    )
    db.seed(task, item)

    with session.begin():
        svc.execute_active_cycle(session, request)

    assert task.amount_text == "2문제"
    new_blocks = [b for b in db.all_rows(PlanBlock) if b.task_id == task.id]
    assert len(new_blocks) == 1
    assert new_blocks[0].allocated_amount_text == "2문제"
    assert new_blocks[0].display_title == "자료구조 2문제"


def test_new_planned_keeps_title_only_fallback_when_current_checked_remains():
    """현재 분기에 보존된 CHECKED가 남아 있으면, 신규 블록이 1개·전량 배치라도 Task
    전체 분량을 대표하지 않으므로 title-only fallback을 유지한다."""
    user_id, cycle, request, db, session = _setup()
    task = make_task(
        user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=90, remaining_minutes=90,
        title="자료구조", amount_text="6문제", created_at=NOW,
    )
    current_checked = make_plan_block(
        user_id=user_id, plan_cycle_id=cycle.id, task_id=task.id, plan_date=CURRENT_DATE, period=CURRENT_PERIOD,
        allocated_minutes=30, status=PlanBlockStatus.CHECKED, display_title="체크된 블록",
        allocated_amount_text=None, now=NOW,
    )
    item = _title_update_item(user_id, request.id, task)
    db.seed(task, current_checked, item)

    with session.begin():
        svc.execute_active_cycle(session, request)

    new_blocks = [
        b for b in db.all_rows(PlanBlock) if b.task_id == task.id and b.status == PlanBlockStatus.PLANNED
    ]
    assert new_blocks
    for block in new_blocks:
        assert block.allocated_amount_text is None
        assert block.display_title == task.title
        assert "6문제" not in block.display_title
    assert current_checked.display_title == "체크된 블록"
    assert current_checked.allocated_amount_text is None


def test_cancelled_task_excluded_from_new_planned_but_current_checked_kept():
    user_id, cycle, request, db, session = _setup()
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60, created_at=NOW)
    current_checked = make_plan_block(
        user_id=user_id, plan_cycle_id=cycle.id, task_id=task.id, plan_date=CURRENT_DATE, period=CURRENT_PERIOD,
        allocated_minutes=30, status=PlanBlockStatus.CHECKED, now=NOW,
    )
    future_planned = make_plan_block(
        user_id=user_id, plan_cycle_id=cycle.id, task_id=task.id, plan_date=FUTURE_DATE, period=PlanPeriod.MORNING,
        allocated_minutes=30, status=PlanBlockStatus.PLANNED, now=NOW,
    )
    item = make_task_cancel_item(user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id)
    db.seed(task, current_checked, future_planned, item)

    with session.begin():
        svc.execute_active_cycle(session, request)

    assert task.status == TaskStatus.CANCELLED
    rows = db.all_rows(PlanBlock)
    assert current_checked in rows
    assert current_checked.status == PlanBlockStatus.CHECKED
    assert future_planned not in rows
    assert not any(b.task_id == task.id and b.status == PlanBlockStatus.PLANNED for b in rows)
