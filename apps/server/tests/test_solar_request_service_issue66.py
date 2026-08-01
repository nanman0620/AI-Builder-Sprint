import uuid
from datetime import datetime, timezone

import pytest

from app.core.errors import ApiError
from app.models.enums import (
    SolarAction,
    SolarEntityType,
    SolarItemStatus,
    SolarMessageKind,
    SolarMessageRole,
    SolarRequestPurpose,
    SolarRequestStatus,
)
from app.models.solar_message import SolarMessage
from app.models.solar_request import SolarRequest
from app.models.solar_request_item import SolarRequestItem
from app.services import solar_request_service
from app.services.solar_client import (
    ChangeInputAddOperation,
    ChangeInputAnalysisResult,
    ChangeInputDeleteRequestItemOperation,
    ChangeInputOperationType,
    ChangeInputPatchRequestItemOperation,
    ResolvedTargetOnly,
    SolarAnalysisItem,
    SolarUnavailableError,
)


class _TransactionBoundary:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        if self.db.active:
            raise RuntimeError("A transaction is already begun on this Session.")
        self.db.active = True
        self._message_count = len(self.db.persisted_messages)
        self._item_count = len(self.db.persisted_items)
        self._status = self.db.request.status
        return self

    def __exit__(self, exc_type, exc, tb):
        self.db.active = False
        if exc_type is None:
            self.db.commit_count += 1
        else:
            self.db.rollback_count += 1
            del self.db.persisted_messages[self._message_count :]
            del self.db.persisted_items[self._item_count :]
            self.db.request.status = self._status
        return False


class _TransactionTrackingDb:
    def __init__(self):
        self.active = False
        self.commit_count = 0
        self.rollback_count = 0
        self.persisted_messages = []
        self.persisted_items = []
        self.request = _GuardedRequest(self)

    def begin(self):
        return _TransactionBoundary(self)


class _GuardedRequest:
    def __init__(self, db):
        self._db = db
        self.id = uuid.uuid4()
        self.user_id = USER_ID
        self.plan_cycle_id = None
        self.status = SolarRequestStatus.CHANGE_INPUT

    @property
    def purpose(self):
        if not self._db.active:
            self._db.active = True
        return SolarRequestPurpose.NEW_CYCLE

USER_ID = uuid.uuid4()
NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


def _make_request(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        user_id=USER_ID,
        plan_cycle_id=None,
        purpose=SolarRequestPurpose.ACTIVE_CYCLE,
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
    )
    defaults.update(overrides)
    return SolarRequest(**defaults)


def _make_item(*, item_order, action, status, entity_type="TASK", missing_fields=None, **overrides):
    defaults = dict(
        id=uuid.uuid4(),
        user_id=USER_ID,
        solar_request_id=uuid.uuid4(),
        item_order=item_order,
        action=SolarAction(action),
        entity_type=SolarEntityType(entity_type),
        status=SolarItemStatus(status),
        raw_line_text="원문",
        normalized_payload={
            "title": "제목",
            "deadlineAt": None,
            "estimatedMinutes": None,
            "estimatedMinutesSource": None,
            "remainingMinutes": None,
            "amountText": None,
            "amountSource": None,
        },
        missing_fields=missing_fields or [],
        pending_question=None,
        target_task_id=None,
        target_fixed_schedule_id=None,
        executed_at=None,
    )
    defaults.update(overrides)
    return SolarRequestItem(**defaults)


def _make_message(*, sequence_no, role, kind, metadata=None, content="내용"):
    return SolarMessage(
        id=uuid.uuid4(),
        user_id=USER_ID,
        solar_request_id=uuid.uuid4(),
        client_event_id=None,
        sequence_no=sequence_no,
        role=role,
        kind=kind,
        content=content,
        message_metadata=metadata or {},
    )


class _FakeDb:
    def __init__(self):
        self.added = []
        self.deleted = []

    def add(self, value):
        self.added.append(value)

    def delete(self, value):
        self.deleted.append(value)

    def flush(self):
        pass


