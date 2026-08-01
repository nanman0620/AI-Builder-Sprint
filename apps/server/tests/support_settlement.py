from __future__ import annotations

from contextlib import AbstractContextManager

from sqlalchemy.sql.elements import TextClause

from tests.support_sql_eval import eval_clause as _eval_clause


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
