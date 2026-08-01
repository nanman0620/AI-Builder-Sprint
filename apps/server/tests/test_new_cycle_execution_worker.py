import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models.enums import (
    AmountSource,
    EstimateSource,
    PlanCycleStatus,
    SolarItemStatus,
    SolarRequestPurpose,
    SolarRequestStatus,
    TaskStatus,
)
from app.models.fixed_schedule import FixedSchedule
from app.models.plan_block import PlanBlock
from app.models.planning_cycle import PlanningCycle
from app.models.task import Task
from app.services import new_cycle_execution_service as svc
from app.workers import solar_execution_worker as worker_module
from app.workers.solar_execution_worker import DefaultExecutor
from tests.support_new_cycle_execution import (
    FakeNewCycleDB,
    make_fixed_schedule_item,
    make_fixed_schedule_payload,
    make_solar_request,
    make_task_item,
    make_task_payload,
)

SEOUL = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 7, 29, 10, 0, tzinfo=SEOUL)  # MORNING(04-12시), plan_date=2026-07-29


@pytest.fixture(autouse=True)
def _fixed_now(monkeypatch):
    """execute_new_cycle은 내부에서 get_current_moment()를 직접 호출한다(Executor.execute
    시그니처가 now를 받지 않으므로) — 테스트 결정성을 위해 고정한다."""
    monkeypatch.setattr(svc, "get_current_moment", lambda: NOW)


def _setup(*, items=()):
    user_id = uuid.uuid4()
    request = make_solar_request(user_id=user_id, now=NOW)
    db = FakeNewCycleDB().seed(request, *items)
    session = db()
    return user_id, request, db, session


# ---------------------------------------------------------------------------
# cycle 생성
# ---------------------------------------------------------------------------


def test_creates_exactly_seven_day_cycle():
    user_id, request, db, session = _setup()

    with session.begin():
        svc.execute_new_cycle(session, request)

    cycles = db.all_rows(PlanningCycle)
    assert len(cycles) == 1
    cycle = cycles[0]
    assert cycle.user_id == user_id
    assert cycle.start_date == date(2026, 7, 29)
    assert cycle.end_date == date(2026, 8, 4)
    assert (cycle.end_date - cycle.start_date).days == 6
    assert cycle.status == PlanCycleStatus.ACTIVE
    assert cycle.activated_at == NOW
    assert cycle.ended_at is None


# ---------------------------------------------------------------------------
# Task 생성
# ---------------------------------------------------------------------------


def test_creates_task_from_ready_task_card():
    user_id, request, db, session = _setup()
    payload = make_task_payload(title="보고서 작성", estimated_minutes=90, estimated_minutes_source="USER")
    item = make_task_item(user_id=user_id, solar_request_id=request.id, item_order=1, payload=payload)
    db.seed(item)

    with session.begin():
        svc.execute_new_cycle(session, request)

    tasks = db.all_rows(Task)
    assert len(tasks) == 1
    task = tasks[0]
    assert task.title == "보고서 작성"
    assert task.source_request_item_id == item.id
    assert task.user_id == user_id
    assert task.plan_cycle_id == db.all_rows(PlanningCycle)[0].id
    assert task.status == TaskStatus.ACTIVE
    assert task.completed_at is None
    assert task.cancelled_at is None


def test_task_time_invariants_initial_equals_estimated_equals_remaining():
    user_id, request, db, session = _setup()
    payload = make_task_payload(estimated_minutes=45)
    item = make_task_item(user_id=user_id, solar_request_id=request.id, item_order=1, payload=payload)
    db.seed(item)

    with session.begin():
        svc.execute_new_cycle(session, request)

    task = db.all_rows(Task)[0]
    assert task.initial_minutes == 45
    assert task.estimated_minutes == 45
    assert task.remaining_minutes == 45


