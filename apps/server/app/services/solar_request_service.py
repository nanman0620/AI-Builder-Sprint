import uuid
from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.models.enums import SolarRequestStatus
from app.models.solar_request import SolarRequest

CODE_REQUEST_NOT_FOUND = "REQUEST_NOT_FOUND"

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
