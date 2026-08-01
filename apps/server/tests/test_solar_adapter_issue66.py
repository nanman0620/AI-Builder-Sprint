import json

import pytest

from app.models.enums import SolarRequestPurpose
from app.services import solar_client
from app.services.solar_client import (
    SolarUnavailableError,
    parse_card_answer_response,
    parse_solar_response,
)

TASK_ID = "11111111-1111-1111-1111-111111111111"
OTHER_TASK_ID = "22222222-2222-2222-2222-222222222222"
REQUEST_ITEM_ID = "44444444-4444-4444-4444-444444444444"
OTHER_REQUEST_ITEM_ID = "55555555-5555-5555-5555-555555555555"


def _task_payload(**overrides):
    payload = {
        "title": "자료구조 과제",
        "deadlineAt": "2026-08-01T23:59:59+09:00",
        "estimatedMinutes": 120,
        "estimatedMinutesSource": "USER",
        "remainingMinutes": None,
        "amountText": None,
        "amountSource": "UNKNOWN",
    }
    payload.update(overrides)
    return payload


def _change_input_create_item(*, target_kind=None, **overrides):
    item = {
        "entityType": "TASK",
        "action": "CREATE",
        "targetEntityId": None,
        "targetKind": target_kind,
        "rawLineText": "새 할 일 추가",
        "deadlineState": "KNOWN",
        "normalizedPayload": _task_payload(),
        "pendingQuestion": None,
    }
    item.update(overrides)
    return item


def _change_input_create_merge_item(*, target_entity_id=REQUEST_ITEM_ID, changed_fields=None, **overrides):
    changed_fields = changed_fields or ["estimatedMinutes"]
    item = {
        "entityType": "TASK",
        "action": "CREATE",
        "targetEntityId": target_entity_id,
        "targetKind": "REQUEST_ITEM",
        "rawLineText": "예상 시간을 2시간으로",
        "deadlineState": "MISSING",
        "changedFields": changed_fields,
        "normalizedPayload": {
            "title": None,
            "deadlineAt": None,
            "estimatedMinutes": 120,
            "estimatedMinutesSource": "USER",
            "remainingMinutes": None,
            "amountText": None,
            "amountSource": None,
        },
        "pendingQuestion": None,
    }
    item.update(overrides)
    return item


def _change_input_delete_request_item(*, target_entity_id=REQUEST_ITEM_ID, **overrides):
    item = {
        "entityType": "TASK",
        "action": "DELETE",
        "targetEntityId": target_entity_id,
        "targetKind": "REQUEST_ITEM",
        "rawLineText": "그 카드는 취소",
        "normalizedPayload": {
            "title": "취소될 카드",
            "deadlineAt": None,
            "estimatedMinutes": None,
            "estimatedMinutesSource": None,
            "remainingMinutes": None,
            "amountText": None,
            "amountSource": None,
        },
        "pendingQuestion": None,
    }
    item.update(overrides)
    return item


def _change_input_envelope(*, items, unresolved_line=None, analysis_message="분석 완료"):
    return json.dumps(
        {"analysisMessage": analysis_message, "items": items, "unresolvedLine": unresolved_line}, ensure_ascii=False
    )


def _parse_change_input(content, *, candidate_task_ids=None, candidate_request_items=None):
    return parse_solar_response(
        content,
        purpose=SolarRequestPurpose.ACTIVE_CYCLE,
        candidate_task_ids=candidate_task_ids or set(),
        candidate_fixed_schedule_ids=set(),
        analysis_mode="CHANGE_INPUT",
        candidate_request_items=candidate_request_items or {},
    )


# ---------------------------------------------------------------------------
# CHANGE_INPUT — CREATE+REQUEST_ITEM(기존 대기 CREATE 카드 patch)
# ---------------------------------------------------------------------------


def test_change_input_create_merge_accepted_when_candidate_is_create():
    content = _change_input_envelope(items=[_change_input_create_merge_item()])
    result = _parse_change_input(
        content, candidate_request_items={REQUEST_ITEM_ID: {"entityType": "TASK", "action": "CREATE"}}
    )
    assert len(result.items) == 1
    item = result.items[0]
    assert item.action == "CREATE"
    assert item.target_kind == "REQUEST_ITEM"
    assert item.target_entity_id == REQUEST_ITEM_ID
    assert item.update_fields == ["estimatedMinutes"]


