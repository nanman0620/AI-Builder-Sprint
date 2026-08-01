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


def test_parse_task_accepts_structured_unsupported_recurring_intent():
    raw = _task_create_item()
    raw["rawLineText"] = "매일 영어 단어 외울래"
    raw["unsupportedIntent"] = "RECURRING_TASK"

    item = _parse(_envelope(items=[raw])).items[0]

    assert item.unsupported_intent == "RECURRING_TASK"


@pytest.mark.parametrize(
    "text",
    ["매일 영어 공부", "매주 월요일 과제 복습", "평일마다 단어 암기", "주 3회 운동 기록", "격일로 문제 풀이"],
)
def test_clear_task_recurrence_guard_true_positives(text):
    assert solar_client.has_clear_task_recurrence_intent(text) is True


@pytest.mark.parametrize(
    "text",
    ["매일경제 기사 읽기", "반복문 문제 5개 풀기", "‘매주’라는 표현을 발표문에서 수정하기"],
)
def test_clear_task_recurrence_guard_false_positives(text):
    assert solar_client.has_clear_task_recurrence_intent(text) is False


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


def test_system_prompt_requires_nonblank_item_specific_raw_line_text_for_every_task_action():
    messages = solar_client._build_prompt_messages(
        "테스트 메시지",
        now=datetime(2026, 7, 31, 14, 0, tzinfo=timezone.utc),
        purpose=SolarRequestPurpose.ACTIVE_CYCLE,
        cycle_start=None,
        cycle_end=None,
        candidate_tasks=[],
        candidate_fixed_schedules=[],
    )

    prompt = messages[0]["content"]
    assert "TASK CREATE: rawLineText" in prompt
    assert "TASK UPDATE: rawLineText" in prompt
    assert "TASK DELETE: rawLineText" in prompt
    assert "비어 있지 않은 문자열" in prompt
    assert "전체 사용자 메시지를 모든 item에 동일하게 복사하지" in prompt


def test_unresolved_answer_prompt_contains_task_update_exact_keys_and_raw_line_rules():
    messages = solar_client._build_unresolved_answer_prompt_messages(
        "20분으로 바꿔줘",
        now=datetime(2026, 7, 31, 14, 0, tzinfo=timezone.utc),
        expected_action="UPDATE",
        expected_entity_type="TASK",
        expected_target_kind="ENTITY",
        original_raw_line_text="발표 대본 수정",
        candidates=[{"id": TASK_ID, "title": "발표 대본"}],
    )

    prompt = messages[0]["content"]
    assert "TASK UPDATE exact keys" in prompt
    assert "rawLineText" in prompt
    assert "deadlineState" in prompt
    assert "updateFields" in prompt
    assert "비어 있지 않은 문자열" in prompt
    assert "TASK CREATE/DELETE" in prompt


def test_repair_prompt_directly_explains_missing_raw_line_text_without_phantom_references():
    messages = solar_client._build_repair_messages(
        [{"role": "system", "content": "schema"}, {"role": "user", "content": "수정해줘"}],
        '{"analysisMessage":"분석","items":[],"unresolvedLine":null}',
        "MISSING_REQUIRED_KEY:rawLineText",
    )

    instruction = messages[-1]["content"]
    assert "TASK UPDATE" in instruction
    assert "rawLineText" in instruction
    assert "사용자 원문 중 해당 item에 대응하는 부분" in instruction
    assert "기존의 유효한 필드" in instruction
    assert "action을 변경하지" in instruction
    assert "action별 필수 키 표" not in instruction
    assert "self-check" not in instruction


