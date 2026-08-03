import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.core.errors import ApiError
from app.models.check_in import CheckIn
from app.models.enums import PlanBlockStatus, PlanCycleStatus, PlanPeriod
from app.models.plan_block import PlanBlock
from app.models.planning_cycle import PlanningCycle
from app.services import check_in_service
from tests.support_check_in import FakeCheckInSession

SEOUL = ZoneInfo("Asia/Seoul")

USER_ID = uuid.uuid4()
OTHER_USER_ID = uuid.uuid4()
CYCLE_ID = uuid.uuid4()

NOW = datetime(2026, 7, 29, 15, 0, tzinfo=SEOUL)


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
    return PlanningCycle(**defaults)


def _check_in(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        check_date=date(2026, 7, 29),
        period=PlanPeriod.MORNING,
        total_plan_count=None,
        completed_plan_count=None,
        score=None,
        replan_unplaced_minutes=None,
        finalization_started_at=datetime(2026, 7, 29, 12, 0, tzinfo=SEOUL),
        replanned_at=None,
        finalized_at=None,
        result_acknowledged_at=None,
    )
    defaults.update(overrides)
    return CheckIn(**defaults)


def _finalized_check_in(**overrides):
    defaults = dict(
        total_plan_count=3,
        completed_plan_count=2,
        score=67,
        replan_unplaced_minutes=0,
        finalized_at=datetime(2026, 7, 29, 12, 0, 5, tzinfo=SEOUL),
    )
    defaults.update(overrides)
    return _check_in(**defaults)


def _block(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        user_id=USER_ID,
        plan_cycle_id=CYCLE_ID,
        task_id=uuid.uuid4(),
        plan_date=date(2026, 7, 29),
        period=PlanPeriod.MORNING,
        allocated_minutes=30,
        allocated_amount_text=None,
        display_title="블록",
        display_order=0,
        status=PlanBlockStatus.COMPLETED,
        checked_at=NOW,
        check_in_id=None,
    )
    defaults.update(overrides)
    return PlanBlock(**defaults)


# ---------------------------------------------------------------------------
# get_finalizing_info
# ---------------------------------------------------------------------------


def test_get_finalizing_info_returns_none_when_no_unfinalized_check_in():
    db = FakeCheckInSession().seed(_finalized_check_in(result_acknowledged_at=NOW))

    assert check_in_service.get_finalizing_info(db, USER_ID) is None


def test_get_finalizing_info_returns_details():
    check_in = _check_in(
        check_date=date(2026, 7, 29),
        period=PlanPeriod.AFTERNOON,
        finalization_started_at=datetime(2026, 7, 29, 18, 0, tzinfo=SEOUL),
    )
    db = FakeCheckInSession().seed(check_in)

    info = check_in_service.get_finalizing_info(db, USER_ID)

    assert info.check_in_id == check_in.id
    assert info.check_date == date(2026, 7, 29)
    assert info.period == PlanPeriod.AFTERNOON
    assert info.finalization_started_at == datetime(2026, 7, 29, 18, 0, tzinfo=SEOUL)


def test_get_finalizing_info_selects_latest_started_at_then_id():
    same_start = datetime(2026, 7, 29, 12, 0, tzinfo=SEOUL)
    low_id = _check_in(id=uuid.UUID(int=1), finalization_started_at=same_start)
    high_id = _check_in(id=uuid.UUID(int=2), finalization_started_at=same_start)
    earlier = _check_in(id=uuid.UUID(int=99), finalization_started_at=same_start.replace(hour=6))
    db = FakeCheckInSession().seed(low_id, high_id, earlier)

    info = check_in_service.get_finalizing_info(db, USER_ID)

    # 동일 finalization_started_at 중에서는 id DESC로 선택한다.
    assert info.check_in_id == high_id.id


def test_get_finalizing_info_ignores_other_users_check_in():
    other = _check_in(user_id=OTHER_USER_ID)
    db = FakeCheckInSession().seed(other)

    assert check_in_service.get_finalizing_info(db, USER_ID) is None


# ---------------------------------------------------------------------------
# get_check_in_result_state
# ---------------------------------------------------------------------------


