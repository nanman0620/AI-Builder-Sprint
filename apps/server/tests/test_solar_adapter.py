import json
import logging
import urllib.error
from datetime import datetime, timezone

import pytest

from app.models.enums import SolarRequestPurpose
from app.services import solar_client
from app.services.solar_client import SolarUnavailableError, call_solar, parse_solar_response

TASK_ID = "11111111-1111-1111-1111-111111111111"
OTHER_TASK_ID = "22222222-2222-2222-2222-222222222222"
FS_ID = "33333333-3333-3333-3333-333333333333"


def _task_create_item(**payload_overrides):
    payload = {
        "title": "자료구조 과제",
        "deadlineAt": "2026-08-01T23:59:59+09:00",
        "estimatedMinutes": 120,
        "estimatedMinutesSource": "USER",
        "remainingMinutes": None,
        "amountText": None,
        "amountSource": "UNKNOWN",
    }
    payload.update(payload_overrides)
    return {
        "entityType": "TASK",
        "action": "CREATE",
        "targetEntityId": None,
        "rawLineText": "금요일까지 자료구조 과제",
        "deadlineState": "KNOWN",
        "normalizedPayload": payload,
        "pendingQuestion": None,
    }


def _envelope(*, items, unresolved_line=None, analysis_message="분석 완료"):
    return json.dumps(
        {"analysisMessage": analysis_message, "items": items, "unresolvedLine": unresolved_line},
        ensure_ascii=False,
    )


def _parse(content, *, purpose=SolarRequestPurpose.NEW_CYCLE, candidate_task_ids=None, candidate_fs_ids=None):
    return parse_solar_response(
        content,
        purpose=purpose,
        candidate_task_ids=candidate_task_ids or set(),
        candidate_fixed_schedule_ids=candidate_fs_ids or set(),
    )


# ---------------------------------------------------------------------------
# parse_solar_response — 컨테이너/최상위 계약
# ---------------------------------------------------------------------------


def test_parse_rejects_non_json():
    with pytest.raises(SolarUnavailableError):
        _parse("이건 JSON이 아니다")


def test_parse_rejects_top_level_not_dict():
    with pytest.raises(SolarUnavailableError):
        _parse(json.dumps([1, 2, 3]))


def test_parse_rejects_unknown_top_level_key():
    body = json.loads(_envelope(items=[_task_create_item()]))
    body["extra"] = "안됨"
    with pytest.raises(SolarUnavailableError):
        _parse(json.dumps(body))


def test_parse_rejects_blank_analysis_message():
    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(items=[_task_create_item()], analysis_message="   "))


def test_parse_rejects_items_and_unresolved_line_both_empty():
    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(items=[], unresolved_line=None))


def test_parse_success_create_task_all_fields_present():
    result = _parse(_envelope(items=[_task_create_item()]))

    assert result.analysis_message == "분석 완료"
    assert len(result.items) == 1
    item = result.items[0]
    assert item.entity_type == "TASK"
    assert item.action == "CREATE"
    assert item.target_entity_id is None
    assert item.missing_fields == []
    assert item.pending_question is None
    assert item.normalized_payload["deadlineAt"] == "2026-08-01T23:59:59+09:00"
    assert item.normalized_payload["remainingMinutes"] is None  # CREATE는 서비스가 채운다.


def test_parse_create_missing_fields_and_pending_question_cross_check():
    item_raw = _task_create_item(
        deadlineAt=None, estimatedMinutes=None, estimatedMinutesSource=None, amountText=None, amountSource=None
    )
    item_raw["deadlineState"] = "MISSING"
    item_raw["pendingQuestion"] = {"field": "deadlineAt", "message": "마감이 언제인가요?"}

    result = _parse(_envelope(items=[item_raw]))

    item = result.items[0]
    assert item.missing_fields == ["deadlineAt", "estimatedMinutes", "amount"]
    assert item.pending_question == {"field": "deadlineAt", "message": "마감이 언제인가요?"}


def test_parse_rejects_pending_question_field_out_of_order():
    item_raw = _task_create_item(
        deadlineAt=None, estimatedMinutes=None, estimatedMinutesSource=None, amountText=None, amountSource=None
    )
    item_raw["deadlineState"] = "MISSING"
    item_raw["pendingQuestion"] = {"field": "estimatedMinutes", "message": "몇 분 걸리나요?"}

    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(items=[item_raw]))


