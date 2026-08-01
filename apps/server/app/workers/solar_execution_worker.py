from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Protocol

from fastapi import FastAPI
from sqlalchemy import null, select, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.core.clock import get_current_moment
from app.db.session import get_engine, get_session_local
from app.models.enums import SolarRequestPurpose, SolarRequestStatus
from app.models.solar_request import SolarRequest
from app.services import active_cycle_execution_service, new_cycle_execution_service

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]
ConnectionFactory = Callable[[], Connection]


class ExecutionDomainError(Exception):
    """Executor가 실제로 실행을 시도했지만 도메인 로직상 실패했을 때만 raise한다.
    그 외 예외(인프라 오류, 버그)는 이 예외로 감싸지 않는다 — Worker가 그 둘을 다르게 처리한다."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class Executor(Protocol):
    def execute(self, db: Session, request: SolarRequest) -> None:
        """request를 실행한다. 성공 시 이 함수 안에서 필요한 모든 쓰기와 request의 최종 COMPLETED
        갱신까지 마치고(같은 트랜잭션에서 커밋 대상으로 남긴 채) 정상 반환해야 한다(DB 명세
        20-7/20-8절: 엔티티 생성과 request COMPLETED 갱신은 하나의 커밋). 실패 시
        ExecutionDomainError만 raise한다."""
        ...


class NotConfiguredExecutor:
    """실제 NEW_CYCLE/ACTIVE_CYCLE 실행 로직이 아직 연결되지 않았을 때 production 기본값.

    호출 즉시 도메인 실패로 처리한다 — EXECUTING에 무기한 방치하거나 가짜로 COMPLETED 처리하지
    않는다. PLAN_EXECUTION_FAILED는 API 명세 8-2절에 이미 정의된 유일한 실행 실패 코드이고,
    retryable이므로 다음 이슈에서 실제 Executor가 연결되면 같은 retry 버튼으로 정상 동작한다.
    """

    def execute(self, db: Session, request: SolarRequest) -> None:
        raise ExecutionDomainError(
            "PLAN_EXECUTION_FAILED", "실행 기능이 아직 준비되지 않았어요. 잠시 후 다시 시도해 주세요."
        )


class DefaultExecutor:
    """purpose에 따라 실제 도메인 실행 서비스로 위임하는 production Executor. NEW_CYCLE과
    ACTIVE_CYCLE 모두 실제 로직(new_cycle_execution_service.execute_new_cycle /
    active_cycle_execution_service.execute_active_cycle)에 연결되어 있다.

    두 분기 모두 execute_new_cycle/execute_active_cycle이 이미 _execute_locked가 연
    `with db.begin()` 블록 안에서 호출된다는 점을 이용해, 분류된 도메인 예외
    (NewCycleExecutionError/ActiveCycleExecutionError)뿐 아니라 그 블록 안에서 발생하는
    그 외 모든 예외(Exception 하위, 프로세스 종료 계열인 BaseException/KeyboardInterrupt/
    SystemExit는 애초에 `except Exception`에 잡히지 않는다)도 ExecutionDomainError로
    변환한다. rollback은 이미 그 with-block이 보장하므로 "실행 트랜잭션 안에서 발생한 예외"는
    분류 여부와 무관하게 항상 별도 트랜잭션 FAILED 기록으로 이어져야 한다는 계약을
    satisfy한다. 이 executor 호출 자체가 시작되기 전(session 생성, requestId advisory lock
    획득 등 _execute_locked/run_worker_for_request 계층)의 인프라 실패는 이 클래스가
    관여하지 않는 별도 경계이며 기존 대로 EXECUTING을 유지한다.

    사용자 응답에는 원본 예외 메시지나 내부 식별자를 노출하지 않는다 — 분류되지 않은 예외는
    항상 고정된 안전 문구로 대체하고, 실제 원인은 로그의 traceback(exc_info, __cause__ 체인)
    으로만 보존한다."""

    def execute(self, db: Session, request: SolarRequest) -> None:
        if request.purpose == SolarRequestPurpose.NEW_CYCLE:
            try:
                new_cycle_execution_service.execute_new_cycle(db, request)
            except new_cycle_execution_service.NewCycleExecutionError as exc:
                raise ExecutionDomainError(exc.code, exc.message) from exc
            except Exception as exc:
                logger.exception(
                    "NEW_CYCLE 실행 트랜잭션 안에서 분류되지 않은 예외 발생 request_id=%s", request.id
                )
                raise ExecutionDomainError(
                    "PLAN_EXECUTION_FAILED", "실행 중 문제가 발생했어요. 다시 시도해 주세요."
                ) from exc
            return
        if request.purpose == SolarRequestPurpose.ACTIVE_CYCLE:
            try:
                active_cycle_execution_service.execute_active_cycle(db, request)
            except active_cycle_execution_service.ActiveCycleExecutionError as exc:
                raise ExecutionDomainError(exc.code, exc.message) from exc
            except Exception as exc:
                logger.exception(
                    "ACTIVE_CYCLE 실행 트랜잭션 안에서 분류되지 않은 예외 발생 request_id=%s", request.id
                )
                raise ExecutionDomainError(
                    "PLAN_EXECUTION_FAILED", "실행 중 문제가 발생했어요. 다시 시도해 주세요."
                ) from exc
            return
        raise ExecutionDomainError(
            "PLAN_EXECUTION_FAILED", "실행 기능이 아직 준비되지 않았어요. 잠시 후 다시 시도해 주세요."
        )


def advisory_lock_key(request_id: uuid.UUID) -> int:
    """프로세스별 hash() 대신 SHA-256으로 안정적인 signed bigint lock key를 만든다
    (check_in_settlement_service.advisory_lock_key와 동일한 방식, 다른 namespace)."""
    identity = f"solar-execution:{request_id}".encode()
    return int.from_bytes(hashlib.sha256(identity).digest()[:8], "big", signed=True)


def _default_lock_connection_factory() -> Connection:
    return get_engine().connect().execution_options(isolation_level="AUTOCOMMIT")


def _execute_locked(session_factory: SessionFactory, request_id: uuid.UUID, executor: Executor) -> None:
    """advisory lock을 이미 획득한 상태에서 호출된다. request를 재조회해 status가 EXECUTING일
    때만 executor를 호출한다. ExecutionDomainError는 그대로 다시 raise해 호출자가 별도
    트랜잭션에서 FAILED를 기록하게 한다. 그 외 예외는 로그만 남기고 삼킨다(EXECUTING 유지)."""
    db = session_factory()
    domain_error: ExecutionDomainError | None = None
    try:
        try:
            with db.begin():
                request = db.execute(
                    select(SolarRequest).where(SolarRequest.id == request_id)
                ).scalar_one_or_none()
                if request is None or request.status != SolarRequestStatus.EXECUTING:
                    return
                try:
                    executor.execute(db, request)
                except ExecutionDomainError as exc:
                    domain_error = exc
                    raise
        except ExecutionDomainError:
            pass  # with-block이 이미 rollback했다 — 엔티티 변경 시도분까지 전부 버려짐
    except Exception:
        logger.exception("solar execution worker infra error request_id=%s", request_id)
        return
    finally:
        db.close()

    if domain_error is not None:
        _finalize_as_failed(session_factory, request_id, domain_error.code, domain_error.message)


def _finalize_as_failed(session_factory: SessionFactory, request_id: uuid.UUID, code: str, message: str) -> None:
    """실제 실행 중 도메인 오류가 발생했을 때만 호출된다. 별도 트랜잭션에서 request만 FAILED로
    기록한다(DB 명세 20-10절). execution_started_at/execution_attempt_count는 건드리지 않는다.

    execution_result는 sqlalchemy.null()을 써야 한다 — JSONB 컬럼에 파이썬 None을 그대로 넘기면
    SQL NULL이 아니라 JSON 리터럴 'null'로 직렬화되어 failed_state_consistency CHECK(
    execution_result IS NULL)를 위반한다(실제 PostgreSQL E2E에서 확인된 결함)."""
    db = session_factory()
    try:
        with db.begin():
            db.execute(
                update(SolarRequest)
                .where(SolarRequest.id == request_id, SolarRequest.status == SolarRequestStatus.EXECUTING)
                .values(
                    status=SolarRequestStatus.FAILED,
                    error_code=code,
                    error_message=message,
                    executed_at=None,
                    execution_result=null(),
                    updated_at=get_current_moment(),
                )
            )
    except Exception:
        logger.exception("solar execution FAILED 기록 실패 request_id=%s", request_id)
    finally:
        db.close()


def run_worker_for_request(
    session_factory: SessionFactory,
    request_id: uuid.UUID,
    executor: Executor,
    *,
    connection_factory: ConnectionFactory | None = None,
) -> None:
    """requestId 기준 session-level advisory lock(pg_try_advisory_lock, non-blocking)을 전용
    connection에서 잡고 Worker 실행 전체(재조회 -> executor 호출 -> 성공/실패 판정)를 보호한다.
    lock을 얻지 못하면(다른 Worker가 실행 중) 아무 것도 바꾸지 않고 즉시 반환한다."""
    connection_factory = connection_factory or _default_lock_connection_factory
    lock_conn = connection_factory()
    lock_key = advisory_lock_key(request_id)
    acquired = False
    try:
        acquired = bool(
            lock_conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": lock_key}).scalar_one()
        )
        if not acquired:
            logger.info("solar execution lock busy request_id=%s", request_id)
            return
        _execute_locked(session_factory, request_id, executor)
    finally:
        if acquired:
            try:
                lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": lock_key})
            except Exception:
                logger.exception(
                    "solar execution unlock 실패 request_id=%s — connection 폐기", request_id
                )
                lock_conn.invalidate()
        lock_conn.close()


class SolarExecutionDispatcher:
    """requestId 기준 Worker 등록·프로세스 내 중복 실행 방지·background 실행을 담당하는 공통
    디스패처. execute/retry API와 startup recovery 모두 같은 register()를 호출하므로 두 경로의
    경쟁도 이 안에서 자연히 dedupe된다."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        executor: Executor | None = None,
        connection_factory: ConnectionFactory | None = None,
        max_workers: int = 4,
    ) -> None:
        self._session_factory = session_factory
        self._executor = executor or NotConfiguredExecutor()
        self._connection_factory = connection_factory
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="solar-execution")
        self._pending: set[uuid.UUID] = set()
        self._pending_lock = threading.Lock()

    def register(self, request_id: uuid.UUID) -> None:
        with self._pending_lock:
            if request_id in self._pending:
                return
            self._pending.add(request_id)
        self._pool.submit(self._run, request_id)

    def _run(self, request_id: uuid.UUID) -> None:
        try:
            run_worker_for_request(
                self._session_factory,
                request_id,
                self._executor,
                connection_factory=self._connection_factory,
            )
        except Exception:
            logger.exception("solar execution worker 실행 실패 request_id=%s", request_id)
        finally:
            with self._pending_lock:
                self._pending.discard(request_id)

    def shutdown(self, *, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait)