def test_change_input_create_merge_rejected_when_candidate_is_not_create():
    """잘못된 종류의 request item 선택 — 계약 위반(repair 대상)이지 409가 아니다(파서 레벨)."""
    content = _change_input_envelope(items=[_change_input_create_merge_item()])
    with pytest.raises(SolarUnavailableError):
        _parse_change_input(
            content, candidate_request_items={REQUEST_ITEM_ID: {"entityType": "TASK", "action": "UPDATE"}}
        )


def test_change_input_create_merge_rejected_when_candidate_missing():
    content = _change_input_envelope(items=[_change_input_create_merge_item()])
    with pytest.raises(SolarUnavailableError):
        _parse_change_input(content, candidate_request_items={})


def test_change_input_create_merge_rejects_remaining_minutes_in_changed_fields():
    content = _change_input_envelope(
        items=[_change_input_create_merge_item(changed_fields=["remainingMinutes"])]
    )
    with pytest.raises(SolarUnavailableError):
        _parse_change_input(
            content, candidate_request_items={REQUEST_ITEM_ID: {"entityType": "TASK", "action": "CREATE"}}
        )


# ---------------------------------------------------------------------------
# CHANGE_INPUT — DELETE+REQUEST_ITEM(대기 카드 취소, action 무관 전부 허용)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("candidate_action", ["CREATE", "UPDATE", "DELETE"])
def test_change_input_delete_request_item_accepted_regardless_of_current_action(candidate_action):
    content = _change_input_envelope(items=[_change_input_delete_request_item()])
    result = _parse_change_input(
        content, candidate_request_items={REQUEST_ITEM_ID: {"entityType": "TASK", "action": candidate_action}}
    )
    assert len(result.items) == 1
    assert result.items[0].action == "DELETE"
    assert result.items[0].target_kind == "REQUEST_ITEM"


def test_change_input_delete_request_item_rejected_when_entity_type_mismatches():
    content = _change_input_envelope(items=[_change_input_delete_request_item()])
    with pytest.raises(SolarUnavailableError):
        _parse_change_input(
            content,
            candidate_request_items={REQUEST_ITEM_ID: {"entityType": "FIXED_SCHEDULE", "action": "CREATE"}},
        )


# ---------------------------------------------------------------------------
# CHANGE_INPUT — UPDATE는 targetKind=ENTITY만 허용
# ---------------------------------------------------------------------------


def test_change_input_update_rejects_request_item_target_kind():
    item = {
        "entityType": "TASK",
        "action": "UPDATE",
        "targetEntityId": TASK_ID,
        "targetKind": "REQUEST_ITEM",
        "rawLineText": "그거 수정",
        "deadlineState": "MISSING",
        "updateFields": ["title"],
        "normalizedPayload": {
            "title": "새 제목",
            "deadlineAt": None,
            "estimatedMinutes": None,
            "estimatedMinutesSource": None,
            "remainingMinutes": None,
            "amountText": None,
            "amountSource": None,
        },
        "pendingQuestion": None,
    }
    content = _change_input_envelope(items=[item])
    with pytest.raises(SolarUnavailableError):
        _parse_change_input(content, candidate_task_ids={TASK_ID})


# ---------------------------------------------------------------------------
# CHANGE_INPUT — 한 응답 안 동일 대상 중복 조작 거부(최종 반영 #4, entityType 포함 키)
# ---------------------------------------------------------------------------


def test_change_input_rejects_duplicate_target_in_same_response():
    content = _change_input_envelope(
        items=[
            _change_input_create_merge_item(),
            _change_input_delete_request_item(target_entity_id=REQUEST_ITEM_ID),
        ]
    )
    with pytest.raises(SolarUnavailableError):
        _parse_change_input(
            content, candidate_request_items={REQUEST_ITEM_ID: {"entityType": "TASK", "action": "CREATE"}}
        )


def test_change_input_allows_different_targets_in_same_response():
    content = _change_input_envelope(
        items=[
            _change_input_create_merge_item(target_entity_id=REQUEST_ITEM_ID),
            _change_input_delete_request_item(target_entity_id=OTHER_REQUEST_ITEM_ID),
        ]
    )
    result = _parse_change_input(
        content,
        candidate_request_items={
            REQUEST_ITEM_ID: {"entityType": "TASK", "action": "CREATE"},
            OTHER_REQUEST_ITEM_ID: {"entityType": "TASK", "action": "CREATE"},
        },
    )
    assert len(result.items) == 2


