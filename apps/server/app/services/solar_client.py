"""Upstage SOLAR 연동. 이 모듈은 전부 동기 함수로만 구성된다 — 이 저장소는 동기 SQLAlchemy
Session을 쓰고, FastAPI의 동기 endpoint(threadpool에서 실행)와 짝을 이루므로 `urllib.request`의
블로킹 호출을 여기서 그대로 써도 메인 이벤트 루프를 막지 않는다. async로 감싸지 않는다.
"""

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import get_solar_api_key, get_solar_base_url, get_solar_model
from app.models.enums import SolarRequestPurpose

_SEOUL_TZ = ZoneInfo("Asia/Seoul")
_REQUEST_TIMEOUT_SECONDS = 30

_RFC3339_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")

_TASK_MISSING_ORDER_CREATE = ["deadlineAt", "estimatedMinutes", "amount"]
_TASK_MISSING_ORDER_UPDATE = ["title", "deadlineAt", "estimatedMinutes", "remainingMinutes", "amount"]
_FIXED_SCHEDULE_MISSING_ORDER = ["title", "startAt", "endAt"]

_TASK_UPDATE_FIELD_NAMES = {"title", "deadlineAt", "estimatedMinutes", "remainingMinutes", "amount"}
_FIXED_SCHEDULE_UPDATE_FIELD_NAMES = {"title", "startAt", "endAt"}

_TOP_LEVEL_KEYS = {"analysisMessage", "items", "unresolvedLine"}
_UNRESOLVED_LINE_KEYS = {"rawLineText", "action", "entityType", "message"}

_TASK_CREATE_ITEM_KEYS = {
    "entityType", "action", "targetEntityId", "rawLineText", "deadlineState",
    "normalizedPayload", "pendingQuestion",
}
_TASK_UPDATE_ITEM_KEYS = _TASK_CREATE_ITEM_KEYS | {"updateFields"}
_TASK_DELETE_ITEM_KEYS = {
    "entityType", "action", "targetEntityId", "rawLineText", "normalizedPayload", "pendingQuestion",
}
_FS_CREATE_ITEM_KEYS = _TASK_DELETE_ITEM_KEYS
_FS_UPDATE_ITEM_KEYS = _FS_CREATE_ITEM_KEYS | {"updateFields"}
_FS_DELETE_ITEM_KEYS = _FS_CREATE_ITEM_KEYS

_TASK_PAYLOAD_KEYS = {
    "title", "deadlineAt", "estimatedMinutes", "estimatedMinutesSource",
    "remainingMinutes", "amountText", "amountSource",
}
_FS_PAYLOAD_KEYS = {"title", "startAt", "endAt"}


class SolarUnavailableError(Exception):
    """네트워크 실패·타임아웃·비2xx·JSON 계약 위반을 전부 이 예외 하나로 통일한다."""


@dataclass(frozen=True)
class SolarAnalysisItem:
    entity_type: str
    action: str
    target_entity_id: str | None
    raw_line_text: str
    update_fields: list[str]
    normalized_payload: dict
    missing_fields: list[str]
    pending_question: dict | None


@dataclass(frozen=True)
class UnresolvedLine:
    raw_line_text: str
    action: str
    entity_type: str
    message: str


@dataclass(frozen=True)
class SolarAnalysisResult:
    analysis_message: str
    items: list[SolarAnalysisItem]
    unresolved_line: UnresolvedLine | None


# ---------------------------------------------------------------------------
# 공통 검증 헬퍼
# ---------------------------------------------------------------------------


def _require_exact_keys(d: dict, allowed: set[str], context: str) -> None:
    actual = set(d.keys())
    if actual != allowed:
        raise SolarUnavailableError(f"{context} 키 집합이 계약과 다르다: {actual} != {allowed}")


def _require_non_blank_str(value: object, context: str) -> str:
    if not isinstance(value, str):
        raise SolarUnavailableError(f"{context}가 문자열이 아니다.")
    trimmed = value.strip()
    if not trimmed:
        raise SolarUnavailableError(f"{context}가 비어있다.")
    return trimmed


def _validate_optional_title(value: object) -> tuple[str | None, bool]:
    """soft-missing 허용 title 정규화. 반환: (정규화된 값 또는 None, missing 여부)."""
    if value is None:
        return None, True
    if not isinstance(value, str):
        raise SolarUnavailableError("title이 문자열이 아니다.")
    trimmed = value.strip()
    if not trimmed:
        return None, True
    return trimmed, False