def test_change_input_add_initializes_remaining_minutes_server_side():
    request = _make_request(status=SolarRequestStatus.CHANGE_INPUT)
    operation = ChangeInputAddOperation(
        ChangeInputOperationType.ADD, "TASK", "과제 추가",
        {"title": "과제", "deadlineAt": None, "estimatedMinutes": 80,
         "estimatedMinutesSource": "USER", "remainingMinutes": None,
         "amountText": None, "amountSource": "UNKNOWN"}, [], None,
    )
    items = []
    solar_request_service._apply_change_input_operations(
        _FakeDb(), user_id=USER_ID, request=request, items=items,
        analysis=ChangeInputAnalysisResult("반영", [operation], None), raw_line_text="추가",
    )
    assert items[0].normalized_payload["remainingMinutes"] == 80


def test_change_input_patch_preserves_untouched_payload_and_syncs_remaining():
    item = _make_item(
        item_order=1, action="CREATE", status="READY",
        normalized_payload={"title": "기존", "deadlineAt": None, "estimatedMinutes": 30,
                            "estimatedMinutesSource": "USER", "remainingMinutes": 10,
                            "amountText": None, "amountSource": "UNKNOWN"},
    )
    operation = ChangeInputPatchRequestItemOperation(
        ChangeInputOperationType.PATCH_REQUEST_ITEM, str(item.id), "TASK",
        ["estimatedMinutes"], {"estimatedMinutes": 90, "estimatedMinutesSource": "USER"}, [], None,
    )
    solar_request_service._apply_change_input_operations(
        _FakeDb(), user_id=USER_ID, request=_make_request(), items=[item],
        analysis=ChangeInputAnalysisResult("반영", [operation], None), raw_line_text="수정",
    )
    assert item.normalized_payload["title"] == "기존"
    assert item.normalized_payload["estimatedMinutes"] == 90
    assert item.normalized_payload["remainingMinutes"] == 90


def test_change_input_delete_request_item_physically_removes_and_renumbers():
    first = _make_item(item_order=1, action="CREATE", status="READY")
    second = _make_item(item_order=2, action="UPDATE", status="READY")
    db = _FakeDb()
    operation = ChangeInputDeleteRequestItemOperation(
        ChangeInputOperationType.DELETE_REQUEST_ITEM, str(first.id), "TASK"
    )
    items = [first, second]
    solar_request_service._apply_change_input_operations(
        db, user_id=USER_ID, request=_make_request(), items=items,
        analysis=ChangeInputAnalysisResult("반영", [operation], None), raw_line_text="삭제",
    )
    assert db.deleted == [first]
    assert items == [second]
    assert second.item_order == 1


def test_change_input_invalid_fixed_schedule_becomes_missing_end_question():
    payload, missing, pending = solar_request_service._normalize_change_fixed_schedule(
        {"title": "회의", "startAt": "2026-08-01T11:00:00+09:00",
         "endAt": "2026-08-01T10:00:00+09:00"}, [], None
    )
    assert payload["endAt"] is None
    assert missing == ["endAt"]
    assert pending["field"] == "endAt"


# ---------------------------------------------------------------------------
# _ensure_pending_question
# ---------------------------------------------------------------------------


def test_ensure_pending_question_leaves_valid_question_untouched():
    item = _make_item(
        item_order=1,
        action="CREATE",
        status="INFO_MISSING",
        missing_fields=["deadlineAt", "amount"],
        pending_question={"field": "deadlineAt", "message": "마감이 언제인가요?", "attemptCount": 1},
    )
    solar_request_service._ensure_pending_question(item)
    assert item.pending_question == {"field": "deadlineAt", "message": "마감이 언제인가요?", "attemptCount": 1}


def test_ensure_pending_question_recovers_when_missing():
    item = _make_item(item_order=1, action="CREATE", status="INFO_MISSING", missing_fields=["amount"], pending_question=None)
    solar_request_service._ensure_pending_question(item)
    assert item.pending_question["field"] == "amount"
    assert item.pending_question["attemptCount"] == 1


def test_ensure_pending_question_recovers_when_field_not_canonical_first():
    item = _make_item(
        item_order=1,
        action="CREATE",
        status="INFO_MISSING",
        missing_fields=["deadlineAt", "amount"],
        pending_question={"field": "amount", "message": "분량?", "attemptCount": 1},
    )
    solar_request_service._ensure_pending_question(item)
    assert item.pending_question["field"] == "deadlineAt"


def test_ensure_pending_question_raises_when_missing_fields_empty_but_status_info_missing():
    item = _make_item(item_order=1, action="CREATE", status="INFO_MISSING", missing_fields=[], pending_question=None)
    with pytest.raises(ApiError):
        solar_request_service._ensure_pending_question(item)


