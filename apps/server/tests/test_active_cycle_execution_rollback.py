"""ACTIVE_CYCLE 실행 rollback 검증.

NEW_CYCLE의 test_new_cycle_execution_rollback.py와 동일한 원칙을 그대로 따른다: 실행
트랜잭션(_execute_locked가 이미 연 `with db.begin()` 블록) 안에서 발생하는 예외는 분류
여부와 무관하게(ActiveCycleExecutionError뿐 아니라 RuntimeError 같은 예상하지 못한 버그도)
rollback 후 별도 트랜잭션에서 request만 FAILED로 기록해야 하고, Task·FixedSchedule·
PlanBlock·item에는 부분 변경이 남지 않아야 한다.
"""

import logging
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models.enums import PlanBlockStatus, SolarItemStatus, SolarRequestStatus, TaskStatus
from app.models.fixed_schedule import FixedSchedule
from app.models.plan_block import PlanBlock
from app.services import active_cycle_execution_service as svc
from app.services import plan_block_service
from app.workers import solar_execution_worker as worker_module
from app.workers.solar_execution_worker import DefaultExecutor
from tests.support_active_cycle_execution import (
    FakeActiveCycleDB,
    make_active_cycle_request,
    make_cycle,
    make_fixed_schedule,
    make_fixed_schedule_delete_item,
    make_fixed_schedule_update_item,
    make_plan_block,
    make_task,
    make_task_cancel_item,
    make_task_update_item,
    make_task_update_payload,
)

SEOUL = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 7, 29, 10, 0, tzinfo=SEOUL)
CURRENT_DATE = date(2026, 7, 29)


@pytest.fixture(autouse=True)
def _fixed_now(monkeypatch):
    monkeypatch.setattr(svc, "get_current_moment", lambda: NOW)


def _setup(*extra_rows):
    user_id = uuid.uuid4()
    cycle = make_cycle(user_id=user_id, start_date=CURRENT_DATE, end_date=CURRENT_DATE + timedelta(days=6))
    request = make_active_cycle_request(user_id=user_id, plan_cycle_id=cycle.id, now=NOW)
    db = FakeActiveCycleDB().seed(cycle, request, *extra_rows)
    return user_id, cycle, request, db


def _assert_failed_safely(request, db):
    assert request.status == SolarRequestStatus.FAILED
    assert request.error_code == "PLAN_EXECUTION_FAILED"
    assert request.error_message
    assert request.executed_at is None
    assert request.execution_result is None
    assert request in db.all_rows(type(request))


def test_rollback_when_second_task_update_fails_first_task_change_reverted():
    """item 1(Task 제목 수정)이 먼저 적용된 뒤 item 2(다른 Task) 처리 중 실패하면, item 1의
    변경까지 전부 rollback돼야 한다 — item 일부만 반영된 채 남지 않는다."""
    user_id, cycle, request, db = _setup()
    task1 = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60,
                       title="원제목1", created_at=NOW)
    task2 = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60,
                       title="원제목2", created_at=NOW)
    item1 = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task1.id,
        payload=make_task_update_payload(title="새제목1", estimated_minutes=60, remaining_minutes=60),
        update_fields=["title"],
    )
    item2 = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=2, target_task_id=task2.id,
        payload=make_task_update_payload(title="새제목2", estimated_minutes=60, remaining_minutes=60),
        update_fields=["title"],
    )
    db.seed(task1, task2, item1, item2)

    def _raise(*args, **kwargs):
        raise RuntimeError("두 번째 카드 처리 중 예상 못한 버그")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(svc, "_apply_task_update", _raise)
        worker_module._execute_locked(db, request.id, DefaultExecutor())

    assert task1.title == "원제목1"
    assert task2.title == "원제목2"
    assert item1.status == SolarItemStatus.READY
    assert item1.executed_at is None
    assert item2.status == SolarItemStatus.READY
    _assert_failed_safely(request, db)


def test_rollback_when_fixed_schedule_mutation_fails_after_task_mutation():
    user_id, cycle, request, db = _setup()
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60,
                      title="원제목", created_at=NOW)
    fs = make_fixed_schedule(user_id=user_id, plan_cycle_id=cycle.id, start_at=NOW + timedelta(hours=2),
                              end_at=NOW + timedelta(hours=3), title="원래 일정")
    task_item = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id,
        payload=make_task_update_payload(title="새제목", estimated_minutes=60, remaining_minutes=60),
        update_fields=["title"],
    )
    fs_item = make_fixed_schedule_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=2, target_fixed_schedule_id=fs.id,
        payload={"title": "바뀐 일정", "startAt": fs.start_at.isoformat(), "endAt": fs.end_at.isoformat()},
        update_fields=["title"],
    )
    db.seed(task, fs, task_item, fs_item)

    def _raise(*args, **kwargs):
        raise RuntimeError("고정 일정 처리 중 예상 못한 버그")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(svc, "_apply_fixed_schedule_update", _raise)
        worker_module._execute_locked(db, request.id, DefaultExecutor())

    assert task.title == "원제목"
    assert fs.title == "원래 일정"
    assert task_item.status == SolarItemStatus.READY
    assert fs_item.status == SolarItemStatus.READY
    _assert_failed_safely(request, db)


