"""Upstage SOLAR 연동. 이 모듈은 전부 동기 함수로만 구성된다 — 이 저장소는 동기 SQLAlchemy
Session을 쓰고, FastAPI의 동기 endpoint(threadpool에서 실행)와 짝을 이루므로 `urllib.request`의
블로킹 호출을 여기서 그대로 써도 메인 이벤트 루프를 막지 않는다. async로 감싸지 않는다.
"""

import asyncio
import json
import logging
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TypeAlias, TypeVar
from zoneinfo import ZoneInfo

from app.core.config import get_solar_api_key, get_solar_base_url, get_solar_model
from app.models.enums import SolarRequestPurpose
from app.services import gemini_change_input_client

_T = TypeVar("_T")

logger = logging.getLogger(__name__)

_SEOUL_TZ = ZoneInfo("Asia/Seoul")
_REQUEST_TIMEOUT_SECONDS = 30

_RFC3339_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")

_TASK_MISSING_ORDER_CREATE = ["deadlineAt", "estimatedMinutes", "amount"]
_TASK_MISSING_ORDER_UPDATE = ["title", "deadlineAt", "estimatedMinutes", "remainingMinutes", "amount"]
# CHANGE_INPUT의 CREATE+REQUEST_ITEM(기존 대기 CREATE 카드 patch) 전용 — title이 소프트해질 수
# 있다는 점에서 plain CREATE와 다르고(그래서 UPDATE 순서 기반), remainingMinutes는 CREATE 카드에
# 독립 필드가 아니라서 제외한다.
_TASK_MISSING_ORDER_CREATE_MERGE = [f for f in _TASK_MISSING_ORDER_UPDATE if f != "remainingMinutes"]
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

# CHANGE_INPUT 전용: 기존 item 키 집합에 targetKind만 추가한 변형(그 외 모드에는 없는 키).
_CHANGE_INPUT_TASK_CREATE_ITEM_KEYS = _TASK_CREATE_ITEM_KEYS | {"targetKind"}
_CHANGE_INPUT_TASK_UPDATE_ITEM_KEYS = _TASK_UPDATE_ITEM_KEYS | {"targetKind"}
_CHANGE_INPUT_TASK_DELETE_ITEM_KEYS = _TASK_DELETE_ITEM_KEYS | {"targetKind"}
_CHANGE_INPUT_FS_CREATE_ITEM_KEYS = _FS_CREATE_ITEM_KEYS | {"targetKind"}
_CHANGE_INPUT_FS_UPDATE_ITEM_KEYS = _FS_UPDATE_ITEM_KEYS | {"targetKind"}
_CHANGE_INPUT_FS_DELETE_ITEM_KEYS = _FS_DELETE_ITEM_KEYS | {"targetKind"}

# CHANGE_INPUT의 CREATE+REQUEST_ITEM(기존 대기 CREATE 카드 수정) 전용 — action은 CREATE로
# 유지하면서 changedFields로 부분 patch를 표현하는 하이브리드 키 집합.
_CHANGE_INPUT_TASK_CREATE_MERGE_ITEM_KEYS = {
    "entityType", "action", "targetEntityId", "targetKind", "rawLineText",
    "deadlineState", "normalizedPayload", "pendingQuestion", "changedFields",
}
_CHANGE_INPUT_FS_CREATE_MERGE_ITEM_KEYS = {
    "entityType", "action", "targetEntityId", "targetKind", "rawLineText",
    "normalizedPayload", "pendingQuestion", "changedFields",
}
# CREATE 카드는 remainingMinutes가 독립 필드가 아니라(estimatedMinutes에서 항상 파생) changedFields
# 대상에서 제외한다.
_TASK_CREATE_MERGE_FIELD_NAMES = _TASK_UPDATE_FIELD_NAMES - {"remainingMinutes"}

_CHANGE_INPUT_UNRESOLVED_LINE_KEYS = _UNRESOLVED_LINE_KEYS | {"targetKind"}

_CARD_ANSWER_TOP_LEVEL_KEYS = {"analysisMessage", "answerDisposition", "pendingQuestion", "fieldValue"}
_ANSWER_DISPOSITIONS = {"PROVIDED", "DONT_KNOW", "UNCLEAR"}

_UNRESOLVED_ANSWER_TOP_LEVEL_KEYS = {"analysisMessage", "items", "unresolvedLine", "resolvedTargetOnly"}

_CHANGE_INPUT_TOP_LEVEL_KEYS = {"analysisMessage", "operations", "unresolvedOperation"}
_CHANGE_PENDING_QUESTION_KEYS = {"field", "message", "attemptCount"}
_CHANGE_ADD_KEYS = {"operationType", "entityType", "rawLineText", "payload", "pendingQuestion"}
_CHANGE_PATCH_ITEM_KEYS = {
    "operationType", "requestItemId", "entityType", "changedFields", "patch", "pendingQuestion",
}
_CHANGE_DELETE_ITEM_KEYS = {"operationType", "requestItemId", "entityType"}
_CHANGE_UPDATE_ENTITY_KEYS = {
    "operationType", "targetEntityId", "entityType", "updateFields", "patch", "pendingQuestion",
}
_CHANGE_DELETE_ENTITY_KEYS = {"operationType", "targetEntityId", "entityType"}
_CHANGE_UNRESOLVED_KEYS = {"intendedOperation", "targetKind", "entityType", "rawLineText", "message"}
_CHANGE_TASK_ADD_PAYLOAD_KEYS = {
    "title", "deadlineAt", "deadlineState", "estimatedMinutes", "estimatedMinutesSource",
    "amountText", "amountSource",
}
_CHANGE_TASK_FIELD_KEYS = {
    "title": {"title"},
    "deadlineAt": {"deadlineAt", "deadlineState"},
    "estimatedMinutes": {"estimatedMinutes", "estimatedMinutesSource"},
    "amount": {"amountText", "amountSource"},
}
_CHANGE_TASK_ENTITY_FIELD_KEYS = {**_CHANGE_TASK_FIELD_KEYS, "remainingMinutes": {"remainingMinutes"}}
_CHANGE_FS_FIELD_KEYS = {"title": {"title"}, "startAt": {"startAt"}, "endAt": {"endAt"}}


class SolarUnavailableError(Exception):
    """네트워크 실패·타임아웃·비2xx·JSON 계약 위반을 전부 이 예외 하나로 통일한다.

    `code`는 계약 위반의 종류를 나타내는 짧은 식별자(`_log_contract_violation`이 로그로 남기는
    코드와 동일한 값)로, repair 프롬프트 구성에 쓰인다. 항상 정적 문자열이거나 우리 스키마의
    키 이름만으로 구성돼 SOLAR가 자유 생성한 원문은 절대 담지 않는다. 특별히 분류되지 않은
    위반(네트워크 실패 등 포함)은 기본값을 쓴다.
    """

    def __init__(self, message: str, *, code: str = "SOLAR_CONTRACT_VIOLATION"):
        super().__init__(message)
        self.code = code


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
    target_kind: str | None = None  # "ENTITY"|"REQUEST_ITEM"|None — CHANGE_INPUT 모드에서만 값 있음


@dataclass(frozen=True)
class UnresolvedLine:
    raw_line_text: str
    action: str
    entity_type: str
    message: str
    target_kind: str = "ENTITY"  # CHANGE_INPUT 자체 unresolvedLine만 "REQUEST_ITEM"일 수 있음


@dataclass(frozen=True)
class ResolvedTargetOnly:
    """UNRESOLVED_ANSWER 전용: 대상은 확정됐지만 무엇을 바꿀지는 이 답변만으로 알 수 없을 때."""

    target_entity_id: str
    target_kind: str  # "ENTITY"|"REQUEST_ITEM"


@dataclass(frozen=True)
class SolarAnalysisResult:
    analysis_message: str
    items: list[SolarAnalysisItem]
    unresolved_line: UnresolvedLine | None
    resolved_target_only: ResolvedTargetOnly | None = None  # UNRESOLVED_ANSWER 모드에서만 값 있음


@dataclass(frozen=True)
class SolarCardAnswerResult:
    analysis_message: str
    answer_disposition: str  # "PROVIDED" | "DONT_KNOW" | "UNCLEAR"
    pending_question_message: str | None
    field_value: dict | None


class ChangeInputOperationType(str, Enum):
    ADD = "ADD"
    PATCH_REQUEST_ITEM = "PATCH_REQUEST_ITEM"
    DELETE_REQUEST_ITEM = "DELETE_REQUEST_ITEM"
    UPDATE_ENTITY = "UPDATE_ENTITY"
    DELETE_ENTITY = "DELETE_ENTITY"


@dataclass(frozen=True)
class ChangeInputAddOperation:
    operation_type: ChangeInputOperationType
    entity_type: str
    raw_line_text: str
    normalized_payload: dict
    missing_fields: list[str]
    pending_question: dict | None


@dataclass(frozen=True)
class ChangeInputPatchRequestItemOperation:
    operation_type: ChangeInputOperationType
    request_item_id: str
    entity_type: str
    changed_fields: list[str]
    patch: dict
    missing_fields: list[str]
    pending_question: dict | None


@dataclass(frozen=True)
class ChangeInputDeleteRequestItemOperation:
    operation_type: ChangeInputOperationType
    request_item_id: str
    entity_type: str


@dataclass(frozen=True)
class ChangeInputUpdateEntityOperation:
    operation_type: ChangeInputOperationType
    target_entity_id: str
    entity_type: str
    update_fields: list[str]
    patch: dict
    missing_fields: list[str]
    pending_question: dict | None


@dataclass(frozen=True)
class ChangeInputDeleteEntityOperation:
    operation_type: ChangeInputOperationType
    target_entity_id: str
    entity_type: str


ChangeInputOperation: TypeAlias = (
    ChangeInputAddOperation
    | ChangeInputPatchRequestItemOperation
    | ChangeInputDeleteRequestItemOperation
    | ChangeInputUpdateEntityOperation
    | ChangeInputDeleteEntityOperation
)


@dataclass(frozen=True)
class ChangeInputUnresolvedOperation:
    intended_operation: ChangeInputOperationType
    target_kind: str
    entity_type: str
    raw_line_text: str
    message: str


@dataclass(frozen=True)
class ChangeInputAnalysisResult:
    analysis_message: str
    operations: list[ChangeInputOperation]
    unresolved_operation: ChangeInputUnresolvedOperation | None


# ---------------------------------------------------------------------------
# 공통 검증 헬퍼
# ---------------------------------------------------------------------------


def _log_contract_violation(code: str, *, context: str | None = None) -> None:
    """SOLAR 계약 위반을 원문 응답·사용자 입력·API key 없이 위반 코드만 남긴다.

    `code`는 항상 정적 문자열(또는 `MISSING_REQUIRED_KEY:<key>`처럼 스키마에 정의된 키 이름만
    결합한 문자열)이고, `context`도 검증을 통과한 enum 값·고정 문자열로만 구성돼 SOLAR가 자유롭게
    생성한 텍스트(analysisMessage/rawLineText 등)는 절대 로그에 남기지 않는다.
    """
    if context is not None:
        logger.warning("SOLAR_CONTRACT_VIOLATION code=%s context=%s", code, context)
    else:
        logger.warning("SOLAR_CONTRACT_VIOLATION code=%s", code)


def _require_exact_keys(d: dict, allowed: set[str], context: str) -> None:
    actual = set(d.keys())
    if actual != allowed:
        codes = []
        for key in sorted(allowed - actual):
            code = f"MISSING_REQUIRED_KEY:{key}"
            _log_contract_violation(code, context=context)
            codes.append(code)
        for key in sorted(actual - allowed):
            code = f"UNEXPECTED_KEY:{key}"
            _log_contract_violation(code, context=context)
            codes.append(code)
        raise SolarUnavailableError(
            f"{context} 키 집합이 계약과 다르다: {actual} != {allowed}", code=",".join(codes)
        )


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


def _require_rfc3339(value: object, context: str) -> str:
    """hard-required RFC 3339 문자열(soft-missing 없음). 성공 시 canonical isoformat 문자열."""
    if not isinstance(value, str) or not value.strip():
        raise SolarUnavailableError(f"{context}가 비어있다.")
    if not _RFC3339_PATTERN.match(value):
        raise SolarUnavailableError(f"{context} 형식이 RFC 3339가 아니다: {value!r}")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise SolarUnavailableError(f"{context}에 존재하지 않는 날짜·시각이다: {value!r}") from exc
    if parsed.tzinfo is None:
        raise SolarUnavailableError(f"{context}에 timezone 없는(naive) 날짜는 허용하지 않는다: {value!r}")
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
        _log_contract_violation("INVALID_ENUM_VALUE:amountSource")
        raise SolarUnavailableError(
            f"amountSource 값이 올바르지 않다: {amount_source_raw!r}", code="INVALID_ENUM_VALUE:amountSource"
        )

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
            _log_contract_violation("UNTOUCHED_FIELD_HAS_VALUE:title", context="TASK UPDATE")
            raise SolarUnavailableError(
                "updateFields에 없는 title에 값이 있다.", code="UNTOUCHED_FIELD_HAS_VALUE:title"
            )
        canonical["title"] = None

    deadline_at, deadline_missing_signal = _validate_deadline_state(deadline_state, payload.get("deadlineAt"))
    if "deadlineAt" in fields:
        canonical["deadlineAt"] = deadline_at
        if deadline_missing_signal:
            missing_fields.append("deadlineAt")
    else:
        if deadline_state != "MISSING":
            _log_contract_violation("UNTOUCHED_FIELD_HAS_VALUE:deadlineState", context="TASK UPDATE")
            raise SolarUnavailableError(
                "updateFields에 없는 deadlineAt인데 deadlineState가 확정값이다.",
                code="UNTOUCHED_FIELD_HAS_VALUE:deadlineState",
            )
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
            _log_contract_violation("UNTOUCHED_FIELD_HAS_VALUE:estimatedMinutes", context="TASK UPDATE")
            raise SolarUnavailableError(
                "updateFields에 없는 estimatedMinutes에 값이 있다.",
                code="UNTOUCHED_FIELD_HAS_VALUE:estimatedMinutes",
            )
        canonical["estimatedMinutes"] = None
        canonical["estimatedMinutesSource"] = None

    if "remainingMinutes" in fields:
        remaining_minutes, remaining_missing = _validate_remaining_minutes(payload.get("remainingMinutes"))
        canonical["remainingMinutes"] = remaining_minutes
        if remaining_missing:
            missing_fields.append("remainingMinutes")
    else:
        if payload.get("remainingMinutes") is not None:
            _log_contract_violation("UNTOUCHED_FIELD_HAS_VALUE:remainingMinutes", context="TASK UPDATE")
            raise SolarUnavailableError(
                "updateFields에 없는 remainingMinutes에 값이 있다.",
                code="UNTOUCHED_FIELD_HAS_VALUE:remainingMinutes",
            )
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
            _log_contract_violation("UNTOUCHED_FIELD_HAS_VALUE:amount", context="TASK UPDATE")
            raise SolarUnavailableError(
                "updateFields에 없는 amount에 값이 있다.", code="UNTOUCHED_FIELD_HAS_VALUE:amount"
            )
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
            _log_contract_violation("UNTOUCHED_FIELD_HAS_VALUE:title", context="FIXED_SCHEDULE UPDATE")
            raise SolarUnavailableError(
                "updateFields에 없는 title에 값이 있다.", code="UNTOUCHED_FIELD_HAS_VALUE:title"
            )
        canonical["title"] = None

    for field_name in ("startAt", "endAt"):
        if field_name in fields:
            value = _resolve_optional_datetime(payload.get(field_name))
            canonical[field_name] = value
            if value is None:
                missing_fields.append(field_name)
        else:
            if payload.get(field_name) is not None:
                code = f"UNTOUCHED_FIELD_HAS_VALUE:{field_name}"
                _log_contract_violation(code, context="FIXED_SCHEDULE UPDATE")
                raise SolarUnavailableError(f"updateFields에 없는 {field_name}에 값이 있다.", code=code)
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


