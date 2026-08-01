import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models.enums import (
    AmountSource,
    PlanBlockStatus,
    PlanPeriod,
    SolarItemStatus,
    SolarRequestStatus,
    TaskStatus,
)
from app.models.fixed_schedule import FixedSchedule
from app.models.plan_block import PlanBlock
from app.models.task import Task
from app.services import active_cycle_execution_service as svc
from app.workers.solar_execution_worker import DefaultExecutor
from tests.support_active_cycle_execution import (
    make_active_cycle_request,
    make_check_in,
    make_cycle,
    make_fixed_schedule,
    make_fixed_schedule_delete_item,
    make_fixed_schedule_item,
    make_fixed_schedule_payload,
    make_fixed_schedule_update_item,
    make_plan_block,
    make_task,
    make_task_cancel_item,
    make_task_item,
    make_task_payload,
    make_task_update_item,
    make_task_update_payload,
    FakeActiveCycleDB,
)

SEOUL = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 7, 29, 10, 0, tzinfo=SEOUL)  # MORNING, plan_date=2026-07-29
CURRENT_DATE = date(2026, 7, 29)
CURRENT_PERIOD = PlanPeriod.MORNING


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


# ---------------------------------------------------------------------------
# Task 추가(CREATE)
# ---------------------------------------------------------------------------


def test_task_create_success():
    user_id, cycle, request, db, session = _setup()
    item = make_task_item(
        user_id=user_id, solar_request_id=request.id, item_order=1,
        payload=make_task_payload(title="새 할 일", estimated_minutes=60),
    )
    db.seed(item)

    with session.begin():
        svc.execute_active_cycle(session, request)

    tasks = db.all_rows(Task)
    assert len(tasks) == 1
    assert tasks[0].title == "새 할 일"
    assert tasks[0].estimated_minutes == tasks[0].remaining_minutes == 60
    assert request.status == SolarRequestStatus.COMPLETED
    assert request.execution_result["createdTaskCount"] == 1
    assert item.status == SolarItemStatus.EXECUTED


# ---------------------------------------------------------------------------
# Task 수정 — 완료 시간 계산
# ---------------------------------------------------------------------------


def test_task_update_remaining_only_no_unsettled_checked():
    user_id, cycle, request, db, session = _setup()
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=100, remaining_minutes=40, created_at=NOW)
    item = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id,
        payload=make_task_update_payload(estimated_minutes=100, remaining_minutes=30),
        update_fields=["remainingMinutes"],
    )
    db.seed(task, item)

    with session.begin():
        svc.execute_active_cycle(session, request)

    # settledCompletedMinutes(COMPLETED 이력 없음)=0, unsettledCheckedMinutes=0
    # calculatedEstimated = 0 + 0 + 30 = 30, storedRemaining = 30 + 0 = 30
    assert task.estimated_minutes == 30
    assert task.remaining_minutes == 30
    assert request.execution_result["updatedTaskCount"] == 1


def test_task_update_remaining_only_with_unsettled_checked_no_double_deduction():
    user_id, cycle, request, db, session = _setup()
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=100, remaining_minutes=40, created_at=NOW)
    checked = make_plan_block(
        user_id=user_id, plan_cycle_id=cycle.id, task_id=task.id, plan_date=CURRENT_DATE, period=CURRENT_PERIOD,
        allocated_minutes=25, status=PlanBlockStatus.CHECKED, now=NOW,
    )
    item = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id,
        payload=make_task_update_payload(estimated_minutes=100, remaining_minutes=30),
        update_fields=["remainingMinutes"],
    )
    db.seed(task, checked, item)

    with session.begin():
        svc.execute_active_cycle(session, request)

    # settled=0, unsettledChecked=25, calculatedEstimated=0+25+30=55, storedRemaining=30+25=55
    assert task.estimated_minutes == 55
    assert task.remaining_minutes == 55
    # 스케줄러가 다시 unsettledChecked를 빼면 effectiveRemaining = 55-25 = 30(사용자 입력값)과 일치해야 한다.
    assert task.remaining_minutes - 25 == 30


