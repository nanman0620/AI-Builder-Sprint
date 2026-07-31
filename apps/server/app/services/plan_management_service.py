import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import (
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
from app.services import plan_block_service, solar_request_service
from app.services.solar_request_service import PlanManagementScreenMode

_SEOUL_TZ = ZoneInfo("Asia/Seoul")

# 명세가 실제 예시 문구를 준 필드만 채운다. 그 외 필드는 추측 문구를 만들지 않고 None으로 반환한다
# (알려진 제약: docs/api 3-10/6-1 예시가 estimatedMinutes/amount 두 개만 제공함).
_INPUT_PLACEHOLDERS = {
    "estimatedMinutes": "예: 2시간 정도 걸려요",
    "amount": "예: 문제 5개",
}

# summaryText의 "정보 부족" 뒤에 나열할 필드 라벨. _INPUT_PLACEHOLDERS보다 넓은 범위가 필요해
# 별개 상수로 관리한다(문구가 있는 필드만 담는 위 상수와 목적이 다름).
_MISSING_FIELD_LABELS = {
    "title": "제목",
    "deadlineAt": "마감",
    "estimatedMinutes": "예상 시간",
    "remainingMinutes": "남은 시간",
    "amount": "분량",
    "startAt": "시작",
    "endAt": "종료",
}

# Issue #50: UPDATE 카드에서 estimatedMinutes와 무관하게 remainingMinutes만 바뀔 수 있어
# missing field로 새로 등장한다. 새 문구를 만들지 않고 estimatedMinutes의 기존 placeholder를
# 그대로 재사용한다.
_INPUT_PLACEHOLDERS["remainingMinutes"] = _INPUT_PLACEHOLDERS["estimatedMinutes"]

_ACTION_LABELS = {
    SolarAction.CREATE: "추가",
    SolarAction.UPDATE: "수정",
    SolarAction.DELETE: "삭제",
}
_ENTITY_LABELS = {
    SolarEntityType.TASK: "할 일",
    SolarEntityType.FIXED_SCHEDULE: "고정 일정",
}
_STATUS_LABELS = {
    SolarItemStatus.INFO_MISSING: "정보 부족",
    SolarItemStatus.READY: "준비됨",
    SolarItemStatus.EXECUTED: "반영 완료",
}

_CHANGE_INPUT_PLACEHOLDER = "추가하거나 수정할 내용을 입력해 주세요."


@dataclass(frozen=True)
class QuickReply:
    value: str
    label: str


_DEFAULT_QUICK_REPLIES = (QuickReply(value="DONT_KNOW", label="잘 모르겠어요"),)


@dataclass(frozen=True)
class DecisionOption:
    value: str
    label: str


@dataclass(frozen=True)
class DecisionPrompt:
    message: str
    options: list[DecisionOption]


_CHANGE_CONFIRMATION_DECISION_PROMPT = DecisionPrompt(
    message="수정하거나 추가할 내용이 있나요?",
    options=[DecisionOption(value="YES", label="네"), DecisionOption(value="NO", label="아니요")],
)


@dataclass(frozen=True)
class CurrentQuestion:
    # Issue #50: 카드 없는 "대상 모호" 질문(unresolvedLine)은 아이템이 없어 itemId가 없다.
    item_id: uuid.UUID | None
    field: str
    message: str


@dataclass(frozen=True)
class PendingQuestion:
    field: str
    message: str
    attempt_count: int


@dataclass(frozen=True)
class ExecutionError:
    code: str
    message: str
    retryable: bool


@dataclass(frozen=True)
class Execution:
    execution_started_at: datetime | None
    execution_attempt_count: int
    executed_at: datetime | None
    execution_result: dict | None
    error: ExecutionError | None


@dataclass(frozen=True)
class SolarRequestItemDetail:
    item: SolarRequestItem
    action_label: str
    entity_label: str
    status_label: str
    title: str
    summary_text: str
    pending_question: PendingQuestion | None
    target_entity_id: uuid.UUID | None


@dataclass(frozen=True)
class SolarRequestDetail:
    request: SolarRequest
    messages: list[SolarMessage]
    items: list[SolarRequestItemDetail]
    current_question: CurrentQuestion | None
    quick_replies: list[QuickReply]
    input_placeholder: str | None
    pending_item_id: uuid.UUID | None
    decision_prompt: DecisionPrompt | None
    # 구조가 명세에 확정되어 있지 않고(3-10 모든 예시가 null) 프론트 타입도 unknown으로 선언한
    # 채 렌더링하지 않으므로, 이번 Issue에서는 항상 None으로 반환하는 의도적 제한이다.
    review_summary: None
    execution: Execution | None


@dataclass(frozen=True)
class PlanManagementState:
    screen_mode: PlanManagementScreenMode
    active_cycle: PlanningCycle | None
    request_detail: SolarRequestDetail | None


# ---------------------------------------------------------------------------
# 방어적 파싱 헬퍼 — pending_question/metadata/normalized_payload는 모두 JSONB라 저장 시점의
# 형식이 기대와 달라도(dict가 아니거나 키가 없거나 타입이 다름) 예외 없이 null/최소 라벨로
# 축소한다.
# ---------------------------------------------------------------------------


def _safe_payload(item: SolarRequestItem) -> dict:
    return item.normalized_payload if isinstance(item.normalized_payload, dict) else {}


def _parse_iso_datetime_seoul(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(_SEOUL_TZ)


def _format_date_kr(d: date) -> str:
    return f"{d.month}월 {d.day}일"


def _format_minutes_kr(value: object) -> str | None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return None
    hours, minutes = divmod(value, 60)
    if hours and minutes:
        return f"{hours}시간 {minutes}분"
    if hours:
        return f"{hours}시간"
    return f"{minutes}분"


def _parse_pending_question(value: object) -> PendingQuestion | None:
    if not isinstance(value, dict):
        return None
    field = value.get("field")
    message = value.get("message")
    if not isinstance(field, str) or not isinstance(message, str):
        return None
    attempt_count = value.get("attemptCount")
    if not isinstance(attempt_count, int) or isinstance(attempt_count, bool):
        attempt_count = 0
    return PendingQuestion(field=field, message=message, attempt_count=attempt_count)


# ---------------------------------------------------------------------------
# 아이템(카드)별 표시 필드 계산
# ---------------------------------------------------------------------------


def _build_missing_summary(missing_fields: object) -> str:
    status_label = _STATUS_LABELS[SolarItemStatus.INFO_MISSING]
    if not isinstance(missing_fields, list) or not missing_fields:
        return status_label
    labels = [
        _MISSING_FIELD_LABELS[field]
        for field in missing_fields
        if isinstance(field, str) and field in _MISSING_FIELD_LABELS
    ]
    if not labels:
        return status_label
    return f"{status_label} · {'·'.join(labels)} 필요"


def _build_task_summary(status_label: str, payload: dict) -> str:
    parts = [status_label]

    deadline = _parse_iso_datetime_seoul(payload.get("deadlineAt"))
    if deadline is not None:
        parts.append(f"{_format_date_kr(deadline.date())}까지")

    amount_text = payload.get("amountText")
    if isinstance(amount_text, str) and amount_text.strip():
        parts.append(amount_text)

    minutes_display = _format_minutes_kr(payload.get("estimatedMinutes"))
    if minutes_display is not None:
        parts.append(minutes_display)

    return " · ".join(parts)


def _build_fixed_schedule_summary(status_label: str, payload: dict) -> str:
    start = _parse_iso_datetime_seoul(payload.get("startAt"))
    end = _parse_iso_datetime_seoul(payload.get("endAt"))
    if start is None or end is None:
        return status_label
    range_display = (
        f"{_format_date_kr(start.date())} {start:%H:%M}-{_format_date_kr(end.date())} {end:%H:%M}"
    )
    return f"{status_label} · {range_display}"


def _build_item_detail(item: SolarRequestItem) -> SolarRequestItemDetail:
    action_label = _ACTION_LABELS.get(item.action, item.action.value)
    entity_label = _ENTITY_LABELS.get(item.entity_type, item.entity_type.value)
    status_label = _STATUS_LABELS.get(item.status, item.status.value)

    payload = _safe_payload(item)
    payload_title = payload.get("title")
    title = payload_title if isinstance(payload_title, str) and payload_title.strip() else item.raw_line_text

    if item.status == SolarItemStatus.INFO_MISSING:
        summary_text = _build_missing_summary(item.missing_fields)
    elif item.entity_type == SolarEntityType.FIXED_SCHEDULE:
        summary_text = _build_fixed_schedule_summary(status_label, payload)
    else:
        summary_text = _build_task_summary(status_label, payload)

    target_entity_id = item.target_task_id or item.target_fixed_schedule_id

    return SolarRequestItemDetail(
        item=item,
        action_label=action_label,
        entity_label=entity_label,
        status_label=status_label,
        title=title,
        summary_text=summary_text,
        pending_question=_parse_pending_question(item.pending_question),
        target_entity_id=target_entity_id,
    )


# ---------------------------------------------------------------------------
# 현재 질문(currentQuestion)/quickReplies/inputPlaceholder 계산
# ---------------------------------------------------------------------------


def _find_pending_item(
    request: SolarRequest, items: Sequence[SolarRequestItem]
) -> SolarRequestItem | None:
    """현재 질문 대상 카드 = current_item_order와 일치 + INFO_MISSING + pending_question 존재.

    조건을 만족하는 카드가 없으면(데이터 불일치 포함) 다른 카드를 임의로 선택하지 않고 None을
    반환한다 — 호출부는 이 경우 질문 관련 필드를 null/빈 배열로 반환해야 한다.
    """
    if request.current_item_order is None:
        return None
    for item in items:
        if (
            item.item_order == request.current_item_order
            and item.status == SolarItemStatus.INFO_MISSING
            and item.pending_question is not None
        ):
            return item
    return None


def _find_unresolved_question_message(messages: Sequence[SolarMessage]) -> SolarMessage | None:
    """Issue #50: 카드 없는 "대상 모호" 질문(unresolvedLine)이 아직 해소되지 않았는지 찾는다.

    `metadata.unresolved=true`인 ASSISTANT/QUESTION 메시지 중 sequence_no가 가장 큰 것을 찾고,
    그보다 sequence_no가 더 큰 메시지(USER 답변이든 더 최신 QUESTION이든)가 하나라도 있으면
    이미 해소된 것으로 보고 사용하지 않는다. 이번 Issue는 한 turn만 만들어 이 조건이 실질적으로
    항상 참이지만, 이후 `/messages`가 메시지를 추가하는 상황에서도 안전하도록 미리 구현한다.
    """
    unresolved_candidates = [
        message
        for message in messages
        if message.role == SolarMessageRole.ASSISTANT
        and message.kind == SolarMessageKind.QUESTION
        and isinstance(message.message_metadata, dict)
        and message.message_metadata.get("unresolved") is True
    ]
    if not unresolved_candidates:
        return None
    latest_unresolved = max(unresolved_candidates, key=lambda m: m.sequence_no)
    if any(message.sequence_no > latest_unresolved.sequence_no for message in messages):
        return None
    return latest_unresolved


def _find_question_metadata(
    messages: Sequence[SolarMessage], pending_item_id: uuid.UUID, field: str
) -> dict | None:
    """pending item과 field가 모두 일치하는 가장 최신 ASSISTANT/QUESTION 메시지의 metadata."""
    candidates = []
    for message in messages:
        if message.role != SolarMessageRole.ASSISTANT or message.kind != SolarMessageKind.QUESTION:
            continue
        metadata = message.message_metadata
        if not isinstance(metadata, dict):
            continue
        if str(metadata.get("itemId")) != str(pending_item_id):
            continue
        if metadata.get("field") != field:
            continue
        candidates.append(message)
    if not candidates:
        return None
    latest = max(candidates, key=lambda m: m.sequence_no)
    metadata = latest.message_metadata
    return metadata if isinstance(metadata, dict) else None


def _resolve_quick_replies_and_placeholder(
    metadata: dict | None, field: str
) -> tuple[list[QuickReply], str | None]:
    quick_replies: list[QuickReply] | None = None
    input_placeholder: str | None = None

    if metadata is not None:
        raw_quick_replies = metadata.get("quickReplies")
        if isinstance(raw_quick_replies, list):
            parsed = [
                QuickReply(value=entry["value"], label=entry["label"])
                for entry in raw_quick_replies
                if isinstance(entry, dict)
                and isinstance(entry.get("value"), str)
                and isinstance(entry.get("label"), str)
            ]
            if parsed:
                quick_replies = parsed

        raw_placeholder = metadata.get("inputPlaceholder")
        if isinstance(raw_placeholder, str) and raw_placeholder.strip():
            input_placeholder = raw_placeholder

    if quick_replies is None:
        quick_replies = list(_DEFAULT_QUICK_REPLIES)
    if input_placeholder is None:
        input_placeholder = _INPUT_PLACEHOLDERS.get(field)

    return quick_replies, input_placeholder


def _build_decision_prompt(status: SolarRequestStatus) -> DecisionPrompt | None:
    if status == SolarRequestStatus.CHANGE_CONFIRMATION:
        return _CHANGE_CONFIRMATION_DECISION_PROMPT
    return None


def _build_execution(request: SolarRequest) -> Execution | None:
    if request.status not in (
        SolarRequestStatus.EXECUTING,
        SolarRequestStatus.COMPLETED,
        SolarRequestStatus.FAILED,
    ):
        return None

    error = None
    if request.status == SolarRequestStatus.FAILED:
        # retryable을 저장하는 컬럼이 없다 — FAILED는 상태 전이표(FAILED --retry 검증 성공--> EXECUTING)
        # 상 항상 재시도 가능한 MVP 상태 모델이므로 True로 고정한다(추측 문구가 아니라 상태 머신
        # 규칙에서 도출한 상수).
        error = ExecutionError(
            code=request.error_code or "", message=request.error_message or "", retryable=True
        )

    return Execution(
        execution_started_at=request.execution_started_at,
        execution_attempt_count=request.execution_attempt_count,
        executed_at=request.executed_at,
        execution_result=request.execution_result,
        error=error,
    )


def _build_solar_request_detail(
    request: SolarRequest,
    messages: Sequence[SolarMessage],
    items: Sequence[SolarRequestItem],
) -> SolarRequestDetail:
    """이미 읽어온 row만으로 상세 payload를 계산하는 순수 함수(DB 호출 없음).

    messages/items는 SQL에서 이미 sequence_no/item_order로 정렬돼 오지만 방어적으로 한 번 더
    정렬한다.
    """
    sorted_messages = sorted(messages, key=lambda m: m.sequence_no)
    sorted_items = sorted(items, key=lambda i: i.item_order)

    item_details = [_build_item_detail(item) for item in sorted_items]

    current_question: CurrentQuestion | None = None
    quick_replies: list[QuickReply] = []
    input_placeholder: str | None = None
    pending_item_id: uuid.UUID | None = None

    if request.status == SolarRequestStatus.COLLECTING:
        # Issue #50: 카드 없는 "대상 모호" 질문이 아직 해소되지 않았으면 카드 기반 질문보다
        # 항상 우선한다(저장 쪽도 둘 중 하나만 메시지를 만들므로 실제로는 상호 배타적이다).
        unresolved_message = _find_unresolved_question_message(sorted_messages)
        if unresolved_message is not None:
            current_question = CurrentQuestion(
                item_id=None, field="targetEntityId", message=unresolved_message.content
            )
            input_placeholder = _CHANGE_INPUT_PLACEHOLDER
        else:
            pending_item = _find_pending_item(request, sorted_items)
            if pending_item is not None:
                pending_question = _parse_pending_question(pending_item.pending_question)
                if pending_question is not None:
                    metadata = _find_question_metadata(
                        sorted_messages, pending_item.id, pending_question.field
                    )
                    quick_replies, input_placeholder = _resolve_quick_replies_and_placeholder(
                        metadata, pending_question.field
                    )
                    current_question = CurrentQuestion(
                        item_id=pending_item.id,
                        field=pending_question.field,
                        message=pending_question.message,
                    )
                    pending_item_id = pending_item.id
    elif request.status == SolarRequestStatus.CHANGE_INPUT:
        input_placeholder = _CHANGE_INPUT_PLACEHOLDER

    return SolarRequestDetail(
        request=request,
        messages=sorted_messages,
        items=item_details,
        current_question=current_question,
        quick_replies=quick_replies,
        input_placeholder=input_placeholder,
        pending_item_id=pending_item_id,
        decision_prompt=_build_decision_prompt(request.status),
        review_summary=None,
        execution=_build_execution(request),
    )


# ---------------------------------------------------------------------------
# 오케스트레이션 — 조회 전용(db.begin()/commit()/flush()/add()/delete() 호출 없음)
# ---------------------------------------------------------------------------


def _load_and_build_detail(db: Session, request: SolarRequest) -> SolarRequestDetail:
    messages = (
        db.execute(
            select(SolarMessage)
            .where(SolarMessage.solar_request_id == request.id)
            .order_by(SolarMessage.sequence_no.asc())
        )
        .scalars()
        .all()
    )
    items = (
        db.execute(
            select(SolarRequestItem)
            .where(SolarRequestItem.solar_request_id == request.id)
            .order_by(SolarRequestItem.item_order.asc())
        )
        .scalars()
        .all()
    )
    return _build_solar_request_detail(request, messages, items)


def get_plan_management_state(db: Session, user_id: uuid.UUID) -> PlanManagementState:
    """계획관리 탭 포커스 시 현재 상태를 복원한다. `activeCycle`은 사용자의 현재 살아있는
    ACTIVE cycle을 그대로 보여준다(요청의 purpose와 무관하게 항상 최신 상태)."""
    active_cycle = plan_block_service.get_active_planning_cycle(db, user_id)
    current_request = solar_request_service.get_current_solar_request(db, user_id)

    if current_request is None:
        screen_mode = solar_request_service.resolve_no_request_screen_mode(
            has_active_cycle=active_cycle is not None
        )
        return PlanManagementState(screen_mode=screen_mode, active_cycle=active_cycle, request_detail=None)

    screen_mode = solar_request_service.resolve_current_request_screen_mode(current_request)
    detail = _load_and_build_detail(db, current_request)
    return PlanManagementState(screen_mode=screen_mode, active_cycle=active_cycle, request_detail=detail)


def get_solar_request_detail_state(
    db: Session, user_id: uuid.UUID, request_id: uuid.UUID
) -> PlanManagementState:
    """특정 요청 1건을 상세 조회한다. 결과 확인이 끝난 과거 COMPLETED 요청도 조회 대상이다 —
    별도의 "과거 완료" screenMode는 없으므로 resolve_current_request_screen_mode의 기존 동작대로
    result_acknowledged_at과 무관하게 COMPLETED는 EXECUTION_SUCCESS로 반환한다.

    activeCycle은 사용자의 "현재" ACTIVE cycle이 아니라 이 요청 자신의 cycle만 사용한다(다른
    ACTIVE cycle이 있어도 섞어 붙이지 않음) — purpose가 ACTIVE_CYCLE이고 plan_cycle_id가 있을
    때만 그 cycle을 조회하고, 그 외(NEW_CYCLE 또는 plan_cycle_id 없음)는 null이다.
    """
    request = solar_request_service.get_owned_solar_request(db, request_id, user_id)

    active_cycle = None
    if request.purpose == SolarRequestPurpose.ACTIVE_CYCLE and request.plan_cycle_id is not None:
        active_cycle = plan_block_service.get_owned_planning_cycle(db, request.plan_cycle_id, user_id)

    screen_mode = solar_request_service.resolve_current_request_screen_mode(request)
    detail = _load_and_build_detail(db, request)
    return PlanManagementState(screen_mode=screen_mode, active_cycle=active_cycle, request_detail=detail)