# ---------------------------------------------------------------------------
# CHANGE_INPUT — 자체 unresolvedLine(targetKind 확장)
# ---------------------------------------------------------------------------


def test_change_input_unresolved_line_requires_target_kind():
    unresolved = {
        "rawLineText": "그거 지워줘",
        "action": "DELETE",
        "entityType": "TASK",
        "message": "어떤 걸 말씀하시는 건가요?",
    }
    content = _change_input_envelope(items=[], unresolved_line=unresolved)
    with pytest.raises(SolarUnavailableError):
        _parse_change_input(content, candidate_request_items={REQUEST_ITEM_ID: {"entityType": "TASK", "action": "CREATE"}})


def test_change_input_unresolved_line_request_item_target_kind_accepted():
    unresolved = {
        "rawLineText": "그거 지워줘",
        "action": "DELETE",
        "entityType": "TASK",
        "message": "어떤 걸 말씀하시는 건가요?",
        "targetKind": "REQUEST_ITEM",
    }
    content = _change_input_envelope(items=[], unresolved_line=unresolved)
    result = _parse_change_input(
        content, candidate_request_items={REQUEST_ITEM_ID: {"entityType": "TASK", "action": "CREATE"}}
    )
    assert result.unresolved_line.target_kind == "REQUEST_ITEM"


# ---------------------------------------------------------------------------
# UNRESOLVED_ANSWER — 3-way XOR(items/unresolvedLine/resolvedTargetOnly)
# ---------------------------------------------------------------------------


def _unresolved_answer_envelope(*, items=None, unresolved_line=None, resolved_target_only=None, analysis_message="분석"):
    return json.dumps(
        {
            "analysisMessage": analysis_message,
            "items": items if items is not None else [],
            "unresolvedLine": unresolved_line,
            "resolvedTargetOnly": resolved_target_only,
        },
        ensure_ascii=False,
    )


def _parse_unresolved(content, **overrides):
    kwargs = dict(
        purpose=SolarRequestPurpose.ACTIVE_CYCLE,
        candidate_task_ids={TASK_ID, OTHER_TASK_ID},
        candidate_fixed_schedule_ids=set(),
        analysis_mode="UNRESOLVED_ANSWER",
        expected_action="UPDATE",
        expected_entity_type="TASK",
        expected_target_kind="ENTITY",
    )
    kwargs.update(overrides)
    return parse_solar_response(content, **kwargs)


def test_unresolved_answer_rejects_all_three_outcomes_present():
    content = _unresolved_answer_envelope(
        resolved_target_only={"targetEntityId": TASK_ID, "targetKind": "ENTITY"},
        unresolved_line={
            "rawLineText": "그거",
            "action": "UPDATE",
            "entityType": "TASK",
            "message": "어떤 항목인가요?",
        },
    )
    with pytest.raises(SolarUnavailableError):
        _parse_unresolved(content)


def test_unresolved_answer_rejects_all_three_outcomes_absent():
    content = _unresolved_answer_envelope()
    with pytest.raises(SolarUnavailableError):
        _parse_unresolved(content)


def test_unresolved_answer_resolved_target_only_success():
    content = _unresolved_answer_envelope(resolved_target_only={"targetEntityId": TASK_ID, "targetKind": "ENTITY"})
    result = _parse_unresolved(content)
    assert result.resolved_target_only.target_entity_id == TASK_ID
    assert result.resolved_target_only.target_kind == "ENTITY"
    assert result.items == []
    assert result.unresolved_line is None


def test_unresolved_answer_resolved_target_only_rejects_unknown_candidate():
    content = _unresolved_answer_envelope(
        resolved_target_only={"targetEntityId": "99999999-9999-9999-9999-999999999999", "targetKind": "ENTITY"}
    )
    with pytest.raises(SolarUnavailableError):
        _parse_unresolved(content)