def test_task_update_completed_history_used_not_estimated_minus_remaining():
    """완료 시간은 COMPLETED PlanBlock 합계여야 하고, estimated-remaining을 쓰면 안 된다.
    remaining > estimated인 기존 상태에서도 정상 계산되어야 한다(비정상 취급 금지)."""
    user_id, cycle, request, db, session = _setup()
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=50, remaining_minutes=80, created_at=NOW)
    completed = make_plan_block(
        user_id=user_id, plan_cycle_id=cycle.id, task_id=task.id, plan_date=CURRENT_DATE - timedelta(days=1),
        period=PlanPeriod.EVENING, allocated_minutes=15, status=PlanBlockStatus.COMPLETED, now=NOW,
    )
    not_done = make_plan_block(
        user_id=user_id, plan_cycle_id=cycle.id, task_id=task.id, plan_date=CURRENT_DATE - timedelta(days=1),
        period=PlanPeriod.AFTERNOON, allocated_minutes=999, status=PlanBlockStatus.NOT_DONE, now=NOW,
    )
    item = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id,
        payload=make_task_update_payload(estimated_minutes=100, remaining_minutes=25),
        update_fields=["remainingMinutes"],
    )
    db.seed(task, completed, not_done, item)

    with session.begin():
        svc.execute_active_cycle(session, request)

    # settled=15(COMPLETED만, NOT_DONE 999는 제외), unsettledChecked=0
    # calculatedEstimated = 15+0+25 = 40, storedRemaining = 25+0 = 25
    assert task.estimated_minutes == 40
    assert task.remaining_minutes == 25


def test_task_update_remaining_greater_than_old_estimated_is_allowed():
    """remaining > estimated인 기존 ACTIVE Task도 정상적으로 다른 필드를 수정할 수 있다."""
    user_id, cycle, request, db, session = _setup()
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=10, remaining_minutes=50,
                      title="원래 제목", created_at=NOW)
    item = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id,
        payload=make_task_update_payload(title="바뀐 제목", estimated_minutes=10, remaining_minutes=50),
        update_fields=["title"],
    )
    db.seed(task, item)

    with session.begin():
        svc.execute_active_cycle(session, request)

    assert task.title == "바뀐 제목"
    assert task.estimated_minutes == 10
    assert task.remaining_minutes == 50  # 시간 필드를 건드리지 않았으므로 그대로


def test_task_update_estimated_only_no_unsettled_checked():
    user_id, cycle, request, db, session = _setup()
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60, created_at=NOW)
    item = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id,
        payload=make_task_update_payload(estimated_minutes=90, remaining_minutes=60),
        update_fields=["estimatedMinutes"],
    )
    db.seed(task, item)

    with session.begin():
        svc.execute_active_cycle(session, request)

    # settled=0, unsettledChecked=0 → effectiveRemaining=90-0-0=90, storedRemaining=90+0=90
    assert task.estimated_minutes == 90
    assert task.remaining_minutes == 90


def test_task_update_estimated_only_with_unsettled_checked():
    user_id, cycle, request, db, session = _setup()
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60, created_at=NOW)
    checked = make_plan_block(
        user_id=user_id, plan_cycle_id=cycle.id, task_id=task.id, plan_date=CURRENT_DATE, period=CURRENT_PERIOD,
        allocated_minutes=20, status=PlanBlockStatus.CHECKED, now=NOW,
    )
    item = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id,
        payload=make_task_update_payload(estimated_minutes=90, remaining_minutes=60),
        update_fields=["estimatedMinutes"],
    )
    db.seed(task, checked, item)

    with session.begin():
        svc.execute_active_cycle(session, request)

    # settled=0, unsettledChecked=20 → effectiveRemaining=90-0-20=70, storedRemaining=70+20=90
    assert task.estimated_minutes == 90
    assert task.remaining_minutes == 90
    assert task.remaining_minutes - 20 == 70  # 이중 차감 없이 effectiveRemaining과 일치