def test_system_prompt_requires_title_amount_text_deduplication():
    """title에 amountText/deadlineAt/estimatedMinutes/remainingMinutes를 중복해 넣지 않는
    규칙, 고유 번호 보존, 모호할 때 확인 질문 유지, CREATE/UPDATE 공통 적용, self-check
    강화, few-shot 예시가 모두 시스템 프롬프트에 포함돼 있는지 확인한다."""
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

    # 1. title/amountText 역할 구분 규칙
    assert "TASK title과 amountText의 역할 구분" in system_prompt
    assert "title은 사용자가 해야 할 일을 식별하는 간결한 작업명" in system_prompt

    # 2. title에서 마감·예상 시간·남은 시간을 중복하지 않는 규칙
    assert (
        "amountText로 담을 전체 분량, deadlineAt으로 담을 마감, estimatedMinutes/"
        "remainingMinutes로 담을 예상·남은 시간을 title에 중복해서 넣지 마세요" in system_prompt
    )

    # 3. 숫자를 무조건 제거하지 않는 보호 규칙(고유 번호 보존)
    assert "그 작업을 다른 것과 구분 짓는 고유 정보" in system_prompt
    assert "2차 과제" in system_prompt and "3분 스피치" in system_prompt and "문제 3 풀이" in system_prompt

    # 4. 모호한 경우 확인 질문을 사용한다는 지침
    assert (
        "숫자가 분량인지 고유 식별 정보인지 문맥만으로 확정할 수 없으면" in system_prompt
    )
    assert "pendingQuestion 흐름으로 확인" in system_prompt

    # CREATE/UPDATE 공통 적용 근거
    assert (
        "action=\"CREATE\"뿐 아니라 action=\"UPDATE\"로 title을 새로 채울 때도" in system_prompt
    )

    # 5. 자료구조·영단어·책 읽기 few-shot 예시
    assert "예시 3" in system_prompt
    assert "자료구조 과제 3문제를 수요일까지 풀어야 해" in system_prompt
    assert "title=\"자료구조 과제\", amountText=\"3문제\"" in system_prompt
    assert "금지: title=\"자료구조 과제 3문제 풀기\"" in system_prompt
    assert "영단어 30개 외우기" in system_prompt
    assert "title=\"영단어 암기\", amountText=\"30개\"" in system_prompt
    assert "책 50페이지 읽기" in system_prompt
    assert "title=\"책 읽기\", amountText=\"50페이지\"" in system_prompt

    # 6. 고유 번호 보존 예시
    assert "운영체제 과제 2번 제출하기" in system_prompt
    assert "title=\"운영체제 과제 2번 제출\"로 그대로 두고 amountText는" in system_prompt

    # 모호해서 확인 질문이 필요한 예시
    assert "숫자가 분량인지 고유 번호인지 문맥만으로 알 수 없으면" in system_prompt

    # 7. self-check에 title/amountText 중복 확인 단계 추가
    assert "아래 6가지" in system_prompt
    assert "6. TASK CREATE/UPDATE에서 title을 채웠다면" in system_prompt
    assert "이미 분리한 분량·마감·시간 표현이 중복으로 남아있지 않은지" in system_prompt


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


def test_parse_mixed_task_create_update_delete_preserves_item_specific_raw_lines():
    create_item = _task_create_item(
        title="영단어 암기",
        amountText="20개",
        amountSource="USER",
    )
    create_item["rawLineText"] = "영단어 20개는 추가하고"
    update_item = {
        "entityType": "TASK",
        "action": "UPDATE",
        "targetEntityId": TASK_ID,
        "rawLineText": "발표 대본은 20분으로 바꾸고",
        "deadlineState": "MISSING",
        "normalizedPayload": {
            "title": None,
            "deadlineAt": None,
            "estimatedMinutes": 20,
            "estimatedMinutesSource": "USER",
            "remainingMinutes": None,
            "amountText": None,
            "amountSource": None,
        },
        "pendingQuestion": None,
        "updateFields": ["estimatedMinutes"],
    }
    delete_item = {
        "entityType": "TASK",
        "action": "DELETE",
        "targetEntityId": OTHER_TASK_ID,
        "rawLineText": "자료구조 복습은 없애줘",
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
    }

    result = _parse(
        _envelope(items=[create_item, update_item, delete_item]),
        purpose=SolarRequestPurpose.ACTIVE_CYCLE,
        candidate_task_ids={TASK_ID, OTHER_TASK_ID},
    )

    assert [item.action for item in result.items] == ["CREATE", "UPDATE", "DELETE"]
    assert [item.raw_line_text for item in result.items] == [
        "영단어 20개는 추가하고",
        "발표 대본은 20분으로 바꾸고",
        "자료구조 복습은 없애줘",
    ]
    assert result.items[1].raw_line_text.strip()


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


# ---------------------------------------------------------------------------
# canonicalization — 좁은 whitelist 3가지만 정규화하고 그 외 값은 손대지 않는지 단위 검증
# ---------------------------------------------------------------------------


