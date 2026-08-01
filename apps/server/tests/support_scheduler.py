"""schedule_plan_blocks() 테스트 전용 in-memory fake Session.

scheduler는 여러 종류의 `select(Model).where(...)` 조회를 수행하므로, 시나리오별로
전용 Fake를 새로 만드는 대신 WHERE 절을 일반적으로 평가하는 하나의 Fake Session을
공유한다. 지원 대상은 이 서비스가 실제로 사용하는 형태(entity-only select, and로
묶인 `==`/`>=`/`>`/`<` 비교)로 한정한다.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from app.models.enums import (
    AmountSource,
    EstimateSource,
    PlanBlockStatus,
    PlanCycleStatus,
    PlanPeriod,
    TaskStatus,
)
from app.models.fixed_schedule import FixedSchedule
from app.models.plan_block import PlanBlock
from app.models.planning_cycle import PlanningCycle
from app.models.task import Task
from tests.support_sql_eval import eval_clause as _eval_clause


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _FakeScalars(self._rows)

    def scalar_one_or_none(self):
        if not self._rows:
            return None
        if len(self._rows) > 1:
            raise AssertionError("scalar_one_or_none()에 두 건 이상의 행이 매칭되었습니다.")
        return self._rows[0]

    def scalar_one(self):
        if len(self._rows) != 1:
            raise AssertionError(f"scalar_one()은 정확히 한 건을 기대하지만 {len(self._rows)}건입니다.")
        return self._rows[0]


class FakeSchedulerSession:
    """add/delete/flush만 지원하고 begin/commit 호출 시 즉시 실패하는 fake Session.

    schedule_plan_blocks()는 외부 트랜잭션을 소유하면 안 된다는 요구사항을
    begin()/commit() 호출 자체를 에러로 만들어 검증한다.
    """

    def __init__(self):
        self._rows: dict[type, list] = {}
        self._pending_add: list = []
        self._pending_delete: list = []
        self.flush_count = 0

    def seed(self, *objects):
        for obj in objects:
            self._rows.setdefault(type(obj), []).append(obj)
        return self

    def add(self, obj):
        self._pending_add.append(obj)

    def delete(self, obj):
        self._pending_delete.append(obj)

    def flush(self):
        self.flush_count += 1
        for obj in self._pending_add:
            self._rows.setdefault(type(obj), []).append(obj)
        self._pending_add.clear()
        for obj in self._pending_delete:
            bucket = self._rows.get(type(obj), [])
            if obj in bucket:
                bucket.remove(obj)
        self._pending_delete.clear()

    def begin(self):
        raise AssertionError(
            "schedule_plan_blocks()가 db.begin()을 호출했습니다 — 외부 트랜잭션을 소유하면 안 됩니다."
        )

    def commit(self):
        raise AssertionError(
            "schedule_plan_blocks()가 db.commit()을 호출했습니다 — 외부 트랜잭션을 소유하면 안 됩니다."
        )

    def execute(self, stmt):
        entity = stmt.column_descriptions[0]["entity"]
        candidates = list(self._rows.get(entity, []))
        whereclause = stmt.whereclause
        if whereclause is not None:
            candidates = [obj for obj in candidates if _eval_clause(whereclause, obj)]
        return _FakeResult(candidates)

    def all_rows(self, model_type):
        return list(self._rows.get(model_type, []))


# ---------------------------------------------------------------------------
# 테스트용 factory 함수 — 유효한 최소 필드만 채우고 override로 조정한다.
# ---------------------------------------------------------------------------


def make_cycle(*, user_id: uuid.UUID, start_date: date, end_date: date, **overrides) -> PlanningCycle:
    fields = dict(
        id=uuid.uuid4(),
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        status=PlanCycleStatus.ACTIVE,
    )
    fields.update(overrides)
    return PlanningCycle(**fields)


def make_task(
    *,
    user_id: uuid.UUID,
    plan_cycle_id: uuid.UUID,
    remaining_minutes: int,
    title: str = "task",
    deadline_at: datetime | None = None,
    created_at: datetime,
    **overrides,
) -> Task:
    fields = dict(
        id=uuid.uuid4(),
        user_id=user_id,
        plan_cycle_id=plan_cycle_id,
        source_request_item_id=None,
        title=title,
        deadline_at=deadline_at,
        amount_text=None,
        amount_source=AmountSource.UNKNOWN,
        initial_minutes=max(1, remaining_minutes),
        estimated_minutes=max(1, remaining_minutes),
        estimated_minutes_source=EstimateSource.USER,
        remaining_minutes=remaining_minutes,
        status=TaskStatus.ACTIVE,
        deadline_warning_acknowledged_at=None,
        completed_at=None,
        cancelled_at=None,
        created_at=created_at,
        updated_at=created_at,
    )
    fields.update(overrides)
    return Task(**fields)


def make_plan_block(
    *,
    user_id: uuid.UUID,
    plan_cycle_id: uuid.UUID,
    task_id: uuid.UUID,
    plan_date: date,
    period: PlanPeriod,
    allocated_minutes: int,
    status: PlanBlockStatus = PlanBlockStatus.PLANNED,
    display_order: int = 0,
    display_title: str = "block",
    now: datetime | None = None,
    **overrides,
) -> PlanBlock:
    needs_checked_at = status in (PlanBlockStatus.CHECKED, PlanBlockStatus.COMPLETED)
    needs_check_in_id = status in (PlanBlockStatus.COMPLETED, PlanBlockStatus.NOT_DONE)
    fields = dict(
        id=uuid.uuid4(),
        user_id=user_id,
        plan_cycle_id=plan_cycle_id,
        task_id=task_id,
        plan_date=plan_date,
        period=period,
        allocated_minutes=allocated_minutes,
        allocated_amount_text=None,
        display_title=display_title,
        display_order=display_order,
        status=status,
        checked_at=now if needs_checked_at else None,
        check_in_id=uuid.uuid4() if needs_check_in_id else None,
        rescheduled_from_block_id=None,
        created_at=now,
        updated_at=now,
    )
    fields.update(overrides)
    return PlanBlock(**fields)


def make_fixed_schedule(
    *,
    user_id: uuid.UUID,
    plan_cycle_id: uuid.UUID,
    start_at: datetime,
    end_at: datetime,
    title: str = "fixed",
    **overrides,
) -> FixedSchedule:
    fields = dict(
        id=uuid.uuid4(),
        user_id=user_id,
        plan_cycle_id=plan_cycle_id,
        source_request_item_id=None,
        title=title,
        start_at=start_at,
        end_at=end_at,
        created_at=start_at,
        updated_at=start_at,
    )
    fields.update(overrides)
    return FixedSchedule(**fields)