def test_task_update_estimated_only_negative_effective_remaining_fails():
    user_id, cycle, request, db, session = _setup()
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=100, remaining_minutes=100, created_at=NOW)
    completed = make_plan_block(
        user_id=user_id, plan_cycle_id=cycle.id, task_id=task.id, plan_date=CURRENT_DATE - timedelta(days=1),
        period=PlanPeriod.EVENING, allocated_minutes=80, status=PlanBlockStatus.COMPLETED, now=NOW,
    )
    item = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id,
        payload=make_task_update_payload(estimated_minutes=50, remaining_minutes=100),
        update_fields=["estimatedMinutes"],
    )
    db.seed(task, completed, item)

    with pytest.raises(svc.ActiveCycleExecutionError) as exc_info:
        with session.begin():
            svc.execute_active_cycle(session, request)

    assert exc_info.value.code == "PLAN_EXECUTION_FAILED"


def test_task_update_estimated_and_remaining_consistent_succeeds():
    user_id, cycle, request, db, session = _setup()
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60, created_at=NOW)
    item = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id,
        payload=make_task_update_payload(estimated_minutes=80, remaining_minutes=80),
        update_fields=["estimatedMinutes", "remainingMinutes"],
    )
    db.seed(task, item)

    with session.begin():
        svc.execute_active_cycle(session, request)

    assert task.estimated_minutes == 80
    assert task.remaining_minutes == 80


def test_task_update_estimated_and_remaining_inconsistent_fails_entire_request():
    user_id, cycle, request, db, session = _setup()
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60, created_at=NOW)
    item = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id,
        # calculatedEstimated = 0+0+80 = 80 인데 payload는 999 — 불일치
        payload=make_task_update_payload(estimated_minutes=999, remaining_minutes=80),
        update_fields=["estimatedMinutes", "remainingMinutes"],
    )
    db.seed(task, item)

    with pytest.raises(svc.ActiveCycleExecutionError):
        with session.begin():
            svc.execute_active_cycle(session, request)

    assert task.estimated_minutes == 60  # 값을 조용히 한쪽만 반영하지 않고 아예 변경 없음


# ---------------------------------------------------------------------------
# 마감 경고 확인 시각 초기화 / no-op
# ---------------------------------------------------------------------------


def test_task_update_deadline_change_resets_warning_ack():
    user_id, cycle, request, db, session = _setup()
    task = make_task(
        user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60,
        deadline_at=NOW + timedelta(days=1), deadline_warning_acknowledged_at=NOW, created_at=NOW,
    )
    item = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id,
        payload=make_task_update_payload(
            deadline_at_iso=(NOW + timedelta(days=2)).isoformat(), estimated_minutes=60, remaining_minutes=60
        ),
        update_fields=["deadlineAt"],
    )
    db.seed(task, item)

    with session.begin():
        svc.execute_active_cycle(session, request)

    assert task.deadline_warning_acknowledged_at is None


def test_task_update_title_only_does_not_reset_warning_ack():
    user_id, cycle, request, db, session = _setup()
    task = make_task(
        user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60,
        title="old", deadline_warning_acknowledged_at=NOW, created_at=NOW,
    )
    item = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id,
        payload=make_task_update_payload(title="new", estimated_minutes=60, remaining_minutes=60),
        update_fields=["title"],
    )
    db.seed(task, item)

    with session.begin():
        svc.execute_active_cycle(session, request)

    assert task.title == "new"
    assert task.deadline_warning_acknowledged_at == NOW


def test_task_update_same_value_is_noop_and_keeps_warning_ack():
    user_id, cycle, request, db, session = _setup()
    task = make_task(
        user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60,
        deadline_at=None, deadline_warning_acknowledged_at=NOW, created_at=NOW,
    )
    item = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id,
        payload=make_task_update_payload(estimated_minutes=60, remaining_minutes=60),
        update_fields=["estimatedMinutes", "remainingMinutes"],
    )
    db.seed(task, item)

    with session.begin():
        svc.execute_active_cycle(session, request)

    assert task.deadline_warning_acknowledged_at == NOW
    assert request.execution_result["updatedTaskCount"] == 0


# ---------------------------------------------------------------------------
# Task amount
# ---------------------------------------------------------------------------