def test_unresolved_answer_items_over_one_rejected():
    item = {
        "entityType": "TASK",
        "action": "UPDATE",
        "targetEntityId": TASK_ID,
        "rawLineText": "제목 바꿔줘",
        "deadlineState": "MISSING",
        "updateFields": ["title"],
        "normalizedPayload": {
            "title": "새 제목",
            "deadlineAt": None,
            "estimatedMinutes": None,
            "estimatedMinutesSource": None,
            "remainingMinutes": None,
            "amountText": None,
            "amountSource": None,
        },
        "pendingQuestion": None,
    }
    content = _unresolved_answer_envelope(items=[item, item])
    with pytest.raises(SolarUnavailableError):
        _parse_unresolved(content)


def test_unresolved_answer_item_action_locked_to_expected():
    item = {
        "entityType": "TASK",
        "action": "DELETE",  # expected_action은 UPDATE
        "targetEntityId": TASK_ID,
        "rawLineText": "그거 지워줘",
        "normalizedPayload": {
            "title": "제목",
            "deadlineAt": None,
            "estimatedMinutes": None,
            "estimatedMinutesSource": None,
            "remainingMinutes": None,
            "amountText": None,
            "amountSource": None,
        },
        "pendingQuestion": None,
    }
    content = _unresolved_answer_envelope(items=[item])
    with pytest.raises(SolarUnavailableError):
        _parse_unresolved(content)


def test_unresolved_answer_item_target_locked_when_change_details_lock_target_set():
    """CHANGE_DETAILS 후속 lock-down: 다른 target을 가리키면 계약 위반."""
    item = {
        "entityType": "TASK",
        "action": "UPDATE",
        "targetEntityId": OTHER_TASK_ID,
        "rawLineText": "그거 바꿔줘",
        "deadlineState": "MISSING",
        "updateFields": ["title"],
        "normalizedPayload": {
            "title": "새 제목",
            "deadlineAt": None,
            "estimatedMinutes": None,
            "estimatedMinutesSource": None,
            "remainingMinutes": None,
            "amountText": None,
            "amountSource": None,
        },
        "pendingQuestion": None,
    }
    content = _unresolved_answer_envelope(items=[item])
    with pytest.raises(SolarUnavailableError):
        _parse_unresolved(content, lock_target_entity_id=TASK_ID)


def test_change_details_lock_down_rejects_unresolved_line():
    content = _unresolved_answer_envelope(
        unresolved_line={
            "rawLineText": "그거",
            "action": "UPDATE",
            "entityType": "TASK",
            "message": "어떤 항목인가요?",
        }
    )
    with pytest.raises(SolarUnavailableError):
        _parse_unresolved(content, lock_target_entity_id=TASK_ID)


def test_unresolved_answer_request_item_target_kind_uses_candidate_request_items():
    content = _unresolved_answer_envelope(resolved_target_only={"targetEntityId": REQUEST_ITEM_ID, "targetKind": "REQUEST_ITEM"})
    result = _parse_unresolved(
        content,
        expected_target_kind="REQUEST_ITEM",
        candidate_task_ids=set(),
        candidate_request_items={REQUEST_ITEM_ID: {"entityType": "TASK", "action": "CREATE"}},
    )
    assert result.resolved_target_only.target_kind == "REQUEST_ITEM"
    assert result.resolved_target_only.target_entity_id == REQUEST_ITEM_ID


# ---------------------------------------------------------------------------
# CARD_ANSWER — 좁은 계약
# ---------------------------------------------------------------------------


def _card_answer_envelope(*, disposition, field_value=None, pending_question=None, analysis_message="분석"):
    return json.dumps(
        {
            "analysisMessage": analysis_message,
            "answerDisposition": disposition,
            "pendingQuestion": pending_question,
            "fieldValue": field_value,
        },
        ensure_ascii=False,
    )


def test_card_answer_provided_estimated_minutes_first_attempt_rejects_ai_estimated():
    content = _card_answer_envelope(
        disposition="PROVIDED",
        field_value={"estimatedMinutes": 90, "estimatedMinutesSource": "AI_ESTIMATED"},
    )
    with pytest.raises(SolarUnavailableError):
        parse_card_answer_response(content, entity_type="TASK", action="CREATE", field="estimatedMinutes", attempt_number=1)


def test_card_answer_provided_estimated_minutes_second_attempt_allows_ai_estimated():
    content = _card_answer_envelope(
        disposition="PROVIDED",
        field_value={"estimatedMinutes": 90, "estimatedMinutesSource": "AI_ESTIMATED"},
    )
    result = parse_card_answer_response(
        content, entity_type="TASK", action="CREATE", field="estimatedMinutes", attempt_number=2
    )
    assert result.answer_disposition == "PROVIDED"
    assert result.field_value == {"estimatedMinutes": 90, "estimatedMinutesSource": "AI_ESTIMATED"}