def test_pending_field_mismatch_logs_violation_code_without_raw_content(caplog):
    item_raw = _task_create_item(
        deadlineAt=None, estimatedMinutes=None, estimatedMinutesSource=None, amountText=None, amountSource=None
    )
    item_raw["deadlineState"] = "MISSING"
    item_raw["pendingQuestion"] = {"field": "estimatedMinutes", "message": "몇 분 걸리나요?"}

    with caplog.at_level(logging.WARNING, logger="app.services.solar_client"):
        with pytest.raises(SolarUnavailableError):
            _parse(_envelope(items=[item_raw]))

    violation_logs = [r.message for r in caplog.records if "SOLAR_CONTRACT_VIOLATION" in r.message]
    assert any("PENDING_FIELD_MISMATCH" in message for message in violation_logs)
    # 원문 rawLineText/pendingQuestion.message가 로그에 섞여 들어가지 않았는지 확인.
    for message in violation_logs:
        assert "자료구조" not in message
        assert "몇 분 걸리나요" not in message


def test_missing_required_key_logs_violation_code_without_raw_content(caplog):
    item_raw = _task_create_item()
    del item_raw["deadlineState"]

    with caplog.at_level(logging.WARNING, logger="app.services.solar_client"):
        with pytest.raises(SolarUnavailableError):
            _parse(_envelope(items=[item_raw]))

    violation_logs = [r.message for r in caplog.records if "SOLAR_CONTRACT_VIOLATION" in r.message]
    assert any("MISSING_REQUIRED_KEY:deadlineState" in message for message in violation_logs)
    for message in violation_logs:
        assert "자료구조" not in message


def test_unexpected_key_logs_violation_code():
    item_raw = _task_create_item()
    item_raw["unexpectedKey"] = "안됨"

    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(items=[item_raw]))


def test_system_prompt_includes_required_key_table_self_check_and_examples():
    messages = solar_client._build_prompt_messages(
        "테스트 메시지",
        now=datetime(2026, 7, 31, 14, 0, tzinfo=timezone.utc),
        purpose=SolarRequestPurpose.NEW_CYCLE,
        cycle_start=None,
        cycle_end=None,
        candidate_tasks=[],
        candidate_fixed_schedules=[],
    )
    system_prompt = messages[0]["content"]

    assert "action별 필수 키 재확인" in system_prompt
    assert "TASK CREATE: deadlineState 필수" in system_prompt
    assert "TASK UPDATE: deadlineState와 updateFields 둘 다 필수" in system_prompt
    assert "TASK DELETE: deadlineState와 updateFields 둘 다 절대 포함하지 마세요" in system_prompt
    assert "FIXED_SCHEDULE: CREATE/UPDATE/DELETE 어떤 action이든 deadlineState를 절대 포함하지" in system_prompt
    assert "응답 전 self-check" in system_prompt
    assert "예시 1" in system_prompt
    assert "예시 2" in system_prompt


def test_parse_rejects_missing_without_pending_question():
    item_raw = _task_create_item(
        deadlineAt=None, estimatedMinutes=None, estimatedMinutesSource=None, amountText=None, amountSource=None
    )
    item_raw["deadlineState"] = "MISSING"
    item_raw["pendingQuestion"] = None

    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(items=[item_raw]))


def test_parse_create_task_blank_title_hard_rejected():
    item_raw = _task_create_item(title="   ")

    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(items=[item_raw]))


def test_parse_create_task_remaining_minutes_must_be_null():
    item_raw = _task_create_item(remainingMinutes=60)

    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(items=[item_raw]))


# ---------------------------------------------------------------------------
# action / targetEntityId 검증
# ---------------------------------------------------------------------------


def test_parse_create_with_target_entity_id_rejected():
    item_raw = _task_create_item()
    item_raw["targetEntityId"] = TASK_ID

    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(items=[item_raw]), purpose=SolarRequestPurpose.ACTIVE_CYCLE, candidate_task_ids={TASK_ID})