def find_executing_request_ids(db: Session) -> list[uuid.UUID]:
    stmt = (
        select(SolarRequest.id)
        .where(SolarRequest.status == SolarRequestStatus.EXECUTING)
        .order_by(SolarRequest.execution_started_at, SolarRequest.id)
    )
    return list(db.execute(stmt).scalars().all())


def run_startup_recovery(dispatcher: SolarExecutionDispatcher, session_factory: SessionFactory) -> None:
    """서버 시작 시 EXECUTING request를 다시 Worker에 등록한다. attempt_count/started_at은
    건드리지 않는다 — 이건 retry가 아니라 잃어버린 Worker의 재등록이다."""
    db = session_factory()
    try:
        request_ids = find_executing_request_ids(db)
    finally:
        db.close()

    for request_id in request_ids:
        dispatcher.register(request_id)


_dispatcher: SolarExecutionDispatcher | None = None


def get_solar_execution_dispatcher() -> SolarExecutionDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = SolarExecutionDispatcher(session_factory=get_session_local(), executor=DefaultExecutor())
    return _dispatcher


@asynccontextmanager
async def solar_execution_lifespan(app: FastAPI, dispatcher: SolarExecutionDispatcher):
    del app
    try:
        await asyncio.to_thread(run_startup_recovery, dispatcher, get_session_local())
    except Exception:
        logger.exception("solar execution startup recovery failed")

    try:
        yield
    finally:
        dispatcher.shutdown()