def missing_order_for(entity_type: str, action: str) -> list[str]:
    """entity_type/action별 canonical missing-field 순서. `solar_request_service.py`가 카드
    답변·CHANGE_INPUT patch 후 다음 질문 필드를 고를 때 그대로 재사용한다(중복 정의 금지).

    action="CREATE_MERGE"는 CHANGE_INPUT의 CREATE+REQUEST_ITEM patch 전용 pseudo-action이다
    (title이 소프트해질 수 있어 plain CREATE와 순서가 다르다)."""
    if entity_type != "TASK":
        return _FIXED_SCHEDULE_MISSING_ORDER
    if action == "UPDATE":
        return _TASK_MISSING_ORDER_UPDATE
    if action == "CREATE_MERGE":
        return _TASK_MISSING_ORDER_CREATE_MERGE
    return _TASK_MISSING_ORDER_CREATE  # CREATE(신규 카드만)


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

    order = missing_order_for(entity_type, action)
    expected = next((f for f in order if f in missing_fields), None)
    if field != expected:
        _log_contract_violation("PENDING_FIELD_MISMATCH", context=f"{entity_type}/{action}")
        raise SolarUnavailableError(
            f"pendingQuestion.field({field!r})가 계산된 첫 missing 필드({expected!r})와 다르다.",
            code="PENDING_FIELD_MISMATCH",
        )
    return {"field": field, "message": message}


def _parse_change_pending_question(raw: object, missing_fields: list[str], entity_type: str) -> dict | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise SolarUnavailableError("pendingQuestion must be an object or null")
    _require_exact_keys(raw, _CHANGE_PENDING_QUESTION_KEYS, "CHANGE_INPUT pendingQuestion")
    field = _require_non_blank_str(raw["field"], "pendingQuestion.field")
    message = _require_non_blank_str(raw["message"], "pendingQuestion.message")
    attempt_count = raw["attemptCount"]
    if type(attempt_count) is not int or attempt_count < 1:
        raise SolarUnavailableError("pendingQuestion.attemptCount must be a positive integer")
    order = _TASK_MISSING_ORDER_CREATE_MERGE if entity_type == "TASK" else _FIXED_SCHEDULE_MISSING_ORDER
    expected = next((name for name in order if name in missing_fields), None)
    if expected is None or field != expected:
        raise SolarUnavailableError("pendingQuestion.field does not match the first missing field", code="PENDING_FIELD_MISMATCH")
    return {"field": field, "message": message, "attemptCount": attempt_count}


def _parse_change_fields(raw: object, allowed: dict[str, set[str]], context: str) -> list[str]:
    if not isinstance(raw, list) or not raw:
        raise SolarUnavailableError(f"{context} must be a non-empty array")
    if any(not isinstance(value, str) or value not in allowed for value in raw):
        raise SolarUnavailableError(f"{context} contains an unknown field")
    if len(set(raw)) != len(raw):
        raise SolarUnavailableError(f"{context} contains a duplicate field")
    return list(raw)


def _validate_change_patch(
    raw: object, fields: list[str], field_keys: dict[str, set[str]], entity_type: str
) -> tuple[dict, list[str]]:
    if not isinstance(raw, dict):
        raise SolarUnavailableError("patch must be an object")
    expected_keys: set[str] = set().union(*(field_keys[field] for field in fields))
    _require_exact_keys(raw, expected_keys, "CHANGE_INPUT patch")
    patch: dict = {}
    missing: list[str] = []
    if "title" in fields:
        patch["title"], is_missing = _validate_optional_title(raw["title"])
        if is_missing:
            missing.append("title")
    if "deadlineAt" in fields:
        patch["deadlineAt"], is_missing = _validate_deadline_state(raw["deadlineState"], raw["deadlineAt"])
        if is_missing:
            missing.append("deadlineAt")
    if "estimatedMinutes" in fields:
        patch["estimatedMinutes"], patch["estimatedMinutesSource"], is_missing = _validate_estimated_minutes(
            raw["estimatedMinutes"], raw["estimatedMinutesSource"]
        )
        if is_missing:
            missing.append("estimatedMinutes")
    if "remainingMinutes" in fields:
        patch["remainingMinutes"], is_missing = _validate_remaining_minutes(raw["remainingMinutes"])
        if is_missing:
            missing.append("remainingMinutes")
    if "amount" in fields:
        patch["amountText"], patch["amountSource"], is_missing = _validate_amount(
            raw["amountText"], raw["amountSource"]
        )
        if is_missing:
            missing.append("amount")
    for field in ("startAt", "endAt"):
        if field in fields:
            patch[field] = _resolve_optional_datetime(raw[field])
            if patch[field] is None:
                missing.append(field)
    order = _TASK_MISSING_ORDER_UPDATE if entity_type == "TASK" else _FIXED_SCHEDULE_MISSING_ORDER
    return patch, [field for field in order if field in missing]


def _parse_change_input_operation(
    raw: object,
    *,
    candidate_task_ids: set[str],
    candidate_fixed_schedule_ids: set[str],
    candidate_request_items: dict[str, dict],
) -> ChangeInputOperation:
    if not isinstance(raw, dict):
        raise SolarUnavailableError("CHANGE_INPUT operation must be an object")
    try:
        operation_type = ChangeInputOperationType(raw.get("operationType"))
    except (TypeError, ValueError) as exc:
        raise SolarUnavailableError("invalid CHANGE_INPUT operationType") from exc
    entity_type = raw.get("entityType")
    if entity_type not in ("TASK", "FIXED_SCHEDULE"):
        raise SolarUnavailableError("invalid CHANGE_INPUT entityType")

    if operation_type is ChangeInputOperationType.ADD:
        _require_exact_keys(raw, _CHANGE_ADD_KEYS, "CHANGE_INPUT ADD")
        raw_line = _require_non_blank_str(raw["rawLineText"], "rawLineText")
        payload = raw["payload"]
        if not isinstance(payload, dict):
            raise SolarUnavailableError("ADD payload must be an object")
        if entity_type == "TASK":
            _require_exact_keys(payload, _CHANGE_TASK_ADD_PAYLOAD_KEYS, "CHANGE_INPUT ADD TASK payload")
            title, title_missing = _validate_optional_title(payload["title"])
            deadline, deadline_missing = _validate_deadline_state(payload["deadlineState"], payload["deadlineAt"])
            estimate, estimate_source, estimate_missing = _validate_estimated_minutes(
                payload["estimatedMinutes"], payload["estimatedMinutesSource"]
            )
            amount, amount_source, amount_missing = _validate_amount(payload["amountText"], payload["amountSource"])
            normalized = {"title": title, "deadlineAt": deadline, "estimatedMinutes": estimate,
                          "estimatedMinutesSource": estimate_source, "remainingMinutes": estimate,
                          "amountText": amount, "amountSource": amount_source}
            flags = {"title": title_missing, "deadlineAt": deadline_missing,
                     "estimatedMinutes": estimate_missing, "amount": amount_missing}
            missing = [field for field in _TASK_MISSING_ORDER_CREATE_MERGE if flags[field]]
        else:
            _require_exact_keys(payload, _FS_PAYLOAD_KEYS, "CHANGE_INPUT ADD FIXED_SCHEDULE payload")
            title, title_missing = _validate_optional_title(payload["title"])
            start_at, end_at = _resolve_optional_datetime(payload["startAt"]), _resolve_optional_datetime(payload["endAt"])
            normalized = {"title": title, "startAt": start_at, "endAt": end_at}
            missing = [field for field, absent in (("title", title_missing), ("startAt", start_at is None),
                                                    ("endAt", end_at is None)) if absent]
        pending = _parse_change_pending_question(raw["pendingQuestion"], missing, entity_type)
        return ChangeInputAddOperation(operation_type, entity_type, raw_line, normalized, missing, pending)

    if operation_type in (ChangeInputOperationType.PATCH_REQUEST_ITEM, ChangeInputOperationType.DELETE_REQUEST_ITEM):
        keys = _CHANGE_PATCH_ITEM_KEYS if operation_type is ChangeInputOperationType.PATCH_REQUEST_ITEM else _CHANGE_DELETE_ITEM_KEYS
        _require_exact_keys(raw, keys, f"CHANGE_INPUT {operation_type.value}")
        request_item_id = _require_non_blank_str(raw["requestItemId"], "requestItemId")
        if request_item_id in candidate_task_ids or request_item_id in candidate_fixed_schedule_ids:
            raise SolarUnavailableError("request item ID collides with the entity namespace", code="INVALID_CANDIDATE_NAMESPACE")
        candidate = candidate_request_items.get(request_item_id)
        if candidate is None or candidate.get("entityType") != entity_type:
            raise SolarUnavailableError("request item is outside its candidate namespace", code="INVALID_CANDIDATE_ID")
        if operation_type is ChangeInputOperationType.DELETE_REQUEST_ITEM:
            return ChangeInputDeleteRequestItemOperation(operation_type, request_item_id, entity_type)
        if candidate.get("action") != "CREATE":
            raise SolarUnavailableError("PATCH_REQUEST_ITEM only accepts CREATE items", code="INVALID_CANDIDATE_ACTION")
        mapping = _CHANGE_TASK_FIELD_KEYS if entity_type == "TASK" else _CHANGE_FS_FIELD_KEYS
        fields = _parse_change_fields(raw["changedFields"], mapping, "changedFields")
        patch, missing = _validate_change_patch(raw["patch"], fields, mapping, entity_type)
        pending = _parse_change_pending_question(raw["pendingQuestion"], missing, entity_type)
        return ChangeInputPatchRequestItemOperation(operation_type, request_item_id, entity_type, fields, patch, missing, pending)

    keys = _CHANGE_UPDATE_ENTITY_KEYS if operation_type is ChangeInputOperationType.UPDATE_ENTITY else _CHANGE_DELETE_ENTITY_KEYS
    _require_exact_keys(raw, keys, f"CHANGE_INPUT {operation_type.value}")
    target_id = _require_non_blank_str(raw["targetEntityId"], "targetEntityId")
    if target_id in candidate_request_items:
        raise SolarUnavailableError("entity ID collides with the request item namespace", code="INVALID_CANDIDATE_NAMESPACE")
    candidate_ids = candidate_task_ids if entity_type == "TASK" else candidate_fixed_schedule_ids
    if target_id not in candidate_ids:
        raise SolarUnavailableError("entity is outside its candidate namespace", code="INVALID_CANDIDATE_ID")
    if operation_type is ChangeInputOperationType.DELETE_ENTITY:
        return ChangeInputDeleteEntityOperation(operation_type, target_id, entity_type)
    mapping = _CHANGE_TASK_ENTITY_FIELD_KEYS if entity_type == "TASK" else _CHANGE_FS_FIELD_KEYS
    fields = _parse_change_fields(raw["updateFields"], mapping, "updateFields")
    patch, missing = _validate_change_patch(raw["patch"], fields, mapping, entity_type)
    pending = _parse_change_pending_question(raw["pendingQuestion"], missing, entity_type)
    return ChangeInputUpdateEntityOperation(operation_type, target_id, entity_type, fields, patch, missing, pending)


