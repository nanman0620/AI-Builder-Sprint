import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.sql.dml import Update

from app.core.errors import ApiError
from app.models.enums import SolarRequestPurpose, SolarRequestStatus
from app.models.solar_request import SolarRequest
from app.services import solar_request_service
from app.workers import solar_execution_worker as worker_module
from app.workers.solar_execution_worker import (
    ExecutionDomainError,
    NotConfiguredExecutor,
    SolarExecutionDispatcher,
    advisory_lock_key,
    run_worker_for_request,
)

USER_ID = uuid.uuid4()
REQUEST_ID = uuid.uuid4()
NOW = datetime(2026, 7, 30, 14, 0, tzinfo=timezone.utc)


def _make_request(**overrides):
    defaults = dict(
        id=REQUEST_ID,
        user_id=USER_ID,
        plan_cycle_id=None,
        purpose=SolarRequestPurpose.NEW_CYCLE,
        status=SolarRequestStatus.FINAL_REVIEW,
        raw_input="테스트",
        current_item_order=None,
        confirmed_at=None,
        execution_started_at=None,
        executed_at=None,
        execution_attempt_count=0,
        execution_result=None,
        error_code=None,
        error_message=None,
        result_acknowledged_at=None,
    )
    defaults.update(overrides)
    return SolarRequest(**defaults)


# ---------------------------------------------------------------------------
# _start_execution 조건부 UPDATE 분기 — 협력자(row lock/precondition/UPDATE 실행)는
# monkeypatch로 대체하고 분기 로직 자체만 검증한다.
# ---------------------------------------------------------------------------


class _FakeTxnSession:
    """`_start_execution`이 요구하는 최소 인터페이스(begin 컨텍스트 매니저, refresh)만 지원."""

    def __init__(self):
        self.committed = 0
        self.rolled_back = 0
        self.refresh_calls = []

    @contextmanager
    def begin(self):
        try:
            yield self
        except BaseException:
            self.rolled_back += 1
            raise
        else:
            self.committed += 1

    def refresh(self, obj):
        self.refresh_calls.append(obj)


class _SpyDispatcher:
    def __init__(self):
        self.registered: list[uuid.UUID] = []

    def register(self, request_id: uuid.UUID) -> None:
        self.registered.append(request_id)


class _RaisingDispatcher:
    def register(self, request_id: uuid.UUID) -> None:
        raise RuntimeError("등록 실패")


def test_start_execution_already_executing_is_idempotent_no_op(monkeypatch):
    request = _make_request(status=SolarRequestStatus.EXECUTING)
    monkeypatch.setattr(solar_request_service, "_lock_owned_solar_request", lambda db, rid, uid: request)
    validate = MagicMock()
    monkeypatch.setattr(solar_request_service, "_validate_execution_preconditions", validate)
    update_fn = MagicMock()
    monkeypatch.setattr(solar_request_service, "_apply_execution_transition_update", update_fn)
    dispatcher = _SpyDispatcher()

    result = solar_request_service.execute_solar_request(
        _FakeTxnSession(), user_id=USER_ID, request_id=REQUEST_ID, now=NOW, dispatcher=dispatcher
    )

    assert result.transitioned is False
    assert result.request is request
    validate.assert_not_called()
    update_fn.assert_not_called()
    assert dispatcher.registered == []


def test_start_execution_already_completed_is_idempotent_no_op(monkeypatch):
    request = _make_request(status=SolarRequestStatus.COMPLETED)
    monkeypatch.setattr(solar_request_service, "_lock_owned_solar_request", lambda db, rid, uid: request)
    update_fn = MagicMock()
    monkeypatch.setattr(solar_request_service, "_apply_execution_transition_update", update_fn)
    dispatcher = _SpyDispatcher()

    result = solar_request_service.execute_solar_request(
        _FakeTxnSession(), user_id=USER_ID, request_id=REQUEST_ID, now=NOW, dispatcher=dispatcher
    )

    assert result.transitioned is False
    update_fn.assert_not_called()
    assert dispatcher.registered == []