def test_estimated_minutes_source_and_amount_source_preserved():
    user_id, request, db, session = _setup()
    payload = make_task_payload(
        estimated_minutes=30,
        estimated_minutes_source="AI_ESTIMATED",
        amount_text="10페이지",
        amount_source="USER",
    )
    item = make_task_item(user_id=user_id, solar_request_id=request.id, item_order=1, payload=payload)
    db.seed(item)

    with session.begin():
        svc.execute_new_cycle(session, request)

    task = db.all_rows(Task)[0]
    assert task.estimated_minutes_source == EstimateSource.AI_ESTIMATED
    assert task.amount_text == "10페이지"
    assert task.amount_source == AmountSource.USER


def test_amount_unknown_when_card_amount_missing():
    user_id, request, db, session = _setup()
    payload = make_task_payload(amount_text=None, amount_source=None)
    item = make_task_item(user_id=user_id, solar_request_id=request.id, item_order=1, payload=payload)
    db.seed(item)

    with session.begin():
        svc.execute_new_cycle(session, request)

    task = db.all_rows(Task)[0]
    assert task.amount_source == AmountSource.UNKNOWN
    assert task.amount_text is None


def test_task_deadline_at_parsed_when_present_and_none_when_absent():
    user_id, request, db, session = _setup()
    deadline = datetime(2026, 8, 15, 18, 0, tzinfo=SEOUL)
    payload = make_task_payload(deadline_at_iso=deadline.isoformat())
    item = make_task_item(user_id=user_id, solar_request_id=request.id, item_order=1, payload=payload)
    payload_no_deadline = make_task_payload(deadline_at_iso=None, title="마감 모름")
    item2 = make_task_item(user_id=user_id, solar_request_id=request.id, item_order=2, payload=payload_no_deadline)
    db.seed(item, item2)

    with session.begin():
        svc.execute_new_cycle(session, request)

    tasks = {task.title: task for task in db.all_rows(Task)}
    assert tasks[payload["title"]].deadline_at == deadline
    assert tasks["마감 모름"].deadline_at is None


# ---------------------------------------------------------------------------
# 고정 일정 생성
# ---------------------------------------------------------------------------


def test_creates_fixed_schedule_from_ready_card():
    user_id, request, db, session = _setup()
    start = datetime(2026, 7, 29, 20, 0, tzinfo=SEOUL)
    end = datetime(2026, 7, 29, 21, 0, tzinfo=SEOUL)
    payload = make_fixed_schedule_payload(title="운동", start_at_iso=start.isoformat(), end_at_iso=end.isoformat())
    item = make_fixed_schedule_item(user_id=user_id, solar_request_id=request.id, item_order=1, payload=payload)
    db.seed(item)

    with session.begin():
        svc.execute_new_cycle(session, request)

    schedules = db.all_rows(FixedSchedule)
    assert len(schedules) == 1
    fs = schedules[0]
    assert fs.title == "운동"
    assert fs.source_request_item_id == item.id
    assert fs.user_id == user_id
    assert fs.plan_cycle_id == db.all_rows(PlanningCycle)[0].id
    assert fs.start_at == start
    assert fs.end_at == end


# ---------------------------------------------------------------------------
# source_request_item_id 1:1 연결
# ---------------------------------------------------------------------------


def test_source_request_item_id_is_one_to_one():
    user_id, request, db, session = _setup()
    task_item = make_task_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, payload=make_task_payload(title="task-a")
    )
    task_item_2 = make_task_item(
        user_id=user_id, solar_request_id=request.id, item_order=2, payload=make_task_payload(title="task-b")
    )
    start = datetime(2026, 7, 30, 9, 0, tzinfo=SEOUL)
    end = datetime(2026, 7, 30, 10, 0, tzinfo=SEOUL)
    fs_item = make_fixed_schedule_item(
        user_id=user_id,
        solar_request_id=request.id,
        item_order=3,
        payload=make_fixed_schedule_payload(start_at_iso=start.isoformat(), end_at_iso=end.isoformat()),
    )
    db.seed(task_item, task_item_2, fs_item)

    with session.begin():
        svc.execute_new_cycle(session, request)

    linked_ids = [task.source_request_item_id for task in db.all_rows(Task)]
    linked_ids += [fs.source_request_item_id for fs in db.all_rows(FixedSchedule)]

    assert sorted(linked_ids, key=str) == sorted([task_item.id, task_item_2.id, fs_item.id], key=str)
    assert len(set(linked_ids)) == len(linked_ids)


