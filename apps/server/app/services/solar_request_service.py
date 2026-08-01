import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from types import SimpleNamespace
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import func, null, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.models.enums import (
    SolarAction,
    SolarEntityType,
    SolarItemStatus,
    SolarMessageKind,
    SolarMessageRole,
    SolarRequestPurpose,
    SolarRequestStatus,
    TaskStatus,
)
from app.models.fixed_schedule import FixedSchedule
from app.models.solar_message import SolarMessage
from app.models.solar_request import SolarRequest
from app.models.solar_request_item import SolarRequestItem
from app.models.task import Task
from app.services import check_in_service, plan_block_service, solar_client

if TYPE_CHECKING:
    from app.services.plan_management_service import PlanManagementState

logger = logging.getLogger(__name__)


class Dispatcher(Protocol):
    def register(self, request_id: uuid.UUID) -> None: ...

CODE_REQUEST_NOT_FOUND = "REQUEST_NOT_FOUND"
CODE_ACTIVE_CYCLE_EXISTS = "ACTIVE_CYCLE_EXISTS"
CODE_NO_ACTIVE_CYCLE = "NO_ACTIVE_CYCLE"
CODE_ACTIVE_REQUEST_EXISTS = "ACTIVE_REQUEST_EXISTS"
CODE_CYCLE_NOT_ACTIVE = "CYCLE_NOT_ACTIVE"
CODE_TARGET_AMBIGUOUS = "TARGET_AMBIGUOUS"
CODE_SOLAR_UNAVAILABLE = "SOLAR_UNAVAILABLE"
# Issue #66 전용 — 그 외 4개 신규 endpoint의 오류는 전부 위 기존 코드를 재사용한다(계획 §10).
CODE_INVALID_REQUEST_STATE = "INVALID_REQUEST_STATE"
CODE_MALFORMED_REQUEST = "MALFORMED_REQUEST"

# CARD_ANSWER의 fieldValue(1개 필드)를 카드 normalized_payload에 patch할 때 그 필드가 실제로
# 건드리는 payload 키 목록. CHANGE_INPUT의 CREATE+REQUEST_ITEM changedFields patch와
# UPDATE 병합(`_merge_real_target_item`)에도 그대로 재사용한다(중복 정의 금지).
_ANSWER_FIELD_KEY_GROUPS = {
    "title": ["title"],
    "deadlineAt": ["deadlineAt"],
    "estimatedMinutes": ["estimatedMinutes", "estimatedMinutesSource"],
    "remainingMinutes": ["remainingMinutes"],
    "amount": ["amountText", "amountSource"],
    "startAt": ["startAt"],
    "endAt": ["endAt"],
}

_DEFAULT_QUESTION_MESSAGES = {
    "title": "제목을 알려주세요.",
    "deadlineAt": "마감이 언제인가요?",
    "estimatedMinutes": "예상 시간이 얼마나 걸릴까요?",
    "remainingMinutes": "남은 시간이 얼마나 될까요?",
    "amount": "분량이 얼마나 되나요?",
    "startAt": "시작 시각이 언제인가요?",
    "endAt": "종료 시각이 언제인가요?",
}

# amount/deadlineAt은 DONT_KNOW를 두 번째로 답해도(더 물어볼 방법이 없어) 서버가 확정적인
# "모름" 값으로 자동 해소한다. 그 외 필드(특히 estimatedMinutes)는 SOLAR가 attemptNumber>=2부터
# AI_ESTIMATED로 스스로 채우도록 프롬프트에서 지시하므로 서버가 임의 기본값을 만들지 않는다.
_AUTO_RESOLVE_ON_SECOND_DONT_KNOW = {
    "amount": {"amountText": None, "amountSource": "UNKNOWN"},
    "deadlineAt": {"deadlineAt": None},
}

_DELETABLE_REQUEST_STATUSES = (
    SolarRequestStatus.COLLECTING,
    SolarRequestStatus.CHANGE_CONFIRMATION,
    SolarRequestStatus.CHANGE_INPUT,
    SolarRequestStatus.FINAL_REVIEW,
    SolarRequestStatus.FAILED,
)

_RESTORABLE_IN_PROGRESS_STATUSES = (
    SolarRequestStatus.COLLECTING,
    SolarRequestStatus.CHANGE_CONFIRMATION,
    SolarRequestStatus.CHANGE_INPUT,
    SolarRequestStatus.FINAL_REVIEW,
    SolarRequestStatus.EXECUTING,
    SolarRequestStatus.FAILED,
)


def get_current_solar_request(db: Session, user_id: uuid.UUID) -> SolarRequest | None:
    """사용자가 복원해야 할 현재 SolarRequest 1건을 조회한다.

    solar_requests.uq_solar_requests_one_current_per_user partial unique index와 동일한 조건
    (작성 중 상태 전부 + FAILED + 미확인 COMPLETED)을 재사용하므로 최대 1건만 반환된다.
    확인 완료된 COMPLETED(result_acknowledged_at IS NOT NULL)는 더 이상 복원 대상이 아니므로 제외한다.

    messages/requestItems 등 요청 상세 조회는 이 함수의 책임이 아니다
    (GET /plan-management/state 구현 시 별도로 추가될 범위).
    """
    stmt = select(SolarRequest).where(
        SolarRequest.user_id == user_id,
        (SolarRequest.status.in_(_RESTORABLE_IN_PROGRESS_STATUSES))
        | (
            (SolarRequest.status == SolarRequestStatus.COMPLETED)
            & (SolarRequest.result_acknowledged_at.is_(None))
        ),
    )
    return db.execute(stmt).scalar_one_or_none()


def get_owned_solar_request(db: Session, request_id: uuid.UUID, user_id: uuid.UUID) -> SolarRequest:
    """소유권을 확인한 SolarRequest 1건을 조회한다. 상태·확인 여부와 무관하게(과거 완료 포함)
    본인 소유의 요청이면 조회할 수 있다. 없거나 타인 소유면 404 REQUEST_NOT_FOUND다."""
    stmt = select(SolarRequest).where(SolarRequest.id == request_id, SolarRequest.user_id == user_id)
    request = db.execute(stmt).scalar_one_or_none()
    if request is None:
        raise ApiError(404, CODE_REQUEST_NOT_FOUND, "요청을 찾을 수 없어요.")
    return request


class PlanManagementScreenMode(str, Enum):
    NEW_CYCLE_ENTRY = "NEW_CYCLE_ENTRY"
    ACTIVE_CYCLE_ENTRY = "ACTIVE_CYCLE_ENTRY"
    COLLECTING = "COLLECTING"
    CHANGE_CONFIRMATION = "CHANGE_CONFIRMATION"
    CHANGE_INPUT = "CHANGE_INPUT"
    FINAL_REVIEW = "FINAL_REVIEW"
    EXECUTING = "EXECUTING"
    EXECUTION_SUCCESS = "EXECUTION_SUCCESS"
    EXECUTION_FAILED = "EXECUTION_FAILED"


_IN_PROGRESS_STATUS_TO_SCREEN_MODE = {
    SolarRequestStatus.COLLECTING: PlanManagementScreenMode.COLLECTING,
    SolarRequestStatus.CHANGE_CONFIRMATION: PlanManagementScreenMode.CHANGE_CONFIRMATION,
    SolarRequestStatus.CHANGE_INPUT: PlanManagementScreenMode.CHANGE_INPUT,
    SolarRequestStatus.FINAL_REVIEW: PlanManagementScreenMode.FINAL_REVIEW,
    SolarRequestStatus.EXECUTING: PlanManagementScreenMode.EXECUTING,
    SolarRequestStatus.FAILED: PlanManagementScreenMode.EXECUTION_FAILED,
}


def resolve_current_request_screen_mode(request: SolarRequest) -> PlanManagementScreenMode:
    """get_current_solar_request가 반환한 요청의 상태를 화면 모드로 변환하는 순수 함수.

    COMPLETED는 get_current_solar_request의 조건상 이 함수에 들어올 때 항상
    result_acknowledged_at IS NULL이므로 무조건 EXECUTION_SUCCESS로 취급한다.
    """
    if request.status == SolarRequestStatus.COMPLETED:
        return PlanManagementScreenMode.EXECUTION_SUCCESS
    return _IN_PROGRESS_STATUS_TO_SCREEN_MODE[request.status]


def resolve_no_request_screen_mode(*, has_active_cycle: bool) -> PlanManagementScreenMode:
    """현재 복원할 요청이 없을 때(ACTIVE cycle 유무만으로) 계획관리 화면 모드를 결정하는 순수 함수."""
    return (
        PlanManagementScreenMode.ACTIVE_CYCLE_ENTRY
        if has_active_cycle
        else PlanManagementScreenMode.NEW_CYCLE_ENTRY
    )


@dataclass(frozen=True)
class CreateSolarRequestResult:
    state: "PlanManagementState"
    created: bool


def _find_first_user_message(
    db: Session, solar_request_id: uuid.UUID, client_event_id: str
) -> SolarMessage | None:
    stmt = select(SolarMessage).where(
        SolarMessage.solar_request_id == solar_request_id,
        SolarMessage.role == SolarMessageRole.USER,
        SolarMessage.kind == SolarMessageKind.TEXT,
        SolarMessage.sequence_no == 1,
        SolarMessage.client_event_id == client_event_id,
    )
    return db.execute(stmt).scalar_one_or_none()


def _ensure_idempotent_or_conflict(
    db: Session,
    current_request: SolarRequest,
    purpose: SolarRequestPurpose,
    canonical_message: str,
    canonical_client_event_id: str,
) -> None:
    """current_request가 이미 있을 때 호출한다. 동일 내용의 재전송이면 예외 없이 반환하고
    (호출부가 created=False로 처리), 다르면 409 ACTIVE_REQUEST_EXISTS를 raise한다."""
    existing_message = _find_first_user_message(db, current_request.id, canonical_client_event_id)
    if (
        existing_message is None
        or current_request.purpose != purpose
        or current_request.raw_input.strip() != canonical_message
    ):
        raise ApiError(409, CODE_ACTIVE_REQUEST_EXISTS, "이미 진행 중인 다른 요청이 있어요.")


def _validate_purpose_against_cycle(purpose, active_cycle) -> None:
    if purpose == SolarRequestPurpose.NEW_CYCLE and active_cycle is not None:
        raise ApiError(409, CODE_ACTIVE_CYCLE_EXISTS, "이미 진행 중인 계획 기간이 있어요.")
    if purpose == SolarRequestPurpose.ACTIVE_CYCLE and active_cycle is None:
        raise ApiError(409, CODE_NO_ACTIVE_CYCLE, "진행 중인 계획 기간이 없어요.")


def _fetch_candidate_tasks(db: Session, user_id: uuid.UUID, plan_cycle_id: uuid.UUID) -> list[dict]:
    stmt = select(Task).where(
        Task.user_id == user_id, Task.plan_cycle_id == plan_cycle_id, Task.status == TaskStatus.ACTIVE
    )
    tasks = db.execute(stmt).scalars().all()
    return [
        {
            "id": str(task.id),
            "title": task.title,
            "deadlineAt": task.deadline_at.isoformat() if task.deadline_at else None,
            "estimatedMinutes": task.estimated_minutes,
            "remainingMinutes": task.remaining_minutes,
            "amountText": task.amount_text,
        }
        for task in tasks
    ]


def _fetch_candidate_fixed_schedules(db: Session, user_id: uuid.UUID, plan_cycle_id: uuid.UUID) -> list[dict]:
    stmt = select(FixedSchedule).where(
        FixedSchedule.user_id == user_id, FixedSchedule.plan_cycle_id == plan_cycle_id
    )
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "id": str(fs.id),
            "title": fs.title,
            "startAt": fs.start_at.isoformat(),
            "endAt": fs.end_at.isoformat(),
        }
        for fs in rows
    ]