def test_parse_update_without_target_entity_id_rejected():
    item_raw = {
        "entityType": "TASK",
        "action": "UPDATE",
        "targetEntityId": None,
        "rawLineText": "마감 바꿔줘",
        "deadlineState": "MISSING",
        "normalizedPayload": {
            "title": None,
            "deadlineAt": None,
            "estimatedMinutes": None,
            "estimatedMinutesSource": None,
            "remainingMinutes": None,
            "amountText": None,
            "amountSource": None,
        },
        "pendingQuestion": None,
        "updateFields": ["deadlineAt"],
    }

    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(items=[item_raw]), purpose=SolarRequestPurpose.ACTIVE_CYCLE, candidate_task_ids={TASK_ID})


def test_parse_update_target_not_in_candidates_rejected():
    item_raw = {
        "entityType": "TASK",
        "action": "UPDATE",
        "targetEntityId": OTHER_TASK_ID,
        "rawLineText": "마감 바꿔줘",
        "deadlineState": "KNOWN",
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
        "updateFields": ["deadlineAt"],
    }

    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(items=[item_raw]), purpose=SolarRequestPurpose.ACTIVE_CYCLE, candidate_task_ids={TASK_ID})


def test_parse_update_field_not_in_update_fields_must_be_null():
    item_raw = {
        "entityType": "TASK",
        "action": "UPDATE",
        "targetEntityId": TASK_ID,
        "rawLineText": "마감 바꿔줘",
        "deadlineState": "KNOWN",
        "normalizedPayload": {
            "title": "이러면 안 됨",  # updateFields에 title이 없는데 값이 있음
            "deadlineAt": "2026-08-01T23:59:59+09:00",
            "estimatedMinutes": None,
            "estimatedMinutesSource": None,
            "remainingMinutes": None,
            "amountText": None,
            "amountSource": None,
        },
        "pendingQuestion": None,
        "updateFields": ["deadlineAt"],
    }

    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(items=[item_raw]), purpose=SolarRequestPurpose.ACTIVE_CYCLE, candidate_task_ids={TASK_ID})


def test_parse_update_empty_update_fields_rejected():
    item_raw = {
        "entityType": "TASK",
        "action": "UPDATE",
        "targetEntityId": TASK_ID,
        "rawLineText": "마감 바꿔줘",
        "deadlineState": "MISSING",
        "normalizedPayload": {
            "title": None,
            "deadlineAt": None,
            "estimatedMinutes": None,
            "estimatedMinutesSource": None,
            "remainingMinutes": None,
            "amountText": None,
            "amountSource": None,
        },
        "pendingQuestion": None,
        "updateFields": [],
    }

    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(items=[item_raw]), purpose=SolarRequestPurpose.ACTIVE_CYCLE, candidate_task_ids={TASK_ID})


def test_parse_update_remaining_minutes_only_success():
    item_raw = {
        "entityType": "TASK",
        "action": "UPDATE",
        "targetEntityId": TASK_ID,
        "rawLineText": "남은 시간을 2시간으로 바꿔줘",
        "deadlineState": "MISSING",
        "normalizedPayload": {
            "title": None,
            "deadlineAt": None,
            "estimatedMinutes": None,
            "estimatedMinutesSource": None,
            "remainingMinutes": 120,
            "amountText": None,
            "amountSource": None,
        },
        "pendingQuestion": None,
        "updateFields": ["remainingMinutes"],
    }

    result = _parse(_envelope(items=[item_raw]), purpose=SolarRequestPurpose.ACTIVE_CYCLE, candidate_task_ids={TASK_ID})

    item = result.items[0]
    assert item.missing_fields == []
    assert item.update_fields == ["remainingMinutes"]
    assert item.normalized_payload["remainingMinutes"] == 120
    assert item.normalized_payload["estimatedMinutes"] is None


def test_parse_delete_always_ready():
    item_raw = {
        "entityType": "TASK",
        "action": "DELETE",
        "targetEntityId": TASK_ID,
        "rawLineText": "그 과제 취소해줘",
        "normalizedPayload": {
            "title": "아무값",
            "deadlineAt": None,
            "estimatedMinutes": None,
            "estimatedMinutesSource": None,
            "remainingMinutes": None,
            "amountText": None,
            "amountSource": None,
        },
        "pendingQuestion": None,
    }

    result = _parse(_envelope(items=[item_raw]), purpose=SolarRequestPurpose.ACTIVE_CYCLE, candidate_task_ids={TASK_ID})

    assert result.items[0].missing_fields == []
    assert result.items[0].update_fields == []