def test_ensure_pending_question_no_op_for_ready_card():
    item = _make_item(item_order=1, action="CREATE", status="READY", missing_fields=[], pending_question=None)
    solar_request_service._ensure_pending_question(item)
    assert item.pending_question is None


# ---------------------------------------------------------------------------
# _advance_card_after_field_resolved / _recompute_request_collecting_state
# ---------------------------------------------------------------------------


def test_advance_card_after_field_resolved_moves_to_next_field_same_card():
    item = _make_item(item_order=1, action="CREATE", status="INFO_MISSING", missing_fields=["deadlineAt", "amount"])
    request = _make_request(current_item_order=1)

    kind, content = solar_request_service._advance_card_after_field_resolved(item, request, ["amount"])

    assert kind == "QUESTION"
    assert item.missing_fields == ["amount"]
    assert item.status == SolarItemStatus.INFO_MISSING
    assert item.pending_question["field"] == "amount"
    assert request.current_item_order == 1


def test_advance_card_after_field_resolved_marks_ready_when_no_missing_left():
    item = _make_item(item_order=1, action="CREATE", status="INFO_MISSING", missing_fields=["amount"])
    request = _make_request(current_item_order=1)

    kind, content = solar_request_service._advance_card_after_field_resolved(item, request, [])

    assert (kind, content) == (None, None)
    assert item.status == SolarItemStatus.READY
    assert item.pending_question is None


def test_recompute_request_collecting_state_zero_items_stays_change_input():
    request = _make_request(status=SolarRequestStatus.COLLECTING)
    kind, content = solar_request_service._recompute_request_collecting_state(request, [])
    assert request.status == SolarRequestStatus.CHANGE_INPUT
    assert request.current_item_order is None
    assert kind == "TEXT"


def test_recompute_request_collecting_state_picks_earliest_info_missing_card():
    ready_item = _make_item(item_order=1, action="CREATE", status="READY")
    missing_item = _make_item(
        item_order=2, action="CREATE", status="INFO_MISSING", missing_fields=["amount"],
        pending_question={"field": "amount", "message": "분량?", "attemptCount": 1},
    )
    request = _make_request()

    kind, content = solar_request_service._recompute_request_collecting_state(request, [ready_item, missing_item])

    assert kind == "QUESTION"
    assert content == "분량?"
    assert request.status == SolarRequestStatus.COLLECTING
    assert request.current_item_order == 2


def test_recompute_request_collecting_state_all_ready_moves_to_change_confirmation():
    ready_item = _make_item(item_order=1, action="CREATE", status="READY")
    request = _make_request()

    kind, content = solar_request_service._recompute_request_collecting_state(request, [ready_item])

    assert (kind, content) == (None, None)
    assert request.status == SolarRequestStatus.CHANGE_CONFIRMATION
    assert request.current_item_order is None


# ---------------------------------------------------------------------------
# _apply_create_merge_patch
# ---------------------------------------------------------------------------


def test_apply_create_merge_patch_updates_payload_and_clears_missing():
    item = _make_item(
        item_order=1,
        action="CREATE",
        status="INFO_MISSING",
        missing_fields=["estimatedMinutes"],
        normalized_payload={
            "title": "제목", "deadlineAt": None, "estimatedMinutes": None, "estimatedMinutesSource": None,
            "remainingMinutes": None, "amountText": None, "amountSource": None,
        },
    )
    canonical_patch_payload = {
        "title": None, "deadlineAt": None, "estimatedMinutes": 90, "estimatedMinutesSource": "USER",
        "remainingMinutes": None, "amountText": None, "amountSource": None,
    }

    solar_request_service._apply_create_merge_patch(item, ["estimatedMinutes"], canonical_patch_payload, [])

    assert item.normalized_payload["estimatedMinutes"] == 90
    assert item.normalized_payload["remainingMinutes"] == 90  # CREATE 카드 동기화
    assert item.missing_fields == []
    assert item.status == SolarItemStatus.READY
    assert item.pending_question is None


