"""home_service.get_home_current_state의 우선순위 오케스트레이션(FINALIZING/CHECK_IN_RESULT/
DEADLINE_WARNING)을 검증한다.

CheckIn 선택 조건·정렬, CheckInResult 상세 구성의 세부 정확성은 tests/test_check_in_service.py가
직접 검증하므로, 여기서는 check_in_service.get_finalizing_info/get_check_in_result_state를
monkeypatch spy로 대체해 "홈이 어떤 순서로 무엇을 호출하고 조합하는지"만 검증한다.
DEADLINE_WARNING은 BE-10의 compute_deadline_warnings를 그대로 재사용하는지(복제하지 않는지)를
spy와 실제 통합 테스트 양쪽으로 검증한다.
"""

import uuid
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from app.models.enums import PlanBlockStatus, PlanCycleStatus, PlanPeriod
from app.services import check_in_service, deadline_warning_service, home_service
from app.services.check_in_service import CheckInResultState, FinalizingInfo
from app.services.deadline_warning_service import DeadlineWarningItem, DeadlineWarningNotice
from tests.support_check_in import FakeCheckInSession
from tests.support_scheduler import make_cycle, make_task

SEOUL = ZoneInfo("Asia/Seoul")

USER_ID = uuid.uuid4()
CYCLE_ID = uuid.uuid4()
NOW = datetime(2026, 7, 29, 14, 10, tzinfo=SEOUL)


def _finalizing_info(**overrides) -> FinalizingInfo:
    defaults = dict(
        check_in_id=uuid.uuid4(),
        check_date=date(2026, 7, 29),
        period=PlanPeriod.MORNING,
        finalization_started_at=NOW,
    )
    defaults.update(overrides)
    return FinalizingInfo(**defaults)


def _check_in_result_state(**overrides) -> CheckInResultState:
    defaults = dict(
        id=uuid.uuid4(),
        check_date=date(2026, 7, 29),
        period=PlanPeriod.MORNING,
        total_plan_count=3,
        completed_plan_count=2,
        not_done_plan_count=1,
        score=67,
        replan_unplaced_minutes=0,
        finalized_at=NOW,
        cycle_ended=False,
        completed_plans=[],
        not_done_plans=[],
    )
    defaults.update(overrides)
    return CheckInResultState(**defaults)


def _deadline_warning_notice(count: int = 1) -> DeadlineWarningNotice:
    items = [
        DeadlineWarningItem(
            task_id=uuid.uuid4(),
            title=f"과제{i}",
            deadline_at=NOW + timedelta(days=1),
            required_minutes=180,
            available_minutes=120,
            shortage_minutes=60,
            created_at=NOW,
        )
        for i in range(count)
    ]
    return DeadlineWarningNotice(items=items)


def _cycle(**overrides):
    defaults = dict(
        id=CYCLE_ID,
        user_id=USER_ID,
        start_date=date(2026, 7, 27),
        end_date=date(2026, 8, 2),
        status=PlanCycleStatus.ACTIVE,
        activated_at=datetime(2026, 7, 27, 4, 0, tzinfo=SEOUL),
        ended_at=None,
    )
    defaults.update(overrides)
    from app.models.planning_cycle import PlanningCycle

    return PlanningCycle(**defaults)


def _patch_check_in_service(monkeypatch, *, finalizing=None, check_in_result=None):
    finalizing_spy = MagicMock(return_value=finalizing)
    result_spy = MagicMock(return_value=check_in_result)
    monkeypatch.setattr(check_in_service, "get_finalizing_info", finalizing_spy)
    monkeypatch.setattr(check_in_service, "get_check_in_result_state", result_spy)
    return finalizing_spy, result_spy


def _patch_deadline_warning(monkeypatch, *, notice=None):
    spy = MagicMock(return_value=notice)
    monkeypatch.setattr(deadline_warning_service, "compute_deadline_warnings", spy)
    return spy


# ---------------------------------------------------------------------------
# 1~3. 우선순위: FINALIZING > CHECK_IN_RESULT > DEADLINE_WARNING
# ---------------------------------------------------------------------------


def test_finalizing_only_returns_finalizing_mode(monkeypatch):
    info = _finalizing_info()
    finalizing_spy, result_spy = _patch_check_in_service(monkeypatch, finalizing=info)
    warning_spy = _patch_deadline_warning(monkeypatch, notice=_deadline_warning_notice())
    db = FakeCheckInSession(forbid_begin=True)

    state = home_service.get_home_current_state(db, USER_ID, now=NOW)

    assert state.home_mode == home_service.HomeMode.FINALIZING
    assert state.finalizing is info
    assert state.check_in_result is None
    assert state.blocking_notice is None
    assert state.progress is None
    assert state.plan_blocks == []
    # FINALIZING이 확정되면 뒤 단계(CHECK_IN_RESULT/DEADLINE_WARNING)는 계산하지 않는다.
    result_spy.assert_not_called()
    warning_spy.assert_not_called()