def _revalidate_target(
    db: Session,
    *,
    user_id: uuid.UUID,
    plan_cycle_id: uuid.UUID,
    entity_type: str,
    target_entity_id: str,
):
    target_id = uuid.UUID(target_entity_id)
    if entity_type == "TASK":
        stmt = select(Task).where(
            Task.id == target_id,
            Task.user_id == user_id,
            Task.plan_cycle_id == plan_cycle_id,
            Task.status == TaskStatus.ACTIVE,
        )
    else:
        stmt = select(FixedSchedule).where(
            FixedSchedule.id == target_id,
            FixedSchedule.user_id == user_id,
            FixedSchedule.plan_cycle_id == plan_cycle_id,
        )
    row = db.execute(stmt).scalar_one_or_none()
    if row is None:
        raise ApiError(409, CODE_TARGET_AMBIGUOUS, "요청을 분석하는 동안 대상이 바뀌었어요. 다시 시도해 주세요.")
    return row


def _backfill_update_payload(item, target_row, *, allow_invalid_fixed_schedule: bool = False) -> dict:
    payload = dict(item.normalized_payload)
    fields = set(item.update_fields)
    if item.entity_type == "TASK":
        if "title" not in fields:
            payload["title"] = target_row.title
        if "deadlineAt" not in fields:
            payload["deadlineAt"] = target_row.deadline_at.isoformat() if target_row.deadline_at else None
        if "estimatedMinutes" not in fields:
            payload["estimatedMinutes"] = target_row.estimated_minutes
            payload["estimatedMinutesSource"] = target_row.estimated_minutes_source.value
        if "remainingMinutes" not in fields:
            payload["remainingMinutes"] = target_row.remaining_minutes
        if "amount" not in fields:
            payload["amountText"] = target_row.amount_text
            payload["amountSource"] = target_row.amount_source.value
    else:
        if "title" not in fields:
            payload["title"] = target_row.title
        if "startAt" not in fields:
            payload["startAt"] = target_row.start_at.isoformat()
        if "endAt" not in fields:
            payload["endAt"] = target_row.end_at.isoformat()
        if (not allow_invalid_fixed_schedule
                and datetime.fromisoformat(payload["endAt"]) <= datetime.fromisoformat(payload["startAt"])):
            raise ApiError(503, CODE_SOLAR_UNAVAILABLE, "SOLAR 분석에 실패했어요. 잠시 후 다시 시도해 주세요.")
    return payload


def _snapshot_for_delete(entity_type: str, target_row) -> dict:
    if entity_type == "TASK":
        return {
            "title": target_row.title,
            "deadlineAt": target_row.deadline_at.isoformat() if target_row.deadline_at else None,
            "estimatedMinutes": target_row.estimated_minutes,
            "estimatedMinutesSource": target_row.estimated_minutes_source.value,
            "remainingMinutes": target_row.remaining_minutes,
            "amountText": target_row.amount_text,
            "amountSource": target_row.amount_source.value,
        }
    return {
        "title": target_row.title,
        "startAt": target_row.start_at.isoformat(),
        "endAt": target_row.end_at.isoformat(),
    }


def _persist_analysis(
    db: Session,
    *,
    user_id: uuid.UUID,
    purpose: SolarRequestPurpose,
    canonical_message: str,
    canonical_client_event_id: str,
    plan_cycle_id: uuid.UUID | None,
    analysis,
    candidate_tasks: list[dict],
    candidate_fixed_schedules: list[dict],
) -> SolarRequest:
    resolved_items: list[tuple] = []
    for item in analysis.items:
        if item.action == "CREATE":
            final_payload = dict(item.normalized_payload)
            if item.entity_type == "TASK":
                final_payload["remainingMinutes"] = final_payload.get("estimatedMinutes")
        else:
            target_row = _revalidate_target(
                db,
                user_id=user_id,
                plan_cycle_id=plan_cycle_id,
                entity_type=item.entity_type,
                target_entity_id=item.target_entity_id,
            )
            if item.action == "UPDATE":
                final_payload = _backfill_update_payload(item, target_row)
            else:
                final_payload = _snapshot_for_delete(item.entity_type, target_row)
        resolved_items.append((item, final_payload))

    has_missing = any(item.missing_fields for item, _ in resolved_items)
    if analysis.unresolved_line is not None:
        request_status = SolarRequestStatus.COLLECTING
        current_item_order = None
    elif has_missing:
        request_status = SolarRequestStatus.COLLECTING
        current_item_order = next(
            (idx + 1 for idx, (item, _) in enumerate(resolved_items) if item.missing_fields), None
        )
    else:
        request_status = SolarRequestStatus.CHANGE_CONFIRMATION
        current_item_order = None

    request = SolarRequest(
        id=uuid.uuid4(),
        user_id=user_id,
        plan_cycle_id=plan_cycle_id,
        purpose=purpose,
        status=request_status,
        raw_input=canonical_message,
        current_item_order=current_item_order,
        execution_attempt_count=0,
    )
    db.add(request)
    db.flush()

    created_db_items: list = []
    for item_order, (item, final_payload) in enumerate(resolved_items, start=1):
        status = SolarItemStatus.INFO_MISSING if item.missing_fields else SolarItemStatus.READY
        stored_payload = dict(final_payload)
        if item.action == "UPDATE":
            stored_payload["_updateFields"] = item.update_fields

        db_item = SolarRequestItem(
            id=uuid.uuid4(),
            user_id=user_id,
            solar_request_id=request.id,
            item_order=item_order,
            action=SolarAction(item.action),
            entity_type=SolarEntityType(item.entity_type),
            status=status,
            raw_line_text=item.raw_line_text,
            normalized_payload=stored_payload,
            missing_fields=list(item.missing_fields),
            pending_question=item.pending_question,
            target_task_id=uuid.UUID(item.target_entity_id)
            if item.entity_type == "TASK" and item.target_entity_id
            else None,
            target_fixed_schedule_id=uuid.UUID(item.target_entity_id)
            if item.entity_type == "FIXED_SCHEDULE" and item.target_entity_id
            else None,
            executed_at=None,
        )
        db.add(db_item)
        created_db_items.append(db_item)
    db.flush()

    from app.services import plan_management_service

    initial_snapshot_metadata = _build_request_item_snapshot_metadata(
        created_db_items, plan_management_service=plan_management_service
    )

    db.add(
        SolarMessage(
            id=uuid.uuid4(),
            user_id=user_id,
            solar_request_id=request.id,
            client_event_id=canonical_client_event_id,
            sequence_no=1,
            role=SolarMessageRole.USER,
            kind=SolarMessageKind.TEXT,
            content=canonical_message,
            message_metadata={},
        )
    )
    db.add(
        SolarMessage(
            id=uuid.uuid4(),
            user_id=user_id,
            solar_request_id=request.id,
            client_event_id=None,
            sequence_no=2,
            role=SolarMessageRole.ASSISTANT,
            kind=SolarMessageKind.TEXT,
            content=analysis.analysis_message,
            message_metadata=initial_snapshot_metadata,
        )
    )
    next_seq = 3
    if analysis.unresolved_line is not None:
        unresolved = analysis.unresolved_line
        candidates = candidate_tasks if unresolved.entity_type == "TASK" else candidate_fixed_schedules
        db.add(
            SolarMessage(
                id=uuid.uuid4(),
                user_id=user_id,
                solar_request_id=request.id,
                client_event_id=None,
                sequence_no=next_seq,
                role=SolarMessageRole.ASSISTANT,
                kind=SolarMessageKind.QUESTION,
                content=unresolved.message,
                message_metadata={
                    "unresolved": True,
                    "field": "targetEntityId",
                    "rawLineText": unresolved.raw_line_text,
                    "action": unresolved.action,
                    "entityType": unresolved.entity_type,
                    "candidateEntityIds": [c["id"] for c in candidates],
                },
            )
        )
    elif current_item_order is not None:
        current_db_item = created_db_items[current_item_order - 1]
        if current_db_item.pending_question is not None:
            db.add(
                SolarMessage(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    solar_request_id=request.id,
                    client_event_id=None,
                    sequence_no=next_seq,
                    role=SolarMessageRole.ASSISTANT,
                    kind=SolarMessageKind.QUESTION,
                    content=current_db_item.pending_question["message"],
                    message_metadata={
                        "itemId": str(current_db_item.id),
                        "field": current_db_item.pending_question["field"],
                    },
                )
            )
    db.flush()
    return request


def create_solar_request(
    db: Session,
    *,
    user_id: uuid.UUID,
    purpose: SolarRequestPurpose,
    client_event_id: str,
    message: str,
    now: datetime,
) -> CreateSolarRequestResult:
    canonical_message = message.strip()
    canonical_client_event_id = client_event_id.strip()

    cycle_id: uuid.UUID | None = None
    cycle_start: date | None = None
    cycle_end: date | None = None
    candidate_tasks: list[dict] = []
    candidate_fixed_schedules: list[dict] = []

    # 1. 읽기 트랜잭션
    with db.begin():
        current_request = get_current_solar_request(db, user_id)
        if current_request is not None:
            _ensure_idempotent_or_conflict(
                db, current_request, purpose, canonical_message, canonical_client_event_id
            )
            from app.services import plan_management_service

            state = plan_management_service.get_plan_management_state(db, user_id)
            return CreateSolarRequestResult(state=state, created=False)

        active_cycle = plan_block_service.get_active_planning_cycle(db, user_id)
        _validate_purpose_against_cycle(purpose, active_cycle)

        if purpose == SolarRequestPurpose.ACTIVE_CYCLE:
            cycle_id = active_cycle.id
            cycle_start = active_cycle.start_date
            cycle_end = active_cycle.end_date
            candidate_tasks = _fetch_candidate_tasks(db, user_id, cycle_id)
            candidate_fixed_schedules = _fetch_candidate_fixed_schedules(db, user_id, cycle_id)

    # 2. SOLAR 호출(트랜잭션 밖)
    try:
        analysis = solar_client.analyze_message(
            canonical_message,
            now=now,
            purpose=purpose,
            cycle_start=cycle_start,
            cycle_end=cycle_end,
            candidate_tasks=candidate_tasks,
            candidate_fixed_schedules=candidate_fixed_schedules,
        )
    except solar_client.SolarUnavailableError as exc:
        raise ApiError(503, CODE_SOLAR_UNAVAILABLE, "SOLAR 분석에 실패했어요. 잠시 후 다시 시도해 주세요.") from exc

    # 3. 쓰기 트랜잭션
    created: bool
    try:
        with db.begin():
            current_request_now = get_current_solar_request(db, user_id)
            if current_request_now is not None:
                _ensure_idempotent_or_conflict(
                    db, current_request_now, purpose, canonical_message, canonical_client_event_id
                )
                created = False
            else:
                active_cycle_now = plan_block_service.get_active_planning_cycle(db, user_id)
                _validate_purpose_against_cycle(purpose, active_cycle_now)
                if purpose == SolarRequestPurpose.ACTIVE_CYCLE and active_cycle_now.id != cycle_id:
                    raise ApiError(409, CODE_CYCLE_NOT_ACTIVE, "계획 기간이 변경됐어요. 다시 시도해 주세요.")

                _persist_analysis(
                    db,
                    user_id=user_id,
                    purpose=purpose,
                    canonical_message=canonical_message,
                    canonical_client_event_id=canonical_client_event_id,
                    plan_cycle_id=cycle_id if purpose == SolarRequestPurpose.ACTIVE_CYCLE else None,
                    analysis=analysis,
                    candidate_tasks=candidate_tasks,
                    candidate_fixed_schedules=candidate_fixed_schedules,
                )
                created = True
    except IntegrityError as exc:
        constraint_name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint_name not in {
            "uq_solar_requests_one_current_per_user",
            "uq_solar_messages_client_event",
        }:
            raise
        with db.begin():
            current_request_after_conflict = get_current_solar_request(db, user_id)
            if current_request_after_conflict is None:
                raise ApiError(409, CODE_ACTIVE_REQUEST_EXISTS, "이미 진행 중인 다른 요청이 있어요.") from exc
            _ensure_idempotent_or_conflict(
                db, current_request_after_conflict, purpose, canonical_message, canonical_client_event_id
            )
            created = False

    from app.services import plan_management_service

    state = plan_management_service.get_plan_management_state(db, user_id)
    return CreateSolarRequestResult(state=state, created=created)