def test_apply_create_merge_patch_preserves_deadline_missing_vs_none_distinction():
    """deadlineAt=null 하나만으로는 "마감 없음 확정"과 "아직 모름"을 구분할 수 없어
    parsed_patch_missing_fields를 그대로 신뢰해야 한다."""
    item = _make_item(
        item_order=1, action="CREATE", status="INFO_MISSING", missing_fields=["deadlineAt"],
        normalized_payload={
            "title": "제목", "deadlineAt": None, "estimatedMinutes": 60, "estimatedMinutesSource": "USER",
            "remainingMinutes": 60, "amountText": None, "amountSource": None,
        },
    )
    canonical_patch_payload = {
        "title": None, "deadlineAt": None, "estimatedMinutes": None, "estimatedMinutesSource": None,
        "remainingMinutes": None, "amountText": None, "amountSource": None,
    }

    # deadlineAt이 changedFields에 있지만 여전히 모름(parsed_patch_missing_fields에 포함)
    solar_request_service._apply_create_merge_patch(item, ["deadlineAt"], canonical_patch_payload, ["deadlineAt"])
    assert item.missing_fields == ["deadlineAt"]
    assert item.status == SolarItemStatus.INFO_MISSING

    # "마감 없음 확정" — parsed_patch_missing_fields가 비어있음
    solar_request_service._apply_create_merge_patch(item, ["deadlineAt"], canonical_patch_payload, [])
    assert item.missing_fields == []
    assert item.status == SolarItemStatus.READY


# ---------------------------------------------------------------------------
# _merge_real_target_item
# ---------------------------------------------------------------------------


def test_merge_real_target_item_delete_wins_over_existing_update():
    existing = _make_item(item_order=1, action="UPDATE", status="READY")
    solar_request_service._merge_real_target_item(existing, "DELETE", {"title": "스냅샷"}, [], [], None, "삭제해줘")
    assert existing.action == SolarAction.DELETE
    assert existing.normalized_payload == {"title": "스냅샷"}
    assert existing.missing_fields == []
    assert existing.status == SolarItemStatus.READY


def test_merge_real_target_item_delete_then_update_becomes_update():
    existing = _make_item(item_order=1, action="DELETE", status="READY", normalized_payload={"title": "스냅샷"})
    new_payload = {
        "title": "새 제목", "deadlineAt": None, "estimatedMinutes": None, "estimatedMinutesSource": None,
        "remainingMinutes": None, "amountText": None, "amountSource": None,
    }
    solar_request_service._merge_real_target_item(existing, "UPDATE", new_payload, ["title"], [], None, "다시 수정")
    assert existing.action == SolarAction.UPDATE
    assert existing.normalized_payload["title"] == "새 제목"
    assert existing.normalized_payload["_updateFields"] == ["title"]


def test_merge_real_target_item_update_plus_update_unions_fields():
    existing = _make_item(
        item_order=1, action="UPDATE", status="READY",
        normalized_payload={
            "title": "기존 제목", "deadlineAt": None, "estimatedMinutes": None, "estimatedMinutesSource": None,
            "remainingMinutes": None, "amountText": None, "amountSource": None, "_updateFields": ["title"],
        },
    )
    new_payload = {
        "title": None, "deadlineAt": "2026-08-01T00:00:00+09:00", "estimatedMinutes": None,
        "estimatedMinutesSource": None, "remainingMinutes": None, "amountText": None, "amountSource": None,
    }
    solar_request_service._merge_real_target_item(existing, "UPDATE", new_payload, ["deadlineAt"], [], None, "마감도 수정")
    assert set(existing.normalized_payload["_updateFields"]) == {"title", "deadlineAt"}
    assert existing.normalized_payload["title"] == "기존 제목"  # 안 건드린 필드는 유지
    assert existing.normalized_payload["deadlineAt"] == "2026-08-01T00:00:00+09:00"


# ---------------------------------------------------------------------------
# _renumber_items_after_delete
# ---------------------------------------------------------------------------


def test_renumber_items_after_delete_produces_contiguous_positive_order():
    item_a = _make_item(item_order=1, action="CREATE", status="READY")
    item_c = _make_item(item_order=3, action="CREATE", status="READY")
    fake_db = _FakeDb()

    solar_request_service._renumber_items_after_delete(fake_db, [item_a, item_c])

    assert [item_a.item_order, item_c.item_order] == [1, 2]


def test_renumber_items_after_delete_empty_list_is_no_op():
    fake_db = _FakeDb()
    solar_request_service._renumber_items_after_delete(fake_db, [])  # raise 없이 통과해야 함