def test_start_execution_wrong_state_raises_invalid_request_state(monkeypatch):
    request = _make_request(status=SolarRequestStatus.COLLECTING)
    monkeypatch.setattr(solar_request_service, "_lock_owned_solar_request", lambda db, rid, uid: request)
    update_fn = MagicMock()
    monkeypatch.setattr(solar_request_service, "_apply_execution_transition_update", update_fn)
    dispatcher = _SpyDispatcher()

    with pytest.raises(ApiError) as exc_info:
        solar_request_service.execute_solar_request(
            _FakeTxnSession(), user_id=USER_ID, request_id=REQUEST_ID, now=NOW, dispatcher=dispatcher
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "INVALID_REQUEST_STATE"
    update_fn.assert_not_called()
    assert dispatcher.registered == []


def test_start_execution_precondition_failure_blocks_update_and_leaves_state_unchanged(monkeypatch):
    request = _make_request(status=SolarRequestStatus.FINAL_REVIEW)
    monkeypatch.setattr(solar_request_service, "_lock_owned_solar_request", lambda db, rid, uid: request)
    monkeypatch.setattr(
        solar_request_service,
        "_validate_execution_preconditions",
        MagicMock(side_effect=ApiError(409, "ACTIVE_CYCLE_EXISTS", "이미 있어요")),
    )
    update_fn = MagicMock()
    monkeypatch.setattr(solar_request_service, "_apply_execution_transition_update", update_fn)
    dispatcher = _SpyDispatcher()
    db = _FakeTxnSession()

    with pytest.raises(ApiError) as exc_info:
        solar_request_service.execute_solar_request(
            db, user_id=USER_ID, request_id=REQUEST_ID, now=NOW, dispatcher=dispatcher
        )

    assert exc_info.value.code == "ACTIVE_CYCLE_EXISTS"
    update_fn.assert_not_called()
    assert dispatcher.registered == []
    assert db.rolled_back == 1
    assert db.committed == 0
    assert request.status == SolarRequestStatus.FINAL_REVIEW
    assert request.execution_attempt_count == 0


def test_start_execution_rowcount_one_transitions_and_registers_after_commit(monkeypatch):
    request = _make_request(status=SolarRequestStatus.FINAL_REVIEW)
    monkeypatch.setattr(solar_request_service, "_lock_owned_solar_request", lambda db, rid, uid: request)
    monkeypatch.setattr(solar_request_service, "_validate_execution_preconditions", MagicMock())
    monkeypatch.setattr(solar_request_service, "_apply_execution_transition_update", MagicMock(return_value=1))
    dispatcher = _SpyDispatcher()
    db = _FakeTxnSession()

    result = solar_request_service.execute_solar_request(
        db, user_id=USER_ID, request_id=REQUEST_ID, now=NOW, dispatcher=dispatcher
    )

    assert result.transitioned is True
    assert dispatcher.registered == [REQUEST_ID]
    assert db.committed == 1
    assert request in db.refresh_calls


def test_start_execution_rowcount_zero_is_idempotent_no_dispatch(monkeypatch):
    """동시 execute/retry에 밀린 경우(rowcount=0) — dispatcher 등록 없음, attempt/시각은 애초에
    UPDATE의 WHERE가 매치되지 않아 안 바뀐다."""
    request = _make_request(status=SolarRequestStatus.FINAL_REVIEW, execution_attempt_count=3)
    monkeypatch.setattr(solar_request_service, "_lock_owned_solar_request", lambda db, rid, uid: request)
    monkeypatch.setattr(solar_request_service, "_validate_execution_preconditions", MagicMock())
    monkeypatch.setattr(solar_request_service, "_apply_execution_transition_update", MagicMock(return_value=0))
    dispatcher = _SpyDispatcher()
    db = _FakeTxnSession()

    result = solar_request_service.execute_solar_request(
        db, user_id=USER_ID, request_id=REQUEST_ID, now=NOW, dispatcher=dispatcher
    )

    assert result.transitioned is False
    assert dispatcher.registered == []
    assert request.execution_attempt_count == 3
    assert request in db.refresh_calls
    assert db.committed == 1  # 롤백이 아니라 정상 커밋(아무 것도 안 바뀐 read-only 성격의 커밋)


def test_start_execution_rowcount_multiple_raises_runtime_error(monkeypatch):
    request = _make_request(status=SolarRequestStatus.FINAL_REVIEW)
    monkeypatch.setattr(solar_request_service, "_lock_owned_solar_request", lambda db, rid, uid: request)
    monkeypatch.setattr(solar_request_service, "_validate_execution_preconditions", MagicMock())
    monkeypatch.setattr(solar_request_service, "_apply_execution_transition_update", MagicMock(return_value=2))
    dispatcher = _SpyDispatcher()

    with pytest.raises(RuntimeError):
        solar_request_service.execute_solar_request(
            _FakeTxnSession(), user_id=USER_ID, request_id=REQUEST_ID, now=NOW, dispatcher=dispatcher
        )
    assert dispatcher.registered == []


def test_start_execution_dispatcher_register_failure_does_not_undo_committed_transition(monkeypatch):
    request = _make_request(status=SolarRequestStatus.FINAL_REVIEW)
    monkeypatch.setattr(solar_request_service, "_lock_owned_solar_request", lambda db, rid, uid: request)
    monkeypatch.setattr(solar_request_service, "_validate_execution_preconditions", MagicMock())
    monkeypatch.setattr(solar_request_service, "_apply_execution_transition_update", MagicMock(return_value=1))

    result = solar_request_service.execute_solar_request(
        _FakeTxnSession(), user_id=USER_ID, request_id=REQUEST_ID, now=NOW, dispatcher=_RaisingDispatcher()
    )

    assert result.transitioned is True


def test_retry_requires_failed_status(monkeypatch):
    request = _make_request(status=SolarRequestStatus.FINAL_REVIEW)
    monkeypatch.setattr(solar_request_service, "_lock_owned_solar_request", lambda db, rid, uid: request)

    with pytest.raises(ApiError) as exc_info:
        solar_request_service.retry_solar_request(
            _FakeTxnSession(), user_id=USER_ID, request_id=REQUEST_ID, now=NOW, dispatcher=_SpyDispatcher()
        )

    assert exc_info.value.code == "INVALID_REQUEST_STATE"


# ---------------------------------------------------------------------------
# _apply_execution_transition_update — 실제 조건부 UPDATE의 SQL 구성 확인
# ---------------------------------------------------------------------------


def _value_key_names(stmt) -> set[str]:
    """ORM-enabled update(SolarRequest)의 values() 키는 Column 객체로 들어온다 — 컬럼명 문자열
    집합으로 정규화한다."""
    return {key.name if hasattr(key, "name") else str(key) for key in stmt._values.keys()}


class _FakeUpdateCaptureSession:
    def __init__(self, rowcount=1):
        self.captured_stmt = None
        self._rowcount = rowcount

    def execute(self, stmt):
        self.captured_stmt = stmt
        return SimpleNamespace(rowcount=self._rowcount)


def test_apply_execution_transition_update_includes_all_fields_in_one_statement():
    db = _FakeUpdateCaptureSession(rowcount=1)

    rowcount = solar_request_service._apply_execution_transition_update(
        db,
        request_id=REQUEST_ID,
        user_id=USER_ID,
        required_status=SolarRequestStatus.FINAL_REVIEW,
        now=NOW,
    )

    assert rowcount == 1
    stmt = db.captured_stmt
    value_keys = _value_key_names(stmt)
    assert value_keys == {
        "status",
        "execution_started_at",
        "execution_attempt_count",
        "executed_at",
        "execution_result",
        "error_code",
        "error_message",
        "updated_at",
    }
    where_sql = str(stmt.whereclause)
    assert "solar_requests.id" in where_sql
    assert "solar_requests.user_id" in where_sql
    assert "solar_requests.status" in where_sql


def test_apply_execution_transition_update_where_uses_required_status_for_retry():
    db = _FakeUpdateCaptureSession(rowcount=1)

    solar_request_service._apply_execution_transition_update(
        db, request_id=REQUEST_ID, user_id=USER_ID, required_status=SolarRequestStatus.FAILED, now=NOW
    )

    where_sql = str(db.captured_stmt.whereclause.compile(compile_kwargs={"literal_binds": True}))
    assert "'FAILED'" in where_sql


# ---------------------------------------------------------------------------
# Worker: pg_try_advisory_lock(non-blocking) + 성공/도메인 실패/인프라 실패 경계
# ---------------------------------------------------------------------------


class _FakeLockConnection:
    def __init__(self, *, try_lock_result: bool = True, unlock_raises: bool = False):
        self.calls: list[tuple[str, dict | None]] = []
        self.closed = False
        self.invalidated = False
        self._try_lock_result = try_lock_result
        self._unlock_raises = unlock_raises

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append((sql, params))
        if "pg_try_advisory_lock" in sql:
            return SimpleNamespace(scalar_one=lambda: self._try_lock_result)
        if "pg_advisory_unlock" in sql:
            if self._unlock_raises:
                raise RuntimeError("unlock 실패")
            return SimpleNamespace(scalar_one=lambda: True)
        raise AssertionError(f"unexpected SQL in fake lock connection: {sql}")

    def invalidate(self):
        self.invalidated = True

    def close(self):
        self.closed = True


class _FakeWorkerSession:
    def __init__(self, request, update_calls):
        self.request = request
        self.update_calls = update_calls
        self.closed = False

    @contextmanager
    def begin(self):
        yield self

    def execute(self, stmt):
        if isinstance(stmt, Update):
            self.update_calls.append(stmt)
            return SimpleNamespace(rowcount=1)
        return SimpleNamespace(scalar_one_or_none=lambda: self.request)

    def close(self):
        self.closed = True


class _FakeWorkerSessionFactory:
    def __init__(self, request):
        self.request = request
        self.sessions: list[_FakeWorkerSession] = []
        self.update_calls: list = []

    def __call__(self):
        session = _FakeWorkerSession(self.request, self.update_calls)
        self.sessions.append(session)
        return session


class _RecordingExecutor:
    def __init__(self):
        self.called_with = None

    def execute(self, db, request):
        self.called_with = request


class _DomainFailingExecutor:
    def __init__(self, code="PLAN_EXECUTION_FAILED", message="실패"):
        self.code = code
        self.message = message
        self.called_with = None

    def execute(self, db, request):
        self.called_with = request
        raise ExecutionDomainError(self.code, self.message)


class _InfraFailingExecutor:
    def execute(self, db, request):
        raise ValueError("예상 못한 버그")


def test_advisory_lock_key_is_deterministic_and_request_specific():
    other_id = uuid.uuid4()
    assert advisory_lock_key(REQUEST_ID) == advisory_lock_key(REQUEST_ID)
    assert advisory_lock_key(REQUEST_ID) != advisory_lock_key(other_id)


def test_not_configured_executor_raises_plan_execution_failed():
    request = _make_request(status=SolarRequestStatus.EXECUTING)
    with pytest.raises(ExecutionDomainError) as exc_info:
        NotConfiguredExecutor().execute(MagicMock(), request)
    assert exc_info.value.code == "PLAN_EXECUTION_FAILED"


def test_execute_locked_skips_when_status_not_executing():
    request = _make_request(status=SolarRequestStatus.COMPLETED)
    factory = _FakeWorkerSessionFactory(request)
    executor = _RecordingExecutor()

    worker_module._execute_locked(factory, REQUEST_ID, executor)

    assert executor.called_with is None
    assert factory.update_calls == []


def test_execute_locked_domain_error_finalizes_as_failed_in_separate_transaction():
    request = _make_request(status=SolarRequestStatus.EXECUTING, execution_attempt_count=1)
    factory = _FakeWorkerSessionFactory(request)
    executor = _DomainFailingExecutor("PLAN_EXECUTION_FAILED", "실패했어요")

    worker_module._execute_locked(factory, REQUEST_ID, executor)

    assert executor.called_with is request
    assert len(factory.update_calls) == 1
    stmt = factory.update_calls[0]
    value_keys = _value_key_names(stmt)
    assert value_keys == {"status", "error_code", "error_message", "executed_at", "execution_result", "updated_at"}
    assert "execution_attempt_count" not in value_keys
    assert "execution_started_at" not in value_keys
    # 재조회 세션(1) + FAILED 기록 세션(1), 둘 다 닫힘
    assert len(factory.sessions) == 2
    assert all(session.closed for session in factory.sessions)


def test_execute_locked_generic_exception_does_not_record_failed():
    request = _make_request(status=SolarRequestStatus.EXECUTING)
    factory = _FakeWorkerSessionFactory(request)
    executor = _InfraFailingExecutor()

    worker_module._execute_locked(factory, REQUEST_ID, executor)

    assert factory.update_calls == []
    assert len(factory.sessions) == 1
    assert factory.sessions[0].closed


def test_run_worker_for_request_uses_non_blocking_try_lock():
    request = _make_request(status=SolarRequestStatus.EXECUTING)
    session_factory = _FakeWorkerSessionFactory(request)
    executor = _RecordingExecutor()
    lock_conn = _FakeLockConnection(try_lock_result=True)

    run_worker_for_request(session_factory, REQUEST_ID, executor, connection_factory=lambda: lock_conn)

    lock_sqls = [sql for sql, _ in lock_conn.calls if "pg_try_advisory_lock" in sql or "pg_advisory_lock" in sql]
    assert any("pg_try_advisory_lock" in sql for sql in lock_sqls)
    assert all("pg_advisory_xact_lock" not in sql for sql, _ in lock_conn.calls)
    assert executor.called_with is request


def test_run_worker_for_request_lock_busy_skips_executor_entirely():
    request = _make_request(status=SolarRequestStatus.EXECUTING)
    session_factory = _FakeWorkerSessionFactory(request)
    executor = _RecordingExecutor()
    lock_conn = _FakeLockConnection(try_lock_result=False)

    run_worker_for_request(session_factory, REQUEST_ID, executor, connection_factory=lambda: lock_conn)

    assert executor.called_with is None
    assert session_factory.sessions == []
    assert lock_conn.closed is True
    assert not any("pg_advisory_unlock" in sql for sql, _ in lock_conn.calls)


def test_run_worker_for_request_unlocks_and_closes_after_success():
    request = _make_request(status=SolarRequestStatus.EXECUTING)
    session_factory = _FakeWorkerSessionFactory(request)
    executor = _RecordingExecutor()
    lock_conn = _FakeLockConnection(try_lock_result=True)

    run_worker_for_request(session_factory, REQUEST_ID, executor, connection_factory=lambda: lock_conn)

    assert any("pg_advisory_unlock" in sql for sql, _ in lock_conn.calls)
    assert lock_conn.closed is True
    assert lock_conn.invalidated is False


def test_run_worker_for_request_invalidates_connection_when_unlock_fails():
    request = _make_request(status=SolarRequestStatus.EXECUTING)
    session_factory = _FakeWorkerSessionFactory(request)
    executor = _RecordingExecutor()
    lock_conn = _FakeLockConnection(try_lock_result=True, unlock_raises=True)

    run_worker_for_request(session_factory, REQUEST_ID, executor, connection_factory=lambda: lock_conn)

    assert lock_conn.invalidated is True
    assert lock_conn.closed is True


def test_run_worker_for_request_closes_lock_connection_even_when_executor_raises_infra_error():
    request = _make_request(status=SolarRequestStatus.EXECUTING)
    session_factory = _FakeWorkerSessionFactory(request)
    executor = _InfraFailingExecutor()
    lock_conn = _FakeLockConnection(try_lock_result=True)

    run_worker_for_request(session_factory, REQUEST_ID, executor, connection_factory=lambda: lock_conn)

    assert lock_conn.closed is True
    assert any("pg_advisory_unlock" in sql for sql, _ in lock_conn.calls)


# ---------------------------------------------------------------------------
# SolarExecutionDispatcher — 실제 스레드로 process-local dedupe 검증
# ---------------------------------------------------------------------------


def test_dispatcher_dedupes_concurrent_register_calls(monkeypatch):
    call_count = 0
    count_lock = threading.Lock()
    started = threading.Event()
    release = threading.Event()

    def fake_run_worker(session_factory, request_id, executor, connection_factory=None):
        nonlocal call_count
        with count_lock:
            call_count += 1
        started.set()
        release.wait(timeout=2)

    monkeypatch.setattr(worker_module, "run_worker_for_request", fake_run_worker)

    dispatcher = SolarExecutionDispatcher(session_factory=lambda: None, max_workers=2)
    try:
        dispatcher.register(REQUEST_ID)
        assert started.wait(timeout=2)
        dispatcher.register(REQUEST_ID)  # 이미 실행 중 — dedupe돼야 한다
        release.set()
    finally:
        dispatcher.shutdown(wait=True)

    assert call_count == 1


def test_dispatcher_allows_reregistration_after_previous_run_finished(monkeypatch):
    calls: list[uuid.UUID] = []
    calls_lock = threading.Lock()

    def fake_run_worker(session_factory, request_id, executor, connection_factory=None):
        with calls_lock:
            calls.append(request_id)

    monkeypatch.setattr(worker_module, "run_worker_for_request", fake_run_worker)

    dispatcher = SolarExecutionDispatcher(session_factory=lambda: None)
    try:
        dispatcher.register(REQUEST_ID)
        _wait_until_not_pending(dispatcher, REQUEST_ID)
        dispatcher.register(REQUEST_ID)
        _wait_until_not_pending(dispatcher, REQUEST_ID)
    finally:
        dispatcher.shutdown(wait=True)

    assert calls == [REQUEST_ID, REQUEST_ID]


def _wait_until_not_pending(dispatcher: SolarExecutionDispatcher, request_id: uuid.UUID, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with dispatcher._pending_lock:
            if request_id not in dispatcher._pending:
                return
        time.sleep(0.01)
    raise AssertionError("dispatcher가 제한 시간 안에 request를 처리하지 못했다")