# ---------------------------------------------------------------------------
# 카드 EXECUTED, 요청 COMPLETED
# ---------------------------------------------------------------------------


def test_cards_marked_executed_and_request_completed():
    user_id, request, db, session = _setup()
    item = make_task_item(user_id=user_id, solar_request_id=request.id, item_order=1, payload=make_task_payload())
    db.seed(item)

    with session.begin():
        svc.execute_new_cycle(session, request)

    assert item.status == SolarItemStatus.EXECUTED
    assert item.executed_at == NOW
    assert request.status == SolarRequestStatus.COMPLETED
    assert request.executed_at == NOW


def test_non_ready_card_mixed_in_fails_entire_execution_without_partial_creation():
    """READY가 아닌 카드가 하나라도 섞여 있으면(예: INFO_MISSING) 나머지 READY 카드까지 포함해
    아무 것도 만들지 않고 실행 전체가 실패해야 한다 — 일부 카드만 생성하고 요청을 COMPLETED로
    만드는 부분 성공 경로를 만들지 않는다."""
    user_id, request, db, session = _setup()
    ready_item = make_task_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, payload=make_task_payload(title="ready")
    )
    missing_item = make_task_item(
        user_id=user_id,
        solar_request_id=request.id,
        item_order=2,
        payload=make_task_payload(title="missing"),
        status=SolarItemStatus.INFO_MISSING,
        missing_fields=["deadlineAt"],
    )
    db.seed(ready_item, missing_item)

    with pytest.raises(RuntimeError):
        with session.begin():
            svc.execute_new_cycle(session, request)

    assert db.all_rows(PlanningCycle) == []
    assert db.all_rows(Task) == []
    assert db.all_rows(FixedSchedule) == []
    assert db.all_rows(PlanBlock) == []
    assert request.status != SolarRequestStatus.COMPLETED

    # 기존 카드 데이터는 그대로 보존된다(삭제·상태 변경 없음).
    assert ready_item in db.all_rows(type(ready_item))
    assert ready_item.status == SolarItemStatus.READY
    assert ready_item.executed_at is None
    assert missing_item in db.all_rows(type(missing_item))
    assert missing_item.status == SolarItemStatus.INFO_MISSING
    assert missing_item.executed_at is None


def test_unsupported_card_entity_type_fails_entire_execution_without_partial_creation():
    """SolarEntityType이 TASK/FIXED_SCHEDULE 외의 값을 갖는(현재 enum상 정상 경로로는 불가능한,
    데이터 손상·향후 enum 확장을 가정한) 카드가 섞여 있으면 조용히 무시하지 않고 실행 전체가
    실패해야 한다."""
    user_id, request, db, session = _setup()
    ready_item = make_task_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, payload=make_task_payload(title="ready")
    )
    unsupported_item = make_task_item(
        user_id=user_id, solar_request_id=request.id, item_order=2, payload=make_task_payload(title="unsupported")
    )
    unsupported_item.entity_type = "UNSUPPORTED_TYPE"  # 실제 enum에는 없는 값을 강제로 주입
    db.seed(ready_item, unsupported_item)

    with pytest.raises(RuntimeError):
        with session.begin():
            svc.execute_new_cycle(session, request)

    assert db.all_rows(PlanningCycle) == []
    assert db.all_rows(Task) == []
    assert request.status != SolarRequestStatus.COMPLETED
    assert ready_item in db.all_rows(type(ready_item))
    assert ready_item.status == SolarItemStatus.READY


# ---------------------------------------------------------------------------
# execution_result 통계
# ---------------------------------------------------------------------------


