"""NEW_CYCLE 실행 rollback 검증.

의도적으로 파이프라인의 서로 다른 지점(Task 생성 이후, 고정 일정 생성 이후, PlanBlock 배치
도중, 상태 변경 도중, cycle 생성 도중)에서 예외를 주입해, 성공 트랜잭션 전체가 rollback되고
별도 트랜잭션에서 request만 FAILED로 기록되는지 실제 DB 관측 기준(FakeNewCycleDB에 남은 행)으로
검증한다.

BE-07 계약: NEW_CYCLE 실행 트랜잭션(_execute_locked가 이미 연 `with db.begin()` 블록) 안에서
발생하는 예외는 rollback이 정상적으로 끝났다면 분류 여부와 무관하게(IntegrityError 같은 예상
가능한 도메인 예외뿐 아니라 RuntimeError 같은 예상하지 못한 버그도) 별도 트랜잭션에서 request를
FAILED로 기록해야 한다. 그 경계는 "executor.execute() 호출이 시작됐는가"다 — 그 호출 자체가
시작되기 전(session 생성, requestId advisory lock 획득 등 _execute_locked/
run_worker_for_request 계층)의 인프라 실패는 이 파일이 다루는 범위가 아니며, 여전히 rollback만
되고 EXECUTING을 유지한다(기존 solar_execution_worker 계약, 이 Issue에서 변경하지 않음).
"""

import logging
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.enums import SolarItemStatus, SolarRequestStatus
from app.models.fixed_schedule import FixedSchedule
from app.models.plan_block import PlanBlock
from app.models.planning_cycle import PlanningCycle
from app.models.task import Task
from app.services import new_cycle_execution_service as svc
from app.services import plan_block_service
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
NOW = datetime(2026, 7, 29, 10, 0, tzinfo=SEOUL)


@pytest.fixture(autouse=True)
def _fixed_now(monkeypatch):
    monkeypatch.setattr(svc, "get_current_moment", lambda: NOW)


def _fake_integrity_error(message: str) -> IntegrityError:
    return IntegrityError("INSERT ...", {}, Exception(message))


def _assert_nothing_persisted(db: FakeNewCycleDB, *, task_item, fixed_schedule_item, request):
    assert db.all_rows(PlanningCycle) == []
    assert db.all_rows(Task) == []
    assert db.all_rows(FixedSchedule) == []
    assert db.all_rows(PlanBlock) == []

    assert task_item.status == SolarItemStatus.READY
    assert task_item.executed_at is None
    assert fixed_schedule_item.status == SolarItemStatus.READY
    assert fixed_schedule_item.executed_at is None

    assert request.status == SolarRequestStatus.FAILED
    assert request.error_code == "PLAN_EXECUTION_FAILED"
    assert request.error_message
    assert request.executed_at is None
    assert request.execution_result is None
    # 요청·카드 자체는 삭제되지 않고 retry 가능한 상태로 남는다.
    assert request in db.all_rows(type(request))
    assert task_item in db.all_rows(type(task_item))
    assert fixed_schedule_item in db.all_rows(type(fixed_schedule_item))


def _seoul_range(hour_start: int, hour_end: int) -> tuple[str, str]:
    start = datetime(2026, 7, 30, hour_start, 0, tzinfo=SEOUL)
    end = datetime(2026, 7, 30, hour_end, 0, tzinfo=SEOUL)
    return start.isoformat(), end.isoformat()


def test_rollback_when_failure_after_task_creation():
    """Task(order=1) 생성 이후, 고정 일정(order=2) 생성 도중 실패 — 이미 만든 Task까지 전부
    rollback돼야 한다."""
    user_id = uuid.uuid4()
    request = make_solar_request(user_id=user_id, now=NOW)
    task_item = make_task_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, payload=make_task_payload(title="task")
    )
    start_iso, end_iso = _seoul_range(20, 21)
    fixed_item = make_fixed_schedule_item(
        user_id=user_id,
        solar_request_id=request.id,
        item_order=2,
        payload=make_fixed_schedule_payload(start_at_iso=start_iso, end_at_iso=end_iso),
    )
    db = FakeNewCycleDB().seed(request, task_item, fixed_item)

    def _raise(*args, **kwargs):
        raise _fake_integrity_error("fixed schedule insert 실패")

    import app.services.new_cycle_execution_service as service_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(service_module, "_create_fixed_schedule_from_item", _raise)
        worker_module._execute_locked(db, request.id, DefaultExecutor())

    _assert_nothing_persisted(db, task_item=task_item, fixed_schedule_item=fixed_item, request=request)