def test_canonicalize_amount_missing_sentinel_normalizes_both_to_none():
    payload = {
        "title": "T",
        "deadlineAt": None,
        "estimatedMinutes": 10,
        "estimatedMinutesSource": "USER",
        "remainingMinutes": None,
        "amountText": None,
        "amountSource": "MISSING",
    }

    solar_client._canonicalize_amount_missing_sentinel(payload)

    assert payload["amountSource"] is None
    assert payload["amountText"] is None
    # 타깃 밖의 필드는 절대 손대지 않는다.
    assert payload["title"] == "T"
    assert payload["estimatedMinutes"] == 10


def test_canonicalize_amount_missing_sentinel_blank_text_also_normalized():
    payload = {"amountText": "   ", "amountSource": "MISSING"}

    solar_client._canonicalize_amount_missing_sentinel(payload)

    assert payload["amountSource"] is None
    assert payload["amountText"] is None


def test_canonicalize_amount_missing_sentinel_does_not_touch_valid_values():
    payload = {"amountText": "5개", "amountSource": "USER"}

    solar_client._canonicalize_amount_missing_sentinel(payload)

    assert payload == {"amountText": "5개", "amountSource": "USER"}


def test_canonicalize_amount_missing_sentinel_does_not_touch_amount_text_when_present():
    """amountSource="MISSING"인데 amountText에 실제 값이 있으면(조건 밖) 손대지 않는다 —
    이 경우는 strict parser/repair가 그대로 거부해야 한다."""
    payload = {"amountText": "5개", "amountSource": "MISSING"}

    solar_client._canonicalize_amount_missing_sentinel(payload)

    assert payload == {"amountText": "5개", "amountSource": "MISSING"}


def test_canonicalize_untouched_deadline_state_normalizes_when_deadline_not_in_update_fields():
    item = {
        "updateFields": ["remainingMinutes"],
        "deadlineState": "KNOWN",
        "normalizedPayload": {"deadlineAt": "2026-08-01T23:59:59+09:00", "title": None},
    }

    solar_client._canonicalize_untouched_deadline_state(item)

    assert item["deadlineState"] == "MISSING"
    assert item["normalizedPayload"]["deadlineAt"] is None
    assert item["normalizedPayload"]["title"] is None


def test_canonicalize_untouched_deadline_state_no_op_when_deadline_in_update_fields():
    item = {
        "updateFields": ["deadlineAt"],
        "deadlineState": "KNOWN",
        "normalizedPayload": {"deadlineAt": "2026-08-01T23:59:59+09:00"},
    }

    solar_client._canonicalize_untouched_deadline_state(item)

    assert item["deadlineState"] == "KNOWN"
    assert item["normalizedPayload"]["deadlineAt"] == "2026-08-01T23:59:59+09:00"


def test_canonicalize_update_field_amount_text_alias_renames_to_amount():
    item = {"updateFields": ["amountText", "title"]}

    solar_client._canonicalize_update_field_amount_text_alias(item)

    assert item["updateFields"] == ["amount", "title"]


def test_canonicalize_update_field_amount_text_alias_no_op_without_amount_text():
    item = {"updateFields": ["deadlineAt"]}

    solar_client._canonicalize_update_field_amount_text_alias(item)

    assert item["updateFields"] == ["deadlineAt"]


def test_canonicalize_update_field_amount_text_alias_deduplicates():
    item = {"updateFields": ["amount", "amountText"]}

    solar_client._canonicalize_update_field_amount_text_alias(item)

    assert item["updateFields"] == ["amount"]


# ---------------------------------------------------------------------------
# analyze_message — canonicalize → strict parser → (실패 시) repair 최대 1회 흐름
# ---------------------------------------------------------------------------


class _FakeHTTPResponseForAnalyze:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def _success_envelope(content: str) -> bytes:
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")


def _queue_urlopen(monkeypatch, bodies: list[bytes]):
    """urlopen을 호출 순서대로 bodies를 반환하도록 monkeypatch하고, 호출 횟수를 세는
    카운터 dict를 반환한다. bodies보다 더 호출되면 AssertionError(최대 호출 횟수 위반)."""
    call_count = {"n": 0}

    def _fake(request, timeout=None):
        call_count["n"] += 1
        idx = call_count["n"] - 1
        if idx >= len(bodies):
            raise AssertionError("urlopen이 예상보다 많이 호출됨(최대 호출 횟수 위반)")
        return _FakeHTTPResponseForAnalyze(bodies[idx])

    monkeypatch.setattr("urllib.request.urlopen", _fake)
    return call_count