def test_execution_result_exact_key_set_matches_api_spec_8_2():
    """API 명세 8-2절 NEW_CYCLE COMPLETED 응답 예시의 8개 key와 정확히 일치해야 한다 —
    subset이 아니라 exact key set을 검증한다. GET /execution의 executionResult는 이
    dict를 필터링 없이 그대로 직렬화하므로, 여기 없는 key는 곧 실제 API 응답에 노출된다."""
    user_id, request, db, session = _setup()
    item = make_task_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, payload=make_task_payload(estimated_minutes=60)
    )
    db.seed(item)

    with session.begin():
        svc.execute_new_cycle(session, request)

    result = request.execution_result
    assert set(result.keys()) == {
        "createdTaskCount",
        "updatedTaskCount",
        "cancelledTaskCount",
        "createdFixedScheduleCount",
        "updatedFixedScheduleCount",
        "deletedFixedScheduleCount",
        "taskCount",
        "fixedScheduleCount",
    }
    assert result["createdTaskCount"] == 1
    assert result["updatedTaskCount"] == 0
    assert result["cancelledTaskCount"] == 0
    assert result["createdFixedScheduleCount"] == 0
    assert result["updatedFixedScheduleCount"] == 0
    assert result["deletedFixedScheduleCount"] == 0
    assert result["taskCount"] == 1
    assert result["fixedScheduleCount"] == 0


def test_execution_result_counts_match_mixed_task_and_fixed_schedule_creation():
    user_id, request, db, session = _setup()
    task_item = make_task_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, payload=make_task_payload(title="task")
    )
    start = datetime(2026, 7, 30, 9, 0, tzinfo=SEOUL)
    end = datetime(2026, 7, 30, 10, 0, tzinfo=SEOUL)
    fs_item = make_fixed_schedule_item(
        user_id=user_id,
        solar_request_id=request.id,
        item_order=2,
        payload=make_fixed_schedule_payload(start_at_iso=start.isoformat(), end_at_iso=end.isoformat()),
    )
    db.seed(task_item, fs_item)

    with session.begin():
        svc.execute_new_cycle(session, request)

    result = request.execution_result
    assert result["createdTaskCount"] == 1
    assert result["createdFixedScheduleCount"] == 1
    assert result["taskCount"] == 1
    assert result["fixedScheduleCount"] == 1


def test_succeeds_even_with_unplaced_minutes():
    user_id, request, db, session = _setup()
    # 7일 * 3분기 * 240분 = 5040분보다 훨씬 큰 필요 시간 -> 반드시 미배치가 남지만 실행은 성공해야 한다.
    requested_minutes = 100_000
    item = make_task_item(
        user_id=user_id,
        solar_request_id=request.id,
        item_order=1,
        payload=make_task_payload(estimated_minutes=requested_minutes),
    )
    db.seed(item)

    with session.begin():
        svc.execute_new_cycle(session, request)  # 예외 없이 성공

    assert request.status == SolarRequestStatus.COMPLETED
    # 미배치 시간은 API 계약(execution_result 8개 key)에 없으므로 응답에 노출하지 않는다 —
    # 대신 실제 배치된 PlanBlock 합계가 요청한 시간보다 훨씬 작다는 사실로 미배치가 실제로
    # 발생했음을 내부 상태(DB) 기준으로 확인한다.
    allocated_total = sum(block.allocated_minutes for block in db.all_rows(PlanBlock))
    assert 0 < allocated_total < requested_minutes
    assert set(request.execution_result.keys()) == {
        "createdTaskCount",
        "updatedTaskCount",
        "cancelledTaskCount",
        "createdFixedScheduleCount",
        "updatedFixedScheduleCount",
        "deletedFixedScheduleCount",
        "taskCount",
        "fixedScheduleCount",
    }


# ---------------------------------------------------------------------------
# 공통 PlanBlock 배치 서비스 호출
# ---------------------------------------------------------------------------