def test_get_check_in_result_state_returns_none_when_nothing_unacknowledged():
    db = FakeCheckInSession()

    assert check_in_service.get_check_in_result_state(db, USER_ID) is None


def test_get_check_in_result_state_ignores_already_acknowledged():
    check_in = _finalized_check_in(result_acknowledged_at=NOW)
    db = FakeCheckInSession().seed(_cycle(), check_in)

    assert check_in_service.get_check_in_result_state(db, USER_ID) is None


def test_get_check_in_result_state_selects_latest_finalized_at_then_id():
    same_finalized = datetime(2026, 7, 29, 12, 0, 5, tzinfo=SEOUL)
    low_id = _finalized_check_in(id=uuid.UUID(int=1), finalized_at=same_finalized)
    high_id = _finalized_check_in(id=uuid.UUID(int=2), finalized_at=same_finalized)
    earlier = _finalized_check_in(id=uuid.UUID(int=99), finalized_at=same_finalized.replace(hour=6))
    db = FakeCheckInSession().seed(_cycle(), low_id, high_id, earlier)

    state = check_in_service.get_check_in_result_state(db, USER_ID)

    assert state.id == high_id.id


def test_get_check_in_result_state_works_without_active_cycle():
    """ACTIVE cycle이 없어도(cycle이 ENDED거나 아예 조회되지 않아도) 결과는 반환돼야 한다."""
    ended_cycle = _cycle(status=PlanCycleStatus.ENDED, ended_at=NOW)
    check_in = _finalized_check_in()
    db = FakeCheckInSession().seed(ended_cycle, check_in)

    state = check_in_service.get_check_in_result_state(db, USER_ID)

    assert state is not None
    assert state.id == check_in.id


def test_get_check_in_result_state_computes_not_done_from_stored_counts():
    check_in = _finalized_check_in(total_plan_count=7, completed_plan_count=3)
    db = FakeCheckInSession().seed(_cycle(), check_in)

    state = check_in_service.get_check_in_result_state(db, USER_ID)

    assert state.total_plan_count == 7
    assert state.completed_plan_count == 3
    assert state.not_done_plan_count == 4
    # score/replanUnplacedMinutes도 저장값을 그대로 쓴다(재계산 없음).
    assert state.score == check_in.score
    assert state.replan_unplaced_minutes == check_in.replan_unplaced_minutes


@pytest.mark.parametrize(
    ("cycle_status", "expected"),
    [(PlanCycleStatus.ENDED, True), (PlanCycleStatus.ACTIVE, False)],
)
def test_get_check_in_result_state_cycle_ended_from_check_ins_own_cycle(cycle_status, expected):
    cycle = _cycle(
        status=cycle_status, ended_at=NOW if cycle_status == PlanCycleStatus.ENDED else None
    )
    check_in = _finalized_check_in()
    db = FakeCheckInSession().seed(cycle, check_in)

    state = check_in_service.get_check_in_result_state(db, USER_ID)

    assert state.cycle_ended is expected


def test_get_check_in_result_state_splits_completed_and_not_done_and_uses_stored_display_title():
    check_in = _finalized_check_in()
    completed = _block(
        id=uuid.UUID(int=1),
        display_order=0,
        display_title="자료구조 2문제",
        status=PlanBlockStatus.COMPLETED,
        checked_at=NOW,
        check_in_id=check_in.id,
    )
    not_done = _block(
        id=uuid.UUID(int=2),
        display_order=1,
        display_title="영단어 암기",
        status=PlanBlockStatus.NOT_DONE,
        checked_at=None,
        check_in_id=check_in.id,
    )
    # 다른 CheckIn 소속 PlanBlock은 섞이지 않아야 한다.
    unrelated = _block(check_in_id=uuid.uuid4())
    db = FakeCheckInSession().seed(_cycle(), check_in, completed, not_done, unrelated)

    state = check_in_service.get_check_in_result_state(db, USER_ID)

    assert [b.id for b in state.completed_plans] == [completed.id]
    assert state.completed_plans[0].display_title == "자료구조 2문제"
    assert state.completed_plans[0].status == PlanBlockStatus.COMPLETED
    assert [b.id for b in state.not_done_plans] == [not_done.id]
    assert state.not_done_plans[0].display_title == "영단어 암기"