def test_rollback_when_failure_after_fixed_schedule_creation():
    """고정 일정(order=1) 생성 이후, Task(order=2) 생성 도중 실패 — 이미 만든 고정 일정까지
    전부 rollback돼야 한다."""
    user_id = uuid.uuid4()
    request = make_solar_request(user_id=user_id, now=NOW)
    start_iso, end_iso = _seoul_range(20, 21)
    fixed_item = make_fixed_schedule_item(
        user_id=user_id,
        solar_request_id=request.id,
        item_order=1,
        payload=make_fixed_schedule_payload(start_at_iso=start_iso, end_at_iso=end_iso),
    )
    task_item = make_task_item(
        user_id=user_id, solar_request_id=request.id, item_order=2, payload=make_task_payload(title="task")
    )
    db = FakeNewCycleDB().seed(request, fixed_item, task_item)

    def _raise(*args, **kwargs):
        raise _fake_integrity_error("task insert 실패")

    import app.services.new_cycle_execution_service as service_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(service_module, "_create_task_from_item", _raise)
        worker_module._execute_locked(db, request.id, DefaultExecutor())

    _assert_nothing_persisted(db, task_item=task_item, fixed_schedule_item=fixed_item, request=request)


def test_rollback_when_failure_during_plan_block_scheduling():
    """모든 카드가 정상적으로 Task/고정 일정으로 변환된 뒤, 공통 PlanBlock 배치 서비스 호출
    도중 실패 — Task/고정 일정까지 전부 rollback돼야 한다."""
    user_id = uuid.uuid4()
    request = make_solar_request(user_id=user_id, now=NOW)
    task_item = make_task_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, payload=make_task_payload(title="task")
    )
    start_iso, end_iso = _seoul_range(20, 21)
    fixed_item = make_fixed_schedule_item(
        user_id=user_id,
        solar_request_id=request.id,
        item_order=2,
        payload=make_fixed_schedule_payload(start_at_iso=start_iso, end_at_iso=end_iso),
    )
    db = FakeNewCycleDB().seed(request, task_item, fixed_item)

    def _raise(*args, **kwargs):
        raise _fake_integrity_error("plan block insert 실패")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(plan_block_service, "schedule_plan_blocks", _raise)
        worker_module._execute_locked(db, request.id, DefaultExecutor())

    _assert_nothing_persisted(db, task_item=task_item, fixed_schedule_item=fixed_item, request=request)


def test_rollback_when_failure_during_status_transition():
    """PlanBlock 배치까지 전부 끝난 뒤, request/카드를 COMPLETED·EXECUTED로 바꾸는 마지막
    단계(execution_result 구성)에서 실패 — cycle·Task·고정 일정·PlanBlock까지 전부
    rollback돼야 한다."""
    user_id = uuid.uuid4()
    request = make_solar_request(user_id=user_id, now=NOW)
    task_item = make_task_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, payload=make_task_payload(title="task")
    )
    start_iso, end_iso = _seoul_range(20, 21)
    fixed_item = make_fixed_schedule_item(
        user_id=user_id,
        solar_request_id=request.id,
        item_order=2,
        payload=make_fixed_schedule_payload(start_at_iso=start_iso, end_at_iso=end_iso),
    )
    db = FakeNewCycleDB().seed(request, task_item, fixed_item)

    def _raise(*args, **kwargs):
        raise _fake_integrity_error("request 상태 갱신 실패")

    import app.services.new_cycle_execution_service as service_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(service_module, "_build_execution_result", _raise)
        worker_module._execute_locked(db, request.id, DefaultExecutor())

    _assert_nothing_persisted(db, task_item=task_item, fixed_schedule_item=fixed_item, request=request)