def _resolve_optional_datetime(value: object) -> str | None:
    """soft-missing과 hard-reject를 분리: null/공백은 soft(None 반환), 공백 아닌데 형식이
    잘못되면 hard(예외). 성공 시 datetime 객체가 아니라 RFC 3339 문자열을 반환한다."""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    if not isinstance(value, str):
        raise SolarUnavailableError("날짜 필드가 문자열이 아니다.")
    if not _RFC3339_PATTERN.match(value):
        raise SolarUnavailableError(f"날짜 형식이 RFC 3339가 아니다: {value!r}")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise SolarUnavailableError(f"존재하지 않는 날짜·시각이다: {value!r}") from exc
    if parsed.tzinfo is None:
        raise SolarUnavailableError(f"timezone 없는(naive) 날짜는 허용하지 않는다: {value!r}")
    return parsed.isoformat()


def _validate_deadline_state(deadline_state: object, deadline_at_raw: object) -> tuple[str | None, bool]:
    """반환: (canonical deadlineAt 문자열 또는 None, missing 여부)."""
    if deadline_state not in ("KNOWN", "NONE", "MISSING"):
        raise SolarUnavailableError(f"deadlineState 값이 올바르지 않다: {deadline_state!r}")
    resolved = _resolve_optional_datetime(deadline_at_raw)
    if deadline_state == "KNOWN":
        if resolved is None:
            raise SolarUnavailableError("deadlineState=KNOWN인데 deadlineAt이 없다.")
        return resolved, False
    if deadline_state == "NONE":
        if resolved is not None:
            raise SolarUnavailableError("deadlineState=NONE인데 deadlineAt이 있다.")
        return None, False
    # MISSING
    if resolved is not None:
        raise SolarUnavailableError("deadlineState=MISSING인데 deadlineAt이 있다.")
    return None, True


def _validate_estimated_minutes(value: object, source: object) -> tuple[int | None, str | None, bool]:
    if source is not None and source not in ("USER", "AI_ESTIMATED"):
        raise SolarUnavailableError(f"estimatedMinutesSource 값이 올바르지 않다: {source!r}")
    valid_value = type(value) is int and value >= 1
    valid_source = source is not None
    if valid_value and valid_source:
        return value, source, False
    return None, None, True


def _validate_remaining_minutes(value: object) -> tuple[int | None, bool]:
    if type(value) is int and value >= 0:
        return value, False
    return None, True


def _validate_amount_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SolarUnavailableError("amountText가 문자열이 아니다.")
    trimmed = value.strip()
    return trimmed if trimmed else None


def _validate_amount(amount_text_raw: object, amount_source_raw: object) -> tuple[str | None, str | None, bool]:
    amount_text = _validate_amount_text(amount_text_raw)
    if amount_source_raw is not None and amount_source_raw not in ("USER", "AI_ESTIMATED", "UNKNOWN"):
        raise SolarUnavailableError(f"amountSource 값이 올바르지 않다: {amount_source_raw!r}")

    if amount_source_raw is None:
        if amount_text is not None:
            raise SolarUnavailableError("amountSource=null인데 amountText가 있다.")
        return None, None, True
    if amount_source_raw == "UNKNOWN":
        if amount_text is not None:
            raise SolarUnavailableError("amountSource=UNKNOWN인데 amountText가 있다.")
        return None, "UNKNOWN", False
    if amount_text is None:
        raise SolarUnavailableError("amountSource가 USER/AI_ESTIMATED인데 amountText가 없다.")
    return amount_text, amount_source_raw, False


# ---------------------------------------------------------------------------
# normalizedPayload 검증·정규화 (action별)
# ---------------------------------------------------------------------------