# ---------------------------------------------------------------------------
# Issue #66 — /messages, /decisions, /reopen, DELETE 공용 헬퍼
# ---------------------------------------------------------------------------


def _lock_owned_solar_request(db: Session, request_id: uuid.UUID, user_id: uuid.UUID) -> SolarRequest:
    """`SELECT ... FOR UPDATE`로 같은 요청에 대한 동시 쓰기를 직렬화한다. 4개 신규 endpoint의
    쓰기 트랜잭션은 모두 이 함수로 시작해, item/message 테이블에 별도 row lock 없이도 같은
    요청을 대상으로 한 동시 mutation을 사실상 하나의 mutex로 묶는다."""
    stmt = (
        select(SolarRequest)
        .where(SolarRequest.id == request_id, SolarRequest.user_id == user_id)
        .with_for_update()
    )
    request = db.execute(stmt).scalar_one_or_none()
    if request is None:
        raise ApiError(404, CODE_REQUEST_NOT_FOUND, "요청을 찾을 수 없어요.")
    return request


def _load_items(db: Session, solar_request_id: uuid.UUID) -> list[SolarRequestItem]:
    stmt = (
        select(SolarRequestItem)
        .where(SolarRequestItem.solar_request_id == solar_request_id)
        .order_by(SolarRequestItem.item_order.asc())
    )
    return list(db.execute(stmt).scalars().all())


def _load_messages(db: Session, solar_request_id: uuid.UUID) -> list[SolarMessage]:
    stmt = (
        select(SolarMessage)
        .where(SolarMessage.solar_request_id == solar_request_id)
        .order_by(SolarMessage.sequence_no.asc())
    )
    return list(db.execute(stmt).scalars().all())


def _find_message_by_client_event_id(
    db: Session, solar_request_id: uuid.UUID, client_event_id: str
) -> SolarMessage | None:
    stmt = select(SolarMessage).where(
        SolarMessage.solar_request_id == solar_request_id, SolarMessage.client_event_id == client_event_id
    )
    return db.execute(stmt).scalar_one_or_none()


def _next_base_sequence_no(db: Session, solar_request_id: uuid.UUID) -> int:
    stmt = select(func.max(SolarMessage.sequence_no)).where(SolarMessage.solar_request_id == solar_request_id)
    current_max = db.execute(stmt).scalar_one()
    return (current_max or 0) + 1


def _persist_ordered_messages(
    db: Session, *, user_id: uuid.UUID, request: SolarRequest, entries: list[dict]
) -> None:
    """`entries`는 이미 순서가 확정된 메시지 사양 목록(각 dict는 SolarMessage 생성자 kwargs에서
    sequence_no만 뺀 것)이다. sequence_no는 여기 한 곳에서만, 이 순서 그대로 배정한다 — 분기마다
    개별 배정하지 않는다(USER TEXT/DECISION → 선택적 ASSISTANT TEXT → 선택적 ASSISTANT
    QUESTION 순서를 호출부가 이미 이 리스트 순서로 보장한다)."""
    next_seq = _next_base_sequence_no(db, request.id)
    for entry in entries:
        db.add(
            SolarMessage(
                id=uuid.uuid4(),
                user_id=user_id,
                solar_request_id=request.id,
                sequence_no=next_seq,
                **entry,
            )
        )
        next_seq += 1
    db.flush()


def _build_request_item_snapshot_metadata(
    items: list[SolarRequestItem], *, plan_management_service=None
) -> dict:
    if not items:
        return {}
    if plan_management_service is None:
        from app.services import plan_management_service as display_service
    else:
        display_service = plan_management_service
    snapshots = []
    for item in sorted(items, key=lambda value: value.item_order):
        snapshot = display_service.build_request_item_snapshot_value(item)
        snapshots.append({"snapshotId": str(uuid.uuid4()), **snapshot})
    return {"snapshotVersion": 1, "requestItemSnapshots": snapshots}


def _snapshot_change_fingerprint(item: SolarRequestItem, *, plan_management_service) -> dict:
    value = plan_management_service.build_request_item_snapshot_value(item)
    # itemOrder 재번호만으로 변경 snapshot을 만들지 않는다. 실제 카드 표시값 변경만 추적한다.
    return {key: field for key, field in value.items() if key != "itemOrder"}


def _find_changed_snapshot_items(
    items: list[SolarRequestItem], before_values: dict[uuid.UUID, dict], *, plan_management_service
) -> list[SolarRequestItem]:
    return [
        item
        for item in items
        if before_values.get(item.id)
        != _snapshot_change_fingerprint(item, plan_management_service=plan_management_service)
    ]


def _find_item_by_id(item_id: str, items: list[SolarRequestItem]) -> SolarRequestItem | None:
    try:
        target_uuid = uuid.UUID(item_id)
    except (ValueError, TypeError):
        return None
    return next((item for item in items if item.id == target_uuid), None)


def _build_candidate_request_items(items: list[SolarRequestItem]) -> dict[str, dict]:
    """CHANGE_INPUT/UNRESOLVED_ANSWER SOLAR 호출의 candidateRequestItems — 파서 검증용
    entityType/action에 더해 프롬프트 컨텍스트로도 쓸 rawLineText/normalizedPayload를 포함한다."""
    return {
        str(item.id): {
            "entityType": item.entity_type.value,
            "action": item.action.value,
            "rawLineText": item.raw_line_text,
            "normalizedPayload": {k: v for k, v in item.normalized_payload.items() if k != "_updateFields"},
        }
        for item in items
    }


def _filter_request_item_candidates(action: str, entity_type: str, items: list[SolarRequestItem]) -> dict[str, dict]:
    """원래 모호했던 참조의 action이 UPDATE면 현재 action=CREATE인 카드만(기존 대기 CREATE 카드
    수정), DELETE면 action 무관 전부를 REQUEST_ITEM 후보로 제공한다(최종 반영 #3)."""
    result = {}
    for item in items:
        if item.entity_type.value != entity_type:
            continue
        if action == "UPDATE" and item.action != SolarAction.CREATE:
            continue
        result[str(item.id)] = {"entityType": item.entity_type.value, "action": item.action.value}
    return result


def _missing_order_action_for(item: SolarRequestItem) -> str:
    """TASK CREATE 카드는(신규든 CHANGE_INPUT patch로 title까지 다시 비워졌든) 항상 title을
    포함하는 CREATE_MERGE 순서를 써도 안전하다 — title이 실제로 missing이 아니면 그 순서에서
    자연히 건너뛰어진다."""
    if item.action == SolarAction.CREATE:
        return "CREATE_MERGE"
    return item.action.value


def _ensure_pending_question(card: SolarRequestItem) -> None:
    """INFO_MISSING 카드인데 pending_question이 없거나 손상됐으면(필드가 missing_fields에 없음,
    canonical 첫 필드가 아님, 메시지 공백, attemptCount가 1 이상 정수가 아님) canonical
    missing-order 첫 필드로 복구한다. current_item_order가 INFO_MISSING 카드를 가리키는데
    currentQuestion이 없는 상태를 만들지 않기 위한 마지막 방어선(최종 반영 #6)."""
    if card.status != SolarItemStatus.INFO_MISSING:
        return

    order = solar_client.missing_order_for(card.entity_type.value, _missing_order_action_for(card))
    canonical_first = next((f for f in order if f in card.missing_fields), None)
    if canonical_first is None:
        raise ApiError(500, "INTERNAL_ERROR", "카드 상태가 손상됐어요.")

    pending = card.pending_question
    field = pending.get("field") if isinstance(pending, dict) else None
    message = pending.get("message") if isinstance(pending, dict) else None
    attempt_count = pending.get("attemptCount") if isinstance(pending, dict) else None
    valid = (
        field == canonical_first
        and isinstance(message, str)
        and message.strip()
        and isinstance(attempt_count, int)
        and not isinstance(attempt_count, bool)
        and attempt_count >= 1
    )
    if valid:
        return
    card.pending_question = {
        "field": canonical_first,
        "message": _DEFAULT_QUESTION_MESSAGES[canonical_first],
        "attemptCount": 1,
    }


def _advance_card_after_field_resolved(
    card: SolarRequestItem, request: SolarRequest, remaining_missing_fields: list[str]
) -> tuple[str | None, str | None]:
    """카드 하나 범위의 진행: 이 카드에 아직 missing 필드가 남아있으면 같은 카드의 다음 필드를
    질문하고(QUESTION), 이 카드가 다 채워졌으면(READY) None을 반환해 호출자가
    `_recompute_request_collecting_state`로 요청 전체 범위 재계산을 이어가게 한다. 두 번째
    DONT_KNOW 자동 해소 후에도 그대로 재사용된다."""
    order = solar_client.missing_order_for(card.entity_type.value, _missing_order_action_for(card))
    ordered_remaining = [f for f in order if f in remaining_missing_fields]
    card.missing_fields = ordered_remaining
    if ordered_remaining:
        first = ordered_remaining[0]
        card.status = SolarItemStatus.INFO_MISSING
        card.pending_question = {"field": first, "message": _DEFAULT_QUESTION_MESSAGES[first], "attemptCount": 1}
        request.status = SolarRequestStatus.COLLECTING
        request.current_item_order = card.item_order
        return SolarMessageKind.QUESTION.value, card.pending_question["message"]
    card.status = SolarItemStatus.READY
    card.pending_question = None
    return None, None


def _recompute_request_collecting_state(
    request: SolarRequest, all_items: list[SolarRequestItem]
) -> tuple[str | None, str | None]:
    """요청 전체 범위의 진행: 남은 카드가 0개면(CHANGE_INPUT에서 마지막 카드를 지운 경우 등)
    CHANGE_CONFIRMATION으로 넘어가지 않고 CHANGE_INPUT을 유지하며 안내 메시지를 반환한다.
    INFO_MISSING 카드가 남아있으면 item_order가 가장 앞선 카드로 이동, 없으면
    CHANGE_CONFIRMATION으로 전이한다."""
    if not all_items:
        request.status = SolarRequestStatus.CHANGE_INPUT
        request.current_item_order = None
        return SolarMessageKind.TEXT.value, "카드가 모두 사라졌어요. 추가하거나 수정할 내용을 입력해 주세요."

    ordered = sorted(all_items, key=lambda i: i.item_order)
    next_missing = next((i for i in ordered if i.status == SolarItemStatus.INFO_MISSING), None)
    if next_missing is not None:
        _ensure_pending_question(next_missing)
        request.status = SolarRequestStatus.COLLECTING
        request.current_item_order = next_missing.item_order
        return SolarMessageKind.QUESTION.value, next_missing.pending_question["message"]

    request.status = SolarRequestStatus.CHANGE_CONFIRMATION
    request.current_item_order = None
    return None, None


def _build_trailing_question_entry(request: SolarRequest, items: list[SolarRequestItem]) -> dict:
    """`_advance_card_after_field_resolved`/`_recompute_request_collecting_state`가 QUESTION을
    반환했을 때, request.current_item_order가 가리키는 카드에서 메시지 metadata(itemId/field)를
    역으로 구성한다 — 두 헬퍼의 반환 타입을 계획에 정의된 `tuple[str|None, str|None]` 그대로
    유지하기 위해 metadata 조립은 호출부 공용 로직으로 분리했다."""
    if request.current_item_order is None:
        return {}
    card = next((i for i in items if i.item_order == request.current_item_order), None)
    if card is None or not isinstance(card.pending_question, dict):
        return {}
    return {"itemId": str(card.id), "field": card.pending_question.get("field")}