def parse_change_input_response(
    content: str,
    *,
    candidate_task_ids: set[str],
    candidate_fixed_schedule_ids: set[str],
    candidate_request_items: dict[str, dict],
) -> ChangeInputAnalysisResult:
    try:
        raw = json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise SolarUnavailableError("CHANGE_INPUT response is not JSON") from exc
    if not isinstance(raw, dict):
        raise SolarUnavailableError("CHANGE_INPUT response must be an object")
    _require_exact_keys(raw, _CHANGE_INPUT_TOP_LEVEL_KEYS, "CHANGE_INPUT response")
    analysis_message = _require_non_blank_str(raw["analysisMessage"], "analysisMessage")
    operations_raw, unresolved_raw = raw["operations"], raw["unresolvedOperation"]
    if not isinstance(operations_raw, list):
        raise SolarUnavailableError("operations must be an array")
    if bool(operations_raw) == (unresolved_raw is not None):
        raise SolarUnavailableError("operations and unresolvedOperation must be mutually exclusive")
    operations = [_parse_change_input_operation(
        operation, candidate_task_ids=candidate_task_ids,
        candidate_fixed_schedule_ids=candidate_fixed_schedule_ids,
        candidate_request_items=candidate_request_items,
    ) for operation in operations_raw]
    identities: set[tuple[str, str, str]] = set()
    for operation in operations:
        if isinstance(operation, (ChangeInputPatchRequestItemOperation, ChangeInputDeleteRequestItemOperation)):
            identity = ("REQUEST_ITEM", operation.entity_type, operation.request_item_id)
        elif isinstance(operation, (ChangeInputUpdateEntityOperation, ChangeInputDeleteEntityOperation)):
            identity = ("ENTITY", operation.entity_type, operation.target_entity_id)
        else:
            continue
        if identity in identities:
            raise SolarUnavailableError("duplicate operation target", code="DUPLICATE_OPERATION_TARGET")
        identities.add(identity)
    unresolved = None
    if unresolved_raw is not None:
        if not isinstance(unresolved_raw, dict):
            raise SolarUnavailableError("unresolvedOperation must be an object or null")
        _require_exact_keys(unresolved_raw, _CHANGE_UNRESOLVED_KEYS, "CHANGE_INPUT unresolvedOperation")
        try:
            intended = ChangeInputOperationType(unresolved_raw["intendedOperation"])
        except (TypeError, ValueError) as exc:
            raise SolarUnavailableError("invalid intendedOperation") from exc
        target_kind = unresolved_raw["targetKind"]
        valid_pair = ((intended in (ChangeInputOperationType.PATCH_REQUEST_ITEM, ChangeInputOperationType.DELETE_REQUEST_ITEM)
                       and target_kind == "REQUEST_ITEM") or
                      (intended in (ChangeInputOperationType.UPDATE_ENTITY, ChangeInputOperationType.DELETE_ENTITY)
                       and target_kind == "ENTITY"))
        if not valid_pair:
            raise SolarUnavailableError("intendedOperation and targetKind do not match")
        entity_type = unresolved_raw["entityType"]
        if entity_type not in ("TASK", "FIXED_SCHEDULE"):
            raise SolarUnavailableError("invalid unresolved entityType")
        unresolved = ChangeInputUnresolvedOperation(
            intended, target_kind, entity_type,
            _require_non_blank_str(unresolved_raw["rawLineText"], "rawLineText"),
            _require_non_blank_str(unresolved_raw["message"], "message"),
        )
    return ChangeInputAnalysisResult(analysis_message, operations, unresolved)


def _parse_item(
    raw: object,
    *,
    purpose: SolarRequestPurpose,
    analysis_mode: str,
    candidate_task_ids: set[str],
    candidate_fixed_schedule_ids: set[str],
    candidate_request_items: dict[str, dict] | None = None,
    fixed_target_kind: str | None = None,
    fixed_action: str | None = None,
    fixed_entity_type: str | None = None,
    fixed_target_entity_id: str | None = None,
) -> SolarAnalysisItem:
    """analysis_mode에 따라 item 파싱 규칙이 달라진다.

    - "INITIAL": 기존(#50) 동작 그대로.
    - "CHANGE_INPUT": targetKind가 item 자체 키로 존재(SOLAR가 결정). CREATE+targetKind=
      REQUEST_ITEM은 기존 대기 CREATE 카드 patch(changedFields 사용), DELETE+targetKind=
      REQUEST_ITEM은 대기 카드 취소, UPDATE는 targetKind=ENTITY만 허용.
    - "UNRESOLVED_ANSWER"(CHANGE_DETAILS 후속 포함): targetKind/action/entityType은 이 item
      자체에 없고 호출자가 이미 확정해 fixed_* 파라미터로 고정한다.
    """
    candidate_request_items = candidate_request_items or {}
    if not isinstance(raw, dict):
        raise SolarUnavailableError("item이 dict가 아니다.")

    entity_type = raw.get("entityType")
    if entity_type not in ("TASK", "FIXED_SCHEDULE"):
        raise SolarUnavailableError(f"entityType 값이 올바르지 않다: {entity_type!r}")
    if fixed_entity_type is not None and entity_type != fixed_entity_type:
        raise SolarUnavailableError("entityType이 고정된 대상과 다르다.")

    action = raw.get("action")
    if action not in ("CREATE", "UPDATE", "DELETE"):
        raise SolarUnavailableError(f"action 값이 올바르지 않다: {action!r}")
    if fixed_action is not None and action != fixed_action:
        raise SolarUnavailableError("action이 고정된 값과 다르다.")

    if analysis_mode == "INITIAL" and purpose == SolarRequestPurpose.NEW_CYCLE and action != "CREATE":
        raise SolarUnavailableError("NEW_CYCLE에서는 action=CREATE만 허용한다.")

    is_task = entity_type == "TASK"
    is_change_input = analysis_mode == "CHANGE_INPUT"

    if is_change_input:
        target_kind_raw = raw.get("targetKind")
    else:
        target_kind_raw = fixed_target_kind  # UNRESOLVED_ANSWER: 호출자가 고정, INITIAL은 None

    is_create_merge = action == "CREATE" and target_kind_raw == "REQUEST_ITEM"

    if is_change_input:
        if action == "CREATE":
            if target_kind_raw not in (None, "REQUEST_ITEM"):
                raise SolarUnavailableError(f"CREATE의 targetKind 값이 올바르지 않다: {target_kind_raw!r}")
        elif action == "UPDATE":
            if target_kind_raw != "ENTITY":
                raise SolarUnavailableError(
                    "UPDATE는 targetKind=ENTITY만 허용한다(REQUEST_ITEM 수정은 CREATE로 표현)."
                )
        else:  # DELETE
            if target_kind_raw not in ("ENTITY", "REQUEST_ITEM"):
                raise SolarUnavailableError(f"DELETE의 targetKind 값이 올바르지 않다: {target_kind_raw!r}")

    if is_create_merge:
        allowed_item_keys = (
            _CHANGE_INPUT_TASK_CREATE_MERGE_ITEM_KEYS if is_task else _CHANGE_INPUT_FS_CREATE_MERGE_ITEM_KEYS
        )
    elif is_change_input:
        if action == "CREATE":
            allowed_item_keys = _CHANGE_INPUT_TASK_CREATE_ITEM_KEYS if is_task else _CHANGE_INPUT_FS_CREATE_ITEM_KEYS
        elif action == "UPDATE":
            allowed_item_keys = _CHANGE_INPUT_TASK_UPDATE_ITEM_KEYS if is_task else _CHANGE_INPUT_FS_UPDATE_ITEM_KEYS
        else:
            allowed_item_keys = _CHANGE_INPUT_TASK_DELETE_ITEM_KEYS if is_task else _CHANGE_INPUT_FS_DELETE_ITEM_KEYS
    else:
        if action == "CREATE":
            allowed_item_keys = _TASK_CREATE_ITEM_KEYS if is_task else _FS_CREATE_ITEM_KEYS
        elif action == "UPDATE":
            allowed_item_keys = _TASK_UPDATE_ITEM_KEYS if is_task else _FS_UPDATE_ITEM_KEYS
        else:
            allowed_item_keys = _TASK_DELETE_ITEM_KEYS if is_task else _FS_DELETE_ITEM_KEYS
    _require_exact_keys(raw, allowed_item_keys, f"{entity_type} item({action})")

    raw_line_text = _require_non_blank_str(raw.get("rawLineText"), "item.rawLineText")

    target_entity_id = raw.get("targetEntityId")

    if action == "CREATE" and not is_create_merge:
        if target_entity_id is not None:
            raise SolarUnavailableError("action=CREATE인데 targetEntityId가 있다.")
        target_entity_id = None
    elif is_create_merge:
        if not isinstance(target_entity_id, str) or not target_entity_id.strip():
            raise SolarUnavailableError("CREATE+REQUEST_ITEM인데 targetEntityId가 없다.")
        candidate = candidate_request_items.get(target_entity_id)
        if candidate is None or candidate.get("action") != "CREATE" or candidate.get("entityType") != entity_type:
            # 존재하지 않거나, 읽기 시점 후보가 CREATE가 아니거나 entityType이 다르면 SOLAR가
            # 잘못된 종류의 request item을 골랐다는 뜻 — 계약 위반(repair 대상), 409가 아니다.
            raise SolarUnavailableError("CREATE+REQUEST_ITEM 대상이 유효한 CREATE 후보가 아니다.")
    else:  # UPDATE(항상 ENTITY) 또는 DELETE(ENTITY|REQUEST_ITEM)
        if not isinstance(target_entity_id, str) or not target_entity_id.strip():
            raise SolarUnavailableError("UPDATE/DELETE인데 targetEntityId가 없다.")
        if target_kind_raw == "REQUEST_ITEM":
            candidate = candidate_request_items.get(target_entity_id)
            if candidate is None or candidate.get("entityType") != entity_type:
                raise SolarUnavailableError("REQUEST_ITEM 대상이 유효한 후보가 아니다.")
        else:
            candidates = candidate_task_ids if is_task else candidate_fixed_schedule_ids
            if target_entity_id not in candidates:
                raise SolarUnavailableError("targetEntityId가 후보 목록에 없다(할루시네이션).")

    if fixed_target_entity_id is not None and target_entity_id != fixed_target_entity_id:
        raise SolarUnavailableError("targetEntityId가 고정된 대상과 다르다.")

    normalized_payload_raw = raw.get("normalizedPayload")
    if not isinstance(normalized_payload_raw, dict):
        raise SolarUnavailableError("normalizedPayload가 dict가 아니다.")

    pending_question_raw = raw.get("pendingQuestion")
    if pending_question_raw is not None and not isinstance(pending_question_raw, dict):
        raise SolarUnavailableError("pendingQuestion이 dict가 아니다.")

    if action == "CREATE" and not is_create_merge:
        update_fields: list[str] = []
        if is_task:
            missing_fields, canonical_payload = _validate_and_normalize_task_create(
                normalized_payload_raw, raw.get("deadlineState")
            )
        else:
            missing_fields, canonical_payload = _validate_and_normalize_fixed_schedule_create(
                normalized_payload_raw
            )
        cross_check_action = "CREATE"
    elif is_create_merge:
        raw_changed_fields = raw.get("changedFields")
        allowed_field_names = _TASK_CREATE_MERGE_FIELD_NAMES if is_task else _FIXED_SCHEDULE_UPDATE_FIELD_NAMES
        if not isinstance(raw_changed_fields, list) or not raw_changed_fields:
            raise SolarUnavailableError("changedFields가 비어있거나 리스트가 아니다.")
        update_fields = []
        for field_name in raw_changed_fields:
            if not isinstance(field_name, str) or field_name not in allowed_field_names:
                _log_contract_violation("INVALID_UPDATE_FIELD_NAME", context=f"{entity_type}/CREATE_MERGE")
                raise SolarUnavailableError(
                    f"changedFields에 알 수 없는 필드가 있다: {field_name!r}", code="INVALID_UPDATE_FIELD_NAME"
                )
            update_fields.append(field_name)
        if is_task:
            missing_fields, canonical_payload = _validate_and_normalize_task_update(
                normalized_payload_raw, update_fields, raw.get("deadlineState")
            )
        else:
            missing_fields, canonical_payload = _validate_and_normalize_fixed_schedule_update(
                normalized_payload_raw, update_fields
            )
        cross_check_action = "CREATE_MERGE"
    elif action == "UPDATE":
        raw_update_fields = raw.get("updateFields")
        allowed_field_names = _TASK_UPDATE_FIELD_NAMES if is_task else _FIXED_SCHEDULE_UPDATE_FIELD_NAMES
        if not isinstance(raw_update_fields, list) or not raw_update_fields:
            raise SolarUnavailableError("updateFields가 비어있거나 리스트가 아니다.")
        update_fields = []
        for field_name in raw_update_fields:
            if not isinstance(field_name, str) or field_name not in allowed_field_names:
                # field_name은 SOLAR가 자유롭게 생성한 문자열일 수 있어 로그·code에 원문 그대로
                # 남기지 않는다(코드만 남긴다는 원칙).
                _log_contract_violation("INVALID_UPDATE_FIELD_NAME", context=f"{entity_type}/{action}")
                raise SolarUnavailableError(
                    f"updateFields에 알 수 없는 필드가 있다: {field_name!r}", code="INVALID_UPDATE_FIELD_NAME"
                )
            update_fields.append(field_name)
        if is_task:
            missing_fields, canonical_payload = _validate_and_normalize_task_update(
                normalized_payload_raw, update_fields, raw.get("deadlineState")
            )
        else:
            missing_fields, canonical_payload = _validate_and_normalize_fixed_schedule_update(
                normalized_payload_raw, update_fields
            )
        cross_check_action = "UPDATE"
    else:  # DELETE
        update_fields = []
        payload_keys = _TASK_PAYLOAD_KEYS if is_task else _FS_PAYLOAD_KEYS
        canonical_payload = _validate_delete_payload(
            normalized_payload_raw, payload_keys, f"{entity_type} normalizedPayload"
        )
        missing_fields = []
        cross_check_action = "DELETE"

    pending_question = _parse_pending_question_cross_check(
        pending_question_raw, missing_fields, entity_type, cross_check_action
    )

    resolved_target_kind = target_kind_raw if is_change_input else None

    return SolarAnalysisItem(
        entity_type=entity_type,
        action=action,
        target_entity_id=target_entity_id,
        raw_line_text=raw_line_text,
        update_fields=update_fields,
        normalized_payload=canonical_payload,
        missing_fields=missing_fields,
        pending_question=pending_question,
        target_kind=resolved_target_kind,
    )