def _validate_and_normalize_task_create(payload: dict, deadline_state: object) -> tuple[list[str], dict]:
    _require_exact_keys(payload, _TASK_PAYLOAD_KEYS, "TASK normalizedPayload")

    title, title_missing = _validate_optional_title(payload.get("title"))
    if title_missing:
        raise SolarUnavailableError("TASK title이 비어있다(CREATE는 hard-required).")

    if payload.get("remainingMinutes") is not None:
        raise SolarUnavailableError("CREATE의 remainingMinutes는 SOLAR가 채우면 안 된다.")

    deadline_at, deadline_missing = _validate_deadline_state(deadline_state, payload.get("deadlineAt"))
    estimated_minutes, estimated_minutes_source, estimated_missing = _validate_estimated_minutes(
        payload.get("estimatedMinutes"), payload.get("estimatedMinutesSource")
    )
    amount_text, amount_source, amount_missing = _validate_amount(
        payload.get("amountText"), payload.get("amountSource")
    )

    missing_fields = []
    if deadline_missing:
        missing_fields.append("deadlineAt")
    if estimated_missing:
        missing_fields.append("estimatedMinutes")
    if amount_missing:
        missing_fields.append("amount")

    canonical_payload = {
        "title": title,
        "deadlineAt": deadline_at,
        "estimatedMinutes": estimated_minutes,
        "estimatedMinutesSource": estimated_minutes_source,
        "remainingMinutes": None,
        "amountText": amount_text,
        "amountSource": amount_source,
    }
    return missing_fields, canonical_payload


def _validate_and_normalize_fixed_schedule_create(payload: dict) -> tuple[list[str], dict]:
    _require_exact_keys(payload, _FS_PAYLOAD_KEYS, "FIXED_SCHEDULE normalizedPayload")

    title, title_missing = _validate_optional_title(payload.get("title"))
    start_at = _resolve_optional_datetime(payload.get("startAt"))
    end_at = _resolve_optional_datetime(payload.get("endAt"))

    if start_at is not None and end_at is not None:
        if datetime.fromisoformat(end_at) <= datetime.fromisoformat(start_at):
            raise SolarUnavailableError("endAt이 startAt보다 앞서거나 같다.")

    missing_fields = []
    if title_missing:
        missing_fields.append("title")
    if start_at is None:
        missing_fields.append("startAt")
    if end_at is None:
        missing_fields.append("endAt")

    canonical_payload = {"title": title, "startAt": start_at, "endAt": end_at}
    return missing_fields, canonical_payload


def _validate_and_normalize_task_update(
    payload: dict, update_fields: list[str], deadline_state: object
) -> tuple[list[str], dict]:
    _require_exact_keys(payload, _TASK_PAYLOAD_KEYS, "TASK normalizedPayload")
    fields = set(update_fields)
    missing_fields: list[str] = []
    canonical: dict = {}

    if "title" in fields:
        title, title_missing = _validate_optional_title(payload.get("title"))
        canonical["title"] = title
        if title_missing:
            missing_fields.append("title")
    else:
        if payload.get("title") is not None:
            raise SolarUnavailableError("updateFields에 없는 title에 값이 있다.")
        canonical["title"] = None

    deadline_at, deadline_missing_signal = _validate_deadline_state(deadline_state, payload.get("deadlineAt"))
    if "deadlineAt" in fields:
        canonical["deadlineAt"] = deadline_at
        if deadline_missing_signal:
            missing_fields.append("deadlineAt")
    else:
        if deadline_state != "MISSING":
            raise SolarUnavailableError("updateFields에 없는 deadlineAt인데 deadlineState가 확정값이다.")
        canonical["deadlineAt"] = None

    if "estimatedMinutes" in fields:
        estimated_minutes, estimated_minutes_source, estimated_missing = _validate_estimated_minutes(
            payload.get("estimatedMinutes"), payload.get("estimatedMinutesSource")
        )
        canonical["estimatedMinutes"] = estimated_minutes
        canonical["estimatedMinutesSource"] = estimated_minutes_source
        if estimated_missing:
            missing_fields.append("estimatedMinutes")
    else:
        if payload.get("estimatedMinutes") is not None or payload.get("estimatedMinutesSource") is not None:
            raise SolarUnavailableError("updateFields에 없는 estimatedMinutes에 값이 있다.")
        canonical["estimatedMinutes"] = None
        canonical["estimatedMinutesSource"] = None

    if "remainingMinutes" in fields:
        remaining_minutes, remaining_missing = _validate_remaining_minutes(payload.get("remainingMinutes"))
        canonical["remainingMinutes"] = remaining_minutes
        if remaining_missing:
            missing_fields.append("remainingMinutes")
    else:
        if payload.get("remainingMinutes") is not None:
            raise SolarUnavailableError("updateFields에 없는 remainingMinutes에 값이 있다.")
        canonical["remainingMinutes"] = None

    if "amount" in fields:
        amount_text, amount_source, amount_missing = _validate_amount(
            payload.get("amountText"), payload.get("amountSource")
        )
        canonical["amountText"] = amount_text
        canonical["amountSource"] = amount_source
        if amount_missing:
            missing_fields.append("amount")
    else:
        if payload.get("amountText") is not None or payload.get("amountSource") is not None:
            raise SolarUnavailableError("updateFields에 없는 amount에 값이 있다.")
        canonical["amountText"] = None
        canonical["amountSource"] = None

    return missing_fields, canonical


