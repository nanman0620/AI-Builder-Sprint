import json
import inspect

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
    monkeypatch.setattr(solar_client, "call_solar", lambda payload: json.dumps({"analysisSummary": "add"}))
    async def fake_generate(**kwargs):
        calls.append(kwargs)
        return next(responses)
    monkeypatch.setattr(solar_client.gemini_change_input_client, "generate_change_input", fake_generate)
    result = solar_client.analyze_change_input("추가", now=solar_client.datetime.now(solar_client._SEOUL_TZ),
                                               purpose=solar_client.SolarRequestPurpose.ACTIVE_CYCLE)
    assert len(calls) == 2
    assert result.operations[0].operation_type.value == "ADD"


def _change_input_system_prompt():
    return solar_client._build_change_input_operation_prompt_messages(
        "message",
        now=solar_client.datetime.now(solar_client._SEOUL_TZ),
        cycle_start=None,
        cycle_end=None,
        candidate_tasks=[],
        candidate_fixed_schedules=[],
        candidate_request_items=[],
    )[0]["content"]


def test_change_input_prompt_contains_operation_decision_table_and_add_boundary():
    prompt = _change_input_system_prompt()
    assert "SECTION 1 — DECIDE OPERATION" in prompt
    assert "First decide the operation. Do not choose a JSON shape before deciding the operation." in prompt
    assert "New Task or FixedSchedule" in prompt
    assert "missing fields" in prompt
    assert "exactly one matching candidateRequestItem" in prompt
    assert "two or more matching existing targets" in prompt
    for pair in (
        "PATCH_REQUEST_ITEM + REQUEST_ITEM",
        "DELETE_REQUEST_ITEM + REQUEST_ITEM",
        "UPDATE_ENTITY + ENTITY",
        "DELETE_ENTITY + ENTITY",
    ):
        assert pair in prompt


def test_change_input_prompt_has_strict_logical_to_storage_mapping():
    prompt = _change_input_system_prompt()
    assert "PATCH_REQUEST_ITEM TASK logical fields: title, deadlineAt, estimatedMinutes, amount" in prompt
    assert "UPDATE_ENTITY TASK logical fields: title, deadlineAt, estimatedMinutes, remainingMinutes, amount" in prompt
    assert "estimatedMinutes -> estimatedMinutes, estimatedMinutesSource" in prompt
    assert "Never put estimatedMinutesSource or amountSource in changedFields/updateFields" in prompt


def test_change_input_prompt_examples_preserve_exact_operation_shapes():
    prompt = _change_input_system_prompt()
    assert "FULL ENVELOPE EXAMPLE 1 — COMPLETE ADD" in prompt
    assert "FULL ENVELOPE EXAMPLE 2 — MISSING ADD" in prompt
    assert "FULL ENVELOPE EXAMPLE 3 — SINGLE-CANDIDATE DELETE_REQUEST_ITEM" in prompt
    assert '"operations":[{"operationType":"ADD","entityType":"TASK","rawLineText":"new task"' in prompt
    assert '"operations":[{"operationType":"DELETE_REQUEST_ITEM","requestItemId":"22222222-2222-2222-2222-222222222222","entityType":"TASK"}]' in prompt
    add_examples = [line for line in prompt.splitlines() if '"operationType":"ADD"' in line]
    assert add_examples
    assert all("requestItemId" not in line and "targetEntityId" not in line and "remainingMinutes" not in line for line in add_examples)
    assert all('"unresolvedOperation":null' in line for line in add_examples)
    assert len([line for line in prompt.splitlines() if "EXAMPLE" in line]) == 3


def test_change_input_delete_contract_is_exact_and_has_no_pending_question():
    prompt = _change_input_system_prompt()
    delete_example = prompt.split(
        "FULL ENVELOPE EXAMPLE 3 — SINGLE-CANDIDATE DELETE_REQUEST_ITEM\n", 1
    )[1].split("\n\n", 1)[0]
    envelope = json.loads(delete_example)
    operation = envelope["operations"][0]
    assert set(operation) == {"operationType", "requestItemId", "entityType"}
    assert "pendingQuestion" not in operation
    assert "unresolvedOperation is forbidden" in prompt
    assert "Do not change this deletion into ADD, PATCH_REQUEST_ITEM, or UPDATE_ENTITY" in prompt


def test_change_input_prompt_states_pending_question_and_analysis_message_rules():
    prompt = _change_input_system_prompt()
    assert "analysisMessage must be a nonblank string; null is forbidden" in prompt
    assert "pendingQuestion is allowed as an object only when at least one field is missing" in prompt
    assert "attemptCount must be an integer >= 1" in prompt
    assert "If nothing is missing, pendingQuestion must be null" in prompt