def test_uses_common_plan_block_scheduling_service(monkeypatch):
    user_id, request, db, session = _setup()
    item = make_task_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, payload=make_task_payload(estimated_minutes=60)
    )
    db.seed(item)

    from app.services import plan_block_service

    calls = []
    original = plan_block_service.schedule_plan_blocks

    def _spy(db_arg, *, user_id, plan_cycle_id, now):
        calls.append((user_id, plan_cycle_id, now))
        return original(db_arg, user_id=user_id, plan_cycle_id=plan_cycle_id, now=now)

    monkeypatch.setattr(svc.plan_block_service, "schedule_plan_blocks", _spy)

    with session.begin():
        svc.execute_new_cycle(session, request)

    cycle = db.all_rows(PlanningCycle)[0]
    assert calls == [(user_id, cycle.id, NOW)]
    blocks = db.all_rows(PlanBlock)
    assert len(blocks) == 1
    assert blocks[0].allocated_minutes == 60
    assert blocks[0].task_id == db.all_rows(Task)[0].id
    assert blocks[0].plan_cycle_id == cycle.id


def test_single_block_display_title_uses_task_amount_text_when_fully_placed():
    """NEW_CYCLE도 ACTIVE_CYCLE과 동일한 공용 schedule_plan_blocks()를 쓰므로, Task가
    신규 블록 1개로 남김없이 배치되면 같은 제한적 MVP fallback이 적용된다."""
    user_id, request, db, session = _setup()
    payload = make_task_payload(
        title="자료구조 과제", estimated_minutes=60, amount_text="2문제", amount_source="USER",
    )
    item = make_task_item(user_id=user_id, solar_request_id=request.id, item_order=1, payload=payload)
    db.seed(item)

    with session.begin():
        svc.execute_new_cycle(session, request)

    blocks = db.all_rows(PlanBlock)
    assert len(blocks) == 1
    assert blocks[0].allocated_amount_text == "2문제"
    assert blocks[0].display_title == "자료구조 과제 2문제"


# ---------------------------------------------------------------------------
# 실행 직전/직후 동시성 재확인
# ---------------------------------------------------------------------------


def test_active_cycle_detected_after_lock_raises_domain_error_without_writes():
    """실행 직전 사전검증(_validate_execution_preconditions)은 통과했지만, lock 획득 직후 최종
    재조회 시점에 이미 ACTIVE cycle이 있는 경우(다른 실행이 먼저 커밋한 경우) — 아무 것도 만들지
    않고 도메인 실패로 끝나야 한다."""
    user_id, request, db, session = _setup()
    existing_cycle = PlanningCycle(
        id=uuid.uuid4(),
        user_id=user_id,
        start_date=NOW.date(),
        end_date=NOW.date() + timedelta(days=6),
        status=PlanCycleStatus.ACTIVE,
        activated_at=NOW,
        ended_at=None,
    )
    db.seed(existing_cycle)

    with pytest.raises(svc.NewCycleExecutionError) as exc_info:
        with session.begin():
            svc.execute_new_cycle(session, request)

    assert exc_info.value.code == "PLAN_EXECUTION_FAILED"
    assert db.all_rows(PlanningCycle) == [existing_cycle]
    assert db.all_rows(Task) == []


def test_acquires_user_scoped_advisory_lock_before_active_cycle_check():
    user_id, request, db, session = _setup()

    with session.begin():
        svc.execute_new_cycle(session, request)

    assert db.advisory_lock_keys == [svc.advisory_lock_key_for_user(user_id)]

    lock_indices = [i for i, op in enumerate(db.operations) if op[0] == "lock"]
    cycle_select_indices = [
        i for i, op in enumerate(db.operations) if op[0] == "select" and op[1] is PlanningCycle
    ]
    assert lock_indices, "advisory lock SQL이 한 번도 실행되지 않았다"
    assert cycle_select_indices, "ACTIVE cycle 재조회가 한 번도 실행되지 않았다"
    assert lock_indices[0] < cycle_select_indices[0]


