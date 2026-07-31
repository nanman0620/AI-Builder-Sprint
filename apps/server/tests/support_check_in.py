"""check_in_service·home_service 테스트 전용 범용 Fake Session.

기존 tests/support_settlement.py, test_deadline_warning_service.py의 Fake들과 달리
ORDER BY와 LIMIT까지 실제 SQLAlchemy Select 객체에서 읽어 평가한다. FINALIZING/
CHECK_IN_RESULT 선택 순서, acknowledge 응답 정렬처럼 이번 Issue의 정확성 요구가 정렬에
크게 의존하기 때문이다. WHERE 평가(and_/or_/is_/in_/비교연산자) 방식은 기존 Fake들과
동일한 패턴을 재사용한다.
"""

from __future__ import annotations

from contextlib import AbstractContextManager

from sqlalchemy.sql import operators as sa_operators
from sqlalchemy.sql.elements import BindParameter, BooleanClauseList, Grouping, Null


def _resolve_operand(side, obj):
    if isinstance(side, BindParameter):
        return side.value
    if isinstance(side, Null):
        return None
    key = getattr(side, "key", None)
    if key is not None and hasattr(obj, key):
        return getattr(obj, key)
    raise AssertionError(f"FakeCheckInSession이 처리할 수 없는 조건식입니다: {side!r}")


def _eval_clause(clause, obj) -> bool:
    if isinstance(clause, Grouping):
        # or_(...)/and_(...)가 다른 조건과 함께 .where()에 여러 인자로 전달되면
        # SQLAlchemy가 괄호 표현을 위해 Grouping으로 한 번 더 감싼다.
        return _eval_clause(clause.element, obj)

    if isinstance(clause, BooleanClauseList):
        results = [_eval_clause(sub, obj) for sub in clause.clauses]
        operator_name = getattr(clause.operator, "__name__", "")
        if operator_name == "and_":
            return all(results)
        if operator_name == "or_":
            return any(results)
        raise AssertionError(f"지원하지 않는 불리언 연산자입니다: {clause.operator}")

    op = clause.operator
    left = _resolve_operand(clause.left, obj)

    if op is sa_operators.in_op or op is sa_operators.not_in_op:
        right = clause.right.value if isinstance(clause.right, BindParameter) else clause.right
        member = left in right
        return member if op is sa_operators.in_op else not member
    if op is sa_operators.is_:
        return left is _resolve_operand(clause.right, obj)
    if op is sa_operators.is_not:
        return left is not _resolve_operand(clause.right, obj)

    right = _resolve_operand(clause.right, obj)
    return bool(op(left, right))


class _FakeScalars:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def one_or_none(self):
        if not self._rows:
            return None
        if len(self._rows) > 1:
            raise AssertionError(f"정확히 0~1건을 기대했지만 {len(self._rows)}건입니다.")
        return self._rows[0]


class _FakeResult:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def scalars(self):
        return _FakeScalars(self._rows)

    def scalar_one_or_none(self):
        return _FakeScalars(self._rows).one_or_none()


class _TransactionRecorder:
    def __init__(self):
        self.committed = False
        self.rolled_back = False


class _FakeTransaction(AbstractContextManager):
    def __init__(self, db: "FakeCheckInSession"):
        self._db = db

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._db.recorder.committed = True
        else:
            self._db.recorder.rolled_back = True
        return False


class FakeCheckInSession:
    """CheckIn/PlanBlock/PlanningCycle/Task/FixedSchedule 등 임의 엔티티를 지원하는 Fake.

    select().where().order_by().limit()를 실제로 평가하고, with_for_update()는 감지만
    한다(잠금 자체는 흉내내지 않음). forbid_begin=True면 db.begin() 호출 자체를 즉시
    실패시켜 GET류 조회 전용 서비스가 쓰기 트랜잭션을 열지 않는지 검증한다.
    """

    def __init__(self, *, forbid_begin: bool = False):
        self._rows: dict[type, list] = {}
        self.recorder = _TransactionRecorder()
        self.flush_calls = 0
        self.for_update_seen = False
        self.raise_on_flush: Exception | None = None
        self._forbid_begin = forbid_begin

    def seed(self, *objects):
        for obj in objects:
            self._rows.setdefault(type(obj), []).append(obj)
        return self

    def execute(self, stmt):
        if stmt._for_update_arg is not None:
            self.for_update_seen = True

        entity = stmt.column_descriptions[0]["entity"]
        candidates = list(self._rows.get(entity, []))

        whereclause = stmt.whereclause
        if whereclause is not None:
            candidates = [obj for obj in candidates if _eval_clause(whereclause, obj)]

        order_clauses = list(stmt._order_by_clauses)
        for clause in reversed(order_clauses):
            # .asc()/.desc()로 명시한 컬럼은 UnaryExpression(.modifier/.element)이고,
            # 아무 수식자 없이 넘긴 컬럼(기본 오름차순)은 컬럼 자체가 그대로 온다.
            has_modifier = hasattr(clause, "modifier") and hasattr(clause, "element")
            is_desc = has_modifier and clause.modifier is sa_operators.desc_op
            sort_key = clause.element.key if has_modifier else clause.key
            candidates.sort(key=lambda row: getattr(row, sort_key), reverse=is_desc)

        if stmt._limit is not None:
            candidates = candidates[: stmt._limit]

        return _FakeResult(candidates)

    def begin(self):
        if self._forbid_begin:
            raise AssertionError("이 서비스는 조회 전용이어야 하므로 db.begin()을 호출하면 안 된다.")
        return _FakeTransaction(self)

    def flush(self):
        self.flush_calls += 1
        if self.raise_on_flush is not None:
            raise self.raise_on_flush
