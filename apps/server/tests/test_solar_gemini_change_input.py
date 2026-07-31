import json

import pytest

from app.models.enums import SolarRequestPurpose
from app.services import solar_client
from app.services.solar_client import SolarUnavailableError


ITEM_ID = "22222222-2222-2222-2222-222222222222"
TASK_ID = "33333333-3333-3333-3333-333333333333"


def _add_result():
    return {
        "analysisMessage": "done",
        "operations": [{
            "operationType": "ADD",
            "entityType": "TASK",
            "rawLineText": "new task",
            "payload": {
                "title": "report",
                "deadlineAt": None,
                "deadlineState": "NONE",
                "estimatedMinutes": 60,
                "estimatedMinutesSource": "USER",
                "amountText": None,
                "amountSource": "UNKNOWN",
            },
            "pendingQuestion": None,
        }],
        "unresolvedOperation": None,
    }


def _delete_result():
    return {
        "analysisMessage": "done",
        "operations": [{
            "operationType": "DELETE_REQUEST_ITEM",
            "requestItemId": ITEM_ID,
            "entityType": "TASK",
        }],
        "unresolvedOperation": None,
    }


def _resolved(operation):
    return {"analysisMessage": "done", "operations": [operation], "unresolvedOperation": None}


@pytest.mark.parametrize(("operation", "kwargs", "expected"), [
    ({
        "operationType": "PATCH_REQUEST_ITEM", "requestItemId": ITEM_ID, "entityType": "TASK",
        "changedFields": ["estimatedMinutes"],
        "patch": {"estimatedMinutes": 90, "estimatedMinutesSource": "USER"},
        "pendingQuestion": None,
    }, {"candidate_request_items": {ITEM_ID: {"entityType": "TASK", "action": "CREATE"}}},
     "PATCH_REQUEST_ITEM"),
    ({
        "operationType": "UPDATE_ENTITY", "targetEntityId": TASK_ID, "entityType": "TASK",
        "updateFields": ["remainingMinutes"], "patch": {"remainingMinutes": 30},
        "pendingQuestion": None,
    }, {"candidate_tasks": [{"id": TASK_ID, "title": "task"}]}, "UPDATE_ENTITY"),
    ({"operationType": "DELETE_REQUEST_ITEM", "requestItemId": ITEM_ID, "entityType": "TASK"},
     {"candidate_request_items": {ITEM_ID: {"entityType": "TASK", "action": "CREATE"}}},
     "DELETE_REQUEST_ITEM"),
    ({"operationType": "DELETE_ENTITY", "targetEntityId": TASK_ID, "entityType": "TASK"},
     {"candidate_tasks": [{"id": TASK_ID, "title": "task"}]}, "DELETE_ENTITY"),
])
def test_gemini_final_operations_use_existing_strict_parser(monkeypatch, operation, kwargs, expected):
    monkeypatch.setattr(solar_client, "call_solar", lambda payload: json.dumps({"analysisSummary": "advice"}))

    async def fake_generate(**unused):
        return json.dumps(_resolved(operation))

    monkeypatch.setattr(solar_client.gemini_change_input_client, "generate_change_input", fake_generate)
    assert _analyze(**kwargs).operations[0].operation_type.value == expected


def test_gemini_final_unresolved_and_multi_operation_use_existing_strict_parser(monkeypatch):
    monkeypatch.setattr(solar_client, "call_solar", lambda payload: json.dumps({"analysisSummary": "advice"}))
    responses = iter([
        {
            "analysisMessage": "question", "operations": [],
            "unresolvedOperation": {
                "intendedOperation": "DELETE_REQUEST_ITEM", "targetKind": "REQUEST_ITEM",
                "entityType": "TASK", "rawLineText": "reference", "message": "question",
            },
        },
        {
            "analysisMessage": "done", "operations": [
                _add_result()["operations"][0], _delete_result()["operations"][0],
            ], "unresolvedOperation": None,
        },
    ])

    async def fake_generate(**unused):
        return json.dumps(next(responses))

    monkeypatch.setattr(solar_client.gemini_change_input_client, "generate_change_input", fake_generate)
    candidates = {ITEM_ID: {"entityType": "TASK", "action": "CREATE"}}
    unresolved = _analyze(candidate_request_items=candidates)
    assert unresolved.unresolved_operation.intended_operation.value == "DELETE_REQUEST_ITEM"
    multi = _analyze(candidate_request_items=candidates)
    assert [operation.operation_type.value for operation in multi.operations] == ["ADD", "DELETE_REQUEST_ITEM"]