def test_card_answer_provided_requires_field_value():
    content = _card_answer_envelope(disposition="PROVIDED", field_value=None)
    with pytest.raises(SolarUnavailableError):
        parse_card_answer_response(content, entity_type="TASK", action="CREATE", field="title", attempt_number=1)


def test_card_answer_dont_know_requires_pending_question_and_no_field_value():
    content = _card_answer_envelope(disposition="DONT_KNOW", pending_question="다시 물어볼게요.")
    result = parse_card_answer_response(content, entity_type="TASK", action="CREATE", field="amount", attempt_number=1)
    assert result.answer_disposition == "DONT_KNOW"
    assert result.field_value is None
    assert result.pending_question_message == "다시 물어볼게요."


def test_card_answer_unclear_requires_pending_question():
    content = _card_answer_envelope(disposition="UNCLEAR", pending_question=None)
    with pytest.raises(SolarUnavailableError):
        parse_card_answer_response(content, entity_type="TASK", action="CREATE", field="amount", attempt_number=1)


def test_card_answer_rejects_unknown_disposition():
    content = _card_answer_envelope(disposition="MAYBE")
    with pytest.raises(SolarUnavailableError):
        parse_card_answer_response(content, entity_type="TASK", action="CREATE", field="title", attempt_number=1)


def test_card_answer_title_field_value_shape():
    content = _card_answer_envelope(disposition="PROVIDED", field_value={"title": "새 제목"})
    result = parse_card_answer_response(content, entity_type="TASK", action="CREATE", field="title", attempt_number=1)
    assert result.field_value == {"title": "새 제목"}


def test_card_answer_deadline_none_field_value_shape():
    content = _card_answer_envelope(
        disposition="PROVIDED", field_value={"deadlineState": "NONE", "deadlineAt": None}
    )
    result = parse_card_answer_response(
        content, entity_type="TASK", action="CREATE", field="deadlineAt", attempt_number=1
    )
    assert result.field_value == {"deadlineState": "NONE", "deadlineAt": None}


def test_card_answer_amount_unknown_field_value_shape():
    content = _card_answer_envelope(
        disposition="PROVIDED", field_value={"amountText": None, "amountSource": "UNKNOWN"}
    )
    result = parse_card_answer_response(content, entity_type="TASK", action="CREATE", field="amount", attempt_number=1)
    assert result.field_value == {"amountText": None, "amountSource": "UNKNOWN"}


# ---------------------------------------------------------------------------
# missing_order_for — CREATE_MERGE pseudo-action
# ---------------------------------------------------------------------------


def test_missing_order_for_create_merge_includes_title_and_excludes_remaining_minutes():
    order = solar_client.missing_order_for("TASK", "CREATE_MERGE")
    assert order[0] == "title"
    assert "remainingMinutes" not in order


def test_missing_order_for_plain_create_excludes_title():
    order = solar_client.missing_order_for("TASK", "CREATE")
    assert "title" not in order


# ---------------------------------------------------------------------------
# Issue #66 후속 — CHANGE_INPUT 실제 API smoke test에서 관측된 3가지 위반에 대한 좁은
# canonicalization. 각각 "보완해야 하는 좁은 조건"과 "건드리면 안 되는 조건(=repair 대상으로
# 남아야 함)"을 짝으로 검증한다.
# ---------------------------------------------------------------------------


def test_canonicalize_missing_deadline_state_for_create_merge_fills_when_untouched_and_null():
    item = {
        "action": "CREATE",
        "changedFields": ["estimatedMinutes"],
        "normalizedPayload": {"deadlineAt": None, "title": None},
    }
    solar_client._canonicalize_missing_deadline_state_for_create_merge(item)
    assert item["deadlineState"] == "MISSING"


def test_canonicalize_missing_deadline_state_for_create_merge_no_op_when_key_already_present():
    """이미 값이 있으면(잘못된 값이라도) 건드리지 않는다 — strict parser/repair 대상."""
    item = {
        "action": "CREATE",
        "deadlineState": "KNOWN",
        "changedFields": ["estimatedMinutes"],
        "normalizedPayload": {"deadlineAt": None},
    }
    solar_client._canonicalize_missing_deadline_state_for_create_merge(item)
    assert item["deadlineState"] == "KNOWN"


