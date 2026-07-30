from __future__ import annotations

from contextlib import AbstractContextManager

from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BindParameter, BooleanClauseList, Null, TextClause


def _resolve_operand(side, obj):
    if isinstance(side, BindParameter):
        return side.value
    if isinstance(side, Null):
        return None
    key = getattr(side, "key", None)
    if key is not None and hasattr(obj, key):
        return getattr(obj, key)
    raise AssertionError(f"FakeSettlementSession이 처리할 수 없는 조건식입니다: {side!r}")


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


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeResult:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def scalars(self):
        return _FakeScalars(self._rows)

    def scalar_one_or_none(self):
        if not self._rows:
            return None
        if len(self._rows) != 1:
            raise AssertionError(f"정확히 0~1건을 기대했지만 {len(self._rows)}건입니다.")
        return self._rows[0]


class _Transaction(AbstractContextManager):
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        self.db.transaction_count += 1
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.db.commit_count += 1
        else:
            self.db.rollback_count += 1
        return False


class FakeSettlementSession:
    def __init__(self):
        self._rows: dict[type, list] = {}
        self._pending_add: list = []
        self.transaction_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.flush_count = 0
        self.advisory_lock_keys: list[int] = []
        self.executed_statements: list = []
        self.closed = False

    def seed(self, *rows):
        for row in rows:
            self._rows.setdefault(type(row), []).append(row)
        return self

    def begin(self):
        return _Transaction(self)

    def add(self, row):
        self._pending_add.append(row)

    def flush(self):
        self.flush_count += 1
        for row in self._pending_add:
            self._rows.setdefault(type(row), []).append(row)
        self._pending_add.clear()

    def execute(self, stmt, params=None):
        self.executed_statements.append(stmt)
        if isinstance(stmt, TextClause):
            self.advisory_lock_keys.append(params["lock_key"])
            return _FakeResult()

        entity = stmt.column_descriptions[0]["entity"]
        candidates = list(self._rows.get(entity, []))
        if stmt.whereclause is not None:
            candidates = [row for row in candidates if _eval_clause(stmt.whereclause, row)]
        return _FakeResult(candidates)

    def rollback(self):
        self.rollback_count += 1
        self._pending_add.clear()

    def close(self):
        self.closed = True

    def all_rows(self, model):
        return list(self._rows.get(model, []))