def test_same_user_two_requests_use_the_same_lock_key():
    user_id = uuid.uuid4()
    request_a = make_solar_request(user_id=user_id, now=NOW)
    request_b = make_solar_request(user_id=user_id, now=NOW)
    item_a = make_task_item(
        user_id=user_id, solar_request_id=request_a.id, item_order=1, payload=make_task_payload(title="a")
    )
    item_b = make_task_item(
        user_id=user_id, solar_request_id=request_b.id, item_order=1, payload=make_task_payload(title="b")
    )
    db = FakeNewCycleDB().seed(request_a, request_b, item_a, item_b)

    worker_module._execute_locked(db, request_a.id, DefaultExecutor())
    worker_module._execute_locked(db, request_b.id, DefaultExecutor())

    assert len(db.advisory_lock_keys) == 2
    assert db.advisory_lock_keys[0] == db.advisory_lock_keys[1] == svc.advisory_lock_key_for_user(user_id)


def test_different_users_use_different_lock_keys():
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    request_a = make_solar_request(user_id=user_a, now=NOW)
    request_b = make_solar_request(user_id=user_b, now=NOW)
    item_a = make_task_item(
        user_id=user_a, solar_request_id=request_a.id, item_order=1, payload=make_task_payload(title="a")
    )
    item_b = make_task_item(
        user_id=user_b, solar_request_id=request_b.id, item_order=1, payload=make_task_payload(title="b")
    )
    db = FakeNewCycleDB().seed(request_a, request_b, item_a, item_b)

    worker_module._execute_locked(db, request_a.id, DefaultExecutor())
    worker_module._execute_locked(db, request_b.id, DefaultExecutor())

    assert len(db.advisory_lock_keys) == 2
    assert db.advisory_lock_keys[0] != db.advisory_lock_keys[1]
    assert db.advisory_lock_keys[0] == svc.advisory_lock_key_for_user(user_a)
    assert db.advisory_lock_keys[1] == svc.advisory_lock_key_for_user(user_b)

    # 서로 다른 사용자이므로 둘 다 성공하고, 각자 자기 cycle을 가진다.
    assert request_a.status == SolarRequestStatus.COMPLETED
    assert request_b.status == SolarRequestStatus.COMPLETED
    assert len(db.all_rows(PlanningCycle)) == 2


def test_wrong_purpose_raises_domain_error_without_writes():
    user_id, request, db, session = _setup()
    request.purpose = SolarRequestPurpose.ACTIVE_CYCLE

    with pytest.raises(svc.NewCycleExecutionError) as exc_info:
        with session.begin():
            svc.execute_new_cycle(session, request)

    assert exc_info.value.code == "PLAN_EXECUTION_FAILED"
    assert db.all_rows(PlanningCycle) == []


# ---------------------------------------------------------------------------
# DefaultExecutor(Worker adapter) 통합 — purpose 분기와 예외 변환
# ---------------------------------------------------------------------------


def test_default_executor_delegates_new_cycle_purpose_to_service():
    user_id, request, db, session = _setup()
    item = make_task_item(user_id=user_id, solar_request_id=request.id, item_order=1, payload=make_task_payload())
    db.seed(item)

    with session.begin():
        DefaultExecutor().execute(session, request)

    assert request.status == SolarRequestStatus.COMPLETED
    assert len(db.all_rows(Task)) == 1


def test_default_executor_wraps_new_cycle_domain_error_as_execution_domain_error():
    user_id, request, db, session = _setup()
    request.purpose = SolarRequestPurpose.ACTIVE_CYCLE  # NEW_CYCLE이 아니므로 도메인 실패

    with pytest.raises(worker_module.ExecutionDomainError) as exc_info:
        with session.begin():
            DefaultExecutor().execute(session, request)

    assert exc_info.value.code == "PLAN_EXECUTION_FAILED"


