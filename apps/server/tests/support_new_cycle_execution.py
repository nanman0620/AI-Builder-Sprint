"""execute_new_cycle()/DefaultExecutor 통합 테스트 전용 in-memory fake DB.

support_scheduler.py/support_settlement.py와 같은 계열이지만, `_execute_locked`가 요구하는
"세션 여러 개가 같은 커밋된 데이터를 공유"와 "실패 시 이번 트랜잭션에서 만든 변경만 정확히
rollback" 두 가지를 모두 지원해야 해서 별도로 둔다.

- FakeNewCycleDB: 여러 FakeNewCycleSession이 공유하는 실제 저장소(session_factory()가 호출될
  때마다 새 세션을 내주지만, 커밋된 데이터는 세션 경계와 무관하게 공유되어야 실제
  PostgreSQL 커넥션 풀과 동등하게 동작한다).
- FakeNewCycleSession.begin(): 진입 시 저장소 전체(각 행의 객체 attribute 포함)를 스냅샷하고,
  예외로 빠져나오면 스냅샷으로 복원한다 — add()로 새로 생긴 행은 사라지고, 기존 행의 in-place
  attribute 변경(예: item.status = EXECUTED)도 되돌아간다. 실제 SQLAlchemy Session.rollback()과
  동등한 관찰 결과를 순수 Python 객체로 재현한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy.sql import operators
from sqlalchemy.sql.dml import Update
from sqlalchemy.sql.elements import BindParameter, BooleanClauseList, Null, TextClause

from app.models.enums import (
    SolarAction,
    SolarEntityType,
    SolarItemStatus,
    SolarRequestPurpose,
    SolarRequestStatus,
)
from app.models.fixed_schedule import FixedSchedule
from app.models.plan_block import PlanBlock
from app.models.planning_cycle import PlanningCycle
from app.models.solar_request import SolarRequest
from app.models.solar_request_item import SolarRequestItem
from app.models.task import Task

_TABLENAME_TO_MODEL = {
    model.__tablename__: model
    for model in (SolarRequest, SolarRequestItem, Task, FixedSchedule, PlanningCycle, PlanBlock)
}


def _resolve_operand(side, obj):
    if isinstance(side, BindParameter):
        return side.value
    if isinstance(side, Null):
        return None
    key = getattr(side, "key", None)
    if key is not None and hasattr(obj, key):
        return getattr(obj, key)
    raise AssertionError(f"FakeNewCycleDB가 처리할 수 없는 조건식입니다: {side!r}")


def _eval_clause(clause, obj) -> bool:
    if isinstance(clause, BooleanClauseList):
        results = [_eval_clause(sub, obj) for sub in clause.clauses]
        operator_name = getattr(clause.operator, "__name__", "")
        if operator_name == "and_":
            return all(results)
        if operator_name == "or_":
            return any(results)
        raise AssertionError(f"지원하지 않는 불리언 연산자입니다: {clause.operator}")
    left = _resolve_operand(clause.left, obj)
    right = _resolve_operand(clause.right, obj)
    if clause.operator is operators.in_op:
        return left in right
    if clause.operator is operators.not_in_op:
        return left not in right
    if clause.operator is operators.is_:
        return left is right
    if clause.operator is operators.is_not:
        return left is not right
    return bool(clause.operator(left, right))


def _apply_update_values(rows: list, stmt: Update) -> list:
    matched = [row for row in rows if stmt.whereclause is None or _eval_clause(stmt.whereclause, row)]
    for row in matched:
        for key, value in stmt._values.items():
            name = key.name if hasattr(key, "name") else str(key)
            if isinstance(value, BindParameter):
                resolved = value.value
            elif isinstance(value, Null):
                resolved = None
            else:
                resolved = value
            setattr(row, name, resolved)
    return matched


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeResult:
    def __init__(self, rows=(), *, scalar=True):
        self._rows = list(rows)
        self._scalar = scalar

    def scalars(self):
        return _FakeScalars(self._rows)

    def scalar_one_or_none(self):
        if not self._rows:
            return None
        if len(self._rows) != 1:
            raise AssertionError(f"정확히 0~1건을 기대했지만 {len(self._rows)}건입니다.")
        return self._rows[0]

    def scalar_one(self):
        return self._scalar


class FakeNewCycleDB:
    def __init__(self):
        self._rows: dict[type, list] = {}
        self.advisory_lock_keys: list[int] = []
        # execute()로 들어온 lock/select/update 호출을 시간순으로 기록한다("lock", key) /
        # ("select", Model) / ("update", Model) — advisory lock이 ACTIVE cycle 재조회보다
        # 먼저 실행되는지 같은 순서 의존 검증에 쓴다.
        self.operations: list[tuple] = []
        self.sessions: list["FakeNewCycleSession"] = []

    def seed(self, *objects):
        for obj in objects:
            self._rows.setdefault(type(obj), []).append(obj)
        return self

    def all_rows(self, model_type) -> list:
        return list(self._rows.get(model_type, []))

    def __call__(self) -> "FakeNewCycleSession":
        """session_factory로 그대로 쓸 수 있도록 DB 자체를 callable로 만든다."""
        session = FakeNewCycleSession(self)
        self.sessions.append(session)
        return session


class _Transaction:
    def __init__(self, session: "FakeNewCycleSession"):
        self._session = session
        self._rows_snapshot: dict[type, list] | None = None
        self._attrs_snapshot: dict[int, dict] | None = None

    def __enter__(self):
        db = self._session._db
        self._rows_snapshot = {model: list(objs) for model, objs in db._rows.items()}
        self._attrs_snapshot = {
            id(obj): dict(obj.__dict__) for objs in db._rows.values() for obj in objs
        }
        return self._session

    def __exit__(self, exc_type, exc, tb):
        db = self._session._db
        if exc_type is None:
            self._session.commit_count += 1
            return False

        db._rows = {model: list(objs) for model, objs in self._rows_snapshot.items()}
        for objs in db._rows.values():
            for obj in objs:
                saved = self._attrs_snapshot.get(id(obj))
                if saved is not None:
                    obj.__dict__.clear()
                    obj.__dict__.update(saved)
        self._session._pending_add.clear()
        self._session.rollback_count += 1
        return False


class FakeNewCycleSession:
    def __init__(self, db: FakeNewCycleDB):
        self._db = db
        self._pending_add: list = []
        self.commit_count = 0
        self.rollback_count = 0
        self.closed = False

    def begin(self):
        return _Transaction(self)

    def add(self, obj):
        self._pending_add.append(obj)

    def delete(self, obj):
        bucket = self._db._rows.get(type(obj), [])
        if obj in bucket:
            bucket.remove(obj)

    def flush(self):
        for obj in self._pending_add:
            self._db._rows.setdefault(type(obj), []).append(obj)
        self._pending_add.clear()

    def refresh(self, obj):
        pass

    def close(self):
        self.closed = True

    def execute(self, stmt, params=None):
        if isinstance(stmt, TextClause):
            key = params["lock_key"]
            self._db.advisory_lock_keys.append(key)
            self._db.operations.append(("lock", key))
            return _FakeResult(scalar=True)

        if isinstance(stmt, Update):
            model = _TABLENAME_TO_MODEL[stmt.table.name]
            rows = self._db._rows.get(model, [])
            matched = _apply_update_values(rows, stmt)
            self._db.operations.append(("update", model))
            return SimpleNamespace(rowcount=len(matched))

        entity = stmt.column_descriptions[0]["entity"]
        self._db.operations.append(("select", entity))
        candidates = list(self._db._rows.get(entity, []))
        candidates += [obj for obj in self._pending_add if isinstance(obj, entity) and obj not in candidates]
        if stmt.whereclause is not None:
            candidates = [obj for obj in candidates if _eval_clause(stmt.whereclause, obj)]
        return _FakeResult(candidates)


# ---------------------------------------------------------------------------
# 테스트용 factory 함수 — 유효한 최소 필드만 채우고 override로 조정한다.
# ---------------------------------------------------------------------------


def make_solar_request(*, user_id: uuid.UUID, now: datetime, **overrides) -> SolarRequest:
    fields = dict(
        id=uuid.uuid4(),
        user_id=user_id,
        plan_cycle_id=None,
        purpose=SolarRequestPurpose.NEW_CYCLE,
        status=SolarRequestStatus.EXECUTING,
        raw_input="테스트 입력",
        current_item_order=None,
        confirmed_at=now,
        execution_started_at=now,
        executed_at=None,
        execution_attempt_count=1,
        execution_result=None,
        error_code=None,
        error_message=None,
        result_acknowledged_at=None,
        created_at=now,
        updated_at=now,
    )
    fields.update(overrides)
    return SolarRequest(**fields)


def make_task_payload(
    *,
    title: str = "할 일",
    deadline_at_iso: str | None = None,
    estimated_minutes: int = 60,
    estimated_minutes_source: str = "USER",
    amount_text: str | None = None,
    amount_source: str | None = None,
) -> dict:
    return {
        "title": title,
        "deadlineAt": deadline_at_iso,
        "estimatedMinutes": estimated_minutes,
        "estimatedMinutesSource": estimated_minutes_source,
        "remainingMinutes": estimated_minutes,
        "amountText": amount_text,
        "amountSource": amount_source,
    }


def make_fixed_schedule_payload(*, title: str = "고정 일정", start_at_iso: str, end_at_iso: str) -> dict:
    return {"title": title, "startAt": start_at_iso, "endAt": end_at_iso}


def make_task_item(
    *, user_id: uuid.UUID, solar_request_id: uuid.UUID, item_order: int, payload: dict, **overrides
) -> SolarRequestItem:
    fields = dict(
        id=uuid.uuid4(),
        user_id=user_id,
        solar_request_id=solar_request_id,
        item_order=item_order,
        action=SolarAction.CREATE,
        entity_type=SolarEntityType.TASK,
        status=SolarItemStatus.READY,
        raw_line_text=payload["title"],
        normalized_payload=payload,
        missing_fields=[],
        pending_question=None,
        target_task_id=None,
        target_fixed_schedule_id=None,
        executed_at=None,
    )
    fields.update(overrides)
    return SolarRequestItem(**fields)


def make_fixed_schedule_item(
    *, user_id: uuid.UUID, solar_request_id: uuid.UUID, item_order: int, payload: dict, **overrides
) -> SolarRequestItem:
    fields = dict(
        id=uuid.uuid4(),
        user_id=user_id,
        solar_request_id=solar_request_id,
        item_order=item_order,
        action=SolarAction.CREATE,
        entity_type=SolarEntityType.FIXED_SCHEDULE,
        status=SolarItemStatus.READY,
        raw_line_text=payload["title"],
        normalized_payload=payload,
        missing_fields=[],
        pending_question=None,
        target_task_id=None,
        target_fixed_schedule_id=None,
        executed_at=None,
    )
    fields.update(overrides)
    return SolarRequestItem(**fields)
