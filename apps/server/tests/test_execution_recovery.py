import inspect
import threading
import uuid
from types import SimpleNamespace

from app.workers import solar_execution_worker as worker_module
from app.workers.solar_execution_worker import (
    SolarExecutionDispatcher,
    find_executing_request_ids,
    run_startup_recovery,
)


class _FakeSelectResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return SimpleNamespace(all=lambda: self._values)


class _FakeRecoverySession:
    """find_executing_request_ids가 실행하는 select statement만 이해하면 되는 최소 fake."""

    def __init__(self, executing_ids):
        self._executing_ids = executing_ids
        self.closed = False
        self.executed_statements = []

    def execute(self, stmt):
        self.executed_statements.append(stmt)
        return _FakeSelectResult(self._executing_ids)

    def close(self):
        self.closed = True


def test_find_executing_request_ids_filters_by_status():
    ids = [uuid.uuid4(), uuid.uuid4()]
    db = _FakeRecoverySession(ids)

    result = find_executing_request_ids(db)

    assert result == ids
    assert len(db.executed_statements) == 1
    sql = str(db.executed_statements[0])
    assert "solar_requests.status" in sql
    assert "solar_requests.execution_started_at" in sql  # ORDER BY 오래된 순


def test_find_executing_request_ids_empty_when_none_executing():
    db = _FakeRecoverySession([])
    assert find_executing_request_ids(db) == []


class _SpyDispatcher:
    def __init__(self):
        self.registered: list[uuid.UUID] = []

    def register(self, request_id: uuid.UUID) -> None:
        self.registered.append(request_id)


def test_run_startup_recovery_registers_each_executing_id_and_closes_session():
    ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    session = _FakeRecoverySession(ids)
    dispatcher = _SpyDispatcher()

    run_startup_recovery(dispatcher, lambda: session)

    assert dispatcher.registered == ids
    assert session.closed is True
    # find_executing_request_ids 조회 외에 어떤 쓰기도 하지 않는다(session에 execute가
    # SELECT 1회만 기록됨 -> attempt_count/started_at을 건드릴 방법 자체가 없다).
    assert len(session.executed_statements) == 1


def test_run_startup_recovery_registers_nothing_when_no_executing_requests():
    session = _FakeRecoverySession([])
    dispatcher = _SpyDispatcher()

    run_startup_recovery(dispatcher, lambda: session)

    assert dispatcher.registered == []


# ---------------------------------------------------------------------------
# startup recovery와 API execute/retry 등록 경쟁 — 둘 다 같은 register()를 거치므로
# dedupe가 자연히 적용된다.
# ---------------------------------------------------------------------------


def test_recovery_and_api_registration_race_only_runs_once(monkeypatch):
    request_id = uuid.uuid4()
    call_count = 0
    count_lock = threading.Lock()
    started = threading.Event()
    release = threading.Event()

    def fake_run_worker(session_factory, req_id, executor, connection_factory=None):
        nonlocal call_count
        with count_lock:
            call_count += 1
        started.set()
        release.wait(timeout=2)

    monkeypatch.setattr(worker_module, "run_worker_for_request", fake_run_worker)

    dispatcher = SolarExecutionDispatcher(session_factory=lambda: None, max_workers=4)
    recovery_session = _FakeRecoverySession([request_id])

    try:
        # "recovery" 경로가 먼저 등록한다.
        run_startup_recovery(dispatcher, lambda: recovery_session)
        assert started.wait(timeout=2)

        # 그 사이 "API execute" 경로가 같은 requestId로 register를 또 호출한다 — 이미 실행
        # 중이므로 dedupe돼야 한다.
        dispatcher.register(request_id)

        release.set()
    finally:
        dispatcher.shutdown(wait=True)

    assert call_count == 1


# ---------------------------------------------------------------------------
# SOLAR/Gemini 비접근 정적 확인 — Worker는 이미 저장된 request item만 사용하고
# 실행 중 SOLAR/Gemini 분석을 다시 호출하지 않는다.
# ---------------------------------------------------------------------------


def test_worker_module_does_not_import_solar_or_gemini_clients():
    source = inspect.getsource(worker_module)
    assert "solar_client" not in source
    assert "gemini_change_input_client" not in source