# ---------------------------------------------------------------------------
# CARD_ANSWER 적용 헬퍼
# ---------------------------------------------------------------------------


def test_apply_card_answer_provided_patches_payload_and_removes_field_from_missing():
    item = _make_item(
        item_order=1, action="CREATE", status="INFO_MISSING", missing_fields=["title", "amount"],
        normalized_payload={
            "title": None, "deadlineAt": None, "estimatedMinutes": None, "estimatedMinutesSource": None,
            "remainingMinutes": None, "amountText": None, "amountSource": None,
        },
    )
    remaining = solar_request_service._apply_card_answer_provided(item, "title", {"title": "새 제목"})
    assert item.normalized_payload["title"] == "새 제목"
    assert remaining == ["amount"]


def test_apply_card_answer_dont_know_first_time_just_reasks():
    item = _make_item(
        item_order=1, action="CREATE", status="INFO_MISSING", missing_fields=["amount"],
        pending_question={"field": "amount", "message": "분량?", "attemptCount": 1},
    )
    auto_resolved, remaining = solar_request_service._apply_card_answer_dont_know(item, "amount", "다시 알려주세요.")
    assert auto_resolved is False
    assert remaining is None
    assert item.pending_question["attemptCount"] == 2


def test_apply_card_answer_dont_know_second_time_auto_resolves_amount():
    item = _make_item(
        item_order=1, action="CREATE", status="INFO_MISSING", missing_fields=["amount"],
        pending_question={"field": "amount", "message": "분량?", "attemptCount": 2},
        normalized_payload={
            "title": "제목", "deadlineAt": None, "estimatedMinutes": None, "estimatedMinutesSource": None,
            "remainingMinutes": None, "amountText": "이전값", "amountSource": "USER",
        },
    )
    auto_resolved, remaining = solar_request_service._apply_card_answer_dont_know(item, "amount", "다시 알려주세요.")
    assert auto_resolved is True
    assert remaining == []
    assert item.normalized_payload["amountSource"] == "UNKNOWN"
    assert item.normalized_payload["amountText"] is None


def test_apply_card_answer_dont_know_second_time_does_not_auto_resolve_estimated_minutes():
    item = _make_item(
        item_order=1, action="CREATE", status="INFO_MISSING", missing_fields=["estimatedMinutes"],
        pending_question={"field": "estimatedMinutes", "message": "얼마나?", "attemptCount": 2},
    )
    auto_resolved, remaining = solar_request_service._apply_card_answer_dont_know(item, "estimatedMinutes", "다시요.")
    assert auto_resolved is False
    assert item.pending_question["attemptCount"] == 3


def test_apply_card_answer_unclear_does_not_change_attempt_count():
    item = _make_item(
        item_order=1, action="CREATE", status="INFO_MISSING", missing_fields=["amount"],
        pending_question={"field": "amount", "message": "분량?", "attemptCount": 1},
    )
    solar_request_service._apply_card_answer_unclear(item, "amount", "이해 못했어요, 다시 알려주세요.")
    assert item.pending_question == {"field": "amount", "message": "이해 못했어요, 다시 알려주세요.", "attemptCount": 1}


# ---------------------------------------------------------------------------
# _resolve_message_dispatch
# ---------------------------------------------------------------------------


def test_resolve_message_dispatch_prefers_special_question_over_card():
    request = _make_request(status=SolarRequestStatus.COLLECTING, current_item_order=1)
    card = _make_item(
        item_order=1, action="CREATE", status="INFO_MISSING", missing_fields=["amount"],
        pending_question={"field": "amount", "message": "분량?", "attemptCount": 1},
    )
    special = _make_message(
        sequence_no=5, role=SolarMessageRole.ASSISTANT, kind=SolarMessageKind.QUESTION,
        metadata={"unresolved": True},
    )
    dispatch = solar_request_service._resolve_message_dispatch(request, [card], [special])
    assert dispatch.kind == "UNRESOLVED"


def test_resolve_message_dispatch_change_details_kind():
    request = _make_request(status=SolarRequestStatus.COLLECTING)
    special = _make_message(
        sequence_no=5, role=SolarMessageRole.ASSISTANT, kind=SolarMessageKind.QUESTION,
        metadata={"followUpType": "CHANGE_DETAILS"},
    )
    dispatch = solar_request_service._resolve_message_dispatch(request, [], [special])
    assert dispatch.kind == "CHANGE_DETAILS"