def test_task_amount_update_success():
    user_id, cycle, request, db, session = _setup()
    task = make_task(
        user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60,
        amount_text="3문제", amount_source=AmountSource.USER, created_at=NOW,
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
    assert task.amount_source == AmountSource.USER


def test_task_amount_time_only_update_keeps_amount_unchanged():
    user_id, cycle, request, db, session = _setup()
    task = make_task(
        user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60,
        amount_text="3문제", amount_source=AmountSource.USER, created_at=NOW,
    )
    item = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id,
        payload=make_task_update_payload(estimated_minutes=90, remaining_minutes=90),
        update_fields=["remainingMinutes"],
    )
    db.seed(task, item)

    with session.begin():
        svc.execute_active_cycle(session, request)

    assert task.amount_text == "3문제"
    assert task.amount_source == AmountSource.USER


def test_task_amount_unknown_source_with_text_fails():
    user_id, cycle, request, db, session = _setup()
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60, created_at=NOW)
    payload = make_task_update_payload(estimated_minutes=60, remaining_minutes=60, amount_text="2문제", amount_source="UNKNOWN")
    item = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id,
        payload=payload, update_fields=["amount"],
    )
    db.seed(task, item)

    with pytest.raises(svc.ActiveCycleExecutionError):
        with session.begin():
            svc.execute_active_cycle(session, request)


def test_task_amount_user_source_without_text_fails():
    user_id, cycle, request, db, session = _setup()
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60, created_at=NOW)
    payload = make_task_update_payload(estimated_minutes=60, remaining_minutes=60, amount_text=None, amount_source="USER")
    item = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id,
        payload=payload, update_fields=["amount"],
    )
    db.seed(task, item)

    with pytest.raises(svc.ActiveCycleExecutionError):
        with session.begin():
            svc.execute_active_cycle(session, request)


def test_task_update_unknown_field_fails():
    user_id, cycle, request, db, session = _setup()
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60, created_at=NOW)
    item = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id,
        payload=make_task_update_payload(estimated_minutes=60, remaining_minutes=60),
        update_fields=["notARealField"],
    )
    db.seed(task, item)

    with pytest.raises(svc.ActiveCycleExecutionError):
        with session.begin():
            svc.execute_active_cycle(session, request)


# ---------------------------------------------------------------------------
# Task 취소
# ---------------------------------------------------------------------------


def test_task_cancel_success():
    user_id, cycle, request, db, session = _setup()
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60, created_at=NOW)
    item = make_task_cancel_item(user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id)
    db.seed(task, item)

    with session.begin():
        svc.execute_active_cycle(session, request)

    assert task.status == TaskStatus.CANCELLED
    assert task.cancelled_at == NOW
    assert task.completed_at is None
    assert request.execution_result["cancelledTaskCount"] == 1


def test_completed_task_update_rejected():
    user_id, cycle, request, db, session = _setup()
    task = make_task(
        user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=0,
        status=TaskStatus.COMPLETED, completed_at=NOW, created_at=NOW,
    )
    item = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id,
        payload=make_task_update_payload(title="바뀐 제목", estimated_minutes=60, remaining_minutes=1),
        update_fields=["title"],
    )
    db.seed(task, item)

    with pytest.raises(svc.ActiveCycleExecutionError):
        with session.begin():
            svc.execute_active_cycle(session, request)

    assert task.title != "바뀐 제목"


def test_cancelled_task_update_rejected():
    user_id, cycle, request, db, session = _setup()
    task = make_task(
        user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60,
        status=TaskStatus.CANCELLED, cancelled_at=NOW, created_at=NOW,
    )
    item = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id,
        payload=make_task_update_payload(title="바뀐 제목", estimated_minutes=60, remaining_minutes=60),
        update_fields=["title"],
    )
    db.seed(task, item)

    with pytest.raises(svc.ActiveCycleExecutionError):
        with session.begin():
            svc.execute_active_cycle(session, request)


def test_duplicate_target_task_cards_rejected():
    user_id, cycle, request, db, session = _setup()
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60, created_at=NOW)
    item1 = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id,
        payload=make_task_update_payload(title="a", estimated_minutes=60, remaining_minutes=60),
        update_fields=["title"],
    )
    item2 = make_task_cancel_item(user_id=user_id, solar_request_id=request.id, item_order=2, target_task_id=task.id)
    db.seed(task, item1, item2)

    with pytest.raises(RuntimeError):
        with session.begin():
            svc.execute_active_cycle(session, request)