# ---------------------------------------------------------------------------
# unresolvedLine
# ---------------------------------------------------------------------------


def _unresolved_raw(**overrides):
    raw = {
        "rawLineText": "그 과제 마감 바꿔줘",
        "action": "UPDATE",
        "entityType": "TASK",
        "message": "어떤 항목을 말씀하시는지 다시 알려주시겠어요?",
    }
    raw.update(overrides)
    return raw


def test_parse_unresolved_line_happy_path():
    result = _parse(
        _envelope(items=[], unresolved_line=_unresolved_raw()),
        purpose=SolarRequestPurpose.ACTIVE_CYCLE,
        candidate_task_ids={TASK_ID},
    )

    assert result.items == []
    assert result.unresolved_line.action == "UPDATE"
    assert result.unresolved_line.entity_type == "TASK"


def test_parse_unresolved_line_create_action_rejected():
    with pytest.raises(SolarUnavailableError):
        _parse(
            _envelope(items=[], unresolved_line=_unresolved_raw(action="CREATE")),
            purpose=SolarRequestPurpose.ACTIVE_CYCLE,
            candidate_task_ids={TASK_ID},
        )


def test_parse_unresolved_line_zero_candidates_rejected():
    with pytest.raises(SolarUnavailableError):
        _parse(
            _envelope(items=[], unresolved_line=_unresolved_raw()),
            purpose=SolarRequestPurpose.ACTIVE_CYCLE,
            candidate_task_ids=set(),
        )


def test_parse_new_cycle_rejects_unresolved_line():
    with pytest.raises(SolarUnavailableError):
        _parse(
            _envelope(items=[_task_create_item()], unresolved_line=_unresolved_raw()),
            purpose=SolarRequestPurpose.NEW_CYCLE,
        )


def test_parse_new_cycle_rejects_non_create_action():
    item_raw = {
        "entityType": "TASK",
        "action": "UPDATE",
        "targetEntityId": TASK_ID,
        "rawLineText": "마감 바꿔줘",
        "deadlineState": "KNOWN",
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
        "updateFields": ["deadlineAt"],
    }

    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(items=[item_raw]), purpose=SolarRequestPurpose.NEW_CYCLE, candidate_task_ids={TASK_ID})


# ---------------------------------------------------------------------------
# 날짜·문자열·enum 정규화
# ---------------------------------------------------------------------------


def test_parse_datetime_field_returns_string_not_datetime_object():
    result = _parse(_envelope(items=[_task_create_item()]))
    assert isinstance(result.items[0].normalized_payload["deadlineAt"], str)


def test_parse_datetime_missing_timezone_rejected():
    item_raw = _task_create_item(deadlineAt="2026-08-01T23:59:59")
    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(items=[item_raw]))


def test_parse_datetime_nonexistent_date_rejected():
    item_raw = _task_create_item(deadlineAt="2026-02-30T23:59:59+09:00")
    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(items=[item_raw]))


def test_parse_datetime_not_a_string_rejected():
    item_raw = _task_create_item(deadlineAt=12345)
    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(items=[item_raw]))


def test_parse_title_number_rejected():
    item_raw = _task_create_item(title=123)
    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(items=[item_raw]))


def test_parse_analysis_message_number_rejected():
    body = json.loads(_envelope(items=[_task_create_item()]))
    body["analysisMessage"] = 123
    with pytest.raises(SolarUnavailableError):
        _parse(json.dumps(body))


def test_parse_amount_unknown_with_text_rejected():
    item_raw = _task_create_item(amountSource="UNKNOWN", amountText="3문제")
    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(items=[item_raw]))


def test_parse_amount_user_without_text_rejected():
    item_raw = _task_create_item(amountSource="USER", amountText="   ")
    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(items=[item_raw]))


def test_parse_amount_null_source_with_text_rejected():
    item_raw = _task_create_item(amountSource=None, amountText="3문제")
    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(items=[item_raw]))