def _validate_and_normalize_fixed_schedule_update(
    payload: dict, update_fields: list[str]
) -> tuple[list[str], dict]:
    _require_exact_keys(payload, _FS_PAYLOAD_KEYS, "FIXED_SCHEDULE normalizedPayload")
    fields = set(update_fields)
    missing_fields: list[str] = []
    canonical: dict = {}

    if "title" in fields:
        title, title_missing = _validate_optional_title(payload.get("title"))
        canonical["title"] = title
        if title_missing:
            missing_fields.append("title")
    else:
        if payload.get("title") is not None:
            raise SolarUnavailableError("updateFields에 없는 title에 값이 있다.")
        canonical["title"] = None

    for field_name in ("startAt", "endAt"):
        if field_name in fields:
            value = _resolve_optional_datetime(payload.get(field_name))
            canonical[field_name] = value
            if value is None:
                missing_fields.append(field_name)
        else:
            if payload.get(field_name) is not None:
                raise SolarUnavailableError(f"updateFields에 없는 {field_name}에 값이 있다.")
            canonical[field_name] = None

    if canonical["startAt"] is not None and canonical["endAt"] is not None:
        if datetime.fromisoformat(canonical["endAt"]) <= datetime.fromisoformat(canonical["startAt"]):
            raise SolarUnavailableError("endAt이 startAt보다 앞서거나 같다.")

    return missing_fields, canonical


def _validate_delete_payload(payload: dict, payload_keys: set[str], context: str) -> dict:
    _require_exact_keys(payload, payload_keys, context)
    return dict(payload)


# ---------------------------------------------------------------------------
# item / unresolvedLine 파싱
# ---------------------------------------------------------------------------


def _missing_order_for(entity_type: str, action: str) -> list[str]:
    if entity_type != "TASK":
        return _FIXED_SCHEDULE_MISSING_ORDER
    return _TASK_MISSING_ORDER_UPDATE if action == "UPDATE" else _TASK_MISSING_ORDER_CREATE


def _parse_pending_question_cross_check(
    pending_question_raw: object, missing_fields: list[str], entity_type: str, action: str
) -> dict | None:
    if not missing_fields:
        # READY(또는 back-fill 전 UPDATE의 1차 계산이 비어있음)인 카드의 pendingQuestion은 무시.
        return None

    if not isinstance(pending_question_raw, dict):
        raise SolarUnavailableError("missing이 있는데 pendingQuestion이 없다.")
    field = pending_question_raw.get("field")
    message = pending_question_raw.get("message")
    if not isinstance(field, str) or not isinstance(message, str):
        raise SolarUnavailableError("pendingQuestion.field/message가 문자열이 아니다.")
    field = field.strip()
    message = message.strip()
    if not field or not message:
        raise SolarUnavailableError("pendingQuestion.field/message가 공백이다.")

    order = _missing_order_for(entity_type, action)
    expected = next((f for f in order if f in missing_fields), None)
    if field != expected:
        raise SolarUnavailableError(
            f"pendingQuestion.field({field!r})가 계산된 첫 missing 필드({expected!r})와 다르다."
        )
    return {"field": field, "message": message}