def test_get_check_in_result_state_orders_plan_blocks_by_display_order_then_id():
    check_in = _finalized_check_in()
    later_order = _block(
        id=uuid.UUID(int=1),
        display_order=1,
        status=PlanBlockStatus.COMPLETED,
        check_in_id=check_in.id,
    )
    tie_low_id = _block(
        id=uuid.UUID(int=2),
        display_order=0,
        status=PlanBlockStatus.COMPLETED,
        check_in_id=check_in.id,
    )
    tie_high_id = _block(
        id=uuid.UUID(int=3),
        display_order=0,
        status=PlanBlockStatus.COMPLETED,
        check_in_id=check_in.id,
    )
    db = FakeCheckInSession().seed(_cycle(), check_in, later_order, tie_low_id, tie_high_id)

    state = check_in_service.get_check_in_result_state(db, USER_ID)

    assert [b.id for b in state.completed_plans] == [tie_low_id.id, tie_high_id.id, later_order.id]


# ---------------------------------------------------------------------------
# acknowledge_check_in — 최초 요청
# ---------------------------------------------------------------------------


def test_acknowledge_check_in_target_only():
    target = _finalized_check_in()
    db = FakeCheckInSession().seed(target)

    result = check_in_service.acknowledge_check_in(
        db, user_id=USER_ID, check_in_id=target.id, now=NOW
    )

    assert result.target_check_in_id == target.id
    assert result.acknowledged_check_in_ids == [target.id]
    assert result.result_acknowledged_at == NOW
    assert target.result_acknowledged_at == NOW
    assert db.recorder.committed is True
    assert db.for_update_seen is True


def test_acknowledge_check_in_includes_older_unacknowledged_results():
    older = _finalized_check_in(
        id=uuid.UUID(int=1), finalized_at=datetime(2026, 7, 29, 6, 0, 5, tzinfo=SEOUL)
    )
    target = _finalized_check_in(
        id=uuid.UUID(int=2), finalized_at=datetime(2026, 7, 29, 12, 0, 5, tzinfo=SEOUL)
    )
    db = FakeCheckInSession().seed(older, target)

    result = check_in_service.acknowledge_check_in(
        db, user_id=USER_ID, check_in_id=target.id, now=NOW
    )

    assert result.acknowledged_check_in_ids == [older.id, target.id]
    assert older.result_acknowledged_at == NOW
    assert target.result_acknowledged_at == NOW


def test_acknowledge_check_in_does_not_touch_newer_results():
    target = _finalized_check_in(
        id=uuid.UUID(int=1), finalized_at=datetime(2026, 7, 29, 12, 0, 5, tzinfo=SEOUL)
    )
    newer = _finalized_check_in(
        id=uuid.UUID(int=2), finalized_at=datetime(2026, 7, 29, 18, 0, 5, tzinfo=SEOUL)
    )
    db = FakeCheckInSession().seed(target, newer)

    result = check_in_service.acknowledge_check_in(
        db, user_id=USER_ID, check_in_id=target.id, now=NOW
    )

    assert result.acknowledged_check_in_ids == [target.id]
    assert newer.result_acknowledged_at is None


def test_acknowledge_check_in_applies_id_boundary_at_same_finalized_at():
    same_finalized_at = datetime(2026, 7, 29, 12, 0, 5, tzinfo=SEOUL)
    target = _finalized_check_in(id=uuid.UUID(int=5), finalized_at=same_finalized_at)
    lower_id_same_time = _finalized_check_in(id=uuid.UUID(int=3), finalized_at=same_finalized_at)
    higher_id_same_time = _finalized_check_in(id=uuid.UUID(int=9), finalized_at=same_finalized_at)
    db = FakeCheckInSession().seed(target, lower_id_same_time, higher_id_same_time)

    result = check_in_service.acknowledge_check_in(
        db, user_id=USER_ID, check_in_id=target.id, now=NOW
    )

    assert result.acknowledged_check_in_ids == [lower_id_same_time.id, target.id]
    assert higher_id_same_time.result_acknowledged_at is None