def test_canonicalize_missing_deadline_state_for_create_merge_no_op_when_deadline_at_is_changed():
    """사용자가 실제로 마감을 바꾸려는 경우(deadlineAt이 changedFields에 있음)는 임의 보완하지
    않고 계약 위반으로 남긴다."""
    item = {
        "action": "CREATE",
        "changedFields": ["deadlineAt"],
        "normalizedPayload": {"deadlineAt": None},
    }
    solar_client._canonicalize_missing_deadline_state_for_create_merge(item)
    assert "deadlineState" not in item


def test_canonicalize_missing_deadline_state_for_create_merge_no_op_when_deadline_at_has_value():
    """deadlineAt이 null이 아닌데 deadlineState 키가 없으면(값을 추측할 근거가 없음) 건드리지
    않는다."""
    item = {
        "action": "CREATE",
        "changedFields": ["estimatedMinutes"],
        "normalizedPayload": {"deadlineAt": "2026-08-01T23:59:59+09:00"},
    }
    solar_client._canonicalize_missing_deadline_state_for_create_merge(item)
    assert "deadlineState" not in item


def test_canonicalize_missing_deadline_state_for_create_merge_no_op_for_plain_create():
    """changedFields 키 자체가 없는 완전히 새로운 CREATE는 건드리지 않는다(그 경우
    deadlineState 누락은 값을 추측할 안전한 근거가 없는 진짜 계약 위반)."""
    item = {"action": "CREATE", "normalizedPayload": {"deadlineAt": None}}
    solar_client._canonicalize_missing_deadline_state_for_create_merge(item)
    assert "deadlineState" not in item


def test_canonicalize_new_create_target_entity_id_nulls_when_no_request_item_signal():
    item = {"action": "CREATE", "targetKind": None, "targetEntityId": "some-id"}
    solar_client._canonicalize_new_create_target_entity_id(item)
    assert item["targetEntityId"] is None


def test_canonicalize_new_create_target_entity_id_no_op_when_target_kind_request_item():
    item = {"action": "CREATE", "targetKind": "REQUEST_ITEM", "targetEntityId": "some-id"}
    solar_client._canonicalize_new_create_target_entity_id(item)
    assert item["targetEntityId"] == "some-id"


def test_canonicalize_new_create_target_entity_id_no_op_when_changed_fields_present():
    """targetKind는 없지만 changedFields가 있으면(REQUEST_ITEM 수정 의도가 있을 수 있음)
    건드리지 않는다."""
    item = {"action": "CREATE", "changedFields": ["title"], "targetEntityId": "some-id"}
    solar_client._canonicalize_new_create_target_entity_id(item)
    assert item["targetEntityId"] == "some-id"


def test_canonicalize_new_create_target_entity_id_no_op_when_already_null():
    item = {"action": "CREATE", "targetKind": None, "targetEntityId": None}
    solar_client._canonicalize_new_create_target_entity_id(item)
    assert item["targetEntityId"] is None


def test_canonicalize_new_create_target_entity_id_no_op_for_non_create_action():
    item = {"action": "UPDATE", "targetKind": None, "targetEntityId": "some-id"}
    solar_client._canonicalize_new_create_target_entity_id(item)
    assert item["targetEntityId"] == "some-id"


def test_canonicalize_missing_remaining_minutes_fills_for_create():
    item = {"action": "CREATE", "normalizedPayload": {"title": "T"}}
    solar_client._canonicalize_missing_remaining_minutes(item)
    assert item["normalizedPayload"]["remainingMinutes"] is None


def test_canonicalize_missing_remaining_minutes_fills_for_update_when_untouched():
    item = {
        "action": "UPDATE",
        "updateFields": ["title"],
        "normalizedPayload": {"title": "T"},
    }
    solar_client._canonicalize_missing_remaining_minutes(item)
    assert item["normalizedPayload"]["remainingMinutes"] is None