def _parse_item(
    raw: object,
    *,
    purpose: SolarRequestPurpose,
    candidate_task_ids: set[str],
    candidate_fixed_schedule_ids: set[str],
) -> SolarAnalysisItem:
    if not isinstance(raw, dict):
        raise SolarUnavailableError("item이 dict가 아니다.")

    entity_type = raw.get("entityType")
    if entity_type not in ("TASK", "FIXED_SCHEDULE"):
        raise SolarUnavailableError(f"entityType 값이 올바르지 않다: {entity_type!r}")

    action = raw.get("action")
    if action not in ("CREATE", "UPDATE", "DELETE"):
        raise SolarUnavailableError(f"action 값이 올바르지 않다: {action!r}")

    if purpose == SolarRequestPurpose.NEW_CYCLE and action != "CREATE":
        raise SolarUnavailableError("NEW_CYCLE에서는 action=CREATE만 허용한다.")

    is_task = entity_type == "TASK"

    if action == "CREATE":
        allowed_item_keys = _TASK_CREATE_ITEM_KEYS if is_task else _FS_CREATE_ITEM_KEYS
    elif action == "UPDATE":
        allowed_item_keys = _TASK_UPDATE_ITEM_KEYS if is_task else _FS_UPDATE_ITEM_KEYS
    else:
        allowed_item_keys = _TASK_DELETE_ITEM_KEYS if is_task else _FS_DELETE_ITEM_KEYS
    _require_exact_keys(raw, allowed_item_keys, f"{entity_type} item({action})")

    raw_line_text = _require_non_blank_str(raw.get("rawLineText"), "item.rawLineText")

    target_entity_id = raw.get("targetEntityId")
    if action == "CREATE":
        if target_entity_id is not None:
            raise SolarUnavailableError("action=CREATE인데 targetEntityId가 있다.")
        target_entity_id = None
    else:
        if not isinstance(target_entity_id, str) or not target_entity_id.strip():
            raise SolarUnavailableError("UPDATE/DELETE인데 targetEntityId가 없다.")
        candidates = candidate_task_ids if is_task else candidate_fixed_schedule_ids
        if target_entity_id not in candidates:
            raise SolarUnavailableError("targetEntityId가 후보 목록에 없다(할루시네이션).")

    normalized_payload_raw = raw.get("normalizedPayload")
    if not isinstance(normalized_payload_raw, dict):
        raise SolarUnavailableError("normalizedPayload가 dict가 아니다.")

    pending_question_raw = raw.get("pendingQuestion")
    if pending_question_raw is not None and not isinstance(pending_question_raw, dict):
        raise SolarUnavailableError("pendingQuestion이 dict가 아니다.")

    if action == "CREATE":
        update_fields: list[str] = []
        if is_task:
            missing_fields, canonical_payload = _validate_and_normalize_task_create(
                normalized_payload_raw, raw.get("deadlineState")
            )
        else:
            missing_fields, canonical_payload = _validate_and_normalize_fixed_schedule_create(
                normalized_payload_raw
            )
    elif action == "UPDATE":
        raw_update_fields = raw.get("updateFields")
        allowed_field_names = _TASK_UPDATE_FIELD_NAMES if is_task else _FIXED_SCHEDULE_UPDATE_FIELD_NAMES
        if not isinstance(raw_update_fields, list) or not raw_update_fields:
            raise SolarUnavailableError("updateFields가 비어있거나 리스트가 아니다.")
        update_fields = []
        for field_name in raw_update_fields:
            if not isinstance(field_name, str) or field_name not in allowed_field_names:
                raise SolarUnavailableError(f"updateFields에 알 수 없는 필드가 있다: {field_name!r}")
            update_fields.append(field_name)
        if is_task:
            missing_fields, canonical_payload = _validate_and_normalize_task_update(
                normalized_payload_raw, update_fields, raw.get("deadlineState")
            )
        else:
            missing_fields, canonical_payload = _validate_and_normalize_fixed_schedule_update(
                normalized_payload_raw, update_fields
            )
    else:  # DELETE
        update_fields = []
        payload_keys = _TASK_PAYLOAD_KEYS if is_task else _FS_PAYLOAD_KEYS
        canonical_payload = _validate_delete_payload(
            normalized_payload_raw, payload_keys, f"{entity_type} normalizedPayload"
        )
        missing_fields = []

    pending_question = _parse_pending_question_cross_check(
        pending_question_raw, missing_fields, entity_type, action
    )

    return SolarAnalysisItem(
        entity_type=entity_type,
        action=action,
        target_entity_id=target_entity_id,
        raw_line_text=raw_line_text,
        update_fields=update_fields,
        normalized_payload=canonical_payload,
        missing_fields=missing_fields,
        pending_question=pending_question,
    )