_NOW = datetime(2026, 7, 31, 14, 0, tzinfo=timezone.utc)


def _pending_field_mismatch_item() -> dict:
    item = _task_create_item(
        deadlineAt=None, estimatedMinutes=None, estimatedMinutesSource=None, amountText=None, amountSource=None
    )
    item["deadlineState"] = "MISSING"
    item["pendingQuestion"] = {"field": "estimatedMinutes", "message": "몇 분 걸릴까요?"}
    return item


def _task_update_item_with_optional_raw_line(*, include_raw_line: bool) -> dict:
    item = {
        "entityType": "TASK",
        "action": "UPDATE",
        "targetEntityId": TASK_ID,
        "deadlineState": "MISSING",
        "normalizedPayload": {
            "title": None,
            "deadlineAt": None,
            "estimatedMinutes": 20,
            "estimatedMinutesSource": "USER",
            "remainingMinutes": None,
            "amountText": None,
            "amountSource": None,
        },
        "pendingQuestion": None,
        "updateFields": ["estimatedMinutes"],
    }
    if include_raw_line:
        item["rawLineText"] = "발표 대본은 20분으로 바꿔줘"
    return item


def test_analyze_message_success_calls_solar_once(monkeypatch):
    content = _envelope(items=[_task_create_item()])
    call_count = _queue_urlopen(monkeypatch, [_success_envelope(content)])

    result = solar_client.analyze_message("테스트 메시지", now=_NOW, purpose=SolarRequestPurpose.NEW_CYCLE)

    assert call_count["n"] == 1
    assert len(result.items) == 1
    assert result.items[0].missing_fields == []


def test_analyze_message_canonicalization_avoids_extra_call(monkeypatch):
    # amountSource="MISSING"+amountText 없음은 canonicalization으로 null/null로 정규화되므로
    # (soft-missing) repair 없이 첫 응답만으로 통과해야 한다(호출 1회). 정규화 후 amount가
    # missing이 되므로 그 필드를 묻는 pendingQuestion을 함께 준다(그래야 다른 규칙에 안 걸림).
    item_raw = _task_create_item(amountSource="MISSING", amountText=None)
    item_raw["pendingQuestion"] = {"field": "amount", "message": "분량이 어느 정도인가요?"}
    content = _envelope(items=[item_raw])
    call_count = _queue_urlopen(monkeypatch, [_success_envelope(content)])

    result = solar_client.analyze_message("테스트 메시지", now=_NOW, purpose=SolarRequestPurpose.NEW_CYCLE)

    assert call_count["n"] == 1
    assert result.items[0].missing_fields == ["amount"]
    assert result.items[0].normalized_payload["amountSource"] is None
    assert result.items[0].normalized_payload["amountText"] is None


def test_analyze_message_repair_succeeds_after_first_violation(monkeypatch):
    bad_content = _envelope(items=[_pending_field_mismatch_item()])
    good_content = _envelope(items=[_task_create_item()])
    call_count = _queue_urlopen(monkeypatch, [_success_envelope(bad_content), _success_envelope(good_content)])

    result = solar_client.analyze_message("테스트 메시지", now=_NOW, purpose=SolarRequestPurpose.NEW_CYCLE)

    assert call_count["n"] == 2
    assert len(result.items) == 1
    assert result.items[0].missing_fields == []


def test_analyze_message_repairs_missing_update_raw_line_text_and_preserves_valid_fields(
    monkeypatch, caplog
):
    bad_content = _envelope(items=[_task_update_item_with_optional_raw_line(include_raw_line=False)])
    good_content = _envelope(items=[_task_update_item_with_optional_raw_line(include_raw_line=True)])
    call_count = _queue_urlopen(
        monkeypatch, [_success_envelope(bad_content), _success_envelope(good_content)]
    )

    with caplog.at_level(logging.WARNING):
        result = solar_client.analyze_message(
            "발표 대본은 20분으로 바꿔줘",
            now=_NOW,
            purpose=SolarRequestPurpose.ACTIVE_CYCLE,
            candidate_tasks=[{"id": TASK_ID}],
        )

    assert call_count["n"] == 2
    assert any("MISSING_REQUIRED_KEY:rawLineText" in record.message for record in caplog.records)
    item = result.items[0]
    assert item.raw_line_text == "발표 대본은 20분으로 바꿔줘"
    assert item.action == "UPDATE"
    assert item.target_entity_id == TASK_ID
    assert item.update_fields == ["estimatedMinutes"]
    assert item.normalized_payload["estimatedMinutes"] == 20
    assert item.normalized_payload["estimatedMinutesSource"] == "USER"