def test_finalizing_takes_priority_over_check_in_result(monkeypatch):
    info = _finalizing_info()
    result_state = _check_in_result_state()
    finalizing_spy, result_spy = _patch_check_in_service(
        monkeypatch, finalizing=info, check_in_result=result_state
    )

    db = FakeCheckInSession(forbid_begin=True)
    state = home_service.get_home_current_state(db, USER_ID, now=NOW)

    assert state.home_mode == home_service.HomeMode.FINALIZING
    # FINALIZING이 있으면 CHECK_IN_RESULT 후보 조회 자체를 하지 않는다.
    result_spy.assert_not_called()


def test_check_in_result_takes_priority_over_deadline_warning(monkeypatch):
    result_state = _check_in_result_state()
    _patch_check_in_service(monkeypatch, finalizing=None, check_in_result=result_state)
    warning_spy = _patch_deadline_warning(monkeypatch, notice=_deadline_warning_notice())

    db = FakeCheckInSession(forbid_begin=True)
    state = home_service.get_home_current_state(db, USER_ID, now=NOW)

    assert state.home_mode == home_service.HomeMode.CHECK_IN_RESULT
    assert state.check_in_result is result_state
    assert state.blocking_notice is None
    # CHECK_IN_RESULT가 확정되면 DEADLINE_WARNING은 계산하지 않는다.
    warning_spy.assert_not_called()


def test_check_in_result_without_active_cycle(monkeypatch):
    """ACTIVE cycle이 없어도 미확인 CheckIn 결과가 있으면 CHECK_IN_RESULT를 반환한다."""
    result_state = _check_in_result_state()
    _patch_check_in_service(monkeypatch, finalizing=None, check_in_result=result_state)

    db = FakeCheckInSession(forbid_begin=True)  # ACTIVE cycle 시드 없음
    state = home_service.get_home_current_state(db, USER_ID, now=NOW)

    assert state.home_mode == home_service.HomeMode.CHECK_IN_RESULT
    assert state.active_cycle is None


# ---------------------------------------------------------------------------
# 14~15. DEADLINE_WARNING이 기본 홈 상태를 유지한 채 blockingNotice로 부착되는지
# ---------------------------------------------------------------------------


def test_no_plans_with_deadline_warning_keeps_home_mode(monkeypatch):
    _patch_check_in_service(monkeypatch, finalizing=None, check_in_result=None)
    notice = _deadline_warning_notice()
    warning_spy = _patch_deadline_warning(monkeypatch, notice=notice)

    cycle = _cycle()
    db = FakeCheckInSession(forbid_begin=True).seed(cycle)
    state = home_service.get_home_current_state(db, USER_ID, now=NOW)

    assert state.home_mode == home_service.HomeMode.NO_PLANS
    assert state.blocking_notice is notice
    assert state.progress.percentage == 0
    warning_spy.assert_called_once()


def test_in_progress_with_deadline_warning_keeps_home_mode_and_progress(monkeypatch):
    from app.models.plan_block import PlanBlock

    _patch_check_in_service(monkeypatch, finalizing=None, check_in_result=None)
    notice = _deadline_warning_notice()
    _patch_deadline_warning(monkeypatch, notice=notice)

    cycle = _cycle()
    block = PlanBlock(
        id=uuid.uuid4(),
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        task_id=uuid.uuid4(),
        plan_date=date(2026, 7, 29),
        period=PlanPeriod.AFTERNOON,
        allocated_minutes=60,
        allocated_amount_text=None,
        display_title="계획",
        display_order=0,
        status=PlanBlockStatus.CHECKED,
        checked_at=NOW,
    )
    db = FakeCheckInSession(forbid_begin=True).seed(cycle, block)
    state = home_service.get_home_current_state(db, USER_ID, now=NOW)

    assert state.home_mode == home_service.HomeMode.IN_PROGRESS
    assert state.blocking_notice is notice
    assert state.progress.checked_count == 1
    assert state.plan_blocks == [block]