def _parse_unresolved_line(
    raw: dict, *, candidate_task_ids: set[str], candidate_fixed_schedule_ids: set[str]
) -> UnresolvedLine:
    _require_exact_keys(raw, _UNRESOLVED_LINE_KEYS, "unresolvedLine")

    raw_line_text = _require_non_blank_str(raw.get("rawLineText"), "unresolvedLine.rawLineText")

    action = raw.get("action")
    if action not in ("UPDATE", "DELETE"):
        raise SolarUnavailableError(f"unresolvedLine.action은 UPDATE/DELETE만 허용한다: {action!r}")

    entity_type = raw.get("entityType")
    if entity_type not in ("TASK", "FIXED_SCHEDULE"):
        raise SolarUnavailableError(f"unresolvedLine.entityType 값이 올바르지 않다: {entity_type!r}")

    message = _require_non_blank_str(raw.get("message"), "unresolvedLine.message")

    candidates = candidate_task_ids if entity_type == "TASK" else candidate_fixed_schedule_ids
    if not candidates:
        raise SolarUnavailableError("unresolvedLine의 entityType에 해당하는 후보가 0개다.")

    return UnresolvedLine(raw_line_text=raw_line_text, action=action, entity_type=entity_type, message=message)


# ---------------------------------------------------------------------------
# 공개 함수
# ---------------------------------------------------------------------------


def parse_solar_response(
    content: str,
    *,
    purpose: SolarRequestPurpose,
    candidate_task_ids: set[str],
    candidate_fixed_schedule_ids: set[str],
) -> SolarAnalysisResult:
    """SOLAR 응답 content(JSON 문자열)를 파싱·검증하는 순수 함수(DB 접근 없음, back-fill 없음)."""
    try:
        raw = json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise SolarUnavailableError("SOLAR 응답이 유효한 JSON이 아니다.") from exc

    if not isinstance(raw, dict):
        raise SolarUnavailableError("SOLAR 응답 최상위가 dict가 아니다.")

    _require_exact_keys(raw, _TOP_LEVEL_KEYS, "최상위")

    analysis_message_raw = raw.get("analysisMessage")
    if not isinstance(analysis_message_raw, str) or not analysis_message_raw.strip():
        raise SolarUnavailableError("analysisMessage가 비어있다.")
    analysis_message = analysis_message_raw.strip()

    raw_items = raw.get("items")
    if not isinstance(raw_items, list):
        raise SolarUnavailableError("items가 list가 아니다.")

    raw_unresolved = raw.get("unresolvedLine")
    if raw_unresolved is not None and not isinstance(raw_unresolved, dict):
        raise SolarUnavailableError("unresolvedLine이 null 또는 dict가 아니다.")

    if not raw_items and raw_unresolved is None:
        raise SolarUnavailableError("items와 unresolvedLine이 모두 비어있다.")

    if purpose == SolarRequestPurpose.NEW_CYCLE and raw_unresolved is not None:
        raise SolarUnavailableError("NEW_CYCLE에서는 unresolvedLine이 있으면 안 된다.")

    unresolved_line = None
    if raw_unresolved is not None:
        unresolved_line = _parse_unresolved_line(
            raw_unresolved,
            candidate_task_ids=candidate_task_ids,
            candidate_fixed_schedule_ids=candidate_fixed_schedule_ids,
        )

    items = [
        _parse_item(
            raw_item,
            purpose=purpose,
            candidate_task_ids=candidate_task_ids,
            candidate_fixed_schedule_ids=candidate_fixed_schedule_ids,
        )
        for raw_item in raw_items
    ]

    return SolarAnalysisResult(analysis_message=analysis_message, items=items, unresolved_line=unresolved_line)