# ---------------------------------------------------------------------------
# FixedSchedule
# ---------------------------------------------------------------------------


def test_fixed_schedule_create_success():
    user_id, cycle, request, db, session = _setup()
    payload = make_fixed_schedule_payload(
        start_at_iso=(NOW + timedelta(hours=2)).isoformat(), end_at_iso=(NOW + timedelta(hours=3)).isoformat()
    )
    item = make_fixed_schedule_item(user_id=user_id, solar_request_id=request.id, item_order=1, payload=payload)
    db.seed(item)

    with session.begin():
        svc.execute_active_cycle(session, request)

    rows = db.all_rows(FixedSchedule)
    assert len(rows) == 1
    assert request.execution_result["createdFixedScheduleCount"] == 1


def test_fixed_schedule_create_start_at_now_rejected():
    user_id, cycle, request, db, session = _setup()
    payload = make_fixed_schedule_payload(start_at_iso=NOW.isoformat(), end_at_iso=(NOW + timedelta(hours=1)).isoformat())
    item = make_fixed_schedule_item(user_id=user_id, solar_request_id=request.id, item_order=1, payload=payload)
    db.seed(item)

    with pytest.raises(svc.ActiveCycleExecutionError):
        with session.begin():
            svc.execute_active_cycle(session, request)


def test_fixed_schedule_create_past_rejected():
    user_id, cycle, request, db, session = _setup()
    payload = make_fixed_schedule_payload(
        start_at_iso=(NOW - timedelta(hours=2)).isoformat(), end_at_iso=(NOW - timedelta(hours=1)).isoformat()
    )
    item = make_fixed_schedule_item(user_id=user_id, solar_request_id=request.id, item_order=1, payload=payload)
    db.seed(item)

    with pytest.raises(svc.ActiveCycleExecutionError):
        with session.begin():
            svc.execute_active_cycle(session, request)


def test_fixed_schedule_update_success():
    user_id, cycle, request, db, session = _setup()
    fs = make_fixed_schedule(
        user_id=user_id, plan_cycle_id=cycle.id, start_at=NOW + timedelta(hours=2), end_at=NOW + timedelta(hours=3)
    )
    payload = {"title": "수정된 일정", "startAt": (NOW + timedelta(hours=4)).isoformat(), "endAt": (NOW + timedelta(hours=5)).isoformat()}
    item = make_fixed_schedule_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_fixed_schedule_id=fs.id,
        payload=payload, update_fields=["title", "startAt", "endAt"],
    )
    db.seed(fs, item)

    with session.begin():
        svc.execute_active_cycle(session, request)

    assert fs.title == "수정된 일정"
    assert request.execution_result["updatedFixedScheduleCount"] == 1


def test_fixed_schedule_update_start_at_now_rejected():
    user_id, cycle, request, db, session = _setup()
    fs = make_fixed_schedule(
        user_id=user_id, plan_cycle_id=cycle.id, start_at=NOW + timedelta(hours=2), end_at=NOW + timedelta(hours=3)
    )
    payload = {"title": fs.title, "startAt": NOW.isoformat(), "endAt": (NOW + timedelta(hours=1)).isoformat()}
    item = make_fixed_schedule_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_fixed_schedule_id=fs.id,
        payload=payload, update_fields=["startAt", "endAt"],
    )
    db.seed(fs, item)

    with pytest.raises(svc.ActiveCycleExecutionError):
        with session.begin():
            svc.execute_active_cycle(session, request)


def test_fixed_schedule_update_in_progress_rejected():
    user_id, cycle, request, db, session = _setup()
    fs = make_fixed_schedule(
        user_id=user_id, plan_cycle_id=cycle.id, start_at=NOW - timedelta(hours=1), end_at=NOW + timedelta(hours=1)
    )
    payload = {"title": "바뀐 제목", "startAt": fs.start_at.isoformat(), "endAt": fs.end_at.isoformat()}
    item = make_fixed_schedule_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_fixed_schedule_id=fs.id,
        payload=payload, update_fields=["title"],
    )
    db.seed(fs, item)

    with pytest.raises(svc.ActiveCycleExecutionError):
        with session.begin():
            svc.execute_active_cycle(session, request)