def test_deadline_warning_absent_when_no_candidates(monkeypatch):
    _patch_check_in_service(monkeypatch, finalizing=None, check_in_result=None)
    _patch_deadline_warning(monkeypatch, notice=None)

    cycle = _cycle()
    db = FakeCheckInSession(forbid_begin=True).seed(cycle)
    state = home_service.get_home_current_state(db, USER_ID, now=NOW)

    assert state.blocking_notice is None


def test_single_deadline_warning_item_still_uses_items_array():
    """items가 1건이어도 배열 형태를 유지해야 한다(명세: 단일 blockingNotice.task 금지)."""
    from app.schemas.home import to_blocking_notice_out

    notice = _deadline_warning_notice(count=1)

    out = to_blocking_notice_out(notice)

    assert isinstance(out.items, list)
    assert len(out.items) == 1
    assert out.type == "DEADLINE_WARNING"


# ---------------------------------------------------------------------------
# 16. 고정 일정만 존재하면 NO_PLANS
# ---------------------------------------------------------------------------


def test_only_fixed_schedule_is_no_plans(monkeypatch):
    from app.models.fixed_schedule import FixedSchedule

    _patch_check_in_service(monkeypatch, finalizing=None, check_in_result=None)
    _patch_deadline_warning(monkeypatch, notice=None)

    cycle = _cycle()
    fixed = FixedSchedule(
        id=uuid.uuid4(),
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        source_request_item_id=None,
        title="수업",
        start_at=datetime(2026, 7, 29, 13, 0, tzinfo=SEOUL),
        end_at=datetime(2026, 7, 29, 14, 0, tzinfo=SEOUL),
    )
    db = FakeCheckInSession(forbid_begin=True).seed(cycle, fixed)
    state = home_service.get_home_current_state(db, USER_ID, now=NOW)

    assert state.home_mode == home_service.HomeMode.NO_PLANS
    assert state.plan_blocks == []


# ---------------------------------------------------------------------------
# 19. GET 호출은 FINALIZING/CHECK_IN_RESULT 경로에서도 DB를 쓰지 않는다
# ---------------------------------------------------------------------------


def test_finalizing_path_never_opens_write_transaction(monkeypatch):
    _patch_check_in_service(monkeypatch, finalizing=_finalizing_info(), check_in_result=None)
    db = FakeCheckInSession(forbid_begin=True)

    home_service.get_home_current_state(db, USER_ID, now=NOW)
    # forbid_begin=True인 Fake가 예외 없이 끝났다는 것 자체가 begin() 미호출의 증거다.


def test_check_in_result_path_never_opens_write_transaction(monkeypatch):
    _patch_check_in_service(
        monkeypatch, finalizing=None, check_in_result=_check_in_result_state()
    )
    db = FakeCheckInSession(forbid_begin=True)

    home_service.get_home_current_state(db, USER_ID, now=NOW)


# ---------------------------------------------------------------------------
# 실제 BE-10 compute_deadline_warnings와의 통합(monkeypatch 없이 실제 계산 경로)
# ---------------------------------------------------------------------------


def test_in_progress_with_real_deadline_warning_service_integration(monkeypatch):
    """compute_deadline_warnings를 monkeypatch하지 않고 실제 BE-10 로직으로 경고를 계산한다.

    home_service가 BE-10 계산을 복제하지 않고 그대로 호출해 통합되는지 증명한다.
    """
    _patch_check_in_service(monkeypatch, finalizing=None, check_in_result=None)

    cycle = make_cycle(
        user_id=USER_ID,
        start_date=date(2026, 7, 27),
        end_date=date(2026, 8, 2),
        id=CYCLE_ID,
        activated_at=datetime(2026, 7, 27, 4, 0, tzinfo=SEOUL),
    )
    # remaining_minutes를 매우 크게 잡아 사용 가능 시간(최대 2개 분기 480분)을 확실히
    # 초과시킨다 — BE-10 자체의 세부 용량 계산은 BE-10 테스트가 이미 검증한다.
    tight_task = make_task(
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        remaining_minutes=1000,
        deadline_at=datetime(2026, 7, 29, 20, 0, tzinfo=SEOUL),
        created_at=datetime(2026, 7, 27, 5, 0, tzinfo=SEOUL),
        title="촉박한 과제",
    )
    db = FakeCheckInSession(forbid_begin=True).seed(cycle, tight_task)

    state = home_service.get_home_current_state(db, USER_ID, now=NOW)

    assert state.home_mode == home_service.HomeMode.NO_PLANS
    assert state.blocking_notice is not None
    assert len(state.blocking_notice.items) == 1
    assert state.blocking_notice.items[0].task_id == tight_task.id
    assert state.blocking_notice.items[0].shortage_minutes > 0