def _parse_unresolved_line(
    raw: dict,
    *,
    analysis_mode: str,
    candidate_task_ids: set[str],
    candidate_fixed_schedule_ids: set[str],
    candidate_request_items: dict[str, dict] | None = None,
    fixed_target_kind: str | None = None,
) -> UnresolvedLine:
    """CHANGE_INPUT은 targetKind를 JSON 키로 받는다(SOLAR가 결정). 그 외 모드(UNRESOLVED_ANSWER
    포함)는 호출자가 fixed_target_kind로 이미 고정한 값을 쓴다(없으면 항상 ENTITY)."""
    candidate_request_items = candidate_request_items or {}
    is_change_input = analysis_mode == "CHANGE_INPUT"
    allowed_keys = _CHANGE_INPUT_UNRESOLVED_LINE_KEYS if is_change_input else _UNRESOLVED_LINE_KEYS
    _require_exact_keys(raw, allowed_keys, "unresolvedLine")

    raw_line_text = _require_non_blank_str(raw.get("rawLineText"), "unresolvedLine.rawLineText")

    action = raw.get("action")
    if action not in ("UPDATE", "DELETE"):
        raise SolarUnavailableError(f"unresolvedLine.action은 UPDATE/DELETE만 허용한다: {action!r}")

    entity_type = raw.get("entityType")
    if entity_type not in ("TASK", "FIXED_SCHEDULE"):
        raise SolarUnavailableError(f"unresolvedLine.entityType 값이 올바르지 않다: {entity_type!r}")

    message = _require_non_blank_str(raw.get("message"), "unresolvedLine.message")

    if is_change_input:
        target_kind = raw.get("targetKind")
        if target_kind not in ("ENTITY", "REQUEST_ITEM"):
            raise SolarUnavailableError(f"unresolvedLine.targetKind 값이 올바르지 않다: {target_kind!r}")
        if action == "UPDATE" and target_kind != "ENTITY":
            raise SolarUnavailableError("unresolvedLine의 UPDATE는 targetKind=ENTITY만 허용한다.")
    else:
        target_kind = fixed_target_kind or "ENTITY"

    if target_kind == "REQUEST_ITEM":
        matching = [
            item_id for item_id, info in candidate_request_items.items() if info.get("entityType") == entity_type
        ]
        if not matching:
            raise SolarUnavailableError("unresolvedLine의 entityType에 해당하는 REQUEST_ITEM 후보가 0개다.")
    else:
        candidates = candidate_task_ids if entity_type == "TASK" else candidate_fixed_schedule_ids
        if not candidates:
            raise SolarUnavailableError("unresolvedLine의 entityType에 해당하는 후보가 0개다.")

    return UnresolvedLine(
        raw_line_text=raw_line_text,
        action=action,
        entity_type=entity_type,
        message=message,
        target_kind=target_kind,
    )


# ---------------------------------------------------------------------------
# 공개 함수
# ---------------------------------------------------------------------------


def parse_solar_response(
    content: str,
    *,
    purpose: SolarRequestPurpose,
    candidate_task_ids: set[str],
    candidate_fixed_schedule_ids: set[str],
    analysis_mode: str = "INITIAL",
    candidate_request_items: dict[str, dict] | None = None,
    expected_action: str | None = None,
    expected_entity_type: str | None = None,
    expected_target_kind: str | None = None,
    lock_target_entity_id: str | None = None,
) -> SolarAnalysisResult:
    """SOLAR 응답 content(JSON 문자열)를 파싱·검증하는 순수 함수(DB 접근 없음, back-fill 없음).

    analysis_mode:
    - "INITIAL": 기존(#50) 동작 그대로.
    - "CHANGE_INPUT": items/unresolvedLine에 targetKind 확장(SOLAR가 item마다 결정),
      CREATE+targetKind=REQUEST_ITEM은 changedFields 병용, 한 응답 안 동일 대상 중복 조작 거부.
    - "UNRESOLVED_ANSWER"(CHANGE_DETAILS 후속 포함): items(최대 1개)/unresolvedLine/
      resolvedTargetOnly 중 정확히 하나만 허용(3-way XOR). expected_action/expected_entity_type/
      expected_target_kind로 그 item(또는 unresolvedLine)의 action/entityType/targetKind를
      호출자가 고정한다. lock_target_entity_id가 있으면(CHANGE_DETAILS 후속) unresolvedLine
      자체를 금지하고 대상을 그 id 하나로 고정한다.
    """
    candidate_request_items = candidate_request_items or {}
    try:
        raw = json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise SolarUnavailableError("SOLAR 응답이 유효한 JSON이 아니다.") from exc

    if not isinstance(raw, dict):
        raise SolarUnavailableError("SOLAR 응답 최상위가 dict가 아니다.")

    is_unresolved_answer = analysis_mode == "UNRESOLVED_ANSWER"
    top_level_keys = _UNRESOLVED_ANSWER_TOP_LEVEL_KEYS if is_unresolved_answer else _TOP_LEVEL_KEYS
    _require_exact_keys(raw, top_level_keys, "최상위")

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

    raw_resolved_target_only = None
    if is_unresolved_answer:
        raw_resolved_target_only = raw.get("resolvedTargetOnly")
        if raw_resolved_target_only is not None and not isinstance(raw_resolved_target_only, dict):
            raise SolarUnavailableError("resolvedTargetOnly가 null 또는 dict가 아니다.")

        outcomes = [bool(raw_items), raw_unresolved is not None, raw_resolved_target_only is not None]
        if sum(outcomes) != 1:
            raise SolarUnavailableError("items/unresolvedLine/resolvedTargetOnly 중 정확히 하나만 있어야 한다.")
        if lock_target_entity_id is not None and raw_unresolved is not None:
            raise SolarUnavailableError("CHANGE_DETAILS 후속 응답에는 unresolvedLine이 있으면 안 된다.")
        if len(raw_items) > 1:
            raise SolarUnavailableError("UNRESOLVED_ANSWER 응답의 items는 최대 1개여야 한다.")
    else:
        if not raw_items and raw_unresolved is None:
            raise SolarUnavailableError("items와 unresolvedLine이 모두 비어있다.")

    if analysis_mode == "INITIAL" and purpose == SolarRequestPurpose.NEW_CYCLE and raw_unresolved is not None:
        raise SolarUnavailableError("NEW_CYCLE에서는 unresolvedLine이 있으면 안 된다.")

    unresolved_line = None
    if raw_unresolved is not None:
        unresolved_line = _parse_unresolved_line(
            raw_unresolved,
            analysis_mode=analysis_mode,
            candidate_task_ids=candidate_task_ids,
            candidate_fixed_schedule_ids=candidate_fixed_schedule_ids,
            candidate_request_items=candidate_request_items,
            fixed_target_kind=expected_target_kind,
        )
        if is_unresolved_answer:
            if expected_action is not None and unresolved_line.action != expected_action:
                raise SolarUnavailableError("unresolvedLine.action이 기대한 값과 다르다.")
            if expected_entity_type is not None and unresolved_line.entity_type != expected_entity_type:
                raise SolarUnavailableError("unresolvedLine.entityType이 기대한 값과 다르다.")

    resolved_target_only = None
    if raw_resolved_target_only is not None:
        _require_exact_keys(raw_resolved_target_only, {"targetEntityId", "targetKind"}, "resolvedTargetOnly")
        rt_target_entity_id = raw_resolved_target_only.get("targetEntityId")
        rt_target_kind = raw_resolved_target_only.get("targetKind")
        if rt_target_kind not in ("ENTITY", "REQUEST_ITEM"):
            raise SolarUnavailableError(f"resolvedTargetOnly.targetKind 값이 올바르지 않다: {rt_target_kind!r}")
        if not isinstance(rt_target_entity_id, str) or not rt_target_entity_id.strip():
            raise SolarUnavailableError("resolvedTargetOnly.targetEntityId가 없다.")
        if rt_target_kind == "REQUEST_ITEM":
            candidate = candidate_request_items.get(rt_target_entity_id)
            if candidate is None or candidate.get("entityType") != expected_entity_type:
                raise SolarUnavailableError("resolvedTargetOnly 대상이 유효한 REQUEST_ITEM 후보가 아니다.")
        else:
            candidates = candidate_task_ids if expected_entity_type == "TASK" else candidate_fixed_schedule_ids
            if rt_target_entity_id not in candidates:
                raise SolarUnavailableError("resolvedTargetOnly.targetEntityId가 후보 목록에 없다.")
        if lock_target_entity_id is not None and rt_target_entity_id != lock_target_entity_id:
            raise SolarUnavailableError("resolvedTargetOnly의 대상이 고정된 대상과 다르다.")
        resolved_target_only = ResolvedTargetOnly(target_entity_id=rt_target_entity_id, target_kind=rt_target_kind)

    items = [
        _parse_item(
            raw_item,
            purpose=purpose,
            analysis_mode=analysis_mode,
            candidate_task_ids=candidate_task_ids,
            candidate_fixed_schedule_ids=candidate_fixed_schedule_ids,
            candidate_request_items=candidate_request_items,
            fixed_target_kind=expected_target_kind if is_unresolved_answer else None,
            fixed_action=expected_action if is_unresolved_answer else None,
            fixed_entity_type=expected_entity_type if is_unresolved_answer else None,
            fixed_target_entity_id=lock_target_entity_id,
        )
        for raw_item in raw_items
    ]

    if analysis_mode == "CHANGE_INPUT":
        seen_targets: set[tuple] = set()
        for item in items:
            if item.target_entity_id is not None:
                key = (item.target_kind, item.entity_type, item.target_entity_id)
                if key in seen_targets:
                    raise SolarUnavailableError("CHANGE_INPUT 응답이 같은 대상을 여러 item에서 동시에 조작한다.")
                seen_targets.add(key)

    return SolarAnalysisResult(
        analysis_message=analysis_message,
        items=items,
        unresolved_line=unresolved_line,
        resolved_target_only=resolved_target_only,
    )


def parse_card_answer_response(
    content: str, *, entity_type: str, action: str, field: str, attempt_number: int
) -> SolarCardAnswerResult:
    """CARD_ANSWER 전용 좁은 계약 파서. items[]/unresolvedLine 재사용 없이 이 카드·이 필드 하나만
    다룬다. answerDisposition은 SOLAR의 자기 보고 값을 그대로 신뢰하고, 서비스는 attemptCount
    증가 여부만 이 값으로 분기한다(필드가 missing에 남아있는지로 추론하지 않는다)."""
    try:
        raw = json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise SolarUnavailableError("SOLAR 응답이 유효한 JSON이 아니다.") from exc

    if not isinstance(raw, dict):
        raise SolarUnavailableError("SOLAR 응답 최상위가 dict가 아니다.")

    _require_exact_keys(raw, _CARD_ANSWER_TOP_LEVEL_KEYS, "최상위")

    analysis_message_raw = raw.get("analysisMessage")
    if not isinstance(analysis_message_raw, str) or not analysis_message_raw.strip():
        raise SolarUnavailableError("analysisMessage가 비어있다.")
    analysis_message = analysis_message_raw.strip()

    answer_disposition = raw.get("answerDisposition")
    if answer_disposition not in _ANSWER_DISPOSITIONS:
        raise SolarUnavailableError(f"answerDisposition 값이 올바르지 않다: {answer_disposition!r}")

    if answer_disposition == "AI_ESTIMATED":  # 방어적 — 값 집합에 원래 없지만 유사 오타 방지
        raise SolarUnavailableError("answerDisposition에 잘못된 값이 왔다.")

    pending_question_message_raw = raw.get("pendingQuestion")
    if pending_question_message_raw is not None and not isinstance(pending_question_message_raw, str):
        raise SolarUnavailableError("pendingQuestion이 문자열 또는 null이 아니다.")
    pending_question_message = (
        pending_question_message_raw.strip() if isinstance(pending_question_message_raw, str) else None
    )
    if pending_question_message == "":
        pending_question_message = None

    field_value_raw = raw.get("fieldValue")
    if field_value_raw is not None and not isinstance(field_value_raw, dict):
        raise SolarUnavailableError("fieldValue가 dict 또는 null이 아니다.")

    field_value: dict | None = None
    if answer_disposition == "PROVIDED":
        if not isinstance(field_value_raw, dict):
            raise SolarUnavailableError("answerDisposition=PROVIDED인데 fieldValue가 없다.")
        field_value = _validate_card_answer_field_value(
            field_value_raw, entity_type=entity_type, action=action, field=field, attempt_number=attempt_number
        )
        if pending_question_message is not None:
            raise SolarUnavailableError("answerDisposition=PROVIDED인데 pendingQuestion이 있다.")
    else:  # DONT_KNOW | UNCLEAR
        if field_value_raw is not None:
            raise SolarUnavailableError("answerDisposition이 PROVIDED가 아닌데 fieldValue가 있다.")
        if not pending_question_message:
            raise SolarUnavailableError("answerDisposition이 PROVIDED가 아니면 pendingQuestion이 필요하다.")

    return SolarCardAnswerResult(
        analysis_message=analysis_message,
        answer_disposition=answer_disposition,
        pending_question_message=pending_question_message,
        field_value=field_value,
    )


def _validate_card_answer_field_value(
    raw: dict, *, entity_type: str, action: str, field: str, attempt_number: int
) -> dict:
    """CARD_ANSWER의 fieldValue는 그 필드 하나만 담는 좁은 dict. 기존 create/update validator를
    필드 단위로 재사용하지 않고(그것들은 카드 전체 payload를 기대) 여기서 직접 검증한다 —
    필드별 형태가 단순해 별도 좁은 계약을 유지하는 편이 기존 코드를 왜곡하지 않는다."""
    if field == "title":
        _require_exact_keys(raw, {"title"}, "fieldValue(title)")
        title = raw.get("title")
        if not isinstance(title, str) or not title.strip():
            raise SolarUnavailableError("fieldValue.title이 비어있다.")
        return {"title": title.strip()}

    if field == "deadlineAt":
        _require_exact_keys(raw, {"deadlineState", "deadlineAt"}, "fieldValue(deadlineAt)")
        deadline_state = raw.get("deadlineState")
        if deadline_state not in ("KNOWN", "NONE"):
            raise SolarUnavailableError(f"fieldValue.deadlineState 값이 올바르지 않다: {deadline_state!r}")
        deadline_at = raw.get("deadlineAt")
        if deadline_state == "KNOWN":
            deadline_at = _require_rfc3339(deadline_at, "fieldValue.deadlineAt")
        else:
            if deadline_at is not None:
                raise SolarUnavailableError("deadlineState=NONE인데 deadlineAt이 null이 아니다.")
        return {"deadlineState": deadline_state, "deadlineAt": deadline_at}

    if field in ("estimatedMinutes", "remainingMinutes"):
        keys = {field, "estimatedMinutesSource"} if field == "estimatedMinutes" else {field}
        _require_exact_keys(raw, keys, f"fieldValue({field})")
        value = raw.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise SolarUnavailableError(f"fieldValue.{field}가 0 이상의 정수가 아니다.")
        result = {field: value}
        if field == "estimatedMinutes":
            source = raw.get("estimatedMinutesSource")
            if source not in ("USER", "AI_ESTIMATED"):
                raise SolarUnavailableError(f"fieldValue.estimatedMinutesSource 값이 올바르지 않다: {source!r}")
            if attempt_number == 1 and source == "AI_ESTIMATED":
                raise SolarUnavailableError("1차 답변에서는 estimatedMinutesSource=AI_ESTIMATED일 수 없다.")
            result["estimatedMinutesSource"] = source
        return result

    if field == "amount":
        _require_exact_keys(raw, {"amountText", "amountSource"}, "fieldValue(amount)")
        amount_source = raw.get("amountSource")
        if amount_source not in ("USER", "AI_ESTIMATED", "UNKNOWN"):
            raise SolarUnavailableError(f"fieldValue.amountSource 값이 올바르지 않다: {amount_source!r}")
        amount_text = raw.get("amountText")
        if amount_source == "UNKNOWN":
            if amount_text is not None:
                raise SolarUnavailableError("amountSource=UNKNOWN인데 amountText가 null이 아니다.")
        else:
            if not isinstance(amount_text, str) or not amount_text.strip():
                raise SolarUnavailableError("amountSource가 USER/AI_ESTIMATED인데 amountText가 없다.")
            amount_text = amount_text.strip()
        return {"amountText": amount_text, "amountSource": amount_source}

    if field in ("startAt", "endAt"):
        # startAt/endAt은 missing_order상 독립 필드로 하나씩 질문·답변된다. 둘 사이의
        # endAt>startAt 교차검증은 두 값이 모두 확정된 카드 전체 payload merge 시점(서비스
        # 계층)에서 하며, 이 좁은 fieldValue 단계에서는 하지 않는다.
        _require_exact_keys(raw, {field}, f"fieldValue({field})")
        value = _require_rfc3339(raw.get(field), f"fieldValue.{field}")
        return {field: value}

    raise SolarUnavailableError(f"알 수 없는 field: {field!r}")