def test_acknowledge_check_in_stores_same_now_for_all_targets():
    older = _finalized_check_in(
        id=uuid.UUID(int=1), finalized_at=datetime(2026, 7, 29, 6, 0, 5, tzinfo=SEOUL)
    )
    target = _finalized_check_in(
        id=uuid.UUID(int=2), finalized_at=datetime(2026, 7, 29, 12, 0, 5, tzinfo=SEOUL)
    )
    db = FakeCheckInSession().seed(older, target)

    check_in_service.acknowledge_check_in(db, user_id=USER_ID, check_in_id=target.id, now=NOW)

    assert older.result_acknowledged_at == target.result_acknowledged_at == NOW


def test_acknowledge_check_in_response_sorted_finalized_at_asc_id_asc():
    a = _finalized_check_in(
        id=uuid.UUID(int=30), finalized_at=datetime(2026, 7, 29, 6, 0, 5, tzinfo=SEOUL)
    )
    b = _finalized_check_in(
        id=uuid.UUID(int=10), finalized_at=datetime(2026, 7, 29, 8, 0, 5, tzinfo=SEOUL)
    )
    target = _finalized_check_in(
        id=uuid.UUID(int=20), finalized_at=datetime(2026, 7, 29, 12, 0, 5, tzinfo=SEOUL)
    )
    db = FakeCheckInSession().seed(a, b, target)

    result = check_in_service.acknowledge_check_in(
        db, user_id=USER_ID, check_in_id=target.id, now=NOW
    )

    assert result.acknowledged_check_in_ids == [a.id, b.id, target.id]


def test_acknowledge_check_in_does_not_touch_other_users_unacknowledged_results():
    target = _finalized_check_in(id=uuid.UUID(int=1))
    other_user_check_in = _finalized_check_in(
        id=uuid.UUID(int=2),
        user_id=OTHER_USER_ID,
        finalized_at=datetime(2026, 7, 29, 6, 0, 5, tzinfo=SEOUL),
    )
    db = FakeCheckInSession().seed(target, other_user_check_in)

    result = check_in_service.acknowledge_check_in(
        db, user_id=USER_ID, check_in_id=target.id, now=NOW
    )

    assert result.acknowledged_check_in_ids == [target.id]
    assert other_user_check_in.result_acknowledged_at is None


# ---------------------------------------------------------------------------
# acknowledge_check_in — 오류
# ---------------------------------------------------------------------------