def _build_prompt_messages(
    message: str,
    *,
    now: datetime,
    purpose: SolarRequestPurpose,
    cycle_start,
    cycle_end,
    candidate_tasks: list[dict],
    candidate_fixed_schedules: list[dict],
) -> list[dict]:
    context: dict = {
        "now": now.astimezone(_SEOUL_TZ).isoformat(),
        "purpose": purpose.value,
    }
    if purpose == SolarRequestPurpose.ACTIVE_CYCLE:
        context["cycleStart"] = cycle_start.isoformat() if cycle_start is not None else None
        context["cycleEnd"] = cycle_end.isoformat() if cycle_end is not None else None
        context["candidateTasks"] = candidate_tasks
        context["candidateFixedSchedules"] = candidate_fixed_schedules

    system_prompt = (
        "당신은 '이음' 서비스에서 사용자의 자연어 입력을 분석해 할 일(TASK)·고정 일정"
        "(FIXED_SCHEDULE) 카드로 구조화하는 분석기입니다. 반드시 아래 JSON 스키마 하나로만"
        " 응답하고, 다른 설명·마크다운·코드블록을 절대 덧붙이지 마세요.\n\n"
        "최상위 키는 정확히 analysisMessage, items, unresolvedLine 세 개만 포함해야 합니다"
        "(다른 키 금지, 누락 금지).\n"
        "- analysisMessage: 분석 결과를 사용자에게 안내하는 한국어 문장(공백 아님).\n"
        "- items: 카드 배열(빈 배열 허용, 단 unresolvedLine도 null이면 안 됨). 각 원소는\n"
        "  entityType(\"TASK\"|\"FIXED_SCHEDULE\"), action(\"CREATE\"|\"UPDATE\"|\"DELETE\"),\n"
        "  targetEntityId(문자열 또는 null), rawLineText(원문 중 이 카드에 해당하는 부분),\n"
        "  normalizedPayload(entityType별 구조), pendingQuestion(dict 또는 null)을 포함합니다.\n"
        "  TASK item은 추가로 deadlineState(\"KNOWN\"|\"NONE\"|\"MISSING\")를 포함합니다.\n"
        "  action=\"UPDATE\"인 item은 추가로 updateFields(문자열 배열, 실제로 바꾸는 필드 이름만,\n"
        "  절대 빈 배열 금지)를 포함합니다.\n"
        "- action=\"CREATE\"면 targetEntityId는 반드시 null입니다.\n"
        "- action=\"UPDATE\"/\"DELETE\"면 targetEntityId는 아래 candidateTasks/"
        "candidateFixedSchedules 중 하나의 id와 정확히 같은 문자열이어야 합니다. 후보에 없는 id를"
        " 지어내지 마세요.\n"
        "- purpose=\"NEW_CYCLE\"이면 candidateTasks/candidateFixedSchedules가 아예 주어지지 않고,"
        " 모든 item은 action=\"CREATE\"여야 하며 unresolvedLine은 반드시 null입니다.\n\n"
        "TASK normalizedPayload는 정확히 title, deadlineAt, estimatedMinutes,"
        " estimatedMinutesSource, remainingMinutes, amountText, amountSource 일곱 키만"
        " 포함합니다.\n"
        "- deadlineState=\"KNOWN\"이면 deadlineAt은 timezone(+09:00 등)이 포함된 RFC 3339"
        " 문자열이어야 합니다. \"NONE\"(마감 없음이 확정)과 \"MISSING\"(아직 모름/안 바뀜)이면"
        " deadlineAt은 반드시 null입니다.\n"
        "- estimatedMinutes/estimatedMinutesSource(\"USER\"|\"AI_ESTIMATED\")는 함께 값이 있거나"
        " 함께 null이어야 합니다.\n"
        "- amountSource는 null(아직 모름/안 바뀜) 또는 \"USER\"/\"AI_ESTIMATED\""
        "(amountText 필수) 또는 \"UNKNOWN\"(분량을 확정적으로 모름, amountText는 null)입니다.\n"
        "- remainingMinutes는 CREATE에서는 항상 null(서버가 채웁니다). UPDATE에서 남은 시간 자체를"
        " 바꾸는 요청일 때만 updateFields에 \"remainingMinutes\"를 넣고 새 정수값(0 이상)을"
        " 채우세요 — estimatedMinutes와는 완전히 별개입니다.\n"
        "- action=\"UPDATE\"일 때 updateFields에 없는 필드는 이 요청에서 안 바꾸는 것이므로"
        " title/amountText는 null, estimatedMinutes/remainingMinutes는 null,"
        " estimatedMinutesSource/amountSource는 null, deadlineState는 \"MISSING\"+"
        "deadlineAt=null로 두세요(값을 채우면 안 됩니다). updateFields에 있는 필드는 새 값을"
        " 확실히 알 때만 채우고, 모르면 해당 필드만 null로 두세요(카드 전체를 포기하지 마세요).\n\n"
        "FIXED_SCHEDULE normalizedPayload는 정확히 title, startAt, endAt 세 키만 포함합니다."
        " startAt/endAt은 timezone이 포함된 RFC 3339 문자열이며 endAt은 반드시 startAt보다"
        " 늦어야 합니다(자정을 넘는 일정도 하루로 취급해 endAt 날짜를 다음날로 표기).\n\n"
        "pendingQuestion: 이 카드에 아직 확정 못 한 필드가 있을 때만"
        " {\"field\": \"<필드명>\", \"message\": \"<한국어 질문 한 문장>\"}로 채우세요. field는"
        " TASK는 deadlineAt/estimatedMinutes/remainingMinutes/amount/title 중, FIXED_SCHEDULE은"
        " title/startAt/endAt 중 그 카드에서 가장 먼저 확인해야 할 값이어야 합니다. 카드에 확정"
        " 못 한 값이 없으면 pendingQuestion은 null입니다. 한 카드당 한 번에 하나의 질문만"
        " 하세요.\n\n"
        "unresolvedLine: 사용자가 가리키는 기존 항목이 후보 여러 개 중 어느 것인지 하나로 특정할"
        " 수 없을 때만 {\"rawLineText\": ..., \"action\": \"UPDATE\"|\"DELETE\","
        " \"entityType\": \"TASK\"|\"FIXED_SCHEDULE\", \"message\": \"<확인 질문>\"}로 채우고 그"
        " 줄에 대한 카드는 만들지 마세요. 특정할 수 없는 참조가 여러 개여도 이번 응답에는 딱"
        " 하나만 보고하세요. 해당 없으면 null입니다.\n\n"
        f"컨텍스트(현재 시각·요청 목적·활성 계획 기간·기존 항목 후보 — 상대 날짜 표현은 이"
        f" \"now\" 기준 Asia/Seoul로 해석):\n{json.dumps(context, ensure_ascii=False)}"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": message},
    ]


