import asyncio
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.models.enums import PlanPeriod
from app.services.check_in_settlement_service import SettlementTarget
from app.workers import check_in_worker

SEOUL = ZoneInfo("Asia/Seoul")


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (
            datetime(2026, 7, 29, 4, 0, tzinfo=SEOUL),
            (date(2026, 7, 28), PlanPeriod.EVENING),
        ),
        (
            datetime(2026, 7, 29, 12, 0, tzinfo=SEOUL),
            (date(2026, 7, 29), PlanPeriod.MORNING),
        ),
        (
            datetime(2026, 7, 29, 18, 0, tzinfo=SEOUL),
            (date(2026, 7, 29), PlanPeriod.AFTERNOON),
        ),
        (
            datetime(2026, 7, 30, 2, 0, tzinfo=SEOUL),
            (date(2026, 7, 29), PlanPeriod.AFTERNOON),
        ),
    ],
)
def test_latest_closed_period_boundaries(now, expected):
    assert check_in_worker.latest_closed_period(now) == expected


@pytest.mark.parametrize(
    ("now", "seconds"),
    [
        (datetime(2026, 7, 29, 3, 59, 59, tzinfo=SEOUL), 1),
        (datetime(2026, 7, 29, 4, 0, tzinfo=SEOUL), 8 * 60 * 60),
        (datetime(2026, 7, 29, 11, 59, 59, tzinfo=SEOUL), 1),
        (datetime(2026, 7, 29, 12, 0, tzinfo=SEOUL), 6 * 60 * 60),
        (datetime(2026, 7, 29, 18, 0, tzinfo=SEOUL), 10 * 60 * 60),
    ],
)
def test_seconds_until_next_boundary(now, seconds):
    assert check_in_worker.seconds_until_next_boundary(now) == seconds


def test_scheduled_worker_runs_recovery_before_and_after_target(monkeypatch):
    events = []
    target = SettlementTarget(
        uuid.uuid4(), uuid.uuid4(), date(2026, 7, 29), PlanPeriod.MORNING
    )
    scans = iter([[target], []])

    monkeypatch.setattr(
        check_in_worker,
        "_load_recovery_targets",
        lambda *args, **kwargs: events.append("scan") or next(scans),
    )
    monkeypatch.setattr(
        check_in_worker,
        "_load_scheduled_targets",
        lambda *args, **kwargs: events.append("scheduled-load") or [target],
    )
    monkeypatch.setattr(
        check_in_worker,
        "_run_targets",
        lambda factory, targets, **kwargs: events.append(
            "run-recovery" if events[-1] == "scan" else "run-scheduled"
        ),
    )

    check_in_worker.run_scheduled_worker(
        now=datetime(2026, 7, 29, 12, 0, tzinfo=SEOUL),
        session_factory=lambda: None,
    )

    assert events == [
        "scan",
        "run-recovery",
        "scheduled-load",
        "run-scheduled",
        "scan",
        "run-recovery",
    ]


def test_target_failure_isolated_and_next_target_continues(monkeypatch):
    first = SettlementTarget(
        uuid.uuid4(), uuid.uuid4(), date(2026, 7, 29), PlanPeriod.MORNING
    )
    second = SettlementTarget(
        uuid.uuid4(), uuid.uuid4(), date(2026, 7, 29), PlanPeriod.MORNING
    )
    sessions = []
    calls = []

    class Session:
        def __init__(self):
            self.rolled_back = False
            self.closed = False

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    def factory():
        session = Session()
        sessions.append(session)
        return session

    def fake_settle(db, target, **kwargs):
        calls.append(target)
        if target == first:
            raise RuntimeError("expected")

    monkeypatch.setattr(check_in_worker, "settle_period", fake_settle)

    check_in_worker._run_targets(
        factory,
        [first, second],
        now=datetime(2026, 7, 29, 12, 0, tzinfo=SEOUL),
    )

    assert calls == [first, second]
    assert sessions[0].rolled_back is True
    assert all(session.closed for session in sessions)


def test_session_creation_and_rollback_failures_do_not_stop_later_targets(monkeypatch):
    first = SettlementTarget(
        uuid.uuid4(), uuid.uuid4(), date(2026, 7, 29), PlanPeriod.MORNING
    )
    second = SettlementTarget(
        uuid.uuid4(), uuid.uuid4(), date(2026, 7, 29), PlanPeriod.AFTERNOON
    )
    third = SettlementTarget(
        uuid.uuid4(), uuid.uuid4(), date(2026, 7, 29), PlanPeriod.EVENING
    )
    factory_calls = 0
    settled = []

    class Session:
        def __init__(self, *, rollback_fails=False):
            self.rollback_fails = rollback_fails

        def rollback(self):
            if self.rollback_fails:
                raise RuntimeError("rollback failed")

        def close(self):
            pass

    def factory():
        nonlocal factory_calls
        factory_calls += 1
        if factory_calls == 1:
            raise RuntimeError("session creation failed")
        return Session(rollback_fails=factory_calls == 2)

    def fake_settle(db, target, **kwargs):
        settled.append(target)
        if target == second:
            raise RuntimeError("settlement failed")

    monkeypatch.setattr(check_in_worker, "settle_period", fake_settle)

    check_in_worker._run_targets(
        factory,
        [first, second, third],
        now=datetime(2026, 7, 30, 4, 0, tzinfo=SEOUL),
    )

    assert factory_calls == 3
    assert settled == [second, third]


def test_scheduler_shutdown_waits_for_loop_to_finish(monkeypatch):
    events = []

    async def fake_loop(stop_event):
        events.append("started")
        await stop_event.wait()
        events.append("stopped")

    monkeypatch.setattr(check_in_worker, "settlement_scheduler_loop", fake_loop)

    async def exercise():
        scheduler = check_in_worker.CheckInScheduler()
        scheduler.start()
        await asyncio.sleep(0)
        await scheduler.shutdown()

    asyncio.run(exercise())

    assert events == ["started", "stopped"]


def test_lifespan_runs_startup_recovery_and_registers_scheduler(monkeypatch):
    events = []

    async def immediate_to_thread(func, *args, **kwargs):
        events.append("startup")
        return func(*args, **kwargs)

    async def fake_loop(stop_event):
        events.append("scheduler")
        await stop_event.wait()

    monkeypatch.setattr(asyncio, "to_thread", immediate_to_thread)
    monkeypatch.setattr(
        check_in_worker,
        "run_recovery_worker",
        lambda: events.append("recovery"),
    )
    monkeypatch.setattr(
        check_in_worker,
        "settlement_scheduler_loop",
        fake_loop,
    )

    async def exercise():
        async with check_in_worker.check_in_lifespan(object()):
            await asyncio.sleep(0)
            assert events == ["startup", "recovery", "scheduler"]

    asyncio.run(exercise())