def _sync_remaining_minutes_for_create(payload: dict, entity_type: str, action: SolarAction) -> dict:
    if entity_type == "TASK" and action == SolarAction.CREATE:
        payload = dict(payload)
        payload["remainingMinutes"] = payload.get("estimatedMinutes")
    return payload


def _renumber_items_after_delete(db: Session, remaining_items_sorted: list[SolarRequestItem]) -> None:
    """UNIQUE(solar_request_id, item_order) 제약을 그 자리에서 위반하지 않도록, 겹치지 않는 양수
    임시 구간(max_order_before+1..+N, N<=삭제 전 카드 수이므로 항상 max_order_before보다 작거나
    같아 수학적으로 겹치지 않는다)으로 먼저 옮긴 뒤(flush) 최종 1..N으로 다시 배정한다(flush).
    음수 임시값은 쓰지 않는다(v3→v4 라운드에서 명시적으로 거부됨)."""
    if not remaining_items_sorted:
        return
    max_order_before = max(item.item_order for item in remaining_items_sorted)
    if max_order_before + len(remaining_items_sorted) > 32767:
        raise ApiError(500, "INTERNAL_ERROR", "카드 개수가 너무 많아요.")
    for offset, item in enumerate(remaining_items_sorted, start=1):
        item.item_order = max_order_before + offset
    db.flush()
    for final_order, item in enumerate(remaining_items_sorted, start=1):
        item.item_order = final_order
    db.flush()


def _apply_create_merge_patch(
    referenced_item: SolarRequestItem,
    changed_fields: list[str],
    canonical_patch_payload: dict,
    parsed_patch_missing_fields: list[str],
) -> None:
    """대기 중인 CREATE 카드에 changedFields로 지정된 필드만 patch한다. missing 여부는 절대
    normalized_payload 값(예: deadlineAt is None)으로 재추정하지 않고, 호출자가 파서 결과에서
    이미 계산해 넘긴 parsed_patch_missing_fields(changedFields 범위 안에서만 유효한 missing
    목록)를 그대로 쓴다 — "마감 없음 확정"과 "아직 모름"이 deadlineAt=null 하나로 뒤섞이지
    않도록 한다(최종 반영 #3)."""
    new_payload = dict(referenced_item.normalized_payload)
    for field in changed_fields:
        for key in _ANSWER_FIELD_KEY_GROUPS[field]:
            new_payload[key] = canonical_patch_payload[key]
    new_payload = _sync_remaining_minutes_for_create(new_payload, referenced_item.entity_type.value, referenced_item.action)
    referenced_item.normalized_payload = new_payload

    remaining_missing = {f for f in referenced_item.missing_fields if f not in changed_fields}
    combined = remaining_missing | set(parsed_patch_missing_fields)
    order = solar_client.missing_order_for(referenced_item.entity_type.value, "CREATE_MERGE")
    new_missing = [f for f in order if f in combined]
    referenced_item.missing_fields = new_missing
    if new_missing:
        first = new_missing[0]
        referenced_item.status = SolarItemStatus.INFO_MISSING
        referenced_item.pending_question = {
            "field": first,
            "message": _DEFAULT_QUESTION_MESSAGES[first],
            "attemptCount": 1,
        }
    else:
        referenced_item.status = SolarItemStatus.READY
        referenced_item.pending_question = None


def _merge_real_target_item(
    existing_item: SolarRequestItem,
    new_action: str,
    new_payload: dict,
    new_update_fields: list[str],
    new_missing_fields: list[str],
    new_pending_question: dict | None,
    new_raw_line_text: str,
) -> None:
    """실제 엔티티(targetKind=ENTITY)를 겨냥하는 카드 병합 규칙(대칭): 최신 action이 항상
    이기고, UPDATE+UPDATE만 `_updateFields`를 합집합한다. anything+DELETE는 DELETE가 되고,
    DELETE+UPDATE는 명시적으로 UPDATE가 된다(v1→v2 라운드에서 새 UPDATE를 무시하던 버그를
    수정)."""
    if new_action == "DELETE":
        existing_item.action = SolarAction.DELETE
        existing_item.normalized_payload = dict(new_payload)
        existing_item.missing_fields = []
        existing_item.pending_question = None
        existing_item.status = SolarItemStatus.READY
        existing_item.raw_line_text = new_raw_line_text
        return

    # new_action == "UPDATE"
    if existing_item.action == SolarAction.DELETE:
        merged_payload = dict(new_payload)
        merged_update_fields = list(new_update_fields)
    else:  # 기존이 UPDATE — 필드 합집합
        existing_fields = set(existing_item.normalized_payload.get("_updateFields", []))
        merged_payload = dict(existing_item.normalized_payload)
        for field in new_update_fields:
            for key in _ANSWER_FIELD_KEY_GROUPS[field]:
                merged_payload[key] = new_payload[key]
        merged_update_fields = sorted(existing_fields | set(new_update_fields))

    merged_payload["_updateFields"] = merged_update_fields
    existing_item.normalized_payload = merged_payload
    existing_item.action = SolarAction.UPDATE
    existing_item.raw_line_text = new_raw_line_text

    combined_missing = {f for f in existing_item.missing_fields if f in merged_update_fields}
    combined_missing |= set(new_missing_fields)
    order = solar_client.missing_order_for(existing_item.entity_type.value, "UPDATE")
    final_missing = [f for f in order if f in combined_missing and f in merged_update_fields]
    existing_item.missing_fields = final_missing
    if final_missing:
        first = final_missing[0]
        if isinstance(new_pending_question, dict) and new_pending_question.get("field") == first:
            existing_item.pending_question = new_pending_question
        else:
            existing_item.pending_question = {
                "field": first,
                "message": _DEFAULT_QUESTION_MESSAGES[first],
                "attemptCount": 1,
            }
        existing_item.status = SolarItemStatus.INFO_MISSING
    else:
        existing_item.status = SolarItemStatus.READY
        existing_item.pending_question = None


def _validate_unresolved_metadata(metadata: dict) -> tuple[str, str, str, str, list[str]]:
    """반환: (target_kind, action, entity_type, raw_line_text, candidate_ids). #50 시절
    메시지는 targetKind 키 자체가 없어 "ENTITY"로 간주한다(하위 호환)."""
    target_kind = metadata.get("targetKind", "ENTITY")
    action = metadata.get("action")
    entity_type = metadata.get("entityType")
    raw_line_text = metadata.get("rawLineText")
    candidate_key = "candidateRequestItemIds" if target_kind == "REQUEST_ITEM" else "candidateEntityIds"
    candidate_ids = metadata.get(candidate_key)
    if (
        target_kind not in ("ENTITY", "REQUEST_ITEM")
        or action not in ("UPDATE", "DELETE")
        or entity_type not in ("TASK", "FIXED_SCHEDULE")
        or not isinstance(raw_line_text, str)
        or not raw_line_text.strip()
        or not isinstance(candidate_ids, list)
        or not all(isinstance(c, str) for c in candidate_ids)
    ):
        raise ApiError(409, CODE_INVALID_REQUEST_STATE, "저장된 질문 정보가 손상됐어요.")
    return target_kind, action, entity_type, raw_line_text, candidate_ids


def _validate_change_details_metadata(metadata: dict) -> tuple[str, str, str, str, str]:
    """반환: (target_kind, action, entity_type, target_entity_id, raw_line_text)."""
    target_kind = metadata.get("targetKind")
    action = metadata.get("action")
    entity_type = metadata.get("entityType")
    target_entity_id = metadata.get("targetEntityId")
    raw_line_text = metadata.get("rawLineText")
    if (
        target_kind not in ("ENTITY", "REQUEST_ITEM")
        or action not in ("UPDATE",)
        or entity_type not in ("TASK", "FIXED_SCHEDULE")
        or not isinstance(target_entity_id, str)
        or not target_entity_id.strip()
        or not isinstance(raw_line_text, str)
        or not raw_line_text.strip()
    ):
        raise ApiError(409, CODE_INVALID_REQUEST_STATE, "저장된 질문 정보가 손상됐어요.")
    return target_kind, action, entity_type, target_entity_id, raw_line_text


def _live_candidate_ids_for_unresolved(
    db: Session,
    request: SolarRequest,
    *,
    target_kind: str,
    action: str,
    entity_type: str,
    stored_candidate_ids: list[str],
    items: list[SolarRequestItem],
) -> list[str]:
    """읽기 시점에 저장된 후보 id 목록을, 지금 시점에도 여전히 유효한 것만으로 좁힌다 — SOLAR를
    호출하기 전에(API 호출을 아끼기 위해) 대상이 전부 사라졌는지 먼저 확인한다."""
    if target_kind == "REQUEST_ITEM":
        live = _filter_request_item_candidates(action, entity_type, items)
        return [cid for cid in stored_candidate_ids if cid in live]
    if entity_type == "TASK":
        candidates = _fetch_candidate_tasks(db, request.user_id, request.plan_cycle_id)
    else:
        candidates = _fetch_candidate_fixed_schedules(db, request.user_id, request.plan_cycle_id)
    live_ids = {c["id"] for c in candidates}
    return [cid for cid in stored_candidate_ids if cid in live_ids]


@dataclass(frozen=True)
class _MessageDispatch:
    kind: str  # "CARD" | "UNRESOLVED" | "CHANGE_DETAILS" | "CHANGE_INPUT"
    card: SolarRequestItem | None = None
    special_message: SolarMessage | None = None


def _resolve_message_dispatch(
    request: SolarRequest, items: list[SolarRequestItem], messages: list[SolarMessage]
) -> _MessageDispatch:
    """`/messages`가 이번 답변을 어떤 SOLAR 진입점으로 보낼지 결정한다. 카드 없는 특수 질문
    (unresolved 대상 모호, CHANGE_DETAILS 대상 확정+내용 미정)은 COLLECTING일 때만, 그리고 항상
    카드 기반 질문보다 우선한다(최종 반영 #2). CHANGE_INPUT은 상태 자체로 별도 분기한다."""
    if request.status == SolarRequestStatus.COLLECTING:
        from app.services.plan_management_service import _find_special_question_message

        special = _find_special_question_message(messages)
        if special is not None:
            metadata = special.message_metadata
            kind = "CHANGE_DETAILS" if isinstance(metadata, dict) and metadata.get("followUpType") == "CHANGE_DETAILS" else "UNRESOLVED"
            return _MessageDispatch(kind=kind, special_message=special)

        pending_item = next(
            (
                item
                for item in items
                if request.current_item_order is not None
                and item.item_order == request.current_item_order
                and item.status == SolarItemStatus.INFO_MISSING
            ),
            None,
        )
        if pending_item is None:
            raise ApiError(409, CODE_INVALID_REQUEST_STATE, "지금은 답변을 받을 카드가 없어요.")
        return _MessageDispatch(kind="CARD", card=pending_item)

    if request.status == SolarRequestStatus.CHANGE_INPUT:
        return _MessageDispatch(kind="CHANGE_INPUT")

    raise ApiError(409, CODE_INVALID_REQUEST_STATE, "지금은 답변을 받을 수 없는 상태예요.")


def _card_context_for_prompt(card: SolarRequestItem) -> dict:
    payload = {k: v for k, v in card.normalized_payload.items() if k != "_updateFields"}
    return {"rawLineText": card.raw_line_text, "currentPayload": payload}


def _apply_card_answer_provided(card: SolarRequestItem, field: str, field_value: dict) -> list[str]:
    """카드 payload에 답변값을 patch하고 이 필드를 제거한 remaining_missing_fields를 반환한다
    (실제 상태 전이는 호출자가 `_advance_card_after_field_resolved`로 이어서 처리)."""
    new_payload = dict(card.normalized_payload)
    for key in _ANSWER_FIELD_KEY_GROUPS[field]:
        if key in field_value:
            new_payload[key] = field_value[key]
    new_payload = _sync_remaining_minutes_for_create(new_payload, card.entity_type.value, card.action)
    card.normalized_payload = new_payload
    return [f for f in card.missing_fields if f != field]