def test_default_executor_active_cycle_purpose_fails_safely_when_cycle_missing():
    """ACTIVE_CYCLE은 BE-08부터 active_cycle_execution_service.execute_active_cycle에
    연결된다(더 이상 NotConfiguredExecutor와 동일하게 처리되지 않는다). 이 테스트는 그
    실제 서비스 로직(test_active_cycle_execution_worker.py에서 상세히 검증)까지 들어가지
    않고, DefaultExecutor의 dispatch·예외 변환 구조만 확인한다 — 존재하지 않는
    plan_cycle_id를 가리키는 요청은 항상 안전한 PLAN_EXECUTION_FAILED로 귀결되어야 한다
    (가짜 COMPLETED 금지)."""
    user_id, request, db, session = _setup()
    request.purpose = SolarRequestPurpose.ACTIVE_CYCLE
    request.plan_cycle_id = uuid.uuid4()

    with pytest.raises(worker_module.ExecutionDomainError) as exc_info:
        with session.begin():
            DefaultExecutor().execute(session, request)

    assert exc_info.value.code == "PLAN_EXECUTION_FAILED"


# ---------------------------------------------------------------------------
# 전체 Worker 파이프라인(_execute_locked) 통합 — 멱등성/중복 실행
# ---------------------------------------------------------------------------


def test_execute_locked_full_pipeline_completes_request_and_creates_cycle():
    user_id, request, db, session = _setup()
    item = make_task_item(user_id=user_id, solar_request_id=request.id, item_order=1, payload=make_task_payload())
    db.seed(item)

    worker_module._execute_locked(db, request.id, DefaultExecutor())

    assert request.status == SolarRequestStatus.COMPLETED
    assert len(db.all_rows(PlanningCycle)) == 1
    assert len(db.all_rows(Task)) == 1


def test_execute_locked_is_noop_when_request_already_completed():
    """이미 COMPLETED인 요청이 재전달돼도(성공 직후 재시도 등) 중복 cycle을 만들지 않는다."""
    user_id, request, db, session = _setup()
    item = make_task_item(user_id=user_id, solar_request_id=request.id, item_order=1, payload=make_task_payload())
    db.seed(item)

    worker_module._execute_locked(db, request.id, DefaultExecutor())
    assert request.status == SolarRequestStatus.COMPLETED
    first_cycle_id = db.all_rows(PlanningCycle)[0].id

    # 같은 request가 다시 Worker에 등록된 상황(성공 직후 재전달, 순차 중복 실행)을 재현한다.
    worker_module._execute_locked(db, request.id, DefaultExecutor())

    cycles = db.all_rows(PlanningCycle)
    assert len(cycles) == 1
    assert cycles[0].id == first_cycle_id
    assert len(db.all_rows(Task)) == 1


def test_two_different_new_cycle_requests_same_user_only_one_cycle_survives():
    """서로 다른 NEW_CYCLE request 두 개가 같은 사용자에 대해 (순차적으로, lock으로 직렬화된 것과
    동등하게) 실행돼도 ACTIVE cycle은 하나만 남고, 진 쪽은 카드를 그대로 보존한 채 FAILED로
    끝나야 한다."""
    user_id = uuid.uuid4()
    request_a = make_solar_request(user_id=user_id, now=NOW)
    request_b = make_solar_request(user_id=user_id, now=NOW)
    item_a = make_task_item(
        user_id=user_id, solar_request_id=request_a.id, item_order=1, payload=make_task_payload(title="a")
    )
    item_b = make_task_item(
        user_id=user_id, solar_request_id=request_b.id, item_order=1, payload=make_task_payload(title="b")
    )
    db = FakeNewCycleDB().seed(request_a, request_b, item_a, item_b)

    worker_module._execute_locked(db, request_a.id, DefaultExecutor())
    worker_module._execute_locked(db, request_b.id, DefaultExecutor())

    assert request_a.status == SolarRequestStatus.COMPLETED
    assert request_b.status == SolarRequestStatus.FAILED
    assert request_b.error_code == "PLAN_EXECUTION_FAILED"

    cycles = db.all_rows(PlanningCycle)
    assert len(cycles) == 1
    assert cycles[0].user_id == user_id

    # 진 쪽(request_b) 카드는 삭제되거나 EXECUTED로 바뀌지 않고 retry 가능한 READY로 남는다.
    assert item_b.status == SolarItemStatus.READY
    assert item_b.executed_at is None
    tasks_from_b = [t for t in db.all_rows(Task) if t.source_request_item_id == item_b.id]
    assert tasks_from_b == []