def test_analyze_message_repair_failure_raises_after_two_calls(monkeypatch):
    bad_content = _envelope(items=[_pending_field_mismatch_item()])
    call_count = _queue_urlopen(monkeypatch, [_success_envelope(bad_content), _success_envelope(bad_content)])

    with pytest.raises(SolarUnavailableError):
        solar_client.analyze_message("테스트 메시지", now=_NOW, purpose=SolarRequestPurpose.NEW_CYCLE)

    assert call_count["n"] == 2


def test_analyze_message_missing_update_raw_line_text_in_both_responses_still_raises(monkeypatch):
    bad_content = _envelope(items=[_task_update_item_with_optional_raw_line(include_raw_line=False)])
    call_count = _queue_urlopen(
        monkeypatch, [_success_envelope(bad_content), _success_envelope(bad_content)]
    )

    with pytest.raises(SolarUnavailableError) as exc_info:
        solar_client.analyze_message(
            "발표 대본은 20분으로 바꿔줘",
            now=_NOW,
            purpose=SolarRequestPurpose.ACTIVE_CYCLE,
            candidate_tasks=[{"id": TASK_ID}],
        )

    assert exc_info.value.code == "MISSING_REQUIRED_KEY:rawLineText"
    assert call_count["n"] == 2


def test_analyze_message_never_attempts_a_third_call(monkeypatch):
    """repair까지 실패해도 3번째(성공할) 응답이 큐에 남아 있으면 절대 소비하지 않는다 —
    전체 SOLAR 호출은 최대 2회여야 한다는 제약의 직접 증거."""
    bad_content = _envelope(items=[_pending_field_mismatch_item()])
    good_content = _envelope(items=[_task_create_item()])
    call_count = _queue_urlopen(
        monkeypatch,
        [_success_envelope(bad_content), _success_envelope(bad_content), _success_envelope(good_content)],
    )

    with pytest.raises(SolarUnavailableError):
        solar_client.analyze_message("테스트 메시지", now=_NOW, purpose=SolarRequestPurpose.NEW_CYCLE)

    assert call_count["n"] == 2


def test_analyze_message_transport_error_on_first_call_is_not_repaired(monkeypatch):
    call_count = {"n": 0}

    def _raise(request, timeout=None):
        call_count["n"] += 1
        raise urllib.error.URLError("network down")

    monkeypatch.setattr("urllib.request.urlopen", _raise)

    with pytest.raises(SolarUnavailableError):
        solar_client.analyze_message("테스트 메시지", now=_NOW, purpose=SolarRequestPurpose.NEW_CYCLE)

    assert call_count["n"] == 1  # 전송 계층 오류는 repair를 시도하지 않고 즉시 전파된다.


def test_analyze_message_repair_logs_no_sensitive_content(monkeypatch, caplog):
    bad_content = _envelope(
        items=[_pending_field_mismatch_item()], analysis_message="이 문장은 로그에 절대 나오면 안 된다"
    )
    good_content = _envelope(items=[_task_create_item()])
    _queue_urlopen(monkeypatch, [_success_envelope(bad_content), _success_envelope(good_content)])

    secret_user_message = "이 사용자 메시지도 로그에 나오면 절대 안 된다"
    with caplog.at_level(logging.WARNING, logger="app.services.solar_client"):
        solar_client.analyze_message(secret_user_message, now=_NOW, purpose=SolarRequestPurpose.NEW_CYCLE)

    for record in caplog.records:
        assert secret_user_message not in record.message
        assert "이 문장은 로그에 절대 나오면 안 된다" not in record.message
        assert "몇 분 걸릴까요?" not in record.message
        assert "Bearer" not in record.message