def _analyze(**kwargs):
    return solar_client.analyze_change_input(
        "message",
        now=solar_client.datetime.now(solar_client._SEOUL_TZ),
        purpose=SolarRequestPurpose.ACTIVE_CYCLE,
        **kwargs,
    )


def test_solar_advisory_is_passed_to_gemini_without_locking_operation(monkeypatch):
    monkeypatch.setattr(solar_client, "call_solar", lambda payload: json.dumps({
        "analysisSummary": "suggest add", "suggestedOperations": ["ADD"]
    }))
    calls = []

    async def fake_generate(*, prompt, response_json_schema):
        calls.append((prompt, response_json_schema))
        return json.dumps(_delete_result())

    monkeypatch.setattr(solar_client.gemini_change_input_client, "generate_change_input", fake_generate)
    result = _analyze(candidate_request_items={ITEM_ID: {"entityType": "TASK", "action": "CREATE"}})
    assert result.operations[0].operation_type.value == "DELETE_REQUEST_ITEM"
    assert "suggest add" in calls[0][0]
    assert len(calls) == 1


@pytest.mark.parametrize("solar_failure", [
    SolarUnavailableError("timeout"),
    "not-json",
])
def test_solar_failure_or_malformed_advisory_falls_back_to_gemini(monkeypatch, solar_failure):
    if isinstance(solar_failure, Exception):
        monkeypatch.setattr(solar_client, "call_solar", lambda payload: (_ for _ in ()).throw(solar_failure))
    else:
        monkeypatch.setattr(solar_client, "call_solar", lambda payload: solar_failure)
    prompts = []

    async def fake_generate(*, prompt, response_json_schema):
        prompts.append(prompt)
        return json.dumps(_add_result())

    monkeypatch.setattr(solar_client.gemini_change_input_client, "generate_change_input", fake_generate)
    assert _analyze().operations[0].operation_type.value == "ADD"
    assert "SOLAR advisory unavailable" in prompts[0]


def test_gemini_parser_failure_repairs_once_with_same_schema(monkeypatch):
    monkeypatch.setattr(solar_client, "call_solar", lambda payload: json.dumps({"analysisSummary": "advice"}))
    responses = iter([json.dumps({"bad": True}), json.dumps(_add_result())])
    calls = []

    async def fake_generate(*, prompt, response_json_schema):
        calls.append((prompt, response_json_schema))
        return next(responses)

    monkeypatch.setattr(solar_client.gemini_change_input_client, "generate_change_input", fake_generate)
    assert _analyze().operations[0].operation_type.value == "ADD"
    assert len(calls) == 2
    assert calls[0][1] == calls[1][1]
    assert "Safe violation" in calls[1][0]


def test_gemini_final_parser_failure_is_not_relaxed(monkeypatch):
    monkeypatch.setattr(solar_client, "call_solar", lambda payload: json.dumps({"analysisSummary": "advice"}))
    calls = []

    async def fake_generate(*, prompt, response_json_schema):
        calls.append(prompt)
        return json.dumps({"bad": True})

    monkeypatch.setattr(solar_client.gemini_change_input_client, "generate_change_input", fake_generate)
    with pytest.raises(SolarUnavailableError):
        _analyze()
    assert len(calls) == 2


def test_gemini_schema_has_strict_top_level_and_candidate_ids():
    schema = solar_client._build_gemini_change_input_schema(
        candidate_task_ids=set(),
        candidate_fixed_schedule_ids=set(),
        candidate_request_items={ITEM_ID: {"entityType": "TASK", "action": "CREATE"}},
    )
    assert schema["required"] == ["analysisMessage", "operations", "unresolvedOperation"]
    assert schema["additionalProperties"] is False
    serialized = json.dumps(schema)
    assert ITEM_ID in serialized
    assert "ADD" in serialized
    assert "PATCH_REQUEST_ITEM" in serialized
    assert "DELETE_REQUEST_ITEM" in serialized
