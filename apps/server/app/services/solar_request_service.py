import uuid
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import select
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
from app.services import plan_block_service, solar_client

if TYPE_CHECKING:
    from app.services.plan_management_service import PlanManagementState

CODE_REQUEST_NOT_FOUND = "REQUEST_NOT_FOUND"
CODE_ACTIVE_CYCLE_EXISTS = "ACTIVE_CYCLE_EXISTS"
CODE_NO_ACTIVE_CYCLE = "NO_ACTIVE_CYCLE"
CODE_ACTIVE_REQUEST_EXISTS = "ACTIVE_REQUEST_EXISTS"
CODE_CYCLE_NOT_ACTIVE = "CYCLE_NOT_ACTIVE"
CODE_TARGET_AMBIGUOUS = "TARGET_AMBIGUOUS"
CODE_SOLAR_UNAVAILABLE = "SOLAR_UNAVAILABLE"

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


def _backfill_update_payload(item, target_row) -> dict:
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
        if datetime.fromisoformat(payload["endAt"]) <= datetime.fromisoformat(payload["startAt"]):
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
            message_metadata={},
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
