"""plan_block_before/at_or_after/strictly_after SQL predicate 단위 테스트.

두 층위로 독립 검증한다:
1. 컴파일된 SQL 문자열 — fake evaluator를 전혀 거치지 않고, PostgreSQL dialect로 리터럴
   바인딩까지 컴파일한 실제 연산자 토큰(<, >, >=)과 CASE 구조를 직접 확인한다. fake
   evaluator 쪽 구현 오류가 predicate 함수 쪽 오류를 가려서 둘 다 잘못됐는데 테스트만
   통과하는 상황을 막기 위함이다.
2. fake evaluator(eval_clause) — 실제 서비스 코드가 쓰는 것과 동일한 평가 경로로,
   MORNING/AFTERNOON/EVENING 전 구간의 이전/현재/이후 경계, 날짜가 바뀌는 경계를
   행동 수준에서 검증한다.
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.sql import operators

from app.models.enums import PlanPeriod
from app.models.plan_block import PlanBlock
from app.services.plan_block_service import (
    plan_block_at_or_after,
    plan_block_before,
    plan_block_strictly_after,
)
from tests.support_sql_eval import eval_clause

REF_DATE = date(2026, 7, 29)


# ---------------------------------------------------------------------------
# 1. SQL 표현식 트리 구조 직접 확인 (fake evaluator를 전혀 거치지 않는다)
#
# expr는 항상 or_(date_op_ref, and_(date_eq_ref, case_op_rank)) 형태의
# BooleanClauseList여야 한다. .clauses[0]/[1]과 각 BinaryExpression의 .operator/.right를
# 직접 읽어 실제 비교 연산자와 바인딩된 rank 값을 확인한다 — support_sql_eval.eval_clause의
# 구현 오류가 predicate 함수 쪽 오류를 가려서 둘 다 잘못됐는데 테스트만 통과하는 상황을
# 막기 위함이다.
# ---------------------------------------------------------------------------


def _unwrap_or(expr):
    date_cmp = expr.clauses[0]
    and_clause = expr.clauses[1]
    date_eq, rank_cmp = and_clause.clauses
    return date_cmp, date_eq, rank_cmp


def test_plan_block_before_uses_strict_less_than():
    expr = plan_block_before(PlanBlock.plan_date, PlanBlock.period, REF_DATE, PlanPeriod.AFTERNOON)
    date_cmp, date_eq, rank_cmp = _unwrap_or(expr)

    assert date_cmp.operator is operators.lt
    assert date_cmp.right.value == REF_DATE
    assert date_eq.operator is operators.eq
    assert rank_cmp.operator is operators.lt
    assert rank_cmp.right.value == 1  # AFTERNOON의 rank


def test_plan_block_at_or_after_uses_greater_than_and_gte():
    expr = plan_block_at_or_after(PlanBlock.plan_date, PlanBlock.period, REF_DATE, PlanPeriod.MORNING)
    date_cmp, date_eq, rank_cmp = _unwrap_or(expr)

    assert date_cmp.operator is operators.gt
    assert date_cmp.right.value == REF_DATE
    assert rank_cmp.operator is operators.ge
    assert rank_cmp.right.value == 0  # MORNING의 rank


def test_plan_block_strictly_after_uses_strict_greater_than():
    expr = plan_block_strictly_after(PlanBlock.plan_date, PlanBlock.period, REF_DATE, PlanPeriod.EVENING)
    date_cmp, date_eq, rank_cmp = _unwrap_or(expr)

    assert date_cmp.operator is operators.gt
    assert rank_cmp.operator is operators.gt
    assert rank_cmp.right.value == 2  # EVENING의 rank — EVENING보다 더 큰 rank는 없으므로
    # 같은 날짜에서는 항상 False가 되고, 실제로 "미래"가 되려면 날짜 자체가 달라져야 한다.


def test_case_expression_enumerates_all_three_periods_in_rank_order():
    expr = plan_block_before(PlanBlock.plan_date, PlanBlock.period, REF_DATE, PlanPeriod.EVENING)
    _, _, rank_cmp = _unwrap_or(expr)
    case_expr = rank_cmp.left

    whens = [(key.value, value.value) for key, value in case_expr.whens]
    assert whens == [(PlanPeriod.MORNING, 0), (PlanPeriod.AFTERNOON, 1), (PlanPeriod.EVENING, 2)]
    assert case_expr.value.key == "period"


# ---------------------------------------------------------------------------
# 2. fake evaluator 행동 검증 — MORNING/AFTERNOON/EVENING 전 경계
# ---------------------------------------------------------------------------


def _block(plan_date: date, period: PlanPeriod):
    return SimpleNamespace(plan_date=plan_date, period=period)


@pytest.mark.parametrize(
    "case_date,case_period,ref_period,expected_before,expected_at_or_after,expected_strictly_after",
    [
        # ---- reference: MORNING ----
        (REF_DATE, PlanPeriod.MORNING, PlanPeriod.MORNING, False, True, False),  # 같은 분기(경계 포함)
        (REF_DATE, PlanPeriod.AFTERNOON, PlanPeriod.MORNING, False, True, True),  # MORNING 이후
        (REF_DATE, PlanPeriod.EVENING, PlanPeriod.MORNING, False, True, True),
        (REF_DATE - timedelta(days=1), PlanPeriod.EVENING, PlanPeriod.MORNING, True, False, False),  # 전날 EVENING
        (REF_DATE - timedelta(days=1), PlanPeriod.MORNING, PlanPeriod.MORNING, True, False, False),  # MORNING 이전 날짜
        (REF_DATE + timedelta(days=1), PlanPeriod.MORNING, PlanPeriod.MORNING, False, True, True),  # 다음 날 MORNING

        # ---- reference: AFTERNOON ----
        (REF_DATE, PlanPeriod.MORNING, PlanPeriod.AFTERNOON, True, False, False),  # AFTERNOON 이전
        (REF_DATE, PlanPeriod.AFTERNOON, PlanPeriod.AFTERNOON, False, True, False),  # 현재(경계 포함)
        (REF_DATE, PlanPeriod.EVENING, PlanPeriod.AFTERNOON, False, True, True),  # AFTERNOON 이후

        # ---- reference: EVENING ----
        (REF_DATE, PlanPeriod.AFTERNOON, PlanPeriod.EVENING, True, False, False),  # EVENING 이전(같은 날짜)
        (REF_DATE, PlanPeriod.EVENING, PlanPeriod.EVENING, False, True, False),  # 현재(경계 포함)
        (REF_DATE + timedelta(days=1), PlanPeriod.MORNING, PlanPeriod.EVENING, False, True, True),  # 다음 날짜(EVENING 다음)
        (REF_DATE - timedelta(days=1), PlanPeriod.EVENING, PlanPeriod.EVENING, True, False, False),  # 전날 EVENING
    ],
)
def test_period_boundary_matrix(
    case_date, case_period, ref_period, expected_before, expected_at_or_after, expected_strictly_after
):
    block = _block(case_date, case_period)

    before_expr = plan_block_before(PlanBlock.plan_date, PlanBlock.period, REF_DATE, ref_period)
    at_or_after_expr = plan_block_at_or_after(PlanBlock.plan_date, PlanBlock.period, REF_DATE, ref_period)
    strictly_after_expr = plan_block_strictly_after(PlanBlock.plan_date, PlanBlock.period, REF_DATE, ref_period)

    assert eval_clause(before_expr, block) is expected_before
    assert eval_clause(at_or_after_expr, block) is expected_at_or_after
    assert eval_clause(strictly_after_expr, block) is expected_strictly_after

    # before/at_or_after는 항상 정확히 상호 배타적(제3의 상태 없음)이어야 한다.
    assert eval_clause(before_expr, block) != eval_clause(at_or_after_expr, block)
    # at_or_after는 strictly_after보다 항상 넓거나 같다(경계 포함 지점에서만 차이).
    if eval_clause(strictly_after_expr, block):
        assert eval_clause(at_or_after_expr, block)