def call_solar(payload: dict) -> str:
    """Upstage Chat Completions(OpenAI 호환)를 호출해 `choices[0].message.content` 문자열을
    반환한다. 네트워크 실패·타임아웃·비2xx·응답 envelope 위반은 전부 SolarUnavailableError로
    통일한다."""
    api_key = get_solar_api_key()
    base_url = get_solar_base_url()
    model = get_solar_model()

    body = {
        "model": model,
        "messages": payload["messages"],
        "response_format": {"type": "json_object"},
        "stream": False,
    }

    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            response_body = response.read()
    except urllib.error.HTTPError as exc:
        raise SolarUnavailableError(f"SOLAR가 오류 상태 코드를 반환했다: {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SolarUnavailableError("SOLAR 호출에 실패했다(네트워크·타임아웃).") from exc

    try:
        response_json = json.loads(response_body)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as exc:
        raise SolarUnavailableError("SOLAR 응답 body가 JSON이 아니다.") from exc

    if not isinstance(response_json, dict):
        raise SolarUnavailableError("SOLAR 응답 body 최상위가 dict가 아니다.")

    choices = response_json.get("choices")
    if not isinstance(choices, list) or not choices:
        raise SolarUnavailableError("SOLAR 응답에 choices가 없다.")

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise SolarUnavailableError("SOLAR choices[0]이 dict가 아니다.")

    message_obj = first_choice.get("message")
    if not isinstance(message_obj, dict):
        raise SolarUnavailableError("SOLAR choices[0].message가 없다.")

    content = message_obj.get("content")
    if not isinstance(content, str):
        raise SolarUnavailableError("SOLAR choices[0].message.content가 문자열이 아니다.")

    return content


def analyze_message(
    message: str,
    *,
    now: datetime,
    purpose: SolarRequestPurpose,
    cycle_start=None,
    cycle_end=None,
    candidate_tasks: list[dict] | None = None,
    candidate_fixed_schedules: list[dict] | None = None,
) -> SolarAnalysisResult:
    """`call_solar` → `parse_solar_response` 순서로 호출하는 단일 진입점(전부 동기). 서비스
    계층은 이 함수 하나만 호출·mock한다."""
    candidate_tasks = candidate_tasks or []
    candidate_fixed_schedules = candidate_fixed_schedules or []

    messages = _build_prompt_messages(
        message,
        now=now,
        purpose=purpose,
        cycle_start=cycle_start,
        cycle_end=cycle_end,
        candidate_tasks=candidate_tasks,
        candidate_fixed_schedules=candidate_fixed_schedules,
    )
    content = call_solar({"messages": messages})

    candidate_task_ids = {str(candidate["id"]) for candidate in candidate_tasks}
    candidate_fixed_schedule_ids = {str(candidate["id"]) for candidate in candidate_fixed_schedules}

    return parse_solar_response(
        content,
        purpose=purpose,
        candidate_task_ids=candidate_task_ids,
        candidate_fixed_schedule_ids=candidate_fixed_schedule_ids,
    )
