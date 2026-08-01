"""fake in-memory SQL WHERE절 평가기 — 여러 support_*.py fake Session이 공유한다.

실제 PostgreSQL 없이, SQLAlchemy가 만드는 `Select.whereclause` 트리를 순수 Python 객체
비교로 평가한다. 이 프로젝트의 서비스 코드가 실제로 만드는 형태(entity 컬럼 vs 상수 비교,
and_/or_로 묶인 조건, `Case` 기반 분기 순위 비교, `in_`/`is_`)만 지원 범위로 한정하며,
지원하지 않는 구조를 만나면 조용히 잘못된 결과를 내는 대신 `AssertionError`로 실패한다.

여러 support 파일(support_scheduler.py, support_settlement.py,
support_active_cycle_execution.py 등)이 각자 `_resolve_operand`/`_eval_clause`를 복제해
두면 한쪽만 고쳐 drift가 생기기 쉬우므로, 이 모듈 하나만 확장한다.
"""

from __future__ import annotations

from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import (
    BinaryExpression,
    BindParameter,
    BooleanClauseList,
    Case,
    Grouping,
    Null,
)


def resolve_operand(side, obj):
    """WHERE절의 한쪽 피연산자를 실제 Python 값으로 변환한다.

    - BindParameter: 바인딩된 리터럴 값
    - Null: SQL NULL → None
    - Case: 아래 _eval_case로 위임
    - 그 외(컬럼 attribute): obj의 동일 이름 attribute 값
    """
    if isinstance(side, BindParameter):
        return side.value
    if isinstance(side, Null):
        return None
    if isinstance(side, Case):
        return _eval_case(side, obj)
    key = getattr(side, "key", None)
    if key is not None and hasattr(obj, key):
        return getattr(obj, key)
    raise AssertionError(f"fake SQL evaluator가 처리할 수 없는 피연산자입니다: {side!r}")


def _eval_case(case_expr: Case, obj) -> object:
    """`case({...}, value=column)` 단순형과 `case((cond, result), ...)` 탐색형을 모두 지원한다."""
    if case_expr.value is not None:
        switch_value = resolve_operand(case_expr.value, obj)
        for when_clause, result_clause in case_expr.whens:
            if resolve_operand(when_clause, obj) == switch_value:
                return resolve_operand(result_clause, obj)
    else:
        for when_clause, result_clause in case_expr.whens:
            if eval_clause(when_clause, obj):
                return resolve_operand(result_clause, obj)
    if case_expr.else_ is not None:
        return resolve_operand(case_expr.else_, obj)
    return None


def eval_clause(clause, obj) -> bool:
    """WHERE절(불리언 조건식) 하나를 obj 하나에 대해 평가한다."""
    if isinstance(clause, Grouping):
        # select(...).where(A, B)처럼 여러 조건을 암묵적 AND로 묶을 때, B가 or_(...)이면
        # 우선순위 보존을 위해 SQLAlchemy가 괄호(Grouping)로 감싼다 — 내부 조건만 평가하면 된다.
        return eval_clause(clause.element, obj)

    if isinstance(clause, BooleanClauseList):
        results = [eval_clause(sub, obj) for sub in clause.clauses]
        operator_name = getattr(clause.operator, "__name__", "")
        if operator_name == "and_":
            return all(results)
        if operator_name == "or_":
            return any(results)
        raise AssertionError(f"지원하지 않는 불리언 연산자입니다: {clause.operator}")

    if isinstance(clause, BinaryExpression):
        left = resolve_operand(clause.left, obj)
        right = resolve_operand(clause.right, obj)
        if clause.operator is operators.in_op:
            return left in right
        if clause.operator is operators.not_in_op:
            return left not in right
        if clause.operator is operators.is_:
            return left is right
        if clause.operator is operators.is_not:
            return left is not right
        return bool(clause.operator(left, right))

    raise AssertionError(f"fake SQL evaluator가 처리할 수 없는 조건식입니다: {clause!r}")