def test_resolve_message_dispatch_falls_back_to_card():
    request = _make_request(status=SolarRequestStatus.COLLECTING, current_item_order=1)
    card = _make_item(
        item_order=1, action="CREATE", status="INFO_MISSING", missing_fields=["amount"],
        pending_question={"field": "amount", "message": "분량?", "attemptCount": 1},
    )
    dispatch = solar_request_service._resolve_message_dispatch(request, [card], [])
    assert dispatch.kind == "CARD"
    assert dispatch.card is card


def test_resolve_message_dispatch_raises_when_no_card_and_no_special():
    request = _make_request(status=SolarRequestStatus.COLLECTING, current_item_order=None)
    with pytest.raises(ApiError):
        solar_request_service._resolve_message_dispatch(request, [], [])


def test_resolve_message_dispatch_change_input_kind():
    request = _make_request(status=SolarRequestStatus.CHANGE_INPUT)
    dispatch = solar_request_service._resolve_message_dispatch(request, [], [])
    assert dispatch.kind == "CHANGE_INPUT"


def test_resolve_message_dispatch_raises_for_other_statuses():
    request = _make_request(status=SolarRequestStatus.FINAL_REVIEW)
    with pytest.raises(ApiError):
        solar_request_service._resolve_message_dispatch(request, [], [])


# ---------------------------------------------------------------------------
# _validate_unresolved_metadata / _validate_change_details_metadata
# ---------------------------------------------------------------------------


def test_validate_unresolved_metadata_defaults_target_kind_to_entity_for_legacy_messages():
    metadata = {
        "unresolved": True, "field": "targetEntityId", "rawLineText": "그거",
        "action": "UPDATE", "entityType": "TASK", "candidateEntityIds": ["a", "b"],
    }
    target_kind, action, entity_type, raw_line_text, candidate_ids = solar_request_service._validate_unresolved_metadata(
        metadata
    )
    assert target_kind == "ENTITY"
    assert action == "UPDATE"
    assert candidate_ids == ["a", "b"]


def test_validate_unresolved_metadata_rejects_malformed():
    with pytest.raises(ApiError):
        solar_request_service._validate_unresolved_metadata({"action": "INVALID"})


def test_validate_change_details_metadata_requires_target_entity_id():
    with pytest.raises(ApiError):
        solar_request_service._validate_change_details_metadata(
            {"followUpType": "CHANGE_DETAILS", "action": "UPDATE", "entityType": "TASK", "targetKind": "ENTITY"}
        )


def test_validate_change_details_metadata_success():
    metadata = {
        "targetKind": "REQUEST_ITEM", "action": "UPDATE", "entityType": "TASK",
        "targetEntityId": "abc", "rawLineText": "그거",
    }
    result = solar_request_service._validate_change_details_metadata(metadata)
    assert result == ("REQUEST_ITEM", "UPDATE", "TASK", "abc", "그거")


# ---------------------------------------------------------------------------
# _filter_request_item_candidates(최종 반영 #3)
# ---------------------------------------------------------------------------


def test_filter_request_item_candidates_update_only_offers_create_cards():
    create_item = _make_item(item_order=1, action="CREATE", status="READY")
    update_item = _make_item(item_order=2, action="UPDATE", status="READY")
    result = solar_request_service._filter_request_item_candidates("UPDATE", "TASK", [create_item, update_item])
    assert list(result.keys()) == [str(create_item.id)]


def test_filter_request_item_candidates_delete_offers_all_actions():
    create_item = _make_item(item_order=1, action="CREATE", status="READY")
    update_item = _make_item(item_order=2, action="UPDATE", status="READY")
    result = solar_request_service._filter_request_item_candidates("DELETE", "TASK", [create_item, update_item])
    assert set(result.keys()) == {str(create_item.id), str(update_item.id)}


# ---------------------------------------------------------------------------
# add_solar_message transaction boundaries
# ---------------------------------------------------------------------------