def _apply_card_answer_dont_know(
    card: SolarRequestItem, field: str, question_message: str
) -> tuple[bool, list[str] | None]:
    """반환: (자동 해소 여부, 자동 해소라면 remaining_missing_fields). 자동 해소가 아니면
    card.pending_question의 attemptCount만 올리고 (False, None)을 반환한다."""
    pending = card.pending_question if isinstance(card.pending_question, dict) else {}
    attempt_count = pending.get("attemptCount", 1)
    if not isinstance(attempt_count, int) or isinstance(attempt_count, bool):
        attempt_count = 1

    auto_resolve = _AUTO_RESOLVE_ON_SECOND_DONT_KNOW.get(field)
    if attempt_count >= 2 and auto_resolve is not None:
        new_payload = dict(card.normalized_payload)
        new_payload.update(auto_resolve)
        card.normalized_payload = new_payload
        return True, [f for f in card.missing_fields if f != field]

    card.pending_question = {"field": field, "message": question_message, "attemptCount": attempt_count + 1}
    return False, None


def _apply_card_answer_unclear(card: SolarRequestItem, field: str, question_message: str) -> None:
    pending = card.pending_question if isinstance(card.pending_question, dict) else {}
    attempt_count = pending.get("attemptCount", 1)
    if not isinstance(attempt_count, int) or isinstance(attempt_count, bool):
        attempt_count = 1
    card.pending_question = {"field": field, "message": question_message, "attemptCount": attempt_count}


def _create_new_item_from_analysis(
    db: Session,
    *,
    user_id: uuid.UUID,
    request: SolarRequest,
    items: list[SolarRequestItem],
    action: str,
    entity_type: str,
    raw_line_text: str,
    final_payload: dict,
    missing_fields: list[str],
    pending_question: dict | None,
    update_fields: list[str],
    target_entity_id: str | None,
) -> SolarRequestItem:
    max_order = max((i.item_order for i in items), default=0) + 1
    stored_payload = dict(final_payload)
    if action == "UPDATE":
        stored_payload["_updateFields"] = update_fields
    target_uuid = uuid.UUID(target_entity_id) if target_entity_id else None
    db_item = SolarRequestItem(
        id=uuid.uuid4(),
        user_id=user_id,
        solar_request_id=request.id,
        item_order=max_order,
        action=SolarAction(action),
        entity_type=SolarEntityType(entity_type),
        status=SolarItemStatus.INFO_MISSING if missing_fields else SolarItemStatus.READY,
        raw_line_text=raw_line_text,
        normalized_payload=stored_payload,
        missing_fields=list(missing_fields),
        pending_question=pending_question,
        target_task_id=target_uuid if entity_type == "TASK" else None,
        target_fixed_schedule_id=target_uuid if entity_type == "FIXED_SCHEDULE" else None,
        executed_at=None,
    )
    db.add(db_item)
    items.append(db_item)
    return db_item


def _find_existing_item_for_real_target(
    entity_type: str, target_entity_id: str, items: list[SolarRequestItem]
) -> SolarRequestItem | None:
    target_uuid = uuid.UUID(target_entity_id)
    return next(
        (
            i
            for i in items
            if i.entity_type.value == entity_type
            and (i.target_task_id == target_uuid or i.target_fixed_schedule_id == target_uuid)
        ),
        None,
    )


def _apply_real_target_update_or_delete(
    db: Session, *, user_id: uuid.UUID, request: SolarRequest, items: list[SolarRequestItem], item
) -> None:
    """targetKind=ENTITY인 UPDATE/DELETE `solar_client.SolarAnalysisItem` 하나를 대상 재검증 후
    기존 카드와 병합하거나 새 카드로 추가한다. CHANGE_INPUT/UNRESOLVED_ANSWER 양쪽에서
    재사용한다."""
    target_row = _revalidate_target(
        db,
        user_id=user_id,
        plan_cycle_id=request.plan_cycle_id,
        entity_type=item.entity_type,
        target_entity_id=item.target_entity_id,
    )
    if item.action == "UPDATE":
        final_payload = _backfill_update_payload(item, target_row)
    else:
        final_payload = _snapshot_for_delete(item.entity_type, target_row)

    existing = _find_existing_item_for_real_target(item.entity_type, item.target_entity_id, items)
    if existing is not None:
        _merge_real_target_item(
            existing, item.action, final_payload, item.update_fields, item.missing_fields, item.pending_question, item.raw_line_text
        )
    else:
        _create_new_item_from_analysis(
            db,
            user_id=user_id,
            request=request,
            items=items,
            action=item.action,
            entity_type=item.entity_type,
            raw_line_text=item.raw_line_text,
            final_payload=final_payload,
            missing_fields=item.missing_fields,
            pending_question=item.pending_question,
            update_fields=item.update_fields,
            target_entity_id=item.target_entity_id,
        )


def _apply_resolved_target_only(
    db: Session,
    *,
    user_id: uuid.UUID,
    request: SolarRequest,
    items: list[SolarRequestItem],
    target,  # solar_client.ResolvedTargetOnly
    expected_action: str,
    expected_entity_type: str,
    original_raw_line_text: str,
) -> tuple[str | None, str | None]:
    """UNRESOLVED_ANSWER의 resolvedTargetOnly 처리. expected_action="DELETE"는 재질문 없이 즉시
    실행하고, "UPDATE"는 이 함수가 아니라 호출자가 CHANGE_DETAILS 후속 질문 metadata를
    저장한다(대상 존재만 여기서 확인)."""
    if expected_action == "DELETE":
        if target.target_kind == "REQUEST_ITEM":
            referenced = _find_item_by_id(target.target_entity_id, items)
            if referenced is None or referenced.entity_type.value != expected_entity_type:
                raise ApiError(409, CODE_TARGET_AMBIGUOUS, "요청을 분석하는 동안 대상 카드가 사라졌어요. 다시 시도해 주세요.")
            items.remove(referenced)
            db.delete(referenced)
        else:
            target_row = _revalidate_target(
                db,
                user_id=user_id,
                plan_cycle_id=request.plan_cycle_id,
                entity_type=expected_entity_type,
                target_entity_id=target.target_entity_id,
            )
            final_payload = _snapshot_for_delete(expected_entity_type, target_row)
            existing = _find_existing_item_for_real_target(expected_entity_type, target.target_entity_id, items)
            if existing is not None:
                _merge_real_target_item(existing, "DELETE", final_payload, [], [], None, original_raw_line_text)
            else:
                _create_new_item_from_analysis(
                    db,
                    user_id=user_id,
                    request=request,
                    items=items,
                    action="DELETE",
                    entity_type=expected_entity_type,
                    raw_line_text=original_raw_line_text,
                    final_payload=final_payload,
                    missing_fields=[],
                    pending_question=None,
                    update_fields=[],
                    target_entity_id=target.target_entity_id,
                )
        db.flush()
        _renumber_items_after_delete(db, sorted(items, key=lambda i: i.item_order))
        return _recompute_request_collecting_state(request, items)

    # expected_action == "UPDATE" — 존재만 확인, 카드는 아직 만들지 않는다(무엇을 바꿀지 모름).
    if target.target_kind == "REQUEST_ITEM":
        referenced = _find_item_by_id(target.target_entity_id, items)
        if referenced is None or referenced.entity_type.value != expected_entity_type:
            raise ApiError(409, CODE_TARGET_AMBIGUOUS, "요청을 분석하는 동안 대상 카드가 사라졌어요. 다시 시도해 주세요.")
    else:
        _revalidate_target(
            db,
            user_id=user_id,
            plan_cycle_id=request.plan_cycle_id,
            entity_type=expected_entity_type,
            target_entity_id=target.target_entity_id,
        )
    request.status = SolarRequestStatus.COLLECTING
    request.current_item_order = None
    return SolarMessageKind.QUESTION.value, "무엇을 바꾸고 싶으신가요?"


def _apply_unresolved_single_item(
    db: Session, *, user_id: uuid.UUID, request: SolarRequest, items: list[SolarRequestItem], item
) -> tuple[str | None, str | None]:
    """UNRESOLVED_ANSWER가 items에 정확히 1개(대상+변경 내용 모두 확정)를 돌려준 경우를
    반영한다."""
    if item.target_kind == "REQUEST_ITEM":
        referenced = _find_item_by_id(item.target_entity_id, items)
        if referenced is None or referenced.entity_type.value != item.entity_type:
            raise ApiError(409, CODE_TARGET_AMBIGUOUS, "요청을 분석하는 동안 대상 카드가 바뀌었어요. 다시 시도해 주세요.")
        if item.action == "DELETE":
            items.remove(referenced)
            db.delete(referenced)
        else:  # UPDATE — CREATE+REQUEST_ITEM patch와 동일한 경로 재사용
            if referenced.action != SolarAction.CREATE:
                raise ApiError(409, CODE_TARGET_AMBIGUOUS, "요청을 분석하는 동안 대상 카드가 바뀌었어요. 다시 시도해 주세요.")
            _apply_create_merge_patch(referenced, item.update_fields, item.normalized_payload, item.missing_fields)
    else:
        _apply_real_target_update_or_delete(db, user_id=user_id, request=request, items=items, item=item)

    db.flush()
    _renumber_items_after_delete(db, sorted(items, key=lambda i: i.item_order))
    return _recompute_request_collecting_state(request, items)


def _apply_change_input_result(
    db: Session, *, user_id: uuid.UUID, request: SolarRequest, items: list[SolarRequestItem], analysis
) -> None:
    """CHANGE_INPUT SOLAR 응답의 items를 전부 반영한다(신규 CREATE 추가, CREATE+REQUEST_ITEM
    patch, DELETE+REQUEST_ITEM 취소, ENTITY UPDATE/DELETE 병합·추가). analysis.items는 이미
    파서가 한 응답 안 동일 대상 중복을 거부해 서로 다른 대상만 남아있다."""
    for item in analysis.items:
        if item.action == "CREATE" and item.target_kind != "REQUEST_ITEM":
            final_payload = _sync_remaining_minutes_for_create(
                dict(item.normalized_payload), item.entity_type, SolarAction.CREATE
            )
            _create_new_item_from_analysis(
                db,
                user_id=user_id,
                request=request,
                items=items,
                action="CREATE",
                entity_type=item.entity_type,
                raw_line_text=item.raw_line_text,
                final_payload=final_payload,
                missing_fields=item.missing_fields,
                pending_question=item.pending_question,
                update_fields=[],
                target_entity_id=None,
            )
            continue

        if item.action == "CREATE" and item.target_kind == "REQUEST_ITEM":
            referenced = _find_item_by_id(item.target_entity_id, items)
            if referenced is None or referenced.action != SolarAction.CREATE or referenced.entity_type.value != item.entity_type:
                raise ApiError(409, CODE_TARGET_AMBIGUOUS, "요청을 분석하는 동안 대상 카드가 바뀌었어요. 다시 시도해 주세요.")
            _apply_create_merge_patch(referenced, item.update_fields, item.normalized_payload, item.missing_fields)
            continue

        if item.target_kind == "REQUEST_ITEM":  # DELETE+REQUEST_ITEM(취소) — action 무관 전부 허용
            referenced = _find_item_by_id(item.target_entity_id, items)
            if referenced is None or referenced.entity_type.value != item.entity_type:
                raise ApiError(409, CODE_TARGET_AMBIGUOUS, "요청을 분석하는 동안 대상 카드가 바뀌었어요. 다시 시도해 주세요.")
            items.remove(referenced)
            db.delete(referenced)
            continue

        # target_kind == "ENTITY", action UPDATE/DELETE
        _apply_real_target_update_or_delete(db, user_id=user_id, request=request, items=items, item=item)

    db.flush()
    _renumber_items_after_delete(db, sorted(items, key=lambda i: i.item_order))