# ---------------------------------------------------------------------------
# canonicalization — strict parser 앞단에서 좁은 whitelist 조건에만 정확히 일치하는 값을
# 정규화한다. 아래 조건들 밖의 값은 절대 임의로 보정하지 않는다(fuzzy mapping 금지).
# Issue #66 CHANGE_INPUT 실제 API smoke test에서 관측된 3가지 위반(TASK CREATE+REQUEST_ITEM
# merge item의 deadlineState 키 누락, 새 CREATE의 불필요한 targetEntityId, TASK
# normalizedPayload의 remainingMinutes 키 누락)에 대해서만 추가로 좁게 정규화한다 — strict
# parser의 검증 로직 자체는 이 3가지를 포함해 어디에서도 완화하지 않는다.
# ---------------------------------------------------------------------------


def _canonicalize_amount_missing_sentinel(payload: dict) -> None:
    """amountSource="MISSING"이고 amountText가 null/공백이면 둘 다 null로 정규화한다.

    amountSource의 유효값은 null/USER/AI_ESTIMATED/UNKNOWN뿐이라 "MISSING"은 원래 항상
    계약 위반이다 — deadlineState의 "MISSING"과 혼동한 것으로 추정되는, 실제로 관측된 실패
    유형 하나를 그대로 흡수한다.
    """
    if payload.get("amountSource") != "MISSING":
        return
    amount_text = payload.get("amountText")
    if amount_text is None or (isinstance(amount_text, str) and not amount_text.strip()):
        payload["amountSource"] = None
        payload["amountText"] = None


def _canonicalize_untouched_deadline_state(item: dict) -> None:
    """TASK UPDATE에서 deadlineAt이 updateFields에 없으면 deadlineState=MISSING,
    normalizedPayload.deadlineAt=null로 정규화한다(그 필드는 "안 건드림" 규칙상 이 값만 유효하다).

    deadlineAt이 updateFields에 있는 경우는 절대 건드리지 않는다 — 그 경우 새 값을 추측할
    안전한 근거가 없어 이 정규화 대상이 아니다(strict parser·repair로 넘긴다).
    """
    update_fields = item.get("updateFields")
    if not isinstance(update_fields, list) or "deadlineAt" in update_fields:
        return
    payload = item.get("normalizedPayload")
    if not isinstance(payload, dict):
        return
    item["deadlineState"] = "MISSING"
    payload["deadlineAt"] = None


def _canonicalize_update_field_amount_text_alias(item: dict) -> None:
    """TASK UPDATE의 updateFields 항목 중 "amountText"는 정확한 이름인 "amount"로만
    정규화한다(그 외 필드 이름은 손대지 않는다). 중복 방지를 위해 이미 "amount"가 있으면
    합친다."""
    update_fields = item.get("updateFields")
    if not isinstance(update_fields, list) or "amountText" not in update_fields:
        return
    canonical: list = []
    seen: set = set()
    for field_name in update_fields:
        name = "amount" if field_name == "amountText" else field_name
        if name not in seen:
            canonical.append(name)
            seen.add(name)
    item["updateFields"] = canonical


def _canonicalize_missing_deadline_state_for_create_merge(item: dict) -> None:
    """CHANGE_INPUT의 CREATE+REQUEST_ITEM merge item(changedFields가 있는 CREATE)에서
    deadlineState 키 자체가 없고, deadlineAt이 changedFields에 없어(이번에 안 건드림)
    normalizedPayload.deadlineAt도 이미 null인 경우에만 deadlineState="MISSING"을 채운다.

    deadlineState 키가 이미 있으면(값이 잘못됐더라도) 절대 건드리지 않는다 — 그건 strict
    parser·repair 대상이다. deadlineAt이 changedFields에 있으면(사용자가 실제로 마감을
    바꾸려는 의도) 새 값을 추측할 안전한 근거가 없어 역시 건드리지 않는다.
    """
    if item.get("action") != "CREATE":
        return
    if "deadlineState" in item:
        return
    changed_fields = item.get("changedFields")
    if not isinstance(changed_fields, list) or "deadlineAt" in changed_fields:
        return
    payload = item.get("normalizedPayload")
    if not isinstance(payload, dict) or payload.get("deadlineAt") is not None:
        return
    item["deadlineState"] = "MISSING"


def _canonicalize_new_create_target_entity_id(item: dict) -> None:
    """CHANGE_INPUT의 완전히 새로운 CREATE(targetKind가 없거나 null이고 changedFields도 없어
    REQUEST_ITEM 수정 의도를 나타내는 키가 전혀 없는 경우)인데 targetEntityId가 불필요하게
    채워져 있으면 null로 정규화한다.

    targetKind="REQUEST_ITEM"이거나 changedFields 키가 있으면(REQUEST_ITEM 수정 의도가 있을
    수 있으면) 절대 건드리지 않는다 — canonicalization은 candidateRequestItems 후보 목록에
    접근할 수 없어 그 targetEntityId가 실제 후보와 연결되는지 스스로 판단할 수 없으므로, 이런
    신호가 조금이라도 있으면 strict parser·repair 대상으로 남긴다.
    """
    if item.get("action") != "CREATE":
        return
    if item.get("targetKind") is not None:
        return
    if "changedFields" in item:
        return
    if item.get("targetEntityId") is None:
        return
    item["targetEntityId"] = None


def _canonicalize_missing_remaining_minutes(item: dict) -> None:
    """TASK item(CREATE 또는 UPDATE)의 normalizedPayload에 remainingMinutes 키 자체가 없을
    때만 null로 채운다.

    CREATE(신규든 REQUEST_ITEM merge든)는 remainingMinutes가 서버가 항상 estimatedMinutes에서
    다시 계산해 덮어쓰는 파생값이라 무조건 null로 채워도 안전하다. UPDATE는 remainingMinutes가
    updateFields에 없을 때(이번 요청에서 안 건드림)만 null로 채우고, updateFields에 있는데
    (실제로 값을 바꾸려는데) 키 자체가 없으면 새 값을 추측할 근거가 없어 계약 위반으로 남긴다.
    """
    action = item.get("action")
    if action not in ("CREATE", "UPDATE"):
        return
    payload = item.get("normalizedPayload")
    if not isinstance(payload, dict) or "remainingMinutes" in payload:
        return
    if action == "UPDATE":
        update_fields = item.get("updateFields")
        if not isinstance(update_fields, list) or "remainingMinutes" in update_fields:
            return
    payload["remainingMinutes"] = None


def _canonicalize_response_dict(raw: dict) -> dict:
    items = raw.get("items")
    if not isinstance(items, list):
        return raw
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("entityType") != "TASK":
            continue
        payload = item.get("normalizedPayload")
        if isinstance(payload, dict):
            _canonicalize_amount_missing_sentinel(payload)
        if item.get("action") == "UPDATE":
            _canonicalize_untouched_deadline_state(item)
            _canonicalize_update_field_amount_text_alias(item)
        elif item.get("action") == "CREATE":
            _canonicalize_missing_deadline_state_for_create_merge(item)
            _canonicalize_new_create_target_entity_id(item)
        _canonicalize_missing_remaining_minutes(item)
    return raw


def _canonicalize_response_content(content: str) -> str:
    """strict parser에 넘기기 전 좁은 whitelist 조건들만 정규화하는 pre-pass.

    JSON이 아니거나 최상위가 dict가 아니면 그대로 반환해 `parse_solar_response`가 원래
    에러를 내도록 둔다(canonicalization이 파싱 자체를 대신하지 않는다). 정의된 조건들 밖의
    값은 이 함수도, 이 함수가 호출하는 어떤 헬퍼도 보정하지 않는다.
    """
    try:
        raw = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return content
    if not isinstance(raw, dict):
        return content
    canonicalized = _canonicalize_response_dict(raw)
    return json.dumps(canonicalized, ensure_ascii=False)


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
        f" \"now\" 기준 Asia/Seoul로 해석):\n{json.dumps(context, ensure_ascii=False)}\n\n"
        "[action별 필수 키 재확인 — 반드시 지키세요]\n"
        "- TASK CREATE: deadlineState 필수(KNOWN/NONE/MISSING 중 하나). updateFields는 포함하지"
        " 않습니다.\n"
        "- TASK UPDATE: deadlineState와 updateFields 둘 다 필수(updateFields는 빈 배열 금지).\n"
        "- TASK DELETE: deadlineState와 updateFields 둘 다 절대 포함하지 마세요(있으면 응답 전체"
        " 거부).\n"
        "- FIXED_SCHEDULE: CREATE/UPDATE/DELETE 어떤 action이든 deadlineState를 절대 포함하지"
        " 마세요(TASK 전용 키입니다).\n\n"
        "[응답 전 self-check — 응답을 만들기 직전 아래 5가지를 순서대로 다시 확인하세요]\n"
        "1. 각 item의 missing 필드를 서버 계산 순서로 다시 계산하세요: TASK CREATE는"
        " deadlineAt→estimatedMinutes→amount 순, TASK UPDATE는 updateFields에 포함된 필드만"
        " title→deadlineAt→estimatedMinutes→remainingMinutes→amount 순, FIXED_SCHEDULE은"
        " title→startAt→endAt 순으로 이 중 이 카드에서 가장 먼저 등장하는 missing 필드가"
        " 무엇인지 확인하세요.\n"
        "2. missing 필드가 하나라도 있으면 pendingQuestion.field는 반드시 1번에서 찾은 첫 번째"
        " missing 필드와 정확히 같은 문자열이어야 합니다(다른 필드를 질문하면 응답 전체가"
        " 거부됩니다).\n"
        "3. missing 필드가 하나도 없으면(카드가 이미 완전하면) pendingQuestion은 반드시 null"
        "이어야 합니다.\n"
        "4. TASK CREATE/UPDATE item이라면 deadlineState 키가 실제로 존재하는지 다시"
        " 확인하세요(빠뜨리면 응답 전체가 거부됩니다).\n"
        "5. 모든 item/normalizedPayload/unresolvedLine이 위에서 정의한 키 집합과 정확히"
        " 일치하는지(정의되지 않은 키 추가 금지, 필수 키 누락 금지) 다시 확인하세요.\n\n"
        "[예시 1 — CREATE, missing 필드가 여러 개여도 첫 번째 필드만 질문]\n"
        "입력 예: \"수학 숙제 해야 해\"(마감·예상 시간·분량을 모두 모름). 이 경우"
        " estimatedMinutes와 amount도 missing이지만 순서상 deadlineAt이 가장 먼저이므로"
        " pendingQuestion은 deadlineAt만 묻습니다.\n"
        "{\"entityType\": \"TASK\", \"action\": \"CREATE\", \"targetEntityId\": null,"
        " \"rawLineText\": \"수학 숙제 해야 해\", \"deadlineState\": \"MISSING\","
        " \"normalizedPayload\": {\"title\": \"수학 숙제\", \"deadlineAt\": null,"
        " \"estimatedMinutes\": null, \"estimatedMinutesSource\": null,"
        " \"remainingMinutes\": null, \"amountText\": null, \"amountSource\": null},"
        " \"pendingQuestion\": {\"field\": \"deadlineAt\", \"message\": \"마감이 언제인가요?\"}}\n\n"
        "[예시 2 — UPDATE, deadlineAt을 바꾸지 않아도 deadlineState 키는 항상 포함]\n"
        "입력 예: \"수학 숙제 남은 시간을 30분으로 바꿔줘\"(마감은 그대로 둠, candidateTasks의"
        " 기존 id를 사용). deadlineAt은 updateFields에 없어 값은 null이지만 deadlineState 키"
        " 자체는 빠뜨리지 않고 \"MISSING\"으로 반드시 포함합니다.\n"
        "{\"entityType\": \"TASK\", \"action\": \"UPDATE\", \"targetEntityId\": \"<후보 id>\","
        " \"rawLineText\": \"수학 숙제 남은 시간을 30분으로 바꿔줘\", \"deadlineState\": \"MISSING\","
        " \"updateFields\": [\"remainingMinutes\"], \"normalizedPayload\": {\"title\": null,"
        " \"deadlineAt\": null, \"estimatedMinutes\": null, \"estimatedMinutesSource\": null,"
        " \"remainingMinutes\": 30, \"amountText\": null, \"amountSource\": null},"
        " \"pendingQuestion\": null}"
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