def test_canonicalize_missing_remaining_minutes_no_op_when_update_field_targets_it():
    """remainingMinutes를 실제로 바꾸려는 UPDATE에서 키가 없으면 계약 위반으로 남긴다."""
    item = {
        "action": "UPDATE",
        "updateFields": ["remainingMinutes"],
        "normalizedPayload": {"title": "T"},
    }
    solar_client._canonicalize_missing_remaining_minutes(item)
    assert "remainingMinutes" not in item["normalizedPayload"]


def test_canonicalize_missing_remaining_minutes_no_op_when_key_already_present():
    item = {"action": "CREATE", "normalizedPayload": {"remainingMinutes": 30}}
    solar_client._canonicalize_missing_remaining_minutes(item)
    assert item["normalizedPayload"]["remainingMinutes"] == 30


def test_canonicalize_missing_remaining_minutes_no_op_for_delete():
    item = {"action": "DELETE", "normalizedPayload": {"title": "T"}}
    solar_client._canonicalize_missing_remaining_minutes(item)
    assert "remainingMinutes" not in item["normalizedPayload"]


# ---------------------------------------------------------------------------
# 위 3가지가 실제로 _canonicalize_response_content 파이프라인을 통해 적용되고, strict
# parser를 통과시키는지 end-to-end로 확인한다.
# ---------------------------------------------------------------------------


def test_canonicalize_response_content_fixes_create_merge_missing_keys_end_to_end():
    body = {
        "analysisMessage": "분석 완료",
        "items": [
            {
                "entityType": "TASK",
                "action": "CREATE",
                "targetEntityId": REQUEST_ITEM_ID,
                "targetKind": "REQUEST_ITEM",
                "rawLineText": "예상 시간을 2시간으로",
                "changedFields": ["estimatedMinutes"],
                "normalizedPayload": {
                    "title": None,
                    "deadlineAt": None,
                    "estimatedMinutes": 120,
                    "estimatedMinutesSource": "USER",
                    "amountText": None,
                    "amountSource": None,
                },
                "pendingQuestion": None,
            }
        ],
        "unresolvedLine": None,
    }
    canonicalized = solar_client._canonicalize_response_content(json.dumps(body, ensure_ascii=False))
    result = parse_solar_response(
        canonicalized,
        purpose=SolarRequestPurpose.ACTIVE_CYCLE,
        candidate_task_ids=set(),
        candidate_fixed_schedule_ids=set(),
        analysis_mode="CHANGE_INPUT",
        candidate_request_items={REQUEST_ITEM_ID: {"entityType": "TASK", "action": "CREATE"}},
    )
    assert len(result.items) == 1
    item = result.items[0]
    assert item.action == "CREATE"
    assert item.target_kind == "REQUEST_ITEM"
    # remainingMinutes를 estimatedMinutes와 동기화하는 건 서비스 계층(`_apply_create_merge_patch`)
    # 책임이라 파서 단계에서는 canonicalization이 채운 null 그대로 통과한다.
    assert item.normalized_payload["remainingMinutes"] is None


def test_canonicalize_response_content_still_rejects_when_user_actually_changes_deadline():
    """deadlineAt이 changedFields에 있는데 deadlineState가 없으면 canonicalization 후에도
    여전히 거부돼야 한다(임의 보완 금지 확인)."""
    body = {
        "analysisMessage": "분석 완료",
        "items": [
            {
                "entityType": "TASK",
                "action": "CREATE",
                "targetEntityId": REQUEST_ITEM_ID,
                "targetKind": "REQUEST_ITEM",
                "rawLineText": "마감을 8월 1일로",
                "changedFields": ["deadlineAt"],
                "normalizedPayload": {
                    "title": None,
                    "deadlineAt": "2026-08-01T23:59:59+09:00",
                    "estimatedMinutes": None,
                    "estimatedMinutesSource": None,
                    "remainingMinutes": None,
                    "amountText": None,
                    "amountSource": None,
                },
                "pendingQuestion": None,
            }
        ],
        "unresolvedLine": None,
    }
    canonicalized = solar_client._canonicalize_response_content(json.dumps(body, ensure_ascii=False))
    with pytest.raises(SolarUnavailableError):
        parse_solar_response(
            canonicalized,
            purpose=SolarRequestPurpose.ACTIVE_CYCLE,
            candidate_task_ids=set(),
            candidate_fixed_schedule_ids=set(),
            analysis_mode="CHANGE_INPUT",
            candidate_request_items={REQUEST_ITEM_ID: {"entityType": "TASK", "action": "CREATE"}},
        )