def _normalize_change_fixed_schedule(payload, missing_fields, pending_question):
    payload, missing = dict(payload), list(missing_fields)
    start_at, end_at = payload.get("startAt"), payload.get("endAt")
    if start_at is not None and end_at is not None and datetime.fromisoformat(end_at) <= datetime.fromisoformat(start_at):
        payload["endAt"] = None
        missing = [field for field in solar_client.missing_order_for("FIXED_SCHEDULE", "CREATE")
                   if field in set(missing) | {"endAt"}]
        pending_question = {"field": missing[0], "message": "종료 시각은 시작 시각보다 늦어야 해요. 종료 시각을 다시 알려 주세요.", "attemptCount": 1}
    return payload, missing, pending_question


def _apply_change_input_operations(
    db: Session, *, user_id: uuid.UUID, request: SolarRequest, items: list[SolarRequestItem],
    analysis, raw_line_text: str,
) -> None:
    for operation in analysis.operations:
        if isinstance(operation, solar_client.ChangeInputAddOperation):
            payload = _sync_remaining_minutes_for_create(operation.normalized_payload, operation.entity_type, SolarAction.CREATE)
            missing, pending = operation.missing_fields, operation.pending_question
            if operation.entity_type == "FIXED_SCHEDULE":
                payload, missing, pending = _normalize_change_fixed_schedule(payload, missing, pending)
            _create_new_item_from_analysis(
                db, user_id=user_id, request=request, items=items, action="CREATE",
                entity_type=operation.entity_type, raw_line_text=operation.raw_line_text,
                final_payload=payload, missing_fields=missing, pending_question=pending,
                update_fields=[], target_entity_id=None,
            )
            continue
        if isinstance(operation, solar_client.ChangeInputPatchRequestItemOperation):
            referenced = _find_item_by_id(operation.request_item_id, items)
            if referenced is None or referenced.action != SolarAction.CREATE or referenced.entity_type.value != operation.entity_type:
                raise ApiError(409, CODE_TARGET_AMBIGUOUS, "변경 대상을 다시 선택해 주세요.")
            _apply_create_merge_patch(referenced, operation.changed_fields, operation.patch, operation.missing_fields)
            if operation.entity_type == "FIXED_SCHEDULE":
                payload, missing, pending = _normalize_change_fixed_schedule(
                    referenced.normalized_payload, referenced.missing_fields, referenced.pending_question
                )
                referenced.normalized_payload, referenced.missing_fields, referenced.pending_question = payload, missing, pending
                referenced.status = SolarItemStatus.INFO_MISSING if missing else SolarItemStatus.READY
            continue
        if isinstance(operation, solar_client.ChangeInputDeleteRequestItemOperation):
            referenced = _find_item_by_id(operation.request_item_id, items)
            if referenced is None or referenced.entity_type.value != operation.entity_type:
                raise ApiError(409, CODE_TARGET_AMBIGUOUS, "변경 대상을 다시 선택해 주세요.")
            items.remove(referenced)
            db.delete(referenced)
            continue
        is_update = isinstance(operation, solar_client.ChangeInputUpdateEntityOperation)
        target_id = operation.target_entity_id
        target = _revalidate_target(db, user_id=user_id, plan_cycle_id=request.plan_cycle_id,
                                    entity_type=operation.entity_type, target_entity_id=target_id)
        if is_update:
            adapter = SimpleNamespace(normalized_payload=operation.patch, update_fields=operation.update_fields,
                                      entity_type=operation.entity_type)
            payload = _backfill_update_payload(adapter, target, allow_invalid_fixed_schedule=True)
            missing, pending, fields, action = operation.missing_fields, operation.pending_question, operation.update_fields, "UPDATE"
            if operation.entity_type == "FIXED_SCHEDULE":
                payload, missing, pending = _normalize_change_fixed_schedule(payload, missing, pending)
        else:
            payload = _snapshot_for_delete(operation.entity_type, target)
            missing, pending, fields, action = [], None, [], "DELETE"
        existing = _find_existing_item_for_real_target(operation.entity_type, target_id, items)
        if existing is not None:
            _merge_real_target_item(existing, action, payload, fields, missing, pending, raw_line_text)
        else:
            _create_new_item_from_analysis(
                db, user_id=user_id, request=request, items=items, action=action,
                entity_type=operation.entity_type, raw_line_text=raw_line_text,
                final_payload=payload, missing_fields=missing, pending_question=pending,
                update_fields=fields, target_entity_id=target_id,
            )
    db.flush()
    _renumber_items_after_delete(db, sorted(items, key=lambda item: item.item_order))


def _persist_change_unresolved(
    db: Session, *, user_id: uuid.UUID, request: SolarRequest, items: list[SolarRequestItem], unresolved
) -> tuple[str, dict]:
    request.status, request.current_item_order = SolarRequestStatus.COLLECTING, None
    if unresolved.target_kind == "REQUEST_ITEM":
        action = "UPDATE" if unresolved.intended_operation.value == "PATCH_REQUEST_ITEM" else "DELETE"
        candidate_ids = list(_filter_request_item_candidates(action, unresolved.entity_type, items).keys())
        candidate_key = "candidateRequestItemIds"
    else:
        action = "UPDATE" if unresolved.intended_operation.value == "UPDATE_ENTITY" else "DELETE"
        candidates = (_fetch_candidate_tasks(db, user_id, request.plan_cycle_id)
                      if unresolved.entity_type == "TASK"
                      else _fetch_candidate_fixed_schedules(db, user_id, request.plan_cycle_id))
        candidate_ids, candidate_key = [candidate["id"] for candidate in candidates], "candidateEntityIds"
    metadata = {"unresolved": True, "field": "targetEntityId", "rawLineText": unresolved.raw_line_text,
                "action": action, "entityType": unresolved.entity_type, "targetKind": unresolved.target_kind,
                candidate_key: candidate_ids}
    return unresolved.message, metadata


def _persist_still_unresolved(
    db: Session, *, user_id: uuid.UUID, request: SolarRequest, items: list[SolarRequestItem], unresolved
) -> tuple[str, dict]:
    """이번 답변으로도 대상을 여전히 하나로 특정하지 못했을 때(unresolvedLine 재발생) 반영할
    request 상태 갱신 + 다음 질문 메시지(content, metadata)를 만든다. UNRESOLVED_ANSWER의
    "여전히 모호" 분기와 CHANGE_INPUT 자체 unresolvedLine 분기가 함께 재사용한다."""
    request.status = SolarRequestStatus.COLLECTING
    request.current_item_order = None
    if unresolved.target_kind == "REQUEST_ITEM":
        live = _filter_request_item_candidates(unresolved.action, unresolved.entity_type, items)
        candidate_ids = list(live.keys())
    else:
        candidates = (
            _fetch_candidate_tasks(db, user_id, request.plan_cycle_id)
            if unresolved.entity_type == "TASK"
            else _fetch_candidate_fixed_schedules(db, user_id, request.plan_cycle_id)
        )
        candidate_ids = [c["id"] for c in candidates]
    metadata = {
        "unresolved": True,
        "field": "targetEntityId",
        "rawLineText": unresolved.raw_line_text,
        "action": unresolved.action,
        "entityType": unresolved.entity_type,
        "targetKind": unresolved.target_kind,
        "candidateEntityIds": candidate_ids,
    }
    return unresolved.message, metadata


def _user_text_entry(client_event_id: str, content: str) -> dict:
    return {
        "client_event_id": client_event_id,
        "role": SolarMessageRole.USER,
        "kind": SolarMessageKind.TEXT,
        "content": content,
        "message_metadata": {},
    }


def _assistant_text_entry(content: str) -> dict:
    return {
        "client_event_id": None,
        "role": SolarMessageRole.ASSISTANT,
        "kind": SolarMessageKind.TEXT,
        "content": content,
        "message_metadata": {},
    }


def _assistant_question_entry(content: str, metadata: dict) -> dict:
    return {
        "client_event_id": None,
        "role": SolarMessageRole.ASSISTANT,
        "kind": SolarMessageKind.QUESTION,
        "content": content,
        "message_metadata": metadata,
    }


def _build_decision_history_entries(
    *, client_event_id: str, decision: str, decision_label: str, prompt_message: str
) -> list[dict]:
    return [
        _assistant_question_entry(
            prompt_message,
            {
                "promptType": "CHANGE_CONFIRMATION",
                "decisionClientEventId": client_event_id,
            },
        ),
        {
            "client_event_id": client_event_id,
            "role": SolarMessageRole.USER,
            "kind": SolarMessageKind.DECISION,
            "content": decision_label,
            "message_metadata": {"decision": decision},
        },
    ]


