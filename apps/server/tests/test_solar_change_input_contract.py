import json

import pytest

from app.services import solar_client
from app.services.solar_client import SolarUnavailableError, parse_change_input_response

TASK_ID = "11111111-1111-1111-1111-111111111111"
ITEM_ID = "22222222-2222-2222-2222-222222222222"


def _parse(data, *, item_action="CREATE"):
    return parse_change_input_response(
        json.dumps(data),
        candidate_task_ids={TASK_ID},
        candidate_fixed_schedule_ids=set(),
        candidate_request_items={ITEM_ID: {"entityType": "TASK", "action": item_action}},
    )


def _envelope(operation=None, unresolved=None):
    return {"analysisMessage": "반영할게요.", "operations": [] if operation is None else [operation],
            "unresolvedOperation": unresolved}


def _task_add(**payload_overrides):
    payload = {"title": "과제", "deadlineAt": None, "deadlineState": "NONE",
               "estimatedMinutes": 60, "estimatedMinutesSource": "USER",
               "amountText": None, "amountSource": "UNKNOWN"}
    payload.update(payload_overrides)
    return {"operationType": "ADD", "entityType": "TASK", "rawLineText": "과제 추가",
            "payload": payload, "pendingQuestion": None}


def test_add_task_omits_remaining_minutes_and_server_model_initializes_it():
    result = _parse(_envelope(_task_add()))
    operation = result.operations[0]
    assert operation.normalized_payload["remainingMinutes"] == 60


def test_add_task_allows_null_title_and_marks_it_missing():
    operation = _parse(_envelope(_task_add(title=None))).operations[0]
    assert operation.missing_fields[0] == "title"


def test_add_rejects_remaining_minutes_as_extra_key():
    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(_task_add(remainingMinutes=60)))


def test_patch_request_item_accepts_exact_sparse_patch():
    operation = {"operationType": "PATCH_REQUEST_ITEM", "requestItemId": ITEM_ID,
                 "entityType": "TASK", "changedFields": ["estimatedMinutes"],
                 "patch": {"estimatedMinutes": 90, "estimatedMinutesSource": "USER"},
                 "pendingQuestion": None}
    parsed = _parse(_envelope(operation)).operations[0]
    assert parsed.patch == {"estimatedMinutes": 90, "estimatedMinutesSource": "USER"}


@pytest.mark.parametrize("changed_fields,patch", [
    ([], {}),
    (["title", "title"], {"title": "x"}),
    (["remainingMinutes"], {"remainingMinutes": 10}),
    (["title"], {"title": "x", "deadlineAt": None}),
    (["deadlineAt"], {"deadlineAt": None}),
])
def test_patch_rejects_invalid_field_or_key_sets(changed_fields, patch):
    operation = {"operationType": "PATCH_REQUEST_ITEM", "requestItemId": ITEM_ID,
                 "entityType": "TASK", "changedFields": changed_fields, "patch": patch,
                 "pendingQuestion": None}
    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(operation))


def test_patch_rejects_non_create_request_item():
    operation = {"operationType": "PATCH_REQUEST_ITEM", "requestItemId": ITEM_ID,
                 "entityType": "TASK", "changedFields": ["title"], "patch": {"title": "x"},
                 "pendingQuestion": None}
    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(operation), item_action="UPDATE")


def test_delete_request_item_rejects_payload():
    operation = {"operationType": "DELETE_REQUEST_ITEM", "requestItemId": ITEM_ID,
                 "entityType": "TASK", "payload": {}}
    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(operation))


def test_update_entity_allows_remaining_minutes_without_untouched_fields():
    operation = {"operationType": "UPDATE_ENTITY", "targetEntityId": TASK_ID,
                 "entityType": "TASK", "updateFields": ["remainingMinutes"],
                 "patch": {"remainingMinutes": 5}, "pendingQuestion": None}
    assert _parse(_envelope(operation)).operations[0].patch == {"remainingMinutes": 5}


def test_delete_entity_rejects_deadline_state():
    operation = {"operationType": "DELETE_ENTITY", "targetEntityId": TASK_ID,
                 "entityType": "TASK", "deadlineState": "NONE"}
    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(operation))


def test_candidate_namespaces_are_not_interchangeable():
    operation = {"operationType": "DELETE_ENTITY", "targetEntityId": ITEM_ID, "entityType": "TASK"}
    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(operation))


def test_duplicate_target_operations_are_rejected_regardless_of_kind():
    patch = {"operationType": "PATCH_REQUEST_ITEM", "requestItemId": ITEM_ID,
             "entityType": "TASK", "changedFields": ["title"], "patch": {"title": "x"},
             "pendingQuestion": None}
    delete = {"operationType": "DELETE_REQUEST_ITEM", "requestItemId": ITEM_ID, "entityType": "TASK"}
    envelope = _envelope()
    envelope["operations"] = [delete, patch]
    with pytest.raises(SolarUnavailableError):
        _parse(envelope)


@pytest.mark.parametrize("operations,unresolved", [([], None), ([_task_add()], {
    "intendedOperation": "UPDATE_ENTITY", "targetKind": "ENTITY", "entityType": "TASK",
    "rawLineText": "수정", "message": "무엇인가요?"})])
def test_top_level_requires_exactly_one_resolved_or_unresolved_branch(operations, unresolved):
    with pytest.raises(SolarUnavailableError):
        _parse({"analysisMessage": "x", "operations": operations, "unresolvedOperation": unresolved})


def test_unresolved_operation_uses_strict_intended_operation_pair():
    unresolved = {"intendedOperation": "PATCH_REQUEST_ITEM", "targetKind": "REQUEST_ITEM",
                  "entityType": "TASK", "rawLineText": "그 카드 수정", "message": "어떤 카드인가요?"}
    assert _parse(_envelope(unresolved=unresolved)).unresolved_operation.target_kind == "REQUEST_ITEM"
    unresolved["targetKind"] = "ENTITY"
    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(unresolved=unresolved))


def test_pending_question_null_allowed_but_malformed_object_rejected():
    operation = _task_add(title=None)
    operation["pendingQuestion"] = {"field": "title", "message": "제목?"}
    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(operation))


def test_change_input_repair_uses_same_strict_parser_and_only_one_retry(monkeypatch):
    responses = iter([json.dumps(_envelope(_task_add(remainingMinutes=60))), json.dumps(_envelope(_task_add()))])
    calls = []
    monkeypatch.setattr(solar_client, "call_solar", lambda payload: calls.append(payload) or next(responses))
    result = solar_client.analyze_change_input("추가", now=solar_client.datetime.now(solar_client._SEOUL_TZ),
                                               purpose=solar_client.SolarRequestPurpose.ACTIVE_CYCLE)
    assert len(calls) == 2
    assert result.operations[0].operation_type.value == "ADD"