def _build_change_input_repair_context(content: str, violation: SolarUnavailableError) -> str:
    """Return schema-only repair facts. Never include IDs, user text, or payload values."""
    facts = [f"safe violation code: {violation.code}"]
    try:
        raw = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return "\n".join([*facts, "top-level response must be a JSON object"])
    if not isinstance(raw, dict):
        return "\n".join([*facts, f"actual top-level type: {type(raw).__name__}"])
    facts.append(f"expected top-level exact keys: {sorted(_CHANGE_INPUT_TOP_LEVEL_KEYS)}")
    facts.append(f"actual top-level keys: {sorted(raw)}")
    operations = raw.get("operations")
    unresolved = raw.get("unresolvedOperation")
    if isinstance(operations, list) and operations:
        operation = operations[0]
        facts.append("operation index: 0")
        if isinstance(operation, dict):
            operation_type = operation.get("operationType")
            facts.append(f"operationType: {operation_type if isinstance(operation_type, str) else 'invalid type'}")
            key_sets = {
                "ADD": _CHANGE_ADD_KEYS,
                "PATCH_REQUEST_ITEM": _CHANGE_PATCH_ITEM_KEYS,
                "DELETE_REQUEST_ITEM": _CHANGE_DELETE_ITEM_KEYS,
                "UPDATE_ENTITY": _CHANGE_UPDATE_ENTITY_KEYS,
                "DELETE_ENTITY": _CHANGE_DELETE_ENTITY_KEYS,
            }
            expected_keys = key_sets.get(operation_type)
            if expected_keys is not None:
                facts.append(f"expected exact keys: {sorted(expected_keys)}")
            facts.append(f"actual keys: {sorted(operation)}")
            entity_type = operation.get("entityType")
            if operation_type == "PATCH_REQUEST_ITEM":
                mapping = _CHANGE_TASK_FIELD_KEYS if entity_type == "TASK" else _CHANGE_FS_FIELD_KEYS
                facts.append("candidate namespace: REQUEST_ITEM")
                fields = operation.get("changedFields")
            elif operation_type == "UPDATE_ENTITY":
                mapping = _CHANGE_TASK_ENTITY_FIELD_KEYS if entity_type == "TASK" else _CHANGE_FS_FIELD_KEYS
                facts.append("candidate namespace: ENTITY")
                fields = operation.get("updateFields")
            else:
                mapping = None
                fields = None
            if mapping is not None:
                facts.append(f"allowed logical fields: {sorted(mapping)}")
                if isinstance(fields, list):
                    safe_fields = [field for field in fields if isinstance(field, str)]
                    facts.append(f"actual logical fields: {safe_fields}")
                    if safe_fields and all(field in mapping for field in safe_fields):
                        required = sorted(set().union(*(mapping[field] for field in safe_fields)))
                        facts.append(f"required patch storage keys: {required}")
                    else:
                        facts.append("required patch storage keys: derive only after removing invalid logical fields")
            if operation_type == "ADD":
                facts.append("ADD rule: unresolvedOperation must be null; requestItemId and targetEntityId are forbidden")
            if operation_type in ("DELETE_REQUEST_ITEM", "DELETE_ENTITY"):
                facts.append("DELETE rule: emit exactly the three expected keys and no others")
    elif isinstance(unresolved, dict):
        facts.extend([
            "operation index: none (unresolvedOperation branch)",
            f"unresolved exact keys: {sorted(_CHANGE_UNRESOLVED_KEYS)}",
            f"actual unresolved keys: {sorted(unresolved)}",
            f"intendedOperation enum: {unresolved.get('intendedOperation') if isinstance(unresolved.get('intendedOperation'), str) else 'invalid type'}",
            f"targetKind enum: {unresolved.get('targetKind') if isinstance(unresolved.get('targetKind'), str) else 'invalid type'}",
            "allowed unresolved pairs: PATCH_REQUEST_ITEM+REQUEST_ITEM, DELETE_REQUEST_ITEM+REQUEST_ITEM, UPDATE_ENTITY+ENTITY, DELETE_ENTITY+ENTITY",
            "ADD rule: ADD is never unresolved; return an ADD operation even when fields are missing",
        ])
    return "\n".join(facts)


def _build_repair_messages(
    original_messages: list[dict],
    first_response_content: str,
    violation_code: str,
    *,
    change_input_context: str | None = None,
) -> list[dict]:
    """기존 대화 컨텍스트(system+user) + 직전 응답 + 교정 요청 한 턴으로 repair 프롬프트를
    만든다. `violation_code`는 우리 스키마 키 이름·정적 문자열로만 구성돼 SOLAR가 자유
    생성했을 수 있는 원문은 담지 않는다."""
    repair_instruction = (
        "직전 응답이 JSON 계약을 위반했습니다(위반 코드: "
        f"{violation_code}). 위 system 지침(특히 action별 필수 키 표와 응답 전 self-check"
        " 규칙)을 다시 확인하고, 직전 응답을 완전히 대체하는 올바른 JSON 하나만 다시"
        " 출력하세요. 설명·마크다운·코드블록 없이 JSON 객체만 응답하세요."
    )
    if change_input_context is not None:
        repair_instruction = (
            "Rewrite the entire JSON object from scratch. Do not copy the previous operation selection unchanged. "
            "Return JSON only, with no prose, markdown, or code fence. analysisMessage must be a nonblank string. "
            "Use the exact top-level keys analysisMessage, operations, unresolvedOperation. Re-run SECTION 1 "
            "DECIDE OPERATION before building JSON; do not preserve a previous unresolved choice. Apply the "
            "logical-to-storage mapping, candidate namespace rules, and exact key sets. A clear request-item "
            "deletion with one matching REQUEST_ITEM candidate must remain DELETE_REQUEST_ITEM. Do not change "
            "deletion intent into ADD, PATCH_REQUEST_ITEM, or UPDATE_ENTITY. Rewrite DELETE_REQUEST_ITEM with "
            "exactly operationType, requestItemId, entityType. Remove pendingQuestion and every other extra key. "
            "For ADD, unresolvedOperation is forbidden. For DELETE, every key beyond its exact three keys is forbidden.\n"
            f"SAFE CONTRACT CONTEXT (contains no user values or IDs):\n{change_input_context}"
        )
    return [
        *original_messages,
        {"role": "assistant", "content": first_response_content},
        {"role": "user", "content": repair_instruction},
    ]


def _call_and_parse_with_repair(
    messages: list[dict],
    parse_fn: Callable[[str], _T],
    *,
    canonicalize_fn: Callable[[str], str] = _canonicalize_response_content,
    repair_context_fn: Callable[[str, SolarUnavailableError], str] | None = None,
) -> _T:
    """`call_solar` → canonicalize → `parse_fn` → (계약 위반 시) 최대 1회 repair → canonicalize →
    `parse_fn` 순서를 모든 analyze_* 진입점이 공유하는 helper. `call_solar`는 이 함수 안에서
    최대 2회(원본 1회 + repair 1회)만 호출된다. timeout·HTTP 오류 등 전송 계층 오류는
    `call_solar`에서 즉시 전파되며 repair 대상이 아니다. repair 응답도 반드시 같은
    canonicalize + `parse_fn`을 다시 통과해야 하며, 그래도 실패하면 예외가 그대로 전파돼(저장
    없이) 호출자가 503으로 매핑한다."""
    content = call_solar({"messages": messages})
    canonical_content = canonicalize_fn(content)
    try:
        return parse_fn(canonical_content)
    except SolarUnavailableError as first_violation:
        violation_code = first_violation.code
        repair_context = repair_context_fn(content, first_violation) if repair_context_fn is not None else None

    logger.warning("SOLAR_REPAIR_ATTEMPT code=%s", violation_code)
    repair_messages = _build_repair_messages(
        messages, content, violation_code, change_input_context=repair_context
    )
    repair_content = call_solar({"messages": repair_messages})
    canonical_repair_content = canonicalize_fn(repair_content)
    return parse_fn(canonical_repair_content)


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
    """`call_solar` → canonicalize → `parse_solar_response` 순서로 호출하는 INITIAL 분석 진입점
    (전부 동기). 서비스 계층은 이 함수 하나만 호출·mock한다. repair 규칙은
    `_call_and_parse_with_repair` 참고."""
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
    candidate_task_ids = {str(candidate["id"]) for candidate in candidate_tasks}
    candidate_fixed_schedule_ids = {str(candidate["id"]) for candidate in candidate_fixed_schedules}

    def _parse(content: str) -> SolarAnalysisResult:
        return parse_solar_response(
            content,
            purpose=purpose,
            candidate_task_ids=candidate_task_ids,
            candidate_fixed_schedule_ids=candidate_fixed_schedule_ids,
        )

    return _call_and_parse_with_repair(messages, _parse)


def _build_card_answer_prompt_messages(
    message: str,
    *,
    now: datetime,
    entity_type: str,
    action: str,
    field: str,
    question_message: str,
    attempt_number: int,
    card_context: dict,
) -> list[dict]:
    context = {
        "now": now.astimezone(_SEOUL_TZ).isoformat(),
        "entityType": entity_type,
        "action": action,
        "field": field,
        "questionAsked": question_message,
        "attemptNumber": attempt_number,
        "cardContext": card_context,
    }
    system_prompt = (
        "당신은 '이음' 서비스에서 하나의 카드의 특정 필드 하나에 대한 사용자의 답변을 해석하는"
        " 분석기입니다. 반드시 아래 JSON 스키마 하나로만 응답하고 다른 설명·마크다운·코드블록을"
        " 절대 덧붙이지 마세요.\n\n"
        "최상위 키는 정확히 analysisMessage, answerDisposition, pendingQuestion, fieldValue"
        " 네 개만 포함해야 합니다.\n"
        "- analysisMessage: 사용자에게 보여줄 한국어 안내 문장(공백 아님).\n"
        "- answerDisposition: \"PROVIDED\"(값을 확정할 수 있음) | \"DONT_KNOW\"(사용자가 모른다고"
        " 답하거나 AI가 대신 추정해야 함) | \"UNCLEAR\"(답변이 이 질문과 무관하거나 이해할 수"
        " 없음) 중 하나입니다.\n"
        "- answerDisposition=\"PROVIDED\"면 fieldValue를 반드시 채우고 pendingQuestion은 반드시"
        " null입니다.\n"
        "- answerDisposition이 \"DONT_KNOW\"/\"UNCLEAR\"면 fieldValue는 반드시 null이고"
        " pendingQuestion에 다시 물어볼 한국어 질문 문장을 채웁니다(빈 문자열 금지).\n\n"
        f"[이 카드/필드 컨텍스트]\n{json.dumps(context, ensure_ascii=False)}\n\n"
        "[field별 fieldValue 형태 — answerDisposition=\"PROVIDED\"일 때만]\n"
        "- title: {\"title\": \"<문자열>\"}\n"
        "- deadlineAt: {\"deadlineState\": \"KNOWN\"|\"NONE\", \"deadlineAt\": deadlineState="
        "\"KNOWN\"이면 timezone 포함 RFC 3339 문자열, \"NONE\"이면 null}\n"
        "- estimatedMinutes: {\"estimatedMinutes\": 0 이상 정수, \"estimatedMinutesSource\":"
        " \"USER\"|\"AI_ESTIMATED\"}."
        + (
            " attemptNumber=1이므로 estimatedMinutesSource는 반드시 \"USER\"여야 합니다(1차 답변은"
            " AI 추정일 수 없음)."
            if attempt_number == 1
            else ""
        )
        + "\n"
        "- remainingMinutes: {\"remainingMinutes\": 0 이상 정수}\n"
        "- amount: {\"amountText\": \"<문자열>\"(amountSource=\"UNKNOWN\"이면 null),"
        " \"amountSource\": \"USER\"|\"AI_ESTIMATED\"|\"UNKNOWN\"}\n"
        "- startAt: {\"startAt\": RFC3339 문자열}, endAt: {\"endAt\": RFC3339 문자열}(그 필드"
        " 하나만, 서로 섞지 마세요)\n\n"
        "사용자의 답변이 질문과 전혀 무관하거나 새로운 다른 요청으로 보이면"
        " answerDisposition=\"UNCLEAR\"로 응답하고 pendingQuestion에 원래 질문을 다시 안내하세요."
        " 값을 모른다고 답하면 answerDisposition=\"DONT_KNOW\"로 응답하세요."
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": message},
    ]


def analyze_card_answer(
    message: str,
    *,
    now: datetime,
    entity_type: str,
    action: str,
    field: str,
    question_message: str,
    attempt_number: int,
    card_context: dict | None = None,
) -> SolarCardAnswerResult:
    """CARD_ANSWER 전용 진입점 — items[]/unresolvedLine을 재사용하지 않는 좁은 계약."""
    card_context = card_context or {}
    messages = _build_card_answer_prompt_messages(
        message,
        now=now,
        entity_type=entity_type,
        action=action,
        field=field,
        question_message=question_message,
        attempt_number=attempt_number,
        card_context=card_context,
    )

    def _parse(content: str) -> SolarCardAnswerResult:
        return parse_card_answer_response(
            content, entity_type=entity_type, action=action, field=field, attempt_number=attempt_number
        )

    return _call_and_parse_with_repair(messages, _parse)


def _build_unresolved_answer_prompt_messages(
    message: str,
    *,
    now: datetime,
    expected_action: str,
    expected_entity_type: str,
    expected_target_kind: str,
    original_raw_line_text: str,
    candidates: list[dict],
) -> list[dict]:
    context = {
        "now": now.astimezone(_SEOUL_TZ).isoformat(),
        "expectedAction": expected_action,
        "expectedEntityType": expected_entity_type,
        "expectedTargetKind": expected_target_kind,
        "originalReference": original_raw_line_text,
        "candidates": candidates,
    }
    system_prompt = (
        "당신은 '이음' 서비스에서 이전에 대상을 하나로 특정하지 못했던 참조에 대한 사용자의"
        " 후속 답변을 해석하는 분석기입니다. 반드시 아래 JSON 스키마 하나로만 응답하세요.\n\n"
        "최상위 키는 정확히 analysisMessage, items, unresolvedLine, resolvedTargetOnly 네 개만"
        " 포함합니다. items(원소 정확히 1개인 배열)/unresolvedLine/resolvedTargetOnly 중"
        " 정확히 하나만 값이 있고, 값이 없는 나머지는 각각 빈 배열([])/null/null이어야 합니다.\n"
        "- items에 1개를 채우는 경우: 대상이 확정됐고 무엇을 어떻게 바꿀지(또는 삭제할지)까지"
        " 이번 답변에서 알 수 있을 때만입니다. entityType은 반드시"
        f" \"{expected_entity_type}\", action은 반드시 \"{expected_action}\"이어야 합니다."
        " targetEntityId는 candidates 중 하나의 id와 정확히 같아야 합니다. 그 외 필드는 기존"
        " CREATE/UPDATE/DELETE item 규칙을 그대로 따릅니다(updateFields/normalizedPayload/"
        " deadlineState/pendingQuestion 등).\n"
        "- resolvedTargetOnly를 채우는 경우: 어떤 대상을 가리키는지는 이번 답변으로 확정됐지만"
        " 무엇을 바꿀지는 이 답변만으로는 아직 알 수 없을 때입니다. 정확히"
        " {\"targetEntityId\": \"<candidates 중 하나의 id>\", \"targetKind\":"
        f" \"{expected_target_kind}\"}}만 채우세요.\n"
        "- unresolvedLine을 채우는 경우: 이 답변으로도 여전히 어떤 대상인지 하나로 특정할 수"
        " 없을 때입니다. entityType/action은 위와 동일하게 고정하고 message에 다시 확인할"
        " 한국어 질문을 채우세요.\n\n"
        f"[컨텍스트]\n{json.dumps(context, ensure_ascii=False)}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": message},
    ]


