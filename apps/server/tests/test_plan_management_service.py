import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.core.errors import ApiError
from app.models.enums import (
    PlanCycleStatus,
    SolarAction,
    SolarEntityType,
    SolarItemStatus,
    SolarMessageKind,
    SolarMessageRole,
    SolarRequestPurpose,
    SolarRequestStatus,
)
from app.models.planning_cycle import PlanningCycle
from app.models.solar_message import SolarMessage
from app.models.solar_request import SolarRequest
from app.models.solar_request_item import SolarRequestItem
from app.services import plan_management_service as svc

SEOUL = ZoneInfo("Asia/Seoul")
USER_ID = uuid.uuid4()
CYCLE_ID = uuid.uuid4()
REQUEST_ID = uuid.uuid4()
NOW = datetime(2026, 7, 29, 14, 0, tzinfo=SEOUL)


def _make_request(**overrides):
    defaults = dict(
        id=REQUEST_ID,
        user_id=USER_ID,
        plan_cycle_id=None,
        purpose=SolarRequestPurpose.NEW_CYCLE,
        status=SolarRequestStatus.COLLECTING,
        raw_input="테스트 입력",
        current_item_order=None,
        confirmed_at=None,
        execution_started_at=None,
        executed_at=None,
        execution_attempt_count=0,
        execution_result=None,
        error_code=None,
        error_message=None,
        result_acknowledged_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
    defaults.update(overrides)
    return SolarRequest(**defaults)


def _make_item(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        user_id=USER_ID,
        solar_request_id=REQUEST_ID,
        item_order=1,
        action=SolarAction.CREATE,
        entity_type=SolarEntityType.TASK,
        status=SolarItemStatus.INFO_MISSING,
        raw_line_text="금요일까지 자료구조 과제",
        normalized_payload={"title": "자료구조 과제"},
        missing_fields=[],
        pending_question=None,
        target_task_id=None,
        target_fixed_schedule_id=None,
        executed_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
    defaults.update(overrides)
    return SolarRequestItem(**defaults)


def _make_message(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        user_id=USER_ID,
        solar_request_id=REQUEST_ID,
        client_event_id=None,
        sequence_no=1,
        role=SolarMessageRole.ASSISTANT,
        kind=SolarMessageKind.TEXT,
        content="내용",
        message_metadata={},
        created_at=NOW,
    )
    defaults.update(overrides)
    return SolarMessage(**defaults)


def _make_cycle(**overrides):
    defaults = dict(
        id=CYCLE_ID,
        user_id=USER_ID,
        start_date=NOW.date(),
        end_date=NOW.date(),
        status=PlanCycleStatus.ACTIVE,
        activated_at=NOW,
        ended_at=None,
    )
    defaults.update(overrides)
    return PlanningCycle(**defaults)


# ---------------------------------------------------------------------------
# _build_solar_request_detail — screenMode별(요청이 존재하는 7개) 동작
# ---------------------------------------------------------------------------


def test_collecting_with_matching_metadata_uses_message_quick_replies_and_placeholder():
    request = _make_request(status=SolarRequestStatus.COLLECTING, current_item_order=1)
    pending_item = _make_item(
        item_order=1,
        status=SolarItemStatus.INFO_MISSING,
        pending_question={"field": "estimatedMinutes", "message": "얼마나 걸릴까요?", "attemptCount": 1},
    )
    question_message = _make_message(
        sequence_no=2,
        role=SolarMessageRole.ASSISTANT,
        kind=SolarMessageKind.QUESTION,
        content="얼마나 걸릴까요?",
        message_metadata={
            "itemId": str(pending_item.id),
            "field": "estimatedMinutes",
            "quickReplies": [{"value": "ONE_HOUR", "label": "1시간 정도"}],
            "inputPlaceholder": "직접 입력해 주세요",
        },
    )

    detail = svc._build_solar_request_detail(request, [question_message], [pending_item])

    assert detail.current_question == svc.CurrentQuestion(
        item_id=pending_item.id, field="estimatedMinutes", message="얼마나 걸릴까요?"
    )
    assert detail.pending_item_id == pending_item.id
    assert detail.quick_replies == [svc.QuickReply(value="ONE_HOUR", label="1시간 정도")]
    assert detail.input_placeholder == "직접 입력해 주세요"
    assert detail.decision_prompt is None
    assert detail.execution is None


def test_collecting_without_matching_message_falls_back_to_defaults():
    request = _make_request(status=SolarRequestStatus.COLLECTING, current_item_order=1)
    pending_item = _make_item(
        item_order=1,
        status=SolarItemStatus.INFO_MISSING,
        pending_question={"field": "estimatedMinutes", "message": "얼마나 걸릴까요?", "attemptCount": 1},
    )

    detail = svc._build_solar_request_detail(request, [], [pending_item])

    assert detail.current_question.field == "estimatedMinutes"
    assert detail.quick_replies == [svc.QuickReply(value="DONT_KNOW", label="잘 모르겠어요")]
    assert detail.input_placeholder == "예: 2시간 정도 걸려요"


def test_collecting_message_matching_itemid_but_different_field_is_ignored():
    request = _make_request(status=SolarRequestStatus.COLLECTING, current_item_order=1)
    pending_item = _make_item(
        item_order=1,
        status=SolarItemStatus.INFO_MISSING,
        pending_question={"field": "amount", "message": "분량은요?", "attemptCount": 1},
    )
    wrong_field_message = _make_message(
        sequence_no=2,
        kind=SolarMessageKind.QUESTION,
        message_metadata={
            "itemId": str(pending_item.id),
            "field": "estimatedMinutes",  # 카드의 pending_question.field("amount")와 불일치
            "quickReplies": [{"value": "X", "label": "X"}],
        },
    )

    detail = svc._build_solar_request_detail(request, [wrong_field_message], [pending_item])

    # 메시지가 일치하지 않으므로 fallback 기본값을 사용해야 한다.
    assert detail.quick_replies == [svc.QuickReply(value="DONT_KNOW", label="잘 모르겠어요")]
    assert detail.input_placeholder == "예: 문제 5개"


def test_collecting_uses_latest_matching_message_by_sequence_no():
    request = _make_request(status=SolarRequestStatus.COLLECTING, current_item_order=1)
    pending_item = _make_item(
        item_order=1,
        status=SolarItemStatus.INFO_MISSING,
        pending_question={"field": "amount", "message": "분량은요?", "attemptCount": 2},
    )
    older = _make_message(
        sequence_no=2,
        kind=SolarMessageKind.QUESTION,
        message_metadata={"itemId": str(pending_item.id), "field": "amount", "inputPlaceholder": "옛날 문구"},
    )
    newer = _make_message(
        sequence_no=3,
        kind=SolarMessageKind.QUESTION,
        message_metadata={"itemId": str(pending_item.id), "field": "amount", "inputPlaceholder": "최신 문구"},
    )

    detail = svc._build_solar_request_detail(request, [older, newer], [pending_item])

    assert detail.input_placeholder == "최신 문구"


def test_collecting_no_pending_item_returns_nulls():
    request = _make_request(status=SolarRequestStatus.COLLECTING, current_item_order=None)

    detail = svc._build_solar_request_detail(request, [], [])

    assert detail.current_question is None
    assert detail.quick_replies == []
    assert detail.input_placeholder is None
    assert detail.pending_item_id is None


def test_collecting_current_item_order_matches_ready_item_is_ignored():
    """current_item_order가 가리키는 카드가 INFO_MISSING이 아니면(데이터 불일치) 다른 카드를
    임의로 고르지 않고 질문 관련 필드를 모두 null/빈 배열로 반환해야 한다."""
    request = _make_request(status=SolarRequestStatus.COLLECTING, current_item_order=1)
    ready_item = _make_item(item_order=1, status=SolarItemStatus.READY, pending_question=None)

    detail = svc._build_solar_request_detail(request, [], [ready_item])

    assert detail.current_question is None
    assert detail.quick_replies == []
    assert detail.input_placeholder is None
    assert detail.pending_item_id is None


def test_change_input_uses_fixed_placeholder_and_no_question():
    request = _make_request(status=SolarRequestStatus.CHANGE_INPUT, current_item_order=1)
    item = _make_item(
        item_order=1,
        status=SolarItemStatus.INFO_MISSING,
        pending_question={"field": "amount", "message": "x", "attemptCount": 1},
    )

    detail = svc._build_solar_request_detail(request, [], [item])

    assert detail.input_placeholder == "추가하거나 수정할 내용을 입력해 주세요."
    assert detail.current_question is None
    assert detail.quick_replies == []
    assert detail.pending_item_id is None
    assert detail.decision_prompt is None


def test_change_confirmation_has_decision_prompt_and_no_question_fields():
    request = _make_request(status=SolarRequestStatus.CHANGE_CONFIRMATION)

    detail = svc._build_solar_request_detail(request, [], [])

    assert detail.decision_prompt == svc.DecisionPrompt(
        message="수정하거나 추가할 내용이 있나요?",
        options=[svc.DecisionOption(value="YES", label="네"), svc.DecisionOption(value="NO", label="아니요")],
    )
    assert detail.current_question is None
    assert detail.quick_replies == []
    assert detail.input_placeholder is None


def test_final_review_has_no_question_decision_or_execution():
    request = _make_request(status=SolarRequestStatus.FINAL_REVIEW)

    detail = svc._build_solar_request_detail(request, [], [])

    assert detail.current_question is None
    assert detail.decision_prompt is None
    assert detail.execution is None
    assert detail.review_summary is None


def test_executing_has_execution_without_error():
    request = _make_request(
        status=SolarRequestStatus.EXECUTING,
        execution_started_at=NOW,
        execution_attempt_count=1,
    )

    detail = svc._build_solar_request_detail(request, [], [])

    assert detail.execution == svc.Execution(
        execution_started_at=NOW,
        execution_attempt_count=1,
        executed_at=None,
        execution_result=None,
        error=None,
    )


def test_completed_has_execution_without_error():
    request = _make_request(
        status=SolarRequestStatus.COMPLETED,
        execution_started_at=NOW,
        executed_at=NOW,
        execution_attempt_count=1,
        execution_result={"createdTaskCount": 2},
        result_acknowledged_at=None,
    )

    detail = svc._build_solar_request_detail(request, [], [])

    assert detail.execution.execution_result == {"createdTaskCount": 2}
    assert detail.execution.error is None


def test_failed_has_execution_with_retryable_error():
    request = _make_request(
        status=SolarRequestStatus.FAILED,
        execution_started_at=NOW,
        execution_attempt_count=1,
        error_code="PLAN_EXECUTION_FAILED",
        error_message="계획을 반영하는 중 문제가 발생했어요.",
    )

    detail = svc._build_solar_request_detail(request, [], [])

    assert detail.execution.error == svc.ExecutionError(
        code="PLAN_EXECUTION_FAILED", message="계획을 반영하는 중 문제가 발생했어요.", retryable=True
    )


# ---------------------------------------------------------------------------
# summaryText 규칙
# ---------------------------------------------------------------------------


def test_summary_text_info_missing_with_fields():
    item = _make_item(
        status=SolarItemStatus.INFO_MISSING, missing_fields=["estimatedMinutes", "amount"]
    )

    detail = svc._build_item_detail(item)

    assert detail.summary_text == "정보 부족 · 예상 시간·분량 필요"


def test_summary_text_info_missing_without_fields():
    item = _make_item(status=SolarItemStatus.INFO_MISSING, missing_fields=[])

    detail = svc._build_item_detail(item)

    assert detail.summary_text == "정보 부족"


def test_summary_text_task_ready_full():
    item = _make_item(
        status=SolarItemStatus.READY,
        entity_type=SolarEntityType.TASK,
        normalized_payload={
            "title": "자료구조 과제",
            "deadlineAt": "2026-07-31T23:59:59+09:00",
            "amountText": "문제 5개",
            "estimatedMinutes": 90,
        },
    )

    detail = svc._build_item_detail(item)

    assert detail.summary_text == "준비됨 · 7월 31일까지 · 문제 5개 · 1시간 30분"


def test_summary_text_task_ready_converts_utc_deadline_to_seoul_date():
    # UTC 14:59:59 = Asia/Seoul 07-31 23:59:59 (다음날로 넘어가지 않아야 한다)
    item = _make_item(
        status=SolarItemStatus.READY,
        normalized_payload={"deadlineAt": "2026-07-31T14:59:59+00:00"},
    )

    detail = svc._build_item_detail(item)

    assert "7월 31일까지" in detail.summary_text


def test_summary_text_task_ready_omits_missing_parts():
    item = _make_item(
        status=SolarItemStatus.READY,
        normalized_payload={"estimatedMinutes": 45},
    )

    detail = svc._build_item_detail(item)

    assert detail.summary_text == "준비됨 · 45분"


def test_summary_text_task_executed_reuses_ready_style_format():
    item = _make_item(
        status=SolarItemStatus.EXECUTED,
        normalized_payload={
            "deadlineAt": "2026-07-31T23:59:59+09:00",
            "amountText": "문제 5개",
            "estimatedMinutes": 180,
        },
        executed_at=NOW,
    )

    detail = svc._build_item_detail(item)

    assert detail.summary_text == "반영 완료 · 7월 31일까지 · 문제 5개 · 3시간"


def test_summary_text_fixed_schedule_ready_same_day():
    item = _make_item(
        status=SolarItemStatus.READY,
        entity_type=SolarEntityType.FIXED_SCHEDULE,
        normalized_payload={
            "title": "알바",
            "startAt": "2026-08-01T22:00:00+09:00",
            "endAt": "2026-08-01T23:30:00+09:00",
        },
    )

    detail = svc._build_item_detail(item)

    assert detail.summary_text == "준비됨 · 8월 1일 22:00-8월 1일 23:30"


def test_summary_text_fixed_schedule_ready_crossing_midnight_keeps_both_dates():
    item = _make_item(
        status=SolarItemStatus.READY,
        entity_type=SolarEntityType.FIXED_SCHEDULE,
        normalized_payload={
            "title": "알바",
            "startAt": "2026-08-01T22:00:00+09:00",
            "endAt": "2026-08-02T02:00:00+09:00",
        },
    )

    detail = svc._build_item_detail(item)

    assert detail.summary_text == "준비됨 · 8월 1일 22:00-8월 2일 02:00"


def test_summary_text_fixed_schedule_missing_times_falls_back_to_status_label():
    item = _make_item(
        status=SolarItemStatus.READY,
        entity_type=SolarEntityType.FIXED_SCHEDULE,
        normalized_payload={"title": "알바"},
    )

    detail = svc._build_item_detail(item)

    assert detail.summary_text == "준비됨"


# ---------------------------------------------------------------------------
# 라벨 매핑
# ---------------------------------------------------------------------------


def test_item_labels_for_create_task_info_missing():
    item = _make_item(
        action=SolarAction.CREATE, entity_type=SolarEntityType.TASK, status=SolarItemStatus.INFO_MISSING
    )

    detail = svc._build_item_detail(item)

    assert detail.action_label == "추가"
    assert detail.entity_label == "할 일"
    assert detail.status_label == "정보 부족"


def test_item_labels_for_update_delete_fixed_schedule():
    update_item = _make_item(
        action=SolarAction.UPDATE,
        entity_type=SolarEntityType.FIXED_SCHEDULE,
        status=SolarItemStatus.READY,
        target_fixed_schedule_id=uuid.uuid4(),
    )
    delete_item = _make_item(
        action=SolarAction.DELETE,
        entity_type=SolarEntityType.FIXED_SCHEDULE,
        status=SolarItemStatus.EXECUTED,
        target_fixed_schedule_id=uuid.uuid4(),
        executed_at=NOW,
    )

    update_detail = svc._build_item_detail(update_item)
    delete_detail = svc._build_item_detail(delete_item)

    assert update_detail.action_label == "수정"
    assert update_detail.entity_label == "고정 일정"
    assert delete_detail.action_label == "삭제"
    assert delete_detail.status_label == "반영 완료"


def test_item_target_entity_id_uses_whichever_target_is_set():
    task_id = uuid.uuid4()
    item = _make_item(action=SolarAction.UPDATE, target_task_id=task_id, target_fixed_schedule_id=None)

    detail = svc._build_item_detail(item)

    assert detail.target_entity_id == task_id


def test_item_title_falls_back_to_raw_line_text_when_payload_has_no_title():
    item = _make_item(raw_line_text="금요일까지 자료구조 과제", normalized_payload={})

    detail = svc._build_item_detail(item)

    assert detail.title == "금요일까지 자료구조 과제"


# ---------------------------------------------------------------------------
# pendingQuestion 변환 + 정렬
# ---------------------------------------------------------------------------


def test_pending_question_converted_to_dto():
    item = _make_item(
        pending_question={"field": "amount", "message": "분량은요?", "attemptCount": 2}
    )

    detail = svc._build_item_detail(item)

    assert detail.pending_question == svc.PendingQuestion(field="amount", message="분량은요?", attempt_count=2)


def test_pending_question_missing_keys_returns_none():
    item = _make_item(pending_question={"field": "amount"})  # message 없음

    detail = svc._build_item_detail(item)

    assert detail.pending_question is None


def test_messages_and_items_are_sorted_defensively():
    request = _make_request(status=SolarRequestStatus.FINAL_REVIEW)
    item_2 = _make_item(item_order=2)
    item_1 = _make_item(item_order=1)
    message_2 = _make_message(sequence_no=2)
    message_1 = _make_message(sequence_no=1)

    detail = svc._build_solar_request_detail(request, [message_2, message_1], [item_2, item_1])

    assert [m.sequence_no for m in detail.messages] == [1, 2]
    assert [d.item.item_order for d in detail.items] == [1, 2]


# ---------------------------------------------------------------------------
# 방어적 파싱
# ---------------------------------------------------------------------------


def test_defensive_parsing_metadata_not_dict_falls_back():
    request = _make_request(status=SolarRequestStatus.COLLECTING, current_item_order=1)
    pending_item = _make_item(
        item_order=1,
        pending_question={"field": "amount", "message": "x", "attemptCount": 1},
    )
    broken_message = _make_message(
        sequence_no=2, kind=SolarMessageKind.QUESTION, message_metadata="not-a-dict"
    )

    detail = svc._build_solar_request_detail(request, [broken_message], [pending_item])

    assert detail.quick_replies == [svc.QuickReply(value="DONT_KNOW", label="잘 모르겠어요")]


def test_defensive_parsing_quick_replies_wrong_type_falls_back():
    request = _make_request(status=SolarRequestStatus.COLLECTING, current_item_order=1)
    pending_item = _make_item(
        item_order=1, pending_question={"field": "amount", "message": "x", "attemptCount": 1}
    )
    message = _make_message(
        sequence_no=2,
        kind=SolarMessageKind.QUESTION,
        message_metadata={"itemId": str(pending_item.id), "field": "amount", "quickReplies": "oops"},
    )

    detail = svc._build_solar_request_detail(request, [message], [pending_item])

    assert detail.quick_replies == [svc.QuickReply(value="DONT_KNOW", label="잘 모르겠어요")]


def test_defensive_parsing_pending_question_not_dict_returns_none():
    item = _make_item(pending_question="broken")

    detail = svc._build_item_detail(item)

    assert detail.pending_question is None


def test_defensive_parsing_normalized_payload_not_dict_falls_back_to_status_label():
    item = _make_item(status=SolarItemStatus.READY, normalized_payload="broken")

    detail = svc._build_item_detail(item)

    assert detail.summary_text == "준비됨"
    assert detail.title == item.raw_line_text


def test_defensive_parsing_unparseable_deadline_is_skipped_not_raised():
    item = _make_item(
        status=SolarItemStatus.READY,
        normalized_payload={"deadlineAt": "not-a-real-date", "amountText": "문제 5개"},
    )

    detail = svc._build_item_detail(item)

    assert detail.summary_text == "준비됨 · 문제 5개"


def test_defensive_parsing_naive_deadline_is_skipped():
    item = _make_item(
        status=SolarItemStatus.READY,
        normalized_payload={"deadlineAt": "2026-07-31T23:59:59"},  # tzinfo 없음
    )

    detail = svc._build_item_detail(item)

    assert detail.summary_text == "준비됨"


def test_defensive_parsing_missing_fields_not_list_falls_back_to_status_label():
    item = _make_item(status=SolarItemStatus.INFO_MISSING, missing_fields="broken")

    detail = svc._build_item_detail(item)

    assert detail.summary_text == "정보 부족"


# ---------------------------------------------------------------------------
# 오케스트레이션 — 조회 전용(add/delete/flush/begin/commit 호출 시 즉시 실패)
# ---------------------------------------------------------------------------


class _FakeScalars:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return _FakeScalars(self._value if isinstance(self._value, list) else [])


class _QueueSession:
    """execute() 호출 순서대로 미리 준비한 결과를 하나씩 돌려주는 fake.

    begin()/commit()/flush()/add()/delete() 중 어떤 것이라도 호출되면 즉시 AssertionError를
    던져 두 오케스트레이션 함수가 완전한 조회 전용으로 동작하는지 검증한다.
    """

    def __init__(self, results):
        self._queue = list(results)

    def execute(self, stmt):
        assert self._queue, "예상보다 많은 db.execute() 호출이 발생했다."
        return _FakeResult(self._queue.pop(0))

    def begin(self):
        raise AssertionError("조회 전용 함수는 db.begin()을 호출하면 안 된다.")

    def commit(self):
        raise AssertionError("조회 전용 함수는 db.commit()을 호출하면 안 된다.")

    def flush(self):
        raise AssertionError("조회 전용 함수는 db.flush()를 호출하면 안 된다.")

    def add(self, obj):
        raise AssertionError("조회 전용 함수는 db.add()를 호출하면 안 된다.")

    def delete(self, obj):
        raise AssertionError("조회 전용 함수는 db.delete()를 호출하면 안 된다.")


def test_get_plan_management_state_no_request_no_active_cycle():
    fake_db = _QueueSession([None, None])  # active_cycle=None, current_request=None

    state = svc.get_plan_management_state(fake_db, USER_ID)

    assert state.screen_mode == svc.PlanManagementScreenMode.NEW_CYCLE_ENTRY
    assert state.active_cycle is None
    assert state.request_detail is None


def test_get_plan_management_state_no_request_with_active_cycle():
    cycle = _make_cycle()
    fake_db = _QueueSession([cycle, None])

    state = svc.get_plan_management_state(fake_db, USER_ID)

    assert state.screen_mode == svc.PlanManagementScreenMode.ACTIVE_CYCLE_ENTRY
    assert state.active_cycle is cycle


def test_get_plan_management_state_with_current_request_loads_detail():
    request = _make_request(status=SolarRequestStatus.CHANGE_CONFIRMATION)
    fake_db = _QueueSession([None, request, [], []])  # active_cycle, request, messages, items

    state = svc.get_plan_management_state(fake_db, USER_ID)

    assert state.screen_mode == svc.PlanManagementScreenMode.CHANGE_CONFIRMATION
    assert state.request_detail is not None
    assert state.request_detail.decision_prompt is not None


def test_get_solar_request_detail_state_raises_404_when_not_owned():
    fake_db = _QueueSession([None])

    with pytest.raises(ApiError) as exc_info:
        svc.get_solar_request_detail_state(fake_db, USER_ID, REQUEST_ID)

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "REQUEST_NOT_FOUND"


def test_get_solar_request_detail_state_active_cycle_purpose_returns_linked_cycle():
    request = _make_request(purpose=SolarRequestPurpose.ACTIVE_CYCLE, plan_cycle_id=CYCLE_ID)
    cycle = _make_cycle()
    fake_db = _QueueSession([request, cycle, [], []])

    state = svc.get_solar_request_detail_state(fake_db, USER_ID, REQUEST_ID)

    assert state.active_cycle is cycle


def test_get_solar_request_detail_state_new_cycle_purpose_ignores_other_active_cycle():
    request = _make_request(purpose=SolarRequestPurpose.NEW_CYCLE, plan_cycle_id=None)
    # NEW_CYCLE purpose이므로 cycle 조회 자체가 발생하지 않아야 한다(큐에 cycle을 넣지 않음).
    fake_db = _QueueSession([request, [], []])

    state = svc.get_solar_request_detail_state(fake_db, USER_ID, REQUEST_ID)

    assert state.active_cycle is None


def test_get_solar_request_detail_state_active_cycle_purpose_without_plan_cycle_id_returns_null():
    request = _make_request(purpose=SolarRequestPurpose.ACTIVE_CYCLE, plan_cycle_id=None)
    fake_db = _QueueSession([request, [], []])

    state = svc.get_solar_request_detail_state(fake_db, USER_ID, REQUEST_ID)

    assert state.active_cycle is None


def test_get_solar_request_detail_state_linked_cycle_missing_raises_404():
    request = _make_request(purpose=SolarRequestPurpose.ACTIVE_CYCLE, plan_cycle_id=CYCLE_ID)
    fake_db = _QueueSession([request, None])  # get_owned_planning_cycle이 못 찾음

    with pytest.raises(ApiError) as exc_info:
        svc.get_solar_request_detail_state(fake_db, USER_ID, REQUEST_ID)

    assert exc_info.value.status_code == 404


def test_get_solar_request_detail_state_completed_acknowledged_returns_execution_success():
    """결과 확인이 끝난 과거 COMPLETED 요청도 requestId로 조회할 수 있고, 별도의 "과거 완료"
    screenMode 없이 기존 resolver 동작대로 EXECUTION_SUCCESS로 반환된다."""
    request = _make_request(
        status=SolarRequestStatus.COMPLETED,
        result_acknowledged_at=NOW,
        execution_started_at=NOW,
        executed_at=NOW,
        execution_attempt_count=1,
        execution_result={},
    )
    fake_db = _QueueSession([request, [], []])

    state = svc.get_solar_request_detail_state(fake_db, USER_ID, REQUEST_ID)

    assert state.screen_mode == svc.PlanManagementScreenMode.EXECUTION_SUCCESS