def test_rollback_when_plan_block_scheduling_raises_unclassified_runtime_error():
    """PlanBlock 배치 서비스에서 분류되지 않은 RuntimeError가 발생해도(예상 가능한
    NewCycleExecutionError/IntegrityError가 아니어도) 실행 트랜잭션 안에서 발생한 예외이므로
    rollback 후 별도 트랜잭션에서 FAILED로 기록돼야 한다(BE-07 요구사항 1번 항목)."""
    user_id = uuid.uuid4()
    request = make_solar_request(user_id=user_id, now=NOW)
    task_item = make_task_item(
        user_id=user_id, solar_request_id=request.id, item_order=1, payload=make_task_payload(title="task")
    )
    start_iso, end_iso = _seoul_range(20, 21)
    fixed_item = make_fixed_schedule_item(
        user_id=user_id,
        solar_request_id=request.id,
        item_order=2,
        payload=make_fixed_schedule_payload(start_at_iso=start_iso, end_at_iso=end_iso),
    )
    db = FakeNewCycleDB().seed(request, task_item, fixed_item)

    def _raise(*args, **kwargs):
        raise RuntimeError("PlanBlock 배치 중 예상 못한 버그")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(plan_block_service, "schedule_plan_blocks", _raise)
        worker_module._execute_locked(db, request.id, DefaultExecutor())

    # rollback: cycle/Task/고정 일정/PlanBlock 전무.
    assert db.all_rows(PlanningCycle) == []
    assert db.all_rows(Task) == []
    assert db.all_rows(FixedSchedule) == []
    assert db.all_rows(PlanBlock) == []

    # 카드는 retry 가능한 READY로 유지, 삭제되지 않음.
    assert task_item.status == SolarItemStatus.READY
    assert task_item.executed_at is None
    assert fixed_item.status == SolarItemStatus.READY
    assert fixed_item.executed_at is None
    assert task_item in db.all_rows(type(task_item))
    assert fixed_item in db.all_rows(type(fixed_item))

    # 별도 트랜잭션에서 요청이 FAILED로 기록되고, retry가 허용되는 기존 정책(error_code와
    # 무관하게 FAILED는 항상 retryable)을 그대로 따른다.
    assert request.status == SolarRequestStatus.FAILED
    assert request.error_code == "PLAN_EXECUTION_FAILED"
    assert request.error_message
    assert request.executed_at is None
    assert request.execution_result is None
    assert request in db.all_rows(type(request))


def test_unclassified_exception_logs_and_preserves_original_runtime_error_as_cause(caplog):
    """로그 또는 예외 체인에 원래 RuntimeError가 보존되는지 확인한다. DefaultExecutor가
    ExecutionDomainError로 변환하기 직전에 logger.exception으로 traceback을 남기고,
    ExecutionDomainError.__cause__가 원래 RuntimeError 인스턴스를 그대로 가리켜야 한다."""
    user_id = uuid.uuid4()
    request = make_solar_request(user_id=user_id, now=NOW)
    task_item = make_task_item(user_id=user_id, solar_request_id=request.id, item_order=1, payload=make_task_payload())
    db = FakeNewCycleDB().seed(request, task_item)

    import app.services.new_cycle_execution_service as service_module

    original_error = RuntimeError("PlanBlock 배치 중 예상 못한 버그")

    def _raise(*args, **kwargs):
        raise original_error

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(service_module, "_create_task_from_item", _raise)
        with caplog.at_level(logging.ERROR, logger="app.workers.solar_execution_worker"):
            worker_module._execute_locked(db, request.id, DefaultExecutor())

    assert request.status == SolarRequestStatus.FAILED
    assert request.error_code == "PLAN_EXECUTION_FAILED"
    # 사용자 응답으로 나가는 error_message에는 원본 예외 텍스트를 노출하지 않는다.
    assert "예상 못한 버그" not in request.error_message

    # 서버 로그에는 traceback(원래 예외)이 남는다.
    matching_records = [r for r in caplog.records if "NEW_CYCLE" in r.message]
    assert matching_records, "분류되지 않은 예외에 대한 logger.exception 기록이 없다"
    assert matching_records[0].exc_info is not None
    logged_exc = matching_records[0].exc_info[1]
    assert logged_exc is original_error