def add_solar_message(
    db: Session,
    *,
    user_id: uuid.UUID,
    request_id: uuid.UUID,
    client_event_id: str,
    message: str,
    now: datetime,
):
    """POST /solar/requests/{id}/messages. COLLECTING(카드 답변, 대상 모호/CHANGE_DETAILS 후속
    답변)과 CHANGE_INPUT(자유 편집) 모두 이 하나의 endpoint로 들어온다. SOLAR 호출 전후로
    트랜잭션을 분리하고, 쓰기 트랜잭션 시작 시 요청을 잠근 뒤 dispatch 컨텍스트(어떤 카드/특수
    질문에 대한 답변인지)가 읽기 시점과 같은지 다시 확인한다."""
    canonical_message = message.strip()
    canonical_client_event_id = client_event_id.strip()

    def _idempotent_state_or_conflict(db: Session, request: SolarRequest):
        existing = _find_message_by_client_event_id(db, request.id, canonical_client_event_id)
        if existing is None:
            return None
        if existing.role == SolarMessageRole.USER and existing.content.strip() == canonical_message:
            from app.services import plan_management_service

            return plan_management_service.get_solar_request_detail_state(db, user_id, request.id)
        raise ApiError(409, CODE_INVALID_REQUEST_STATE, "이미 처리된 다른 내용의 요청이에요.")

    # 1. 읽기 트랜잭션
    with db.begin():
        request = _lock_owned_solar_request(db, request_id, user_id)
        idempotent_state = _idempotent_state_or_conflict(db, request)
        if idempotent_state is not None:
            return idempotent_state

        items = _load_items(db, request.id)
        messages = _load_messages(db, request.id)
        dispatch = _resolve_message_dispatch(request, items, messages)

        call_ctx: dict = {}
        if dispatch.kind == "CARD":
            card = dispatch.card
            pending = card.pending_question
            call_ctx = {
                "entity_type": card.entity_type.value,
                "action": card.action.value,
                "field": pending["field"],
                "question_message": pending["message"],
                "attempt_number": int(pending.get("attemptCount", 1))
                if isinstance(pending.get("attemptCount"), int) and not isinstance(pending.get("attemptCount"), bool)
                else 1,
                "card_context": _card_context_for_prompt(card),
            }
        elif dispatch.kind in ("UNRESOLVED", "CHANGE_DETAILS"):
            metadata = dispatch.special_message.message_metadata
            if dispatch.kind == "UNRESOLVED":
                target_kind, action, entity_type, raw_line_text, candidate_ids = _validate_unresolved_metadata(metadata)
                lock_target_entity_id = None
            else:
                target_kind, action, entity_type, target_entity_id, raw_line_text = _validate_change_details_metadata(
                    metadata
                )
                candidate_ids = [target_entity_id]
                lock_target_entity_id = target_entity_id

            live_ids = _live_candidate_ids_for_unresolved(
                db,
                request,
                target_kind=target_kind,
                action=action,
                entity_type=entity_type,
                stored_candidate_ids=candidate_ids,
                items=items,
            )
            if not live_ids:
                raise ApiError(409, CODE_TARGET_AMBIGUOUS, "요청을 분석하는 동안 대상이 사라졌어요. 다시 시도해 주세요.")

            candidate_request_items: dict[str, dict] = {}
            candidate_tasks: list[dict] = []
            candidate_fixed_schedules: list[dict] = []
            if target_kind == "REQUEST_ITEM":
                all_request_items = _build_candidate_request_items(items)
                candidate_request_items = {cid: info for cid, info in all_request_items.items() if cid in live_ids}
            elif entity_type == "TASK":
                candidate_tasks = [
                    c for c in _fetch_candidate_tasks(db, request.user_id, request.plan_cycle_id) if c["id"] in live_ids
                ]
            else:
                candidate_fixed_schedules = [
                    c
                    for c in _fetch_candidate_fixed_schedules(db, request.user_id, request.plan_cycle_id)
                    if c["id"] in live_ids
                ]

            call_ctx = {
                "purpose": request.purpose,
                "expected_action": action,
                "expected_entity_type": entity_type,
                "expected_target_kind": target_kind,
                "original_raw_line_text": raw_line_text,
                "candidate_tasks": candidate_tasks,
                "candidate_fixed_schedules": candidate_fixed_schedules,
                "candidate_request_items": candidate_request_items,
                "lock_target_entity_id": lock_target_entity_id,
            }
        else:  # CHANGE_INPUT
            plan_cycle_id = request.plan_cycle_id
            if plan_cycle_id is not None:
                cycle = plan_block_service.get_owned_planning_cycle(db, plan_cycle_id, user_id)
                cycle_start, cycle_end = cycle.start_date, cycle.end_date
                candidate_tasks = _fetch_candidate_tasks(db, user_id, plan_cycle_id)
                candidate_fixed_schedules = _fetch_candidate_fixed_schedules(db, user_id, plan_cycle_id)
            else:
                cycle_start = cycle_end = None
                candidate_tasks = []
                candidate_fixed_schedules = []
            call_ctx = {
                "purpose": request.purpose,
                "cycle_start": cycle_start,
                "cycle_end": cycle_end,
                "candidate_tasks": candidate_tasks,
                "candidate_fixed_schedules": candidate_fixed_schedules,
                "candidate_request_items": _build_candidate_request_items(items),
            }

    # 2. SOLAR 호출(트랜잭션 밖) — dispatch 종류별로 analyze_* 진입점 하나만 호출한다.
    try:
        if dispatch.kind == "CARD":
            result = solar_client.analyze_card_answer(
                canonical_message,
                now=now,
                entity_type=call_ctx["entity_type"],
                action=call_ctx["action"],
                field=call_ctx["field"],
                question_message=call_ctx["question_message"],
                attempt_number=call_ctx["attempt_number"],
                card_context=call_ctx["card_context"],
            )
        elif dispatch.kind in ("UNRESOLVED", "CHANGE_DETAILS"):
            result = solar_client.analyze_unresolved_answer(
                canonical_message,
                now=now,
                purpose=call_ctx["purpose"],
                expected_action=call_ctx["expected_action"],
                expected_entity_type=call_ctx["expected_entity_type"],
                expected_target_kind=call_ctx["expected_target_kind"],
                original_raw_line_text=call_ctx["original_raw_line_text"],
                candidate_tasks=call_ctx["candidate_tasks"],
                candidate_fixed_schedules=call_ctx["candidate_fixed_schedules"],
                candidate_request_items=call_ctx["candidate_request_items"],
                lock_target_entity_id=call_ctx["lock_target_entity_id"],
            )
        else:
            result = solar_client.analyze_change_input(
                canonical_message,
                now=now,
                purpose=call_ctx["purpose"],
                cycle_start=call_ctx["cycle_start"],
                cycle_end=call_ctx["cycle_end"],
                candidate_tasks=call_ctx["candidate_tasks"],
                candidate_fixed_schedules=call_ctx["candidate_fixed_schedules"],
                candidate_request_items=call_ctx["candidate_request_items"],
            )
    except solar_client.SolarUnavailableError as exc:
        raise ApiError(503, CODE_SOLAR_UNAVAILABLE, "SOLAR 분석에 실패했어요. 잠시 후 다시 시도해 주세요.") from exc

    # 3. 쓰기 트랜잭션 — 상태·질문·cycle·target을 다시 검증한 뒤 반영한다.
    with db.begin():
        request = _lock_owned_solar_request(db, request_id, user_id)
        idempotent_state = _idempotent_state_or_conflict(db, request)
        if idempotent_state is not None:
            return idempotent_state

        items = _load_items(db, request.id)
        messages = _load_messages(db, request.id)
        dispatch_now = _resolve_message_dispatch(request, items, messages)

        if dispatch_now.kind != dispatch.kind:
            raise ApiError(409, CODE_INVALID_REQUEST_STATE, "요청 상태가 바뀌었어요. 다시 시도해 주세요.")

        from app.services import plan_management_service

        before_item_values = {
            item.id: _snapshot_change_fingerprint(
                item, plan_management_service=plan_management_service
            )
            for item in items
        }
        analysis_entry = _assistant_text_entry(result.analysis_message)
        entries = [_user_text_entry(canonical_client_event_id, canonical_message), analysis_entry]

        if dispatch.kind == "CARD":
            field = call_ctx["field"]
            card = dispatch_now.card
            if (
                card is None
                or card.id != dispatch.card.id
                or not isinstance(card.pending_question, dict)
                or card.pending_question.get("field") != field
            ):
                raise ApiError(409, CODE_INVALID_REQUEST_STATE, "카드 상태가 바뀌었어요. 다시 시도해 주세요.")

            if result.answer_disposition == "PROVIDED":
                remaining = _apply_card_answer_provided(card, field, result.field_value)
                kind, content = _advance_card_after_field_resolved(card, request, remaining)
                if kind is None:
                    kind, content = _recompute_request_collecting_state(request, items)
            elif result.answer_disposition == "DONT_KNOW":
                question_message = result.pending_question_message or _DEFAULT_QUESTION_MESSAGES[field]
                auto_resolved, remaining = _apply_card_answer_dont_know(card, field, question_message)
                if auto_resolved:
                    kind, content = _advance_card_after_field_resolved(card, request, remaining)
                    if kind is None:
                        kind, content = _recompute_request_collecting_state(request, items)
                else:
                    request.current_item_order = card.item_order
                    kind, content = SolarMessageKind.QUESTION.value, card.pending_question["message"]
            else:  # UNCLEAR
                question_message = result.pending_question_message or _DEFAULT_QUESTION_MESSAGES[field]
                _apply_card_answer_unclear(card, field, question_message)
                request.current_item_order = card.item_order
                kind, content = SolarMessageKind.QUESTION.value, card.pending_question["message"]

            if kind == SolarMessageKind.QUESTION.value:
                entries.append(_assistant_question_entry(content, _build_trailing_question_entry(request, items)))
            elif kind == SolarMessageKind.TEXT.value:
                entries.append(_assistant_text_entry(content))

        elif dispatch.kind in ("UNRESOLVED", "CHANGE_DETAILS"):
            special_now = dispatch_now.special_message
            if special_now is None or special_now.id != dispatch.special_message.id:
                raise ApiError(409, CODE_INVALID_REQUEST_STATE, "질문 상태가 바뀌었어요. 다시 시도해 주세요.")

            expected_action = call_ctx["expected_action"]
            expected_entity_type = call_ctx["expected_entity_type"]
            original_raw_line_text = call_ctx["original_raw_line_text"]

            if result.resolved_target_only is not None:
                target = result.resolved_target_only
                kind, content = _apply_resolved_target_only(
                    db,
                    user_id=user_id,
                    request=request,
                    items=items,
                    target=target,
                    expected_action=expected_action,
                    expected_entity_type=expected_entity_type,
                    original_raw_line_text=original_raw_line_text,
                )
                if expected_action == "UPDATE":
                    entries.append(
                        _assistant_question_entry(
                            content,
                            {
                                "followUpType": "CHANGE_DETAILS",
                                "targetKind": target.target_kind,
                                "targetEntityId": target.target_entity_id,
                                "action": "UPDATE",
                                "entityType": expected_entity_type,
                                "rawLineText": original_raw_line_text,
                            },
                        )
                    )
                elif kind == SolarMessageKind.QUESTION.value:
                    entries.append(_assistant_question_entry(content, _build_trailing_question_entry(request, items)))
                elif kind == SolarMessageKind.TEXT.value:
                    entries.append(_assistant_text_entry(content))
            elif len(result.items) == 1:
                kind, content = _apply_unresolved_single_item(
                    db, user_id=user_id, request=request, items=items, item=result.items[0]
                )
                if kind == SolarMessageKind.QUESTION.value:
                    entries.append(_assistant_question_entry(content, _build_trailing_question_entry(request, items)))
                elif kind == SolarMessageKind.TEXT.value:
                    entries.append(_assistant_text_entry(content))
            else:  # 여전히 모호
                content, metadata = _persist_still_unresolved(
                    db, user_id=user_id, request=request, items=items, unresolved=result.unresolved_line
                )
                entries.append(_assistant_question_entry(content, metadata))

        else:  # CHANGE_INPUT
            if request.status != SolarRequestStatus.CHANGE_INPUT:
                raise ApiError(409, CODE_INVALID_REQUEST_STATE, "요청 상태가 바뀌었어요. 다시 시도해 주세요.")

            _apply_change_input_operations(
                db, user_id=user_id, request=request, items=items, analysis=result,
                raw_line_text=canonical_message,
            )

            if result.unresolved_operation is not None:
                content, metadata = _persist_change_unresolved(
                    db, user_id=user_id, request=request, items=items, unresolved=result.unresolved_operation
                )
                entries.append(_assistant_question_entry(content, metadata))
            else:
                kind, content = _recompute_request_collecting_state(request, items)
                if kind == SolarMessageKind.QUESTION.value:
                    entries.append(_assistant_question_entry(content, _build_trailing_question_entry(request, items)))
                elif kind == SolarMessageKind.TEXT.value:
                    entries.append(_assistant_text_entry(content))

        changed_items = _find_changed_snapshot_items(
            items, before_item_values, plan_management_service=plan_management_service
        )
        analysis_entry["message_metadata"] = _build_request_item_snapshot_metadata(
            changed_items, plan_management_service=plan_management_service
        )

        _persist_ordered_messages(db, user_id=user_id, request=request, entries=entries)

        return plan_management_service.get_solar_request_detail_state(db, user_id, request.id)


def add_solar_decision(
    db: Session, *, user_id: uuid.UUID, request_id: uuid.UUID, client_event_id: str, decision: str, now: datetime
):
    """POST /solar/requests/{id}/decisions. CHANGE_CONFIRMATION에서만 유효하다. YES(수정할 내용
    있음) → CHANGE_INPUT, NO(확정) → FINAL_REVIEW + confirmed_at 기록. SOLAR를 호출하지 않는
    순수 구조적 전이라 트랜잭션을 분리하지 않는다."""
    canonical_client_event_id = client_event_id.strip()
    if decision not in ("YES", "NO"):
        raise ApiError(400, CODE_MALFORMED_REQUEST, "decision 값이 올바르지 않아요.")

    with db.begin():
        request = _lock_owned_solar_request(db, request_id, user_id)

        existing = _find_message_by_client_event_id(db, request.id, canonical_client_event_id)
        if existing is not None:
            if existing.kind == SolarMessageKind.DECISION and existing.message_metadata.get("decision") == decision:
                from app.services import plan_management_service

                return plan_management_service.get_solar_request_detail_state(db, user_id, request.id)
            raise ApiError(409, CODE_INVALID_REQUEST_STATE, "이미 처리된 다른 내용의 요청이에요.")

        if request.status != SolarRequestStatus.CHANGE_CONFIRMATION:
            raise ApiError(409, CODE_INVALID_REQUEST_STATE, "지금은 확인할 수 없는 상태예요.")

        from app.services import plan_management_service

        prompt = plan_management_service._build_decision_prompt(request.status)
        if prompt is None:
            raise ApiError(409, CODE_INVALID_REQUEST_STATE, "Decision prompt is unavailable.")
        decision_content = next(
            (option.label for option in prompt.options if option.value == decision),
            decision,
        )

        if decision == "YES":
            request.status = SolarRequestStatus.CHANGE_INPUT
        else:
            request.status = SolarRequestStatus.FINAL_REVIEW
            request.confirmed_at = now
        request.current_item_order = None

        entries = _build_decision_history_entries(
            client_event_id=canonical_client_event_id,
            decision=decision,
            decision_label=decision_content,
            prompt_message=prompt.message,
        )
        _persist_ordered_messages(db, user_id=user_id, request=request, entries=entries)

        return plan_management_service.get_solar_request_detail_state(db, user_id, request.id)


