import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.models.check_in import CheckIn
from app.models.enums import PlanBlockStatus, PlanCycleStatus, PlanPeriod
from app.models.plan_block import PlanBlock
from app.services.plan_block_service import get_owned_planning_cycle

CODE_CHECK_IN_NOT_FOUND = "CHECK_IN_NOT_FOUND"
CODE_INVALID_REQUEST_STATE = "INVALID_REQUEST_STATE"


@dataclass(frozen=True)
class FinalizingInfo:
    check_in_id: uuid.UUID
    check_date: date
    period: PlanPeriod
    finalization_started_at: datetime


@dataclass(frozen=True)
class CheckInResultPlanBlock:
    id: uuid.UUID
    display_title: str
    status: PlanBlockStatus


@dataclass(frozen=True)
class CheckInResultState:
    id: uuid.UUID
    check_date: date
    period: PlanPeriod
    total_plan_count: int
    completed_plan_count: int
    not_done_plan_count: int
    score: int
    replan_unplaced_minutes: int
    finalized_at: datetime
    cycle_ended: bool
    completed_plans: list[CheckInResultPlanBlock]
    not_done_plans: list[CheckInResultPlanBlock]


@dataclass(frozen=True)
class AcknowledgeResult:
    target_check_in_id: uuid.UUID
    acknowledged_check_in_ids: list[uuid.UUID]
    result_acknowledged_at: datetime


def get_finalizing_info(db: Session, user_id: uuid.UUID) -> FinalizingInfo | None:
    """정산 중(finalized_at IS NULL)인 CheckIn 하나를 조회한다.

    완전한 조회 전용이며 DB에 어떤 쓰기도 하지 않는다. ACTIVE cycle 존재 여부와
    무관하게 조회한다(명세 4절). 여러 건이면 finalization_started_at DESC, id DESC로
    가장 최근 것 하나만 선택한다.
    """
    stmt = (
        select(CheckIn)
        .where(CheckIn.user_id == user_id, CheckIn.finalized_at.is_(None))
        .order_by(CheckIn.finalization_started_at.desc(), CheckIn.id.desc())
        .limit(1)
    )
    check_in = db.execute(stmt).scalars().first()
    if check_in is None:
        return None
    return FinalizingInfo(
        check_in_id=check_in.id,
        check_date=check_in.check_date,
        period=check_in.period,
        finalization_started_at=check_in.finalization_started_at,
    )


def _list_result_plan_blocks(db: Session, check_in_id: uuid.UUID) -> list[PlanBlock]:
    stmt = (
        select(PlanBlock)
        .where(PlanBlock.check_in_id == check_in_id)
        .order_by(PlanBlock.display_order, PlanBlock.id)
    )
    return list(db.execute(stmt).scalars().all())


def _to_result_plan_block(block: PlanBlock) -> CheckInResultPlanBlock:
    return CheckInResultPlanBlock(id=block.id, display_title=block.display_title, status=block.status)


def get_check_in_result_state(db: Session, user_id: uuid.UUID) -> CheckInResultState | None:
    """가장 최근 미확인 CheckIn 결과 하나를 상세 조회한다.

    완전한 조회 전용이며 DB에 어떤 쓰기도 하지 않는다. totalPlanCount/completedPlanCount/
    score/replanUnplacedMinutes는 CheckIn 저장값을 그대로 쓰고 재계산하지 않는다(명세 5절).
    cycleEnded는 CheckIn.plan_cycle_id에 연결된 PlanningCycle.status로 계산하며, 현재
    ACTIVE cycle 조회 결과를 사용하지 않는다(과거 cycle이 이미 ENDED됐을 수 있음).
    """
    stmt = (
        select(CheckIn)
        .where(
            CheckIn.user_id == user_id,
            CheckIn.finalized_at.isnot(None),
            CheckIn.result_acknowledged_at.is_(None),
        )
        .order_by(CheckIn.finalized_at.desc(), CheckIn.id.desc())
        .limit(1)
    )
    check_in = db.execute(stmt).scalars().first()
    if check_in is None:
        return None

    cycle = get_owned_planning_cycle(db, check_in.plan_cycle_id, user_id)
    blocks = _list_result_plan_blocks(db, check_in.id)
    completed_plans = [
        _to_result_plan_block(block) for block in blocks if block.status == PlanBlockStatus.COMPLETED
    ]
    not_done_plans = [
        _to_result_plan_block(block) for block in blocks if block.status == PlanBlockStatus.NOT_DONE
    ]

    return CheckInResultState(
        id=check_in.id,
        check_date=check_in.check_date,
        period=check_in.period,
        total_plan_count=check_in.total_plan_count,
        completed_plan_count=check_in.completed_plan_count,
        not_done_plan_count=check_in.total_plan_count - check_in.completed_plan_count,
        score=check_in.score,
        replan_unplaced_minutes=check_in.replan_unplaced_minutes,
        finalized_at=check_in.finalized_at,
        cycle_ended=cycle.status == PlanCycleStatus.ENDED,
        completed_plans=completed_plans,
        not_done_plans=not_done_plans,
    )