def test_change_input_repair_contains_safe_specific_contract_context(monkeypatch):
    invalid = _envelope({
        "operationType": "PATCH_REQUEST_ITEM",
        "requestItemId": ITEM_ID,
        "entityType": "TASK",
        "changedFields": ["estimatedMinutes", "estimatedMinutesSource"],
        "patch": {"estimatedMinutes": 90, "estimatedMinutesSource": "USER"},
        "pendingQuestion": None,
    })
    responses = iter([json.dumps(invalid), json.dumps(_envelope(_task_add()))])
    calls = []
    monkeypatch.setattr(solar_client, "call_solar", lambda payload: json.dumps({"analysisSummary": "change"}))
    async def fake_generate(**kwargs):
        calls.append(kwargs)
        return next(responses)
    monkeypatch.setattr(solar_client.gemini_change_input_client, "generate_change_input", fake_generate)
    solar_client.analyze_change_input(
        "change",
        now=solar_client.datetime.now(solar_client._SEOUL_TZ),
        purpose=solar_client.SolarRequestPurpose.ACTIVE_CYCLE,
        candidate_request_items={ITEM_ID: {"entityType": "TASK", "action": "CREATE"}},
    )
    repair_instruction = calls[1]["prompt"]
    assert "REPAIR THE FINAL RESPONSE" in repair_instruction
    assert "operation index: 0" in repair_instruction
    assert "expected exact keys:" in repair_instruction
    assert "allowed logical fields:" in repair_instruction
    assert "required patch storage keys:" in repair_instruction
    safe_context = repair_instruction.split("Safe violation context:\n", 1)[1]
    assert ITEM_ID not in safe_context
    assert len(calls) == 2


def test_change_input_delete_repair_preserves_intent_and_restates_exact_keys(monkeypatch):
    invalid = {
        "analysisMessage": "x",
        "operations": [],
        "unresolvedOperation": None,
    }
    valid = _envelope({
        "operationType": "DELETE_REQUEST_ITEM",
        "requestItemId": ITEM_ID,
        "entityType": "TASK",
    })
    responses = iter([json.dumps(invalid), json.dumps(valid)])
    calls = []
    monkeypatch.setattr(solar_client, "call_solar", lambda payload: json.dumps({"analysisSummary": "delete"}))
    async def fake_generate(**kwargs):
        calls.append(kwargs)
        return next(responses)
    monkeypatch.setattr(solar_client.gemini_change_input_client, "generate_change_input", fake_generate)
    solar_client.analyze_change_input(
        "delete",
        now=solar_client.datetime.now(solar_client._SEOUL_TZ),
        purpose=solar_client.SolarRequestPurpose.ACTIVE_CYCLE,
        candidate_request_items={ITEM_ID: {"entityType": "TASK", "action": "CREATE"}},
    )
    instruction = calls[1]["prompt"]
    assert "REPAIR THE FINAL RESPONSE" in instruction
    assert "SOLAR advisory remains non-authoritative" in instruction
    assert len(calls) == 2


def test_change_input_context_includes_candidate_counts_without_replacing_candidates():
    content = solar_client._build_change_input_operation_prompt_messages(
        "message",
        now=solar_client.datetime.now(solar_client._SEOUL_TZ),
        cycle_start=None,
        cycle_end=None,
        candidate_tasks=[{"id": TASK_ID}],
        candidate_fixed_schedules=[{"id": "33333333-3333-3333-3333-333333333333"}],
        candidate_request_items=[{"id": ITEM_ID, "entityType": "TASK", "action": "CREATE"}],
    )[0]["content"]
    context_text = content.split("SECTION 2 — CANDIDATE FACTS\n", 1)[1].split("\n\n", 1)[0]
    context = json.loads(context_text)
    assert context["candidateRequestItemCount"] == 1
    assert context["candidateTaskCount"] == 1
    assert context["candidateFixedScheduleCount"] == 1
    assert context["totalEntityCandidateCount"] == 2
    assert context["candidateRequestItems"][0]["id"] == ITEM_ID
    assert context["candidateTasks"][0]["id"] == TASK_ID


def test_change_input_decision_section_encodes_filtered_candidate_hard_rules():
    prompt = _change_input_system_prompt()
    decide = prompt.split("SECTION 1 — DECIDE OPERATION", 1)[1].split("SECTION 2 — CANDIDATE FACTS", 1)[0]
    assert "candidate count is zero" in decide
    assert "null values and pendingQuestion" in decide
    assert "exactly one matching candidateRequestItem" in decide
    assert "DELETE_REQUEST_ITEM" in decide
    assert "two or more matching existing targets" in decide
    assert "unresolvedOperation" in decide


def test_change_input_prompt_orders_decision_facts_then_exact_json():
    prompt = _change_input_system_prompt()
    assert prompt.index("SECTION 1 — DECIDE OPERATION") < prompt.index("SECTION 2 — CANDIDATE FACTS")
    assert prompt.index("SECTION 2 — CANDIDATE FACTS") < prompt.index("SECTION 3 — BUILD EXACT JSON")
    assert "A namespace with count 0 cannot supply an ID" in prompt
    assert "A single matching candidate is not ambiguous" in prompt


def test_change_input_builder_has_no_unused_legacy_prompt_variables():
    source = inspect.getsource(solar_client._build_change_input_operation_prompt_messages)
    assert "system_prompt =" not in source
    assert "final_decision_gate =" not in source