def test_fixed_schedule_update_ended_rejected():
    user_id, cycle, request, db, session = _setup()
    fs = make_fixed_schedule(
        user_id=user_id, plan_cycle_id=cycle.id, start_at=NOW - timedelta(hours=3), end_at=NOW - timedelta(hours=1)
    )
    payload = {"title": "바뀐 제목", "startAt": fs.start_at.isoformat(), "endAt": fs.end_at.isoformat()}
    item = make_fixed_schedule_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_fixed_schedule_id=fs.id,
        payload=payload, update_fields=["title"],
    )
    db.seed(fs, item)

    with pytest.raises(svc.ActiveCycleExecutionError):
        with session.begin():
            svc.execute_active_cycle(session, request)


def test_fixed_schedule_delete_success_and_item_executed_before_delete():
    user_id, cycle, request, db, session = _setup()
    fs = make_fixed_schedule(
        user_id=user_id, plan_cycle_id=cycle.id, start_at=NOW + timedelta(hours=2), end_at=NOW + timedelta(hours=3)
    )
    item = make_fixed_schedule_delete_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_fixed_schedule_id=fs.id
    )
    db.seed(fs, item)

    with session.begin():
        svc.execute_active_cycle(session, request)

    assert db.all_rows(FixedSchedule) == []
    assert item.status == SolarItemStatus.EXECUTED
    assert item.executed_at == NOW
    assert request.execution_result["deletedFixedScheduleCount"] == 1


def test_fixed_schedule_delete_in_progress_rejected():
    user_id, cycle, request, db, session = _setup()
    fs = make_fixed_schedule(
        user_id=user_id, plan_cycle_id=cycle.id, start_at=NOW - timedelta(hours=1), end_at=NOW + timedelta(hours=1)
    )
    item = make_fixed_schedule_delete_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_fixed_schedule_id=fs.id
    )
    db.seed(fs, item)

    with pytest.raises(svc.ActiveCycleExecutionError):
        with session.begin():
            svc.execute_active_cycle(session, request)

    assert db.all_rows(FixedSchedule) == [fs]


def test_duplicate_target_fixed_schedule_cards_rejected():
    user_id, cycle, request, db, session = _setup()
    fs = make_fixed_schedule(
        user_id=user_id, plan_cycle_id=cycle.id, start_at=NOW + timedelta(hours=2), end_at=NOW + timedelta(hours=3)
    )
    item1 = make_fixed_schedule_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_fixed_schedule_id=fs.id,
        payload={"title": "a", "startAt": fs.start_at.isoformat(), "endAt": fs.end_at.isoformat()},
        update_fields=["title"],
    )
    item2 = make_fixed_schedule_delete_item(
        user_id=user_id, solar_request_id=request.id, item_order=2, target_fixed_schedule_id=fs.id
    )
    db.seed(fs, item1, item2)

    with pytest.raises(RuntimeError):
        with session.begin():
            svc.execute_active_cycle(session, request)


# ---------------------------------------------------------------------------
# 정산 경쟁 재검증
# ---------------------------------------------------------------------------


def test_unfinalized_check_in_in_cycle_fails_execution():
    user_id, cycle, request, db, session = _setup()
    check_in = make_check_in(
        user_id=user_id, plan_cycle_id=cycle.id, check_date=CURRENT_DATE, period=PlanPeriod.AFTERNOON,
        finalization_started_at=NOW, finalized_at=None,
    )
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60, created_at=NOW)
    item = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id,
        payload=make_task_update_payload(title="바뀐 제목", estimated_minutes=60, remaining_minutes=60),
        update_fields=["title"],
    )
    db.seed(check_in, task, item)

    with pytest.raises(svc.ActiveCycleExecutionError):
        with session.begin():
            svc.execute_active_cycle(session, request)

    assert task.title != "바뀐 제목"