def _boundary_clause(*, finalized_at: datetime, check_in_id: uuid.UUID):
    """finalized_at < target 또는 (finalized_at == target AND id <= target)를 만드는 공통 조건.

    최초 확인의 처리 대상 조회와 중복 확인의 기존 결과 재구성 조회가 동일한 경계를
    사용해야 하므로(명세 9·10절) 하나의 함수로 공유한다.
    """
    return or_(
        CheckIn.finalized_at < finalized_at,
        and_(CheckIn.finalized_at == finalized_at, CheckIn.id <= check_in_id),
    )


def acknowledge_check_in(
    db: Session, *, user_id: uuid.UUID, check_in_id: uuid.UUID, now: datetime
) -> AcknowledgeResult:
    """대상 CheckIn과 그보다 오래된 미확인 결과를 같은 시각으로 확인 처리한다.

    이미 확인된 target으로 재호출하면 DB를 변경하지 않고, 최초 확인과 동일한 경계
    조건에 target의 기존 result_acknowledged_at을 결합해 원래 응답을 재구성한다(멱등).
    트랜잭션 전체가 성공하거나 전체 rollback된다. now는 반드시 호출자가 전달하며
    이 함수 내부에서 datetime.now()를 호출하지 않는다.
    """
    with db.begin():
        target = (
            db.execute(
                select(CheckIn)
                .where(CheckIn.id == check_in_id, CheckIn.user_id == user_id)
                .with_for_update()
            )
            .scalars()
            .one_or_none()
        )
        if target is None:
            raise ApiError(404, CODE_CHECK_IN_NOT_FOUND, "CheckIn을 찾을 수 없어요.")

        if target.finalized_at is None:
            raise ApiError(409, CODE_INVALID_REQUEST_STATE, "정산이 끝나지 않은 결과예요.")

        if target.result_acknowledged_at is not None:
            existing_stmt = (
                select(CheckIn)
                .where(
                    CheckIn.user_id == user_id,
                    CheckIn.result_acknowledged_at == target.result_acknowledged_at,
                    CheckIn.finalized_at.isnot(None),
                    _boundary_clause(finalized_at=target.finalized_at, check_in_id=target.id),
                )
                .order_by(CheckIn.finalized_at.asc(), CheckIn.id.asc())
            )
            existing_rows = db.execute(existing_stmt).scalars().all()
            return AcknowledgeResult(
                target_check_in_id=target.id,
                acknowledged_check_in_ids=[row.id for row in existing_rows],
                result_acknowledged_at=target.result_acknowledged_at,
            )

        boundary_stmt = (
            select(CheckIn)
            .where(
                CheckIn.user_id == user_id,
                CheckIn.result_acknowledged_at.is_(None),
                CheckIn.finalized_at.isnot(None),
                _boundary_clause(finalized_at=target.finalized_at, check_in_id=target.id),
            )
            .order_by(CheckIn.finalized_at.asc(), CheckIn.id.asc())
            .with_for_update()
        )
        targets = list(db.execute(boundary_stmt).scalars().all())

        for row in targets:
            row.result_acknowledged_at = now
        db.flush()

        acknowledged_ids = [row.id for row in targets]

    return AcknowledgeResult(
        target_check_in_id=target.id,
        acknowledged_check_in_ids=acknowledged_ids,
        result_acknowledged_at=now,
    )