def test_default_executor_preserves_runtime_error_as_exception_cause():
    """DefaultExecutor.execute()가 던지는 ExecutionDomainError의 __cause__가 원래 RuntimeError
    인스턴스를 그대로 가리키는지 exception 체인 수준에서 직접 확인한다."""
    user_id = uuid.uuid4()
    request = make_solar_request(user_id=user_id, now=NOW)
    task_item = make_task_item(user_id=user_id, solar_request_id=request.id, item_order=1, payload=make_task_payload())
    db = FakeNewCycleDB().seed(request, task_item)
    session = db()

    import app.services.new_cycle_execution_service as service_module

    original_error = RuntimeError("예상 못한 버그")

    def _raise(*args, **kwargs):
        raise original_error

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(service_module, "_create_task_from_item", _raise)
        with pytest.raises(worker_module.ExecutionDomainError) as exc_info:
            with session.begin():
                DefaultExecutor().execute(session, request)

    assert exc_info.value.code == "PLAN_EXECUTION_FAILED"
    assert exc_info.value.__cause__ is original_error


def test_rollback_when_active_cycle_unique_index_violation_during_cycle_creation():
    """advisory lock으로도 못 막은 잔여 경쟁이 실제 cycle INSERT 시점에
    uq_planning_cycles_one_active_per_user partial UNIQUE index 위반(IntegrityError)으로
    나타나는 경우도 동일하게 rollback + 별도 트랜잭션 FAILED로 이어져야 한다."""
    user_id = uuid.uuid4()
    request = make_solar_request(user_id=user_id, now=NOW)
    task_item = make_task_item(user_id=user_id, solar_request_id=request.id, item_order=1, payload=make_task_payload())
    db = FakeNewCycleDB().seed(request, task_item)

    import app.services.new_cycle_execution_service as service_module

    def _raise(*args, **kwargs):
        raise _fake_integrity_error("uq_planning_cycles_one_active_per_user violation")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(service_module, "_create_planning_cycle", _raise)
        worker_module._execute_locked(db, request.id, DefaultExecutor())

    assert db.all_rows(PlanningCycle) == []
    assert db.all_rows(Task) == []
    assert task_item.status == SolarItemStatus.READY
    assert task_item.executed_at is None
    assert request.status == SolarRequestStatus.FAILED
    assert request.error_code == "PLAN_EXECUTION_FAILED"
    assert request.executed_at is None
    assert request.execution_result is None


def test_infra_failure_before_executor_invoked_still_leaves_executing():
    """executor.execute() 호출 자체가 시작되기 전(예: _execute_locked의 재조회 select 단계)의
    인프라 실패는 이 Issue의 FAILED 확대 대상이 아니다 — 여전히 EXECUTING을 유지한다(기존
    solar_execution_worker 계약, 변경하지 않음). request 재조회 자체가 실패하는 상황을
    FakeNewCycleSession.execute를 일시적으로 깨서 재현한다."""
    user_id = uuid.uuid4()
    request = make_solar_request(user_id=user_id, now=NOW)
    task_item = make_task_item(user_id=user_id, solar_request_id=request.id, item_order=1, payload=make_task_payload())
    db = FakeNewCycleDB().seed(request, task_item)

    class _BrokenSession:
        def __init__(self, inner):
            self._inner = inner

        def begin(self):
            return self._inner.begin()

        def execute(self, stmt, params=None):
            raise ConnectionError("DB 연결 끊김(인프라 장애)")

        def close(self):
            self._inner.close()

    def _broken_factory():
        return _BrokenSession(db())

    worker_module._execute_locked(_broken_factory, request.id, DefaultExecutor())

    assert request.status == SolarRequestStatus.EXECUTING
    assert request.error_code is None
    assert db.all_rows(PlanningCycle) == []