def test_parse_enum_blank_padding_rejected():
    item_raw = _task_create_item(amountSource=" USER ", amountText="3문제")
    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(items=[item_raw]))


# ---------------------------------------------------------------------------
# FIXED_SCHEDULE CREATE
# ---------------------------------------------------------------------------


def _fs_create_item(**payload_overrides):
    payload = {"title": "알바", "startAt": "2026-07-28T17:00:00+09:00", "endAt": "2026-07-28T18:00:00+09:00"}
    payload.update(payload_overrides)
    return {
        "entityType": "FIXED_SCHEDULE",
        "action": "CREATE",
        "targetEntityId": None,
        "rawLineText": "금요일 5시부터 6시까지 알바",
        "normalizedPayload": payload,
        "pendingQuestion": None,
    }


def test_parse_fixed_schedule_create_success():
    result = _parse(_envelope(items=[_fs_create_item()]))
    assert result.items[0].missing_fields == []


def test_parse_fixed_schedule_end_at_before_start_at_rejected():
    item_raw = _fs_create_item(endAt="2026-07-28T16:00:00+09:00")
    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(items=[item_raw]))


def test_parse_fixed_schedule_end_at_equal_start_at_rejected():
    item_raw = _fs_create_item(endAt="2026-07-28T17:00:00+09:00")
    with pytest.raises(SolarUnavailableError):
        _parse(_envelope(items=[item_raw]))


# ---------------------------------------------------------------------------
# call_solar — HTTP 계약
# ---------------------------------------------------------------------------


class _FakeHTTPResponse:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def _success_body(content: str) -> bytes:
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")


def test_call_solar_success_returns_content(monkeypatch):
    captured = {}

    def _fake_urlopen(request, timeout=None):
        captured["timeout"] = timeout
        captured["url"] = request.full_url
        return _FakeHTTPResponse(_success_body("응답 본문"))

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    content = call_solar({"messages": [{"role": "user", "content": "hi"}]})

    assert content == "응답 본문"
    assert captured["timeout"] == solar_client._REQUEST_TIMEOUT_SECONDS
    assert captured["url"].endswith("/chat/completions")


def test_call_solar_http_error_maps_to_unavailable(monkeypatch):
    def _raise(request, timeout=None):
        raise urllib.error.HTTPError("url", 500, "boom", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", _raise)

    with pytest.raises(SolarUnavailableError):
        call_solar({"messages": []})


def test_call_solar_timeout_maps_to_unavailable(monkeypatch):
    def _raise(request, timeout=None):
        raise TimeoutError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", _raise)

    with pytest.raises(SolarUnavailableError):
        call_solar({"messages": []})


def test_call_solar_url_error_maps_to_unavailable(monkeypatch):
    def _raise(request, timeout=None):
        raise urllib.error.URLError("network down")

    monkeypatch.setattr("urllib.request.urlopen", _raise)

    with pytest.raises(SolarUnavailableError):
        call_solar({"messages": []})


def test_call_solar_non_json_body_rejected(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda request, timeout=None: _FakeHTTPResponse(b"not json")
    )

    with pytest.raises(SolarUnavailableError):
        call_solar({"messages": []})


def test_call_solar_missing_choices_rejected(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout=None: _FakeHTTPResponse(json.dumps({}).encode("utf-8")),
    )

    with pytest.raises(SolarUnavailableError):
        call_solar({"messages": []})


def test_call_solar_empty_choices_rejected(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout=None: _FakeHTTPResponse(json.dumps({"choices": []}).encode("utf-8")),
    )

    with pytest.raises(SolarUnavailableError):
        call_solar({"messages": []})


def test_call_solar_missing_message_rejected(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout=None: _FakeHTTPResponse(json.dumps({"choices": [{}]}).encode("utf-8")),
    )

    with pytest.raises(SolarUnavailableError):
        call_solar({"messages": []})


def test_call_solar_content_not_string_rejected(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout=None: _FakeHTTPResponse(
            json.dumps({"choices": [{"message": {"content": 123}}]}).encode("utf-8")
        ),
    )

    with pytest.raises(SolarUnavailableError):
        call_solar({"messages": []})