def _configure_message_transaction_test(monkeypatch, db, *, fail_on_persist_call=None):
    dispatch = solar_request_service._MessageDispatch(kind="CHANGE_INPUT")
    persist_calls = 0

    monkeypatch.setattr(solar_request_service, "_lock_owned_solar_request", lambda *_: db.request)
    monkeypatch.setattr(solar_request_service, "_find_message_by_client_event_id", lambda *_: None)
    monkeypatch.setattr(solar_request_service, "_load_items", lambda *_: [])
    monkeypatch.setattr(solar_request_service, "_load_messages", lambda *_: [])
    monkeypatch.setattr(solar_request_service, "_resolve_message_dispatch", lambda *_: dispatch)
    monkeypatch.setattr(
        solar_request_service.solar_client,
        "analyze_change_input",
        lambda *args, **kwargs: ChangeInputAnalysisResult("반영했어요.", [], None),
    )
    monkeypatch.setattr(
        solar_request_service,
        "_apply_change_input_operations",
        lambda *args, **kwargs: db.persisted_items.append(object()),
    )
    monkeypatch.setattr(
        solar_request_service,
        "_recompute_request_collecting_state",
        lambda request, items: (None, None),
    )

    def persist(*args, entries, **kwargs):
        nonlocal persist_calls
        persist_calls += 1
        db.persisted_messages.extend(entries)
        if persist_calls == fail_on_persist_call:
            db.request.status = SolarRequestStatus.FINAL_REVIEW
            raise RuntimeError("write failed")

    monkeypatch.setattr(solar_request_service, "_persist_ordered_messages", persist)
    monkeypatch.setattr(
        "app.services.plan_management_service.get_solar_request_detail_state",
        lambda *args, **kwargs: object(),
    )


def _add_message(db, *, event_id, message):
    return solar_request_service.add_solar_message(
        db,
        user_id=USER_ID,
        request_id=db.request.id,
        client_event_id=event_id,
        message=message,
        now=NOW,
    )


def test_add_solar_message_same_request_consecutive_messages_use_clean_transactions(monkeypatch):
    db = _TransactionTrackingDb()
    _configure_message_transaction_test(monkeypatch, db)

    _add_message(
        db,
        event_id="evt-1",
        message="영단어 오늘 5시 50분까지 20개 외워야 해. 10분 정도 걸릴 것 같아.",
    )
    _add_message(db, event_id="evt-2", message="네")

    assert db.active is False
    assert db.commit_count == 4
    assert db.rollback_count == 0
    assert len(db.persisted_items) == 2
    assert [entry["content"] for entry in db.persisted_messages if entry["role"] == SolarMessageRole.USER] == [
        "영단어 오늘 5시 50분까지 20개 외워야 해. 10분 정도 걸릴 것 같아.",
        "네",
    ]


def test_add_solar_message_write_failure_rolls_back_second_phase_once(monkeypatch):
    db = _TransactionTrackingDb()
    _configure_message_transaction_test(monkeypatch, db, fail_on_persist_call=2)

    _add_message(
        db,
        event_id="evt-1",
        message="영단어 오늘 5시 50분까지 20개 외워야 해. 10분 정도 걸릴 것 같아.",
    )
    committed_messages = list(db.persisted_messages)
    committed_items = list(db.persisted_items)

    with pytest.raises(RuntimeError, match="write failed"):
        _add_message(db, event_id="evt-2", message="네")

    assert db.active is False
    assert db.commit_count == 3
    assert db.rollback_count == 1
    assert db.persisted_messages == committed_messages
    assert db.persisted_items == committed_items
    assert db.request.status == SolarRequestStatus.CHANGE_INPUT


def test_add_solar_message_repair_failure_returns_503_without_partial_writes(monkeypatch):
    db = _TransactionTrackingDb()
    _configure_message_transaction_test(monkeypatch, db)

    def _raise_after_repair(*args, **kwargs):
        raise SolarUnavailableError(
            "repair 응답도 rawLineText를 누락했다.", code="MISSING_REQUIRED_KEY:rawLineText"
        )

    monkeypatch.setattr(solar_request_service.solar_client, "analyze_change_input", _raise_after_repair)

    with pytest.raises(ApiError) as exc_info:
        _add_message(
            db,
            event_id="evt-raw-line-repair-failed",
            message="영단어 20개는 추가하고, 발표 대본은 20분으로 바꾸고, 자료구조 복습은 없애줘",
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.code == solar_request_service.CODE_SOLAR_UNAVAILABLE
    assert db.persisted_messages == []
    assert db.persisted_items == []
    assert db.request.status == SolarRequestStatus.CHANGE_INPUT
    assert db.commit_count == 1
    assert db.rollback_count == 0