def reopen_solar_request(db: Session, *, user_id: uuid.UUID, request_id: uuid.UUID, now: datetime):
    """POST /solar/requests/{id}/reopen. FINAL_REVIEW → CHANGE_INPUT만 허용한다."""
    with db.begin():
        request = _lock_owned_solar_request(db, request_id, user_id)
        if request.status != SolarRequestStatus.FINAL_REVIEW:
            raise ApiError(409, CODE_INVALID_REQUEST_STATE, "지금은 다시 수정할 수 없는 상태예요.")
        request.status = SolarRequestStatus.CHANGE_INPUT
        request.confirmed_at = None
        request.current_item_order = None
        db.flush()

        from app.services import plan_management_service

        return plan_management_service.get_solar_request_detail_state(db, user_id, request.id)


def delete_solar_request(db: Session, *, user_id: uuid.UUID, request_id: uuid.UUID) -> None:
    """DELETE /solar/requests/{id}. 진행 중(EXECUTING 제외)인 요청만 삭제할 수 있다. FK
    ondelete=CASCADE로 solar_messages/solar_request_items가 함께 삭제된다."""
    with db.begin():
        request = _lock_owned_solar_request(db, request_id, user_id)
        if request.status not in _DELETABLE_REQUEST_STATUSES:
            raise ApiError(409, CODE_INVALID_REQUEST_STATE, "지금은 삭제할 수 없는 상태예요.")
        db.delete(request)


# ---------------------------------------------------------------------------
# BE-06 — execute / retry / execution 조회 / acknowledge-result
# ---------------------------------------------------------------------------

CODE_SETTLEMENT_IN_PROGRESS = "SETTLEMENT_IN_PROGRESS"


def is_execution_error_retryable(error_code: str | None) -> bool:
    """FAILED는 상태 전이표(FAILED --retry 검증 성공--> EXECUTING)상 error_code와 무관하게 항상
    재시도 가능한 MVP 상태 모델이다 — retryable을 저장하는 별도 컬럼이 없다."""
    return True


def _validate_execution_preconditions(db: Session, request: SolarRequest) -> None:
    """execute/retry 직전 검증. request row lock을 쥔 트랜잭션 안에서만 호출해야 한다 — lock
    밖에서 먼저 호출하면 검증과 조건부 UPDATE 사이에 cycle·정산·대상이 바뀔 수 있다(TOCTOU).
    DB를 쓰지 않는다 — 실패하면 ApiError를 raise한다."""
    if request.purpose == SolarRequestPurpose.NEW_CYCLE:
        if plan_block_service.get_active_planning_cycle(db, request.user_id) is not None:
            raise ApiError(409, CODE_ACTIVE_CYCLE_EXISTS, "이미 진행 중인 계획 기간이 있어요.")
        return

    cycle = plan_block_service.get_active_planning_cycle(db, request.user_id)
    if cycle is None or cycle.id != request.plan_cycle_id:
        raise ApiError(409, CODE_CYCLE_NOT_ACTIVE, "계획 기간이 변경됐어요. 다시 시도해 주세요.")

    if check_in_service.get_finalizing_info(db, request.user_id) is not None:
        raise ApiError(409, CODE_SETTLEMENT_IN_PROGRESS, "정산이 진행 중이에요. 잠시 후 다시 시도해 주세요.")

    for item in _load_items(db, request.id):
        if item.action == SolarAction.CREATE:
            continue
        target_id = item.target_task_id or item.target_fixed_schedule_id
        _revalidate_target(
            db,
            user_id=request.user_id,
            plan_cycle_id=request.plan_cycle_id,
            entity_type=item.entity_type.value,
            target_entity_id=str(target_id),
        )


@dataclass(frozen=True)
class ExecutionTransitionResult:
    request: SolarRequest
    transitioned: bool


def _apply_execution_transition_update(
    db: Session,
    *,
    request_id: uuid.UUID,
    user_id: uuid.UUID,
    required_status: SolarRequestStatus,
    now: datetime,
) -> int:
    """FINAL_REVIEW/FAILED -> EXECUTING 조건부 단일 UPDATE. 상태와 실행 관련 필드를 한 statement
    에서 함께 바꾼다(DB 명세 20-5절 원문 SQL과 동일한 필드 집합, updated_at 포함).

    execution_result는 반드시 sqlalchemy.null()을 써야 한다 — JSONB 컬럼에 파이썬 None을
    그대로 넘기면 SQLAlchemy postgresql.JSONB의 기본 none_as_null=False 동작 때문에 SQL NULL이
    아니라 JSON 리터럴 'null'로 직렬화되어 executing_state_consistency CHECK(execution_result
    IS NULL)를 위반한다(실제 PostgreSQL E2E에서 확인된 결함, executed_at/error_code/
    error_message는 JSONB가 아니므로 None 그대로 SQL NULL이 되어 영향이 없다)."""
    stmt = (
        update(SolarRequest)
        .where(
            SolarRequest.id == request_id,
            SolarRequest.user_id == user_id,
            SolarRequest.status == required_status,
        )
        .values(
            status=SolarRequestStatus.EXECUTING,
            execution_started_at=now,
            execution_attempt_count=SolarRequest.execution_attempt_count + 1,
            executed_at=None,
            execution_result=null(),
            error_code=None,
            error_message=None,
            updated_at=now,
        )
    )
    return db.execute(stmt).rowcount


def _start_execution(
    db: Session,
    *,
    user_id: uuid.UUID,
    request_id: uuid.UUID,
    now: datetime,
    dispatcher: Dispatcher,
    required_status: SolarRequestStatus,
    invalid_state_message: str,
) -> ExecutionTransitionResult:
    with db.begin():
        locked = _lock_owned_solar_request(db, request_id, user_id)
        if locked.status in (SolarRequestStatus.EXECUTING, SolarRequestStatus.COMPLETED):
            return ExecutionTransitionResult(request=locked, transitioned=False)
        if locked.status != required_status:
            raise ApiError(409, CODE_INVALID_REQUEST_STATE, invalid_state_message)

        _validate_execution_preconditions(db, locked)

        affected = _apply_execution_transition_update(
            db, request_id=request_id, user_id=user_id, required_status=required_status, now=now
        )
        if affected == 1:
            db.refresh(locked)
            transitioned = True
        elif affected == 0:
            # 동시 execute/retry에 밀렸다 — 최신 상태로 재조회해 멱등 응답을 만든다.
            db.refresh(locked)
            transitioned = False
        else:
            raise RuntimeError("조건부 UPDATE가 둘 이상의 row에 영향을 줬다 — id는 PK여야 한다.")

    if transitioned:
        try:
            dispatcher.register(locked.id)
        except Exception:
            # commit은 이미 끝났다 — EXECUTING 상태를 되돌리지 않는다. startup recovery가 재등록한다.
            logger.exception("solar execution dispatcher 등록 실패 request_id=%s", locked.id)

    return ExecutionTransitionResult(request=locked, transitioned=transitioned)


def execute_solar_request(
    db: Session, *, user_id: uuid.UUID, request_id: uuid.UUID, now: datetime, dispatcher: Dispatcher
) -> ExecutionTransitionResult:
    """POST /solar/requests/{id}/execute. FINAL_REVIEW -> EXECUTING."""
    return _start_execution(
        db,
        user_id=user_id,
        request_id=request_id,
        now=now,
        dispatcher=dispatcher,
        required_status=SolarRequestStatus.FINAL_REVIEW,
        invalid_state_message="지금은 실행할 수 없는 상태예요.",
    )


def retry_solar_request(
    db: Session, *, user_id: uuid.UUID, request_id: uuid.UUID, now: datetime, dispatcher: Dispatcher
) -> ExecutionTransitionResult:
    """POST /solar/requests/{id}/retry. FAILED -> EXECUTING.

    result_acknowledged_at은 건드리지 않는다 — result_acknowledged_requires_completed CHECK
    제약상 FAILED 상태에서는 이미 항상 NULL이다.
    """
    return _start_execution(
        db,
        user_id=user_id,
        request_id=request_id,
        now=now,
        dispatcher=dispatcher,
        required_status=SolarRequestStatus.FAILED,
        invalid_state_message="지금은 다시 실행할 수 없는 상태예요.",
    )


@dataclass(frozen=True)
class SolarExecutionErrorView:
    code: str
    message: str
    retryable: bool


@dataclass(frozen=True)
class SolarExecutionView:
    request_id: uuid.UUID
    purpose: SolarRequestPurpose
    status: SolarRequestStatus
    screen_mode: PlanManagementScreenMode
    execution_started_at: datetime | None
    execution_attempt_count: int
    executed_at: datetime | None
    execution_result: dict | None
    error: SolarExecutionErrorView | None


def get_solar_request_execution(
    db: Session, *, user_id: uuid.UUID, request_id: uuid.UUID
) -> SolarExecutionView:
    """GET /solar/requests/{id}/execution. DB의 현재 request 상태를 그대로 반환한다(조회 전용 —
    상태·시각·attempt count를 변경하지 않음). FAILED일 때만 error를 채운다."""
    request = get_owned_solar_request(db, request_id, user_id)

    error = None
    if request.status == SolarRequestStatus.FAILED:
        error = SolarExecutionErrorView(
            code=request.error_code or "",
            message=request.error_message or "",
            retryable=is_execution_error_retryable(request.error_code),
        )

    return SolarExecutionView(
        request_id=request.id,
        purpose=request.purpose,
        status=request.status,
        screen_mode=resolve_current_request_screen_mode(request),
        execution_started_at=request.execution_started_at,
        execution_attempt_count=request.execution_attempt_count,
        executed_at=request.executed_at,
        execution_result=request.execution_result,
        error=error,
    )


@dataclass(frozen=True)
class AcknowledgeExecutionResult:
    request_id: uuid.UUID
    result_acknowledged_at: datetime
    next_screen_mode: PlanManagementScreenMode


def acknowledge_solar_execution_result(
    db: Session, *, user_id: uuid.UUID, request_id: uuid.UUID, now: datetime
) -> AcknowledgeExecutionResult:
    """POST /solar/requests/{id}/acknowledge-result. 미확인 COMPLETED 요청만 대상이며 멱등이다."""
    with db.begin():
        locked = _lock_owned_solar_request(db, request_id, user_id)
        if locked.status != SolarRequestStatus.COMPLETED:
            raise ApiError(409, CODE_INVALID_REQUEST_STATE, "확인할 결과가 없어요.")

        if locked.result_acknowledged_at is None:
            locked.result_acknowledged_at = now
            db.flush()
        acknowledged_at = locked.result_acknowledged_at

        active_cycle = plan_block_service.get_active_planning_cycle(db, user_id)
        next_mode = resolve_no_request_screen_mode(has_active_cycle=active_cycle is not None)

    return AcknowledgeExecutionResult(
        request_id=locked.id, result_acknowledged_at=acknowledged_at, next_screen_mode=next_mode
    )
