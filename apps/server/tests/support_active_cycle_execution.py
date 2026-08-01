"""execute_active_cycle() 테스트 전용 factory 모음.

fake DB/Session 자체는 support_new_cycle_execution.py의 FakeNewCycleDB/FakeNewCycleSession을
그대로 재사용한다(두 실행 서비스가 완전히 같은 "여러 세션이 커밋된 데이터를 공유"·"실패 시
롤백" 요구를 가지므로 fake 인프라를 중복 작성하지 않는다). 이 모듈은 ACTIVE_CYCLE 시나리오
(Task/FixedSchedule UPDATE·DELETE 카드, 기존 PlanningCycle/Task/FixedSchedule/PlanBlock/
CheckIn 시딩)에 필요한 factory 함수만 추가한다.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from app.models.check_in import CheckIn
from app.models.enums import (
    AmountSource,
    EstimateSource,
    PlanBlockStatus,
    PlanCycleStatus,
    PlanPeriod,
    SolarAction,
    SolarEntityType,
    SolarItemStatus,
    SolarRequestPurpose,
    SolarRequestStatus,
    TaskStatus,
)
from app.models.fixed_schedule import FixedSchedule
from app.models.plan_block import PlanBlock
from app.models.planning_cycle import PlanningCycle
from app.models.solar_request import SolarRequest
from app.models.solar_request_item import SolarRequestItem
from app.models.task import Task

# fake DB/Session 및 request/CREATE 카드 factory는 NEW_CYCLE 테스트와 완전히 동일하므로
# 그대로 재사용한다 — 별도로 다시 만들지 않는다.
from tests.support_new_cycle_execution import (  # noqa: F401
    FakeNewCycleDB,
    FakeNewCycleSession,
    make_fixed_schedule_item,
    make_fixed_schedule_payload,
    make_solar_request,
    make_task_item,
    make_task_payload,
)

FakeActiveCycleDB = FakeNewCycleDB
FakeActiveCycleSession = FakeNewCycleSession


def make_active_cycle_request(*, user_id: uuid.UUID, plan_cycle_id: uuid.UUID, now: datetime, **overrides) -> SolarRequest:
    fields = dict(purpose=SolarRequestPurpose.ACTIVE_CYCLE, plan_cycle_id=plan_cycle_id, status=SolarRequestStatus.EXECUTING)
    fields.update(overrides)
    return make_solar_request(user_id=user_id, now=now, **fields)


def make_cycle(*, user_id: uuid.UUID, start_date: date, end_date: date, **overrides) -> PlanningCycle:
    fields = dict(
        id=uuid.uuid4(),
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        status=PlanCycleStatus.ACTIVE,
        activated_at=datetime.combine(start_date, datetime.min.time()).replace(tzinfo=None),
        ended_at=None,
    )
    fields.update(overrides)
    return PlanningCycle(**fields)


def make_task(
    *,
    user_id: uuid.UUID,
    plan_cycle_id: uuid.UUID,
    estimated_minutes: int,
    remaining_minutes: int,
    title: str = "task",
    deadline_at: datetime | None = None,
    amount_text: str | None = None,
    amount_source: AmountSource = AmountSource.UNKNOWN,
    status: TaskStatus = TaskStatus.ACTIVE,
    created_at: datetime,
    **overrides,
) -> Task:
    fields = dict(
        id=uuid.uuid4(),
        user_id=user_id,
        plan_cycle_id=plan_cycle_id,
        source_request_item_id=None,
        title=title,
        deadline_at=deadline_at,
        amount_text=amount_text,
        amount_source=amount_source,
        initial_minutes=estimated_minutes,
        estimated_minutes=estimated_minutes,
        estimated_minutes_source=EstimateSource.USER,
        remaining_minutes=remaining_minutes,
        status=status,
        deadline_warning_acknowledged_at=None,
        completed_at=None,
        cancelled_at=None,
        created_at=created_at,
        updated_at=created_at,
    )
    fields.update(overrides)
    return Task(**fields)


def make_fixed_schedule(
    *,
    user_id: uuid.UUID,
    plan_cycle_id: uuid.UUID,
    start_at: datetime,
    end_at: datetime,
    title: str = "fixed",
    **overrides,
) -> FixedSchedule:
    fields = dict(
        id=uuid.uuid4(),
        user_id=user_id,
        plan_cycle_id=plan_cycle_id,
        source_request_item_id=None,
        title=title,
        start_at=start_at,
        end_at=end_at,
        created_at=start_at,
        updated_at=start_at,
    )
    fields.update(overrides)
    return FixedSchedule(**fields)


def make_plan_block(
    *,
    user_id: uuid.UUID,
    plan_cycle_id: uuid.UUID,
    task_id: uuid.UUID,
    plan_date: date,
    period: PlanPeriod,
    allocated_minutes: int,
    status: PlanBlockStatus = PlanBlockStatus.PLANNED,
    display_order: int = 0,
    display_title: str = "block",
    allocated_amount_text: str | None = None,
    now: datetime | None = None,
    **overrides,
) -> PlanBlock:
    needs_checked_at = status in (PlanBlockStatus.CHECKED, PlanBlockStatus.COMPLETED)
    needs_check_in_id = status in (PlanBlockStatus.COMPLETED, PlanBlockStatus.NOT_DONE)
    fields = dict(
        id=uuid.uuid4(),
        user_id=user_id,
        plan_cycle_id=plan_cycle_id,
        task_id=task_id,
        plan_date=plan_date,
        period=period,
        allocated_minutes=allocated_minutes,
        allocated_amount_text=allocated_amount_text,
        display_title=display_title,
        display_order=display_order,
        status=status,
        checked_at=now if needs_checked_at else None,
        check_in_id=uuid.uuid4() if needs_check_in_id else None,
        rescheduled_from_block_id=None,
        created_at=now,
        updated_at=now,
    )
    fields.update(overrides)
    return PlanBlock(**fields)


def make_check_in(
    *,
    user_id: uuid.UUID,
    plan_cycle_id: uuid.UUID,
    check_date: date,
    period: PlanPeriod,
    finalization_started_at: datetime,
    finalized_at: datetime | None = None,
    **overrides,
) -> CheckIn:
    fields = dict(
        id=uuid.uuid4(),
        user_id=user_id,
        plan_cycle_id=plan_cycle_id,
        check_date=check_date,
        period=period,
        total_plan_count=None,
        completed_plan_count=None,
        score=None,
        replan_unplaced_minutes=None,
        finalization_started_at=finalization_started_at,
        replanned_at=None,
        finalized_at=finalized_at,
        result_acknowledged_at=None,
        created_at=finalization_started_at,
    )
    fields.update(overrides)
    return CheckIn(**fields)


def make_task_update_payload(
    *,
    title: str = "할 일",
    deadline_at_iso: str | None = None,
    estimated_minutes: int,
    remaining_minutes: int,
    estimated_minutes_source: str = "USER",
    amount_text: str | None = None,
    amount_source: str = "UNKNOWN",
) -> dict:
    """_backfill_update_payload가 실제로 만드는 것처럼 UPDATE 카드는 모든 필드를 항상
    채운다 — _updateFields가 실제로 바뀐 필드만 표시한다."""
    return {
        "title": title,
        "deadlineAt": deadline_at_iso,
        "estimatedMinutes": estimated_minutes,
        "estimatedMinutesSource": estimated_minutes_source,
        "remainingMinutes": remaining_minutes,
        "amountText": amount_text,
        "amountSource": amount_source,
    }


def make_task_update_item(
    *,
    user_id: uuid.UUID,
    solar_request_id: uuid.UUID,
    item_order: int,
    target_task_id: uuid.UUID,
    payload: dict,
    update_fields: list[str],
    **overrides,
) -> SolarRequestItem:
    fields = dict(
        id=uuid.uuid4(),
        user_id=user_id,
        solar_request_id=solar_request_id,
        item_order=item_order,
        action=SolarAction.UPDATE,
        entity_type=SolarEntityType.TASK,
        status=SolarItemStatus.READY,
        raw_line_text=payload.get("title", "task update"),
        normalized_payload={**payload, "_updateFields": update_fields},
        missing_fields=[],
        pending_question=None,
        target_task_id=target_task_id,
        target_fixed_schedule_id=None,
        executed_at=None,
    )
    fields.update(overrides)
    return SolarRequestItem(**fields)


def make_task_cancel_item(
    *,
    user_id: uuid.UUID,
    solar_request_id: uuid.UUID,
    item_order: int,
    target_task_id: uuid.UUID,
    **overrides,
) -> SolarRequestItem:
    fields = dict(
        id=uuid.uuid4(),
        user_id=user_id,
        solar_request_id=solar_request_id,
        item_order=item_order,
        action=SolarAction.DELETE,
        entity_type=SolarEntityType.TASK,
        status=SolarItemStatus.READY,
        raw_line_text="task cancel",
        normalized_payload={"title": "취소된 할 일", "deadlineAt": None, "estimatedMinutes": 1,
                             "estimatedMinutesSource": "USER", "remainingMinutes": 1,
                             "amountText": None, "amountSource": "UNKNOWN"},
        missing_fields=[],
        pending_question=None,
        target_task_id=target_task_id,
        target_fixed_schedule_id=None,
        executed_at=None,
    )
    fields.update(overrides)
    return SolarRequestItem(**fields)


def make_fixed_schedule_update_item(
    *,
    user_id: uuid.UUID,
    solar_request_id: uuid.UUID,
    item_order: int,
    target_fixed_schedule_id: uuid.UUID,
    payload: dict,
    update_fields: list[str],
    **overrides,
) -> SolarRequestItem:
    fields = dict(
        id=uuid.uuid4(),
        user_id=user_id,
        solar_request_id=solar_request_id,
        item_order=item_order,
        action=SolarAction.UPDATE,
        entity_type=SolarEntityType.FIXED_SCHEDULE,
        status=SolarItemStatus.READY,
        raw_line_text=payload.get("title", "fixed schedule update"),
        normalized_payload={**payload, "_updateFields": update_fields},
        missing_fields=[],
        pending_question=None,
        target_task_id=None,
        target_fixed_schedule_id=target_fixed_schedule_id,
        executed_at=None,
    )
    fields.update(overrides)
    return SolarRequestItem(**fields)


def make_fixed_schedule_delete_item(
    *,
    user_id: uuid.UUID,
    solar_request_id: uuid.UUID,
    item_order: int,
    target_fixed_schedule_id: uuid.UUID,
    **overrides,
) -> SolarRequestItem:
    fields = dict(
        id=uuid.uuid4(),
        user_id=user_id,
        solar_request_id=solar_request_id,
        item_order=item_order,
        action=SolarAction.DELETE,
        entity_type=SolarEntityType.FIXED_SCHEDULE,
        status=SolarItemStatus.READY,
        raw_line_text="fixed schedule delete",
        normalized_payload={"title": "삭제된 일정", "startAt": "2026-07-29T10:00:00+09:00",
                             "endAt": "2026-07-29T11:00:00+09:00"},
        missing_fields=[],
        pending_question=None,
        target_task_id=None,
        target_fixed_schedule_id=target_fixed_schedule_id,
        executed_at=None,
    )
    fields.update(overrides)
    return SolarRequestItem(**fields)