def test_unfinalized_check_in_from_other_cycle_does_not_block():
    """다른(종료된) cycle의 미정산 CheckIn은 현재 ACTIVE cycle 실행을 막지 않아야 한다."""
    user_id, cycle, request, db, session = _setup()
    other_cycle_id = uuid.uuid4()
    check_in = make_check_in(
        user_id=user_id, plan_cycle_id=other_cycle_id, check_date=CURRENT_DATE - timedelta(days=30),
        period=PlanPeriod.EVENING, finalization_started_at=NOW - timedelta(days=30), finalized_at=None,
    )
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60, created_at=NOW)
    item = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id,
        payload=make_task_update_payload(title="바뀐 제목", estimated_minutes=60, remaining_minutes=60),
        update_fields=["title"],
    )
    db.seed(check_in, task, item)

    with session.begin():
        svc.execute_active_cycle(session, request)

    assert task.title == "바뀐 제목"


def test_past_checked_plan_block_fails_execution():
    user_id, cycle, request, db, session = _setup()
    stale_checked = make_plan_block(
        user_id=user_id, plan_cycle_id=cycle.id, task_id=uuid.uuid4(), plan_date=CURRENT_DATE - timedelta(days=1),
        period=PlanPeriod.EVENING, allocated_minutes=30, status=PlanBlockStatus.CHECKED, now=NOW,
    )
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60, created_at=NOW)
    item = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id,
        payload=make_task_update_payload(title="바뀐 제목", estimated_minutes=60, remaining_minutes=60),
        update_fields=["title"],
    )
    db.seed(stale_checked, task, item)

    with pytest.raises(svc.ActiveCycleExecutionError):
        with session.begin():
            svc.execute_active_cycle(session, request)


def test_settlement_completed_then_retry_succeeds():
    user_id, cycle, request, db, session = _setup()
    check_in = make_check_in(
        user_id=user_id, plan_cycle_id=cycle.id, check_date=CURRENT_DATE - timedelta(days=1), period=PlanPeriod.EVENING,
        finalization_started_at=NOW - timedelta(hours=5), finalized_at=NOW - timedelta(hours=4),
    )
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60, created_at=NOW)
    item = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id,
        payload=make_task_update_payload(title="바뀐 제목", estimated_minutes=60, remaining_minutes=60),
        update_fields=["title"],
    )
    db.seed(check_in, task, item)

    with session.begin():
        svc.execute_active_cycle(session, request)

    assert task.title == "바뀐 제목"
    assert request.status == SolarRequestStatus.COMPLETED


# ---------------------------------------------------------------------------
# 예외 처리 / DefaultExecutor 연결
# ---------------------------------------------------------------------------


def test_default_executor_delegates_active_cycle_purpose_to_service():
    user_id, cycle, request, db, session = _setup()
    item = make_task_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, payload=make_task_payload(estimated_minutes=60)
    )
    db.seed(item)

    with session.begin():
        DefaultExecutor().execute(session, request)

    assert request.status == SolarRequestStatus.COMPLETED


def test_get_current_moment_called_exactly_once(monkeypatch):
    user_id, cycle, request, db, session = _setup()
    item = make_task_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, payload=make_task_payload(estimated_minutes=60)
    )
    db.seed(item)

    call_count = 0

    def _counting_now():
        nonlocal call_count
        call_count += 1
        return NOW

    monkeypatch.setattr(svc, "get_current_moment", _counting_now)

    with session.begin():
        svc.execute_active_cycle(session, request)

    assert call_count == 1


def test_execution_result_key_set_matches_api_spec():
    user_id, cycle, request, db, session = _setup()
    item = make_task_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, payload=make_task_payload(estimated_minutes=60)
    )
    db.seed(item)

    with session.begin():
        svc.execute_active_cycle(session, request)

    assert set(request.execution_result.keys()) == {
        "createdTaskCount",
        "updatedTaskCount",
        "cancelledTaskCount",
        "createdFixedScheduleCount",
        "updatedFixedScheduleCount",
        "deletedFixedScheduleCount",
        "deletedPlanBlockCount",
        "createdPlanBlockCount",
    }