def test_acknowledge_check_in_missing_raises_404():
    db = FakeCheckInSession()

    with pytest.raises(ApiError) as exc_info:
        check_in_service.acknowledge_check_in(
            db, user_id=USER_ID, check_in_id=uuid.uuid4(), now=NOW
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == check_in_service.CODE_CHECK_IN_NOT_FOUND


def test_acknowledge_check_in_other_users_check_in_raises_404_same_as_missing():
    other = _finalized_check_in(user_id=OTHER_USER_ID)
    db = FakeCheckInSession().seed(other)

    with pytest.raises(ApiError) as exc_info:
        check_in_service.acknowledge_check_in(
            db, user_id=USER_ID, check_in_id=other.id, now=NOW
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == check_in_service.CODE_CHECK_IN_NOT_FOUND


def test_acknowledge_check_in_not_finalized_raises_409():
    unfinalized = _check_in()
    db = FakeCheckInSession().seed(unfinalized)

    with pytest.raises(ApiError) as exc_info:
        check_in_service.acknowledge_check_in(
            db, user_id=USER_ID, check_in_id=unfinalized.id, now=NOW
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == check_in_service.CODE_INVALID_REQUEST_STATE


def test_acknowledge_check_in_flush_failure_rolls_back_transaction():
    target = _finalized_check_in()
    db = FakeCheckInSession().seed(target)
    db.raise_on_flush = RuntimeError("시뮬레이션된 DB 오류")

    with pytest.raises(RuntimeError):
        check_in_service.acknowledge_check_in(
            db, user_id=USER_ID, check_in_id=target.id, now=NOW
        )

    assert db.recorder.rolled_back is True
    assert db.recorder.committed is False


# ---------------------------------------------------------------------------
# acknowledge_check_in — 이미 확인된 target 재호출(멱등)
# ---------------------------------------------------------------------------


def test_acknowledge_check_in_duplicate_call_keeps_existing_result_acknowledged_at():
    original_ack_at = datetime(2026, 7, 29, 14, 45, tzinfo=SEOUL)
    target = _finalized_check_in(result_acknowledged_at=original_ack_at)
    db = FakeCheckInSession().seed(target)
    replay_now = datetime(2026, 7, 29, 20, 0, tzinfo=SEOUL)  # 최초 확인과는 다른 now

    result = check_in_service.acknowledge_check_in(
        db, user_id=USER_ID, check_in_id=target.id, now=replay_now
    )

    assert result.result_acknowledged_at == original_ack_at
    assert target.result_acknowledged_at == original_ack_at  # 덮어쓰지 않음


def test_acknowledge_check_in_duplicate_call_does_not_mutate_db():
    original_ack_at = datetime(2026, 7, 29, 14, 45, tzinfo=SEOUL)
    target = _finalized_check_in(result_acknowledged_at=original_ack_at)
    db = FakeCheckInSession().seed(target)
    replay_now = datetime(2026, 7, 29, 20, 0, tzinfo=SEOUL)

    check_in_service.acknowledge_check_in(
        db, user_id=USER_ID, check_in_id=target.id, now=replay_now
    )

    assert db.flush_calls == 0


def test_acknowledge_check_in_duplicate_call_reconstructs_original_batch():
    original_ack_at = datetime(2026, 7, 29, 14, 45, tzinfo=SEOUL)
    older = _finalized_check_in(
        id=uuid.UUID(int=1),
        finalized_at=datetime(2026, 7, 29, 6, 0, 5, tzinfo=SEOUL),
        result_acknowledged_at=original_ack_at,
    )
    target = _finalized_check_in(
        id=uuid.UUID(int=2),
        finalized_at=datetime(2026, 7, 29, 12, 0, 5, tzinfo=SEOUL),
        result_acknowledged_at=original_ack_at,
    )
    db = FakeCheckInSession().seed(older, target)
    replay_now = datetime(2026, 7, 29, 20, 0, tzinfo=SEOUL)

    result = check_in_service.acknowledge_check_in(
        db, user_id=USER_ID, check_in_id=target.id, now=replay_now
    )

    assert result.acknowledged_check_in_ids == [older.id, target.id]
    assert result.acknowledged_check_in_ids[-1] == target.id


def test_acknowledge_check_in_duplicate_call_excludes_later_batch_at_same_timestamp_boundary():
    """다른(더 최근) batch가 우연히 같은 acknowledgedAt을 가져도 target 경계 밖이면 제외된다."""
    same_ack_at = datetime(2026, 7, 29, 14, 45, tzinfo=SEOUL)
    target = _finalized_check_in(
        id=uuid.UUID(int=1),
        finalized_at=datetime(2026, 7, 29, 12, 0, 5, tzinfo=SEOUL),
        result_acknowledged_at=same_ack_at,
    )
    later_batch_same_timestamp = _finalized_check_in(
        id=uuid.UUID(int=2),
        finalized_at=datetime(2026, 7, 29, 18, 0, 5, tzinfo=SEOUL),
        result_acknowledged_at=same_ack_at,
    )
    db = FakeCheckInSession().seed(target, later_batch_same_timestamp)

    result = check_in_service.acknowledge_check_in(
        db, user_id=USER_ID, check_in_id=target.id, now=datetime(2026, 7, 29, 20, 0, tzinfo=SEOUL)
    )

    assert result.acknowledged_check_in_ids == [target.id]


def test_acknowledge_check_in_duplicate_call_does_not_touch_check_ins_created_after_replay():
    original_ack_at = datetime(2026, 7, 29, 14, 45, tzinfo=SEOUL)
    target = _finalized_check_in(id=uuid.UUID(int=1), result_acknowledged_at=original_ack_at)
    new_unacknowledged = _finalized_check_in(
        id=uuid.UUID(int=2),
        finalized_at=datetime(2026, 7, 30, 6, 0, 5, tzinfo=SEOUL),
        result_acknowledged_at=None,
    )
    db = FakeCheckInSession().seed(target, new_unacknowledged)

    check_in_service.acknowledge_check_in(
        db, user_id=USER_ID, check_in_id=target.id, now=datetime(2026, 7, 30, 7, 0, tzinfo=SEOUL)
    )

    assert new_unacknowledged.result_acknowledged_at is None
