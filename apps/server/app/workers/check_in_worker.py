from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from sqlalchemy.orm import Session

from app.core.clock import get_current_moment
from app.db.session import get_session_local
from app.models.enums import PlanPeriod
from app.services.check_in_settlement_service import (
    SettlementTarget,
    find_recovery_targets,
    find_targets_for_period,
    latest_closed_period,
    settle_period,
)

logger = logging.getLogger(__name__)

_SEOUL_TZ = ZoneInfo("Asia/Seoul")
SessionFactory = Callable[[], Session]


def seconds_until_next_boundary(now: datetime) -> float:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now는 timezone-aware datetime이어야 한다.")
    local = now.astimezone(_SEOUL_TZ)
    candidates = [
        datetime.combine(local.date(), time(4, 0), tzinfo=_SEOUL_TZ),
        datetime.combine(local.date(), time(12, 0), tzinfo=_SEOUL_TZ),
        datetime.combine(local.date(), time(18, 0), tzinfo=_SEOUL_TZ),
        datetime.combine(local.date() + timedelta(days=1), time(4, 0), tzinfo=_SEOUL_TZ),
    ]
    next_boundary = min(candidate for candidate in candidates if candidate > local)
    return (next_boundary - local).total_seconds()


def _resolve_session_factory(session_factory: SessionFactory | None) -> SessionFactory:
    return session_factory or get_session_local()


def _load_recovery_targets(
    session_factory: SessionFactory, *, now: datetime
) -> list[SettlementTarget]:
    db = session_factory()
    try:
        return find_recovery_targets(db, now=now)
    finally:
        db.close()


def _load_scheduled_targets(
    session_factory: SessionFactory,
    *,
    plan_date: date,
    period: PlanPeriod,
) -> list[SettlementTarget]:
    db = session_factory()
    try:
        return find_targets_for_period(db, plan_date=plan_date, period=period)
    finally:
        db.close()


def _run_targets(
    session_factory: SessionFactory,
    targets: list[SettlementTarget],
    *,
    now: datetime,
) -> None:
    for target in targets:
        db: Session | None = None
        try:
            db = session_factory()
            settle_period(db, target, now=now)
        except Exception:
            logger.exception(
                "check-in settlement failed cycle_id=%s plan_date=%s period=%s",
                target.plan_cycle_id,
                target.plan_date,
                target.period.value,
            )
            if db is not None:
                try:
                    db.rollback()
                except Exception:
                    logger.exception(
                        "check-in settlement rollback failed cycle_id=%s",
                        target.plan_cycle_id,
                    )
        finally:
            if db is not None:
                try:
                    db.close()
                except Exception:
                    logger.exception(
                        "check-in settlement session close failed cycle_id=%s",
                        target.plan_cycle_id,
                    )


def run_recovery_worker(
    *, now: datetime | None = None, session_factory: SessionFactory | None = None
) -> None:
    current = now or get_current_moment()
    factory = _resolve_session_factory(session_factory)
    targets = _load_recovery_targets(factory, now=current)
    _run_targets(factory, targets, now=current)


def run_scheduled_worker(
    *, now: datetime | None = None, session_factory: SessionFactory | None = None
) -> None:
    """복구 scan 전 → 정시 대상 → 복구 scan 후 순서로 실행한다."""
    current = now or get_current_moment()
    factory = _resolve_session_factory(session_factory)
    logger.info("check-in scheduled worker started at=%s", current.isoformat())

    before_targets = _load_recovery_targets(factory, now=current)
    _run_targets(factory, before_targets, now=current)

    plan_date, period = latest_closed_period(current)
    scheduled_targets = _load_scheduled_targets(
        factory, plan_date=plan_date, period=period
    )
    _run_targets(factory, scheduled_targets, now=current)

    after_targets = _load_recovery_targets(factory, now=current)
    _run_targets(factory, after_targets, now=current)


async def settlement_scheduler_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        delay = seconds_until_next_boundary(get_current_moment())
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=delay)
        except TimeoutError:
            try:
                await asyncio.to_thread(run_scheduled_worker)
            except Exception:
                # 개별 대상 오류는 worker가 격리하고, 초기화·DB 연결 오류도 서버를 종료시키지 않는다.
                logger.exception("check-in scheduled worker invocation failed")


class CheckInScheduler:
    """FastAPI lifespan에 묶이는 정시 실행 task의 시작·graceful shutdown을 관리한다."""

    def __init__(self) -> None:
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(
            settlement_scheduler_loop(self._stop_event),
            name="check-in-settlement-scheduler",
        )

    async def shutdown(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        try:
            # 실행 중인 to_thread 정산이 있으면 완료될 때까지 기다린 뒤 loop를 종료한다.
            await self._task
        finally:
            self._task = None


@asynccontextmanager
async def check_in_lifespan(app: FastAPI):
    del app
    try:
        await asyncio.to_thread(run_recovery_worker)
    except Exception:
        logger.exception("check-in startup recovery failed")

    scheduler = CheckInScheduler()
    scheduler.start()
    try:
        yield
    finally:
        await scheduler.shutdown()