def analyze_unresolved_answer(
    message: str,
    *,
    now: datetime,
    purpose: SolarRequestPurpose,
    expected_action: str,
    expected_entity_type: str,
    expected_target_kind: str,
    original_raw_line_text: str,
    candidate_tasks: list[dict] | None = None,
    candidate_fixed_schedules: list[dict] | None = None,
    candidate_request_items: dict[str, dict] | None = None,
    lock_target_entity_id: str | None = None,
) -> SolarAnalysisResult:
    """UNRESOLVED_ANSWER 전용 진입점. `candidate_request_items`의 값 dict는 최소한
    entityType/action 키를 포함해야 한다(파서 검증용). `lock_target_entity_id`가 있으면
    CHANGE_DETAILS 후속 답변 — 대상 하나로 고정하고 unresolvedLine을 금지한다."""
    candidate_tasks = candidate_tasks or []
    candidate_fixed_schedules = candidate_fixed_schedules or []
    candidate_request_items = candidate_request_items or {}

    if expected_target_kind == "REQUEST_ITEM":
        prompt_candidates = [{"id": item_id, **info} for item_id, info in candidate_request_items.items()]
    else:
        prompt_candidates = candidate_tasks if expected_entity_type == "TASK" else candidate_fixed_schedules

    messages = _build_unresolved_answer_prompt_messages(
        message,
        now=now,
        expected_action=expected_action,
        expected_entity_type=expected_entity_type,
        expected_target_kind=expected_target_kind,
        original_raw_line_text=original_raw_line_text,
        candidates=prompt_candidates,
    )
    candidate_task_ids = {str(c["id"]) for c in candidate_tasks}
    candidate_fixed_schedule_ids = {str(c["id"]) for c in candidate_fixed_schedules}

    def _parse(content: str) -> SolarAnalysisResult:
        return parse_solar_response(
            content,
            purpose=purpose,
            candidate_task_ids=candidate_task_ids,
            candidate_fixed_schedule_ids=candidate_fixed_schedule_ids,
            analysis_mode="UNRESOLVED_ANSWER",
            candidate_request_items=candidate_request_items,
            expected_action=expected_action,
            expected_entity_type=expected_entity_type,
            expected_target_kind=expected_target_kind,
            lock_target_entity_id=lock_target_entity_id,
        )

    return _call_and_parse_with_repair(messages, _parse)


def _build_change_input_prompt_messages(
    message: str,
    *,
    now: datetime,
    cycle_start,
    cycle_end,
    candidate_tasks: list[dict],
    candidate_fixed_schedules: list[dict],
    candidate_request_items: list[dict],
) -> list[dict]:
    context = {
        "now": now.astimezone(_SEOUL_TZ).isoformat(),
        "cycleStart": cycle_start.isoformat() if cycle_start is not None else None,
        "cycleEnd": cycle_end.isoformat() if cycle_end is not None else None,
        "candidateTasks": candidate_tasks,
        "candidateFixedSchedules": candidate_fixed_schedules,
        "candidateRequestItems": candidate_request_items,
    }
    system_prompt = (
        "당신은 '이음' 서비스에서 사용자가 이번 계획 요청 전체를 자유롭게 다시 편집하는 발화를"
        " 분석하는 분석기입니다. 반드시 아래 JSON 스키마 하나로만 응답하세요.\n\n"
        "최상위 키는 정확히 analysisMessage, items, unresolvedLine 세 개만 포함합니다. 각 item은"
        " entityType, action, targetEntityId, targetKind, rawLineText, pendingQuestion을"
        " 포함하고, targetKind는 \"ENTITY\"(실제 존재하는 TASK/FIXED_SCHEDULE) 또는"
        " \"REQUEST_ITEM\"(이번 요청에서 아직 실행되지 않은 대기 중인 카드, candidateRequestItems"
        " 중 하나) 중 하나입니다.\n"
        "- action=\"CREATE\"+targetKind=\"REQUEST_ITEM\": candidateRequestItems 중 action이"
        " 정확히 \"CREATE\"인 카드를 골라 일부 필드만 바꿀 때 씁니다. targetEntityId는 그 카드의"
        " id, changedFields는 이번에 실제로 바꾸는 필드 이름 배열(빈 배열 금지, remainingMinutes"
        " 포함 불가), normalizedPayload는 changedFields에 있는 필드만 값을 채우고 나머지는 기존"
        " UPDATE 규칙처럼 null/deadlineState=MISSING으로 둡니다.\n"
        "- action=\"CREATE\"이고 targetKind가 없거나 null: 완전히 새로운 카드를 추가합니다(기존"
        " CREATE와 동일한 필수 키, normalizedPayload/deadlineState 사용).\n"
        "- action=\"UPDATE\": targetKind는 반드시 \"ENTITY\"입니다(실제 항목만 직접 수정,"
        " updateFields/normalizedPayload/deadlineState 사용).\n"
        "- action=\"DELETE\"+targetKind=\"ENTITY\": 실제 항목을 삭제합니다. targetKind="
        "\"REQUEST_ITEM\": candidateRequestItems 중 아무 action의 카드나 취소합니다(그 카드를"
        " 요청에서 제거, action이 CREATE/UPDATE/DELETE 무엇이든 상관없습니다).\n"
        "- 같은 (targetKind, entityType, targetEntityId) 조합을 이번 응답 안에서 두 item 이상이"
        " 동시에 가리키면 안 됩니다.\n"
        "unresolvedLine도 targetKind(\"ENTITY\"|\"REQUEST_ITEM\")를 포함해야 하며, action="
        "\"UPDATE\"면 targetKind는 반드시 \"ENTITY\"입니다.\n\n"
        "[응답 전 self-check — 응답을 만들기 직전 아래를 다시 확인하세요]\n"
        "1. TASK item이라면 action이 무엇이든(CREATE는 targetKind 무관, UPDATE/DELETE도 마찬가지)"
        " deadlineState 키를 반드시 포함하세요(targetKind=\"REQUEST_ITEM\"인 CREATE도 예외"
        " 없습니다 — 빠뜨리면 응답 전체가 거부됩니다). FIXED_SCHEDULE item은 반대로 deadlineState를"
        " 절대 포함하지 마세요.\n"
        "2. 사용자가 candidateRequestItems 중 하나(아직 실행되지 않은 대기 카드)를 가리키며 내용을"
        " 바꾸려 한다면, 그 카드의 현재 action이 \"CREATE\"인 한 반드시 action=\"CREATE\"+"
        "targetKind=\"REQUEST_ITEM\"+changedFields로 표현하세요. action=\"UPDATE\"로 쓰면 안 됩니다"
        "(UPDATE는 targetKind=\"ENTITY\", 즉 candidateTasks/candidateFixedSchedules의 실제 항목"
        "에만 씁니다).\n"
        "3. candidateRequestItems를 가리키는 게 전혀 아니고 완전히 새로운 항목을 추가하는"
        " 문장이면 targetKind 키 자체를 생략하거나 null로 두고 targetEntityId는 반드시 null로"
        " 두세요(REQUEST_ITEM으로 지어내거나 targetEntityId를 채우면 안 됩니다).\n"
        "4. normalizedPayload는 TASK든 FIXED_SCHEDULE든 항상 정해진 키 전체(TASK는 title,"
        " deadlineAt, estimatedMinutes, estimatedMinutesSource, remainingMinutes, amountText,"
        " amountSource 일곱 개, FIXED_SCHEDULE은 title, startAt, endAt 세 개)를 빠짐없이"
        " 포함하세요 — changedFields/updateFields에 없는 필드도 값만 null로 두고 키 자체는"
        " 반드시 있어야 합니다.\n\n"
        "[예시 — action=\"CREATE\"+targetKind=\"REQUEST_ITEM\", candidateRequestItems에 id"
        " \"item-1\"인 CREATE 카드가 있고 그 카드의 예상 시간만 2시간으로 바꾸는 경우]\n"
        "{\"entityType\": \"TASK\", \"action\": \"CREATE\", \"targetEntityId\": \"item-1\","
        " \"targetKind\": \"REQUEST_ITEM\", \"rawLineText\": \"그거 예상 시간 2시간으로\","
        " \"deadlineState\": \"MISSING\", \"changedFields\": [\"estimatedMinutes\"],"
        " \"normalizedPayload\": {\"title\": null, \"deadlineAt\": null, \"estimatedMinutes\":"
        " 120, \"estimatedMinutesSource\": \"USER\", \"remainingMinutes\": null, \"amountText\":"
        " null, \"amountSource\": null}, \"pendingQuestion\": null}\n\n"
        f"[컨텍스트]\n{json.dumps(context, ensure_ascii=False)}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": message},
    ]


def _build_change_input_operation_prompt_messages(
    message: str,
    *,
    now: datetime,
    cycle_start,
    cycle_end,
    candidate_tasks: list[dict],
    candidate_fixed_schedules: list[dict],
    candidate_request_items: list[dict],
) -> list[dict]:
    context = {
        "now": now.astimezone(_SEOUL_TZ).isoformat(),
        "cycleStart": cycle_start.isoformat() if cycle_start is not None else None,
        "cycleEnd": cycle_end.isoformat() if cycle_end is not None else None,
        "candidateTasks": candidate_tasks,
        "candidateFixedSchedules": candidate_fixed_schedules,
        "candidateRequestItems": candidate_request_items,
        "candidateRequestItemCount": len(candidate_request_items),
        "candidateTaskCount": len(candidate_tasks),
        "candidateFixedScheduleCount": len(candidate_fixed_schedules),
        "totalEntityCandidateCount": len(candidate_tasks) + len(candidate_fixed_schedules),
    }
    decide_prompt = """You analyze a user's CHANGE_INPUT request. Return exactly one JSON object without prose, markdown, or a code fence.

SECTION 1 — DECIDE OPERATION
First decide the operation. Do not choose a JSON shape before deciding the operation.
1. New Task or FixedSchedule creation intent -> ADD. Do not select an existing candidate. ADD applies when the candidate count is zero and when fields are missing. Missing values use null values and pendingQuestion; they are not target ambiguity. unresolvedOperation is forbidden.
2. Modify an existing unexecuted request item whose action is CREATE -> PATCH_REQUEST_ITEM.
3. Cancel or remove an existing request item -> DELETE_REQUEST_ITEM. If intent, REQUEST_ITEM namespace, and entityType filtering leave exactly one matching candidateRequestItem, it must be DELETE_REQUEST_ITEM; select it directly and do not ask a confirmation question. unresolvedOperation is forbidden. Do not change this deletion into ADD, PATCH_REQUEST_ITEM, or UPDATE_ENTITY.
4. Modify a real existing Task or FixedSchedule -> UPDATE_ENTITY.
5. Mark a real existing Task or FixedSchedule for deletion -> DELETE_ENTITY.
6. unresolvedOperation is the last resort, only for modifying or deleting an existing target when intent, namespace, and entityType filtering still leave two or more matching existing targets that the user cannot distinguish. It is forbidden for ADD, missing fields, zero matching candidates, or one matching candidate.
Allowed unresolved pairs: PATCH_REQUEST_ITEM + REQUEST_ITEM; DELETE_REQUEST_ITEM + REQUEST_ITEM; UPDATE_ENTITY + ENTITY; DELETE_ENTITY + ENTITY."""

    build_prompt = """SECTION 3 — BUILD EXACT JSON
Only after deciding the operation, build its exact JSON shape.
Top-level exact keys: analysisMessage, operations, unresolvedOperation. analysisMessage must be a nonblank string; null is forbidden. Use either a non-empty operations array with unresolvedOperation null, or operations [] with one unresolvedOperation object.

EXACT OPERATION KEYS
ADD: operationType, entityType, rawLineText, payload, pendingQuestion.
PATCH_REQUEST_ITEM: operationType, requestItemId, entityType, changedFields, patch, pendingQuestion.
DELETE_REQUEST_ITEM: operationType, requestItemId, entityType.
UPDATE_ENTITY: operationType, targetEntityId, entityType, updateFields, patch, pendingQuestion.
DELETE_ENTITY: operationType, targetEntityId, entityType.
TASK ADD payload: title, deadlineAt, deadlineState, estimatedMinutes, estimatedMinutesSource, amountText, amountSource.
FIXED_SCHEDULE ADD payload: title, startAt, endAt.
Unknown, additional, or omitted keys are forbidden. ADD has no target ID or remainingMinutes. DELETE_REQUEST_ITEM has exactly operationType, requestItemId, entityType and never has pendingQuestion, payload, patch, changedFields, updateFields, deadlineState, or targetEntityId. DELETE_ENTITY also has exactly its three listed keys.

LOGICAL FIELDS AND STORAGE KEYS
PATCH_REQUEST_ITEM TASK logical fields: title, deadlineAt, estimatedMinutes, amount.
UPDATE_ENTITY TASK logical fields: title, deadlineAt, estimatedMinutes, remainingMinutes, amount.
FIXED_SCHEDULE logical fields: title, startAt, endAt.
Storage mapping: title -> title; deadlineAt -> deadlineAt, deadlineState; estimatedMinutes -> estimatedMinutes, estimatedMinutesSource; remainingMinutes -> remainingMinutes; amount -> amountText, amountSource; startAt -> startAt; endAt -> endAt.
changedFields/updateFields contain only logical fields. patch contains exactly their mapped storage keys and no untouched fields. Never put estimatedMinutesSource or amountSource in changedFields/updateFields. remainingMinutes is forbidden for ADD and PATCH_REQUEST_ITEM. A non-null estimatedMinutes requires source USER or AI_ESTIMATED.

PENDING QUESTION
pendingQuestion is null or an object with exact keys field, message, attemptCount. pendingQuestion is allowed as an object only when at least one field is missing. field is the canonical first missing field, message is nonblank, and attemptCount must be an integer >= 1. If nothing is missing, pendingQuestion must be null.

FULL ENVELOPE EXAMPLE 1 — COMPLETE ADD
{"analysisMessage":"Added.","operations":[{"operationType":"ADD","entityType":"TASK","rawLineText":"new task","payload":{"title":"report","deadlineAt":"2026-08-07T17:00:00+09:00","deadlineState":"KNOWN","estimatedMinutes":45,"estimatedMinutesSource":"USER","amountText":"1 page","amountSource":"USER"},"pendingQuestion":null}],"unresolvedOperation":null}

FULL ENVELOPE EXAMPLE 2 — MISSING ADD
{"analysisMessage":"I need one detail.","operations":[{"operationType":"ADD","entityType":"TASK","rawLineText":"new task","payload":{"title":"report","deadlineAt":null,"deadlineState":"MISSING","estimatedMinutes":null,"estimatedMinutesSource":null,"amountText":null,"amountSource":null},"pendingQuestion":{"field":"deadlineAt","message":"When is the deadline?","attemptCount":1}}],"unresolvedOperation":null}

FULL ENVELOPE EXAMPLE 3 — SINGLE-CANDIDATE DELETE_REQUEST_ITEM
{"analysisMessage":"Removed the request item.","operations":[{"operationType":"DELETE_REQUEST_ITEM","requestItemId":"22222222-2222-2222-2222-222222222222","entityType":"TASK"}],"unresolvedOperation":null}

Use IDs exactly as supplied. Never invent an ID, mix REQUEST_ITEM and ENTITY namespaces, or emit duplicate target operations. unresolvedOperation exact keys are intendedOperation, targetKind, entityType, rawLineText, message; it contains no candidate ID."""
    return [
        {
            "role": "system",
            "content": (
                f"{decide_prompt}\n\nSECTION 2 — CANDIDATE FACTS\n"
                f"{json.dumps(context, ensure_ascii=False)}\n\n"
                "Counts and arrays are server-provided facts, not guesses. A namespace with count 0 cannot supply "
                "an ID. Never invent a candidate ID. A single matching candidate is not ambiguous.\n\n"
                f"{build_prompt}"
            ),
        },
        {"role": "user", "content": message},
    ]