def test_rollback_when_fixed_schedule_delete_fails_deletion_reverted():
    user_id, cycle, request, db = _setup()
    fs = make_fixed_schedule(user_id=user_id, plan_cycle_id=cycle.id, start_at=NOW + timedelta(hours=2),
                              end_at=NOW + timedelta(hours=3))
    item = make_fixed_schedule_delete_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_fixed_schedule_id=fs.id
    )
    db.seed(fs, item)

    def _raise_on_delete(self, obj):
        raise RuntimeError("삭제 도중 예상 못한 버그")

    with pytest.MonkeyPatch.context() as mp:
        from tests.support_new_cycle_execution import FakeNewCycleSession

        mp.setattr(FakeNewCycleSession, "delete", _raise_on_delete)
        worker_module._execute_locked(db, request.id, DefaultExecutor())

    assert db.all_rows(FixedSchedule) == [fs]
    assert item.status == SolarItemStatus.READY
    assert item.executed_at is None
    _assert_failed_safely(request, db)


def test_rollback_when_plan_block_scheduling_fails_planned_delete_reverted():
    """기존 PLANNED 삭제(잠금까지)까지는 진행됐는데 schedule_plan_blocks()가 실패하면,
    삭제 자체도 rollback돼야 한다(부분 삭제가 남지 않는다)."""
    user_id, cycle, request, db = _setup()
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60,
                      title="원제목", created_at=NOW)
    stale_planned = make_plan_block(
        user_id=user_id, plan_cycle_id=cycle.id, task_id=task.id, plan_date=CURRENT_DATE,
        period=plan_block_service.resolve_period(NOW), allocated_minutes=60,
        status=PlanBlockStatus.PLANNED, now=NOW,
    )
    item = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id,
        payload=make_task_update_payload(title="새제목", estimated_minutes=60, remaining_minutes=60),
        update_fields=["title"],
    )
    db.seed(task, stale_planned, item)

    def _raise(*args, **kwargs):
        raise RuntimeError("PlanBlock 배치 중 예상 못한 버그")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(plan_block_service, "schedule_plan_blocks", _raise)
        worker_module._execute_locked(db, request.id, DefaultExecutor())

    # rollback: 삭제 대상으로 지웠던 PlanBlock도 되돌아와 있어야 한다.
    assert stale_planned in db.all_rows(PlanBlock)
    assert task.title == "원제목"
    assert item.status == SolarItemStatus.READY
    _assert_failed_safely(request, db)


def test_active_cycle_execution_error_finalizes_as_failed_without_leaking_original_message(caplog):
    user_id, cycle, request, db = _setup()
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60, created_at=NOW)
    item = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id,
        payload=make_task_update_payload(estimated_minutes=60, remaining_minutes=60),
        update_fields=["notARealField"],
    )
    db.seed(task, item)

    with caplog.at_level(logging.WARNING, logger="app.services.active_cycle_execution_service"):
        worker_module._execute_locked(db, request.id, DefaultExecutor())

    _assert_failed_safely(request, db)
    assert "notARealField" not in request.error_message
    assert request.error_message == "실행 중 문제가 발생했어요. 다시 시도해 주세요."
    # 서버 로그에는 원인이 남아 있어야 한다.
    matching = [r for r in caplog.records if "notARealField" in r.getMessage()]
    assert matching, "재검증 실패 원인이 서버 로그에 남지 않았다"


def test_unclassified_runtime_error_finalizes_as_failed_and_preserves_cause():
    user_id, cycle, request, db = _setup()
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60, created_at=NOW)
    item = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id,
        payload=make_task_update_payload(title="새제목", estimated_minutes=60, remaining_minutes=60),
        update_fields=["title"],
    )
    db.seed(task, item)
    session = db()

    original_error = RuntimeError("예상 못한 버그 - 절대 노출되면 안 되는 문자열")

    def _raise(*args, **kwargs):
        raise original_error

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(svc, "_apply_task_update", _raise)
        with pytest.raises(worker_module.ExecutionDomainError) as exc_info:
            with session.begin():
                DefaultExecutor().execute(session, request)

    assert exc_info.value.code == "PLAN_EXECUTION_FAILED"
    assert exc_info.value.__cause__ is original_error
    assert "절대 노출되면 안 되는" not in exc_info.value.message


def test_duplicate_execution_when_already_completed_is_noop():
    user_id, cycle, request, db = _setup()
    request.status = SolarRequestStatus.COMPLETED
    request.execution_result = {"createdTaskCount": 0}

    worker_module._execute_locked(db, request.id, DefaultExecutor())

    # 이미 COMPLETED이므로 재실행 자체가 시도되지 않는다 — 상태와 결과가 그대로 유지된다.
    assert request.status == SolarRequestStatus.COMPLETED
    assert request.execution_result == {"createdTaskCount": 0}


def test_task_cancel_rollback_reverts_status():
    user_id, cycle, request, db = _setup()
    task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60, created_at=NOW)
    item1 = make_task_cancel_item(user_id=user_id, solar_request_id=request.id, item_order=1, target_task_id=task.id)
    other_task = make_task(user_id=user_id, plan_cycle_id=cycle.id, estimated_minutes=60, remaining_minutes=60, created_at=NOW)
    item2 = make_task_update_item(
        user_id=user_id, solar_request_id=request.id, item_order=2, target_task_id=other_task.id,
        payload=make_task_update_payload(estimated_minutes=60, remaining_minutes=60),
        update_fields=["notARealField"],
    )
    db.seed(task, other_task, item1, item2)

    worker_module._execute_locked(db, request.id, DefaultExecutor())

    assert task.status == TaskStatus.ACTIVE
    assert task.cancelled_at is None
    assert item1.status == SolarItemStatus.READY
    _assert_failed_safely(request, db)