def _identity_canonicalize(content: str) -> str:
    return content


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def _change_pending_question_schema() -> dict:
    return _nullable({
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "field": {"type": "string", "minLength": 1},
            "message": {"type": "string", "minLength": 1},
            "attemptCount": {"type": "integer", "minimum": 1},
        },
        "required": ["field", "message", "attemptCount"],
    })


def _build_gemini_change_input_schema(
    *,
    candidate_task_ids: set[str],
    candidate_fixed_schedule_ids: set[str],
    candidate_request_items: dict[str, dict],
) -> dict:
    entity_type = {"type": "string", "enum": ["TASK", "FIXED_SCHEDULE"]}
    nonblank = {"type": "string", "minLength": 1}
    nullable_string = _nullable({"type": "string"})
    operations: list[dict] = []

    task_payload = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "title": nullable_string,
            "deadlineAt": nullable_string,
            "deadlineState": {"type": "string", "enum": ["KNOWN", "NONE", "MISSING"]},
            "estimatedMinutes": _nullable({"type": "integer", "minimum": 1}),
            "estimatedMinutesSource": _nullable({"type": "string", "enum": ["USER", "AI_ESTIMATED"]}),
            "amountText": nullable_string,
            "amountSource": _nullable({"type": "string", "enum": ["USER", "AI_ESTIMATED", "UNKNOWN"]}),
        },
        "required": ["title", "deadlineAt", "deadlineState", "estimatedMinutes",
                     "estimatedMinutesSource", "amountText", "amountSource"],
    }
    fixed_payload = {
        "type": "object", "additionalProperties": False,
        "properties": {"title": nullable_string, "startAt": nullable_string, "endAt": nullable_string},
        "required": ["title", "startAt", "endAt"],
    }
    operations.append({
        "type": "object", "additionalProperties": False,
        "properties": {
            "operationType": {"type": "string", "enum": ["ADD"]},
            "entityType": entity_type,
            "rawLineText": nonblank,
            "payload": {"anyOf": [task_payload, fixed_payload]},
            "pendingQuestion": _change_pending_question_schema(),
        },
        "required": ["operationType", "entityType", "rawLineText", "payload", "pendingQuestion"],
    })

    patch_properties = {
        "title": nullable_string,
        "deadlineAt": nullable_string,
        "deadlineState": {"type": "string", "enum": ["KNOWN", "NONE", "MISSING"]},
        "estimatedMinutes": _nullable({"type": "integer", "minimum": 1}),
        "estimatedMinutesSource": _nullable({"type": "string", "enum": ["USER", "AI_ESTIMATED"]}),
        "remainingMinutes": _nullable({"type": "integer", "minimum": 0}),
        "amountText": nullable_string,
        "amountSource": _nullable({"type": "string", "enum": ["USER", "AI_ESTIMATED", "UNKNOWN"]}),
        "startAt": nullable_string,
        "endAt": nullable_string,
    }
    create_item_ids = [
        item_id for item_id, item in candidate_request_items.items() if item.get("action") == "CREATE"
    ]
    all_item_ids = list(candidate_request_items)
    if create_item_ids:
        operations.append({
            "type": "object", "additionalProperties": False,
            "properties": {
                "operationType": {"type": "string", "enum": ["PATCH_REQUEST_ITEM"]},
                "requestItemId": {"type": "string", "enum": create_item_ids},
                "entityType": entity_type,
                "changedFields": {"type": "array", "minItems": 1, "uniqueItems": True,
                                  "items": {"type": "string", "enum": ["title", "deadlineAt", "estimatedMinutes", "amount", "startAt", "endAt"]}},
                "patch": {"type": "object", "additionalProperties": False, "properties": patch_properties},
                "pendingQuestion": _change_pending_question_schema(),
            },
            "required": ["operationType", "requestItemId", "entityType", "changedFields", "patch", "pendingQuestion"],
        })
    if all_item_ids:
        operations.append({
            "type": "object", "additionalProperties": False,
            "properties": {
                "operationType": {"type": "string", "enum": ["DELETE_REQUEST_ITEM"]},
                "requestItemId": {"type": "string", "enum": all_item_ids},
                "entityType": entity_type,
            },
            "required": ["operationType", "requestItemId", "entityType"],
        })

    all_entity_ids = list(candidate_task_ids) + list(candidate_fixed_schedule_ids)
    if all_entity_ids:
        operations.append({
            "type": "object", "additionalProperties": False,
            "properties": {
                "operationType": {"type": "string", "enum": ["UPDATE_ENTITY"]},
                "targetEntityId": {"type": "string", "enum": all_entity_ids},
                "entityType": entity_type,
                "updateFields": {"type": "array", "minItems": 1, "uniqueItems": True,
                                 "items": {"type": "string", "enum": ["title", "deadlineAt", "estimatedMinutes", "remainingMinutes", "amount", "startAt", "endAt"]}},
                "patch": {"type": "object", "additionalProperties": False, "properties": patch_properties},
                "pendingQuestion": _change_pending_question_schema(),
            },
            "required": ["operationType", "targetEntityId", "entityType", "updateFields", "patch", "pendingQuestion"],
        })
        operations.append({
            "type": "object", "additionalProperties": False,
            "properties": {
                "operationType": {"type": "string", "enum": ["DELETE_ENTITY"]},
                "targetEntityId": {"type": "string", "enum": all_entity_ids},
                "entityType": entity_type,
            },
            "required": ["operationType", "targetEntityId", "entityType"],
        })

    unresolved = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "intendedOperation": {"type": "string", "enum": ["PATCH_REQUEST_ITEM", "DELETE_REQUEST_ITEM", "UPDATE_ENTITY", "DELETE_ENTITY"]},
            "targetKind": {"type": "string", "enum": ["REQUEST_ITEM", "ENTITY"]},
            "entityType": entity_type,
            "rawLineText": nonblank,
            "message": nonblank,
        },
        "required": ["intendedOperation", "targetKind", "entityType", "rawLineText", "message"],
    }
    base_properties = {
        "analysisMessage": nonblank,
        "operations": {"type": "array", "items": {"anyOf": operations}},
        "unresolvedOperation": _nullable(unresolved),
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": base_properties,
        "required": ["analysisMessage", "operations", "unresolvedOperation"],
        "anyOf": [
            {"properties": {"operations": {"type": "array", "minItems": 1, "items": {"anyOf": operations}},
                            "unresolvedOperation": {"type": "null"}}},
            {"properties": {"operations": {"type": "array", "maxItems": 0},
                            "unresolvedOperation": unresolved}},
        ],
    }


def _build_solar_change_input_advisory_messages(message: str, *, context: dict) -> list[dict]:
    prompt = """Analyze the user's CHANGE_INPUT intent as non-authoritative advice for another model.
Return one small JSON object. Describe suggested operations, referenced candidate kinds/IDs, missing information, ambiguity reason, and a short analysis summary. Do not generate payloads, patches, pending questions, or final user-facing messages. A new item with missing fields is still a new ADD intent. Use only candidate IDs from context."""
    return [
        {"role": "system", "content": f"{prompt}\n\nCANDIDATE CONTEXT\n{json.dumps(context, ensure_ascii=False)}"},
        {"role": "user", "content": message},
    ]


def _get_solar_change_input_advisory(message: str, *, context: dict) -> str | None:
    try:
        content = call_solar({"messages": _build_solar_change_input_advisory_messages(message, context=context)})
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("advisory must be an object")
        return json.dumps(parsed, ensure_ascii=False)
    except (SolarUnavailableError, json.JSONDecodeError, TypeError, ValueError):
        logger.warning("CHANGE_INPUT_SOLAR_ADVISORY_FALLBACK")
        return None


def _build_gemini_change_input_prompt(
    message: str,
    *,
    now: datetime,
    context: dict,
    solar_advisory: str | None,
) -> str:
    advisory = solar_advisory if solar_advisory is not None else "SOLAR advisory unavailable"
    return f"""Produce the final CHANGE_INPUT analysis for the strict server contract.
Use the original user message and candidate context as authoritative. The SOLAR advisory is optional and non-authoritative: correct or ignore it when it conflicts with the user intent or candidates.
Support ADD, PATCH_REQUEST_ITEM, DELETE_REQUEST_ITEM, UPDATE_ENTITY, DELETE_ENTITY, unresolved target selection, and multiple operations in user order.
For sparse PATCH/UPDATE, changedFields/updateFields contain logical fields and patch contains exactly their mapped storage keys. Do not emit untouched keys. DELETE operations contain only their three exact keys. Missing ADD fields use null pairs and a pendingQuestion for the canonical first missing field.
Current time: {now.astimezone(_SEOUL_TZ).isoformat()}
CANDIDATE CONTEXT:
{json.dumps(context, ensure_ascii=False)}
SOLAR ADVISORY:
{advisory}
ORIGINAL USER MESSAGE:
{message}"""


def _run_gemini_change_input(*, prompt: str, response_json_schema: dict) -> str:
    try:
        return asyncio.run(gemini_change_input_client.generate_change_input(
            prompt=prompt, response_json_schema=response_json_schema
        ))
    except gemini_change_input_client.GeminiChangeInputError as exc:
        raise SolarUnavailableError("Gemini CHANGE_INPUT analysis failed") from exc


def analyze_change_input(
    message: str,
    *,
    now: datetime,
    purpose: SolarRequestPurpose,
    cycle_start=None,
    cycle_end=None,
    candidate_tasks: list[dict] | None = None,
    candidate_fixed_schedules: list[dict] | None = None,
    candidate_request_items: dict[str, dict] | None = None,
) -> ChangeInputAnalysisResult:
    """CHANGE_INPUT 전용 진입점. `candidate_request_items`의 값 dict는 파서 검증용
    entityType/action을 최소한 포함해야 하며, 프롬프트 컨텍스트로도 그대로 노출된다."""
    candidate_tasks = candidate_tasks or []
    candidate_fixed_schedules = candidate_fixed_schedules or []
    candidate_request_items = candidate_request_items or {}

    prompt_request_items = [{"id": item_id, **info} for item_id, info in candidate_request_items.items()]
    candidate_task_ids = {str(c["id"]) for c in candidate_tasks}
    candidate_fixed_schedule_ids = {str(c["id"]) for c in candidate_fixed_schedules}
    context = {
        "cycleStart": cycle_start.isoformat() if cycle_start is not None else None,
        "cycleEnd": cycle_end.isoformat() if cycle_end is not None else None,
        "candidateTasks": candidate_tasks,
        "candidateFixedSchedules": candidate_fixed_schedules,
        "candidateRequestItems": prompt_request_items,
    }
    solar_advisory = _get_solar_change_input_advisory(message, context=context)
    response_schema = _build_gemini_change_input_schema(
        candidate_task_ids=candidate_task_ids,
        candidate_fixed_schedule_ids=candidate_fixed_schedule_ids,
        candidate_request_items=candidate_request_items,
    )
    prompt = _build_gemini_change_input_prompt(
        message, now=now, context=context, solar_advisory=solar_advisory
    )

    def _parse(content: str) -> ChangeInputAnalysisResult:
        return parse_change_input_response(
            content,
            candidate_task_ids=candidate_task_ids,
            candidate_fixed_schedule_ids=candidate_fixed_schedule_ids,
            candidate_request_items=candidate_request_items,
        )

    content = _run_gemini_change_input(prompt=prompt, response_json_schema=response_schema)
    try:
        return _parse(content)
    except SolarUnavailableError as violation:
        safe_context = _build_change_input_repair_context(content, violation)
        logger.warning("GEMINI_CHANGE_INPUT_REPAIR_ATTEMPT code=%s", violation.code)
        repair_prompt = (
            f"{prompt}\n\nREPAIR THE FINAL RESPONSE. Re-evaluate the original user intent and candidates; "
            "the SOLAR advisory remains non-authoritative. Return a complete response matching the same structured "
            "schema. Do not ignore extra keys, invent IDs, or copy invalid fields.\n"
            f"Safe violation context:\n{safe_context}"
        )
    repair_content = _run_gemini_change_input(
        prompt=repair_prompt, response_json_schema=response_schema
    )
    return _parse(repair_content)
