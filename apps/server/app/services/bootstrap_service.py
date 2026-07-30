import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from sqlalchemy.orm import Session

from app.models.planning_cycle import PlanningCycle
from app.models.solar_request import SolarRequest
from app.services import home_service, profile_service, solar_request_service
from app.services.home_service import HomeCurrentState
from app.services.solar_request_service import PlanManagementScreenMode


class InitialScreen(str, Enum):
    NICKNAME_CREATION = "NICKNAME_CREATION"
    # 우선순위 2: 현재 SOLAR 요청 존재 (EXECUTION_SUCCESS/EXECUTION_FAILED 포함).
    COLLECTING = "COLLECTING"
    CHANGE_CONFIRMATION = "CHANGE_CONFIRMATION"
    CHANGE_INPUT = "CHANGE_INPUT"
    FINAL_REVIEW = "FINAL_REVIEW"
    EXECUTING = "EXECUTING"
    EXECUTION_SUCCESS = "EXECUTION_SUCCESS"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    # 우선순위 3: 현재 SOLAR 요청 없음. home_service가 실제로 지원하는 상태만 포함한다
    # (FINALIZING/CHECK_IN_RESULT/DEADLINE_WARNING은 home_service 미구현이라 여기 없음).
    NO_ACTIVE_CYCLE = "NO_ACTIVE_CYCLE"
    NO_PLANS = "NO_PLANS"
    IN_PROGRESS = "IN_PROGRESS"


@dataclass(frozen=True)
class BootstrapProfile:
    id: uuid.UUID
    email: str
    nickname: str | None
    onboarding_completed: bool


@dataclass(frozen=True)
class BootstrapState:
    server_time: datetime
    profile: BootstrapProfile
    initial_screen: InitialScreen
    active_cycle: PlanningCycle | None
    plan_management_screen_mode: PlanManagementScreenMode | None
    current_request: SolarRequest | None
    home_state: HomeCurrentState | None


def get_bootstrap_state(db: Session, user_id: uuid.UUID, *, now: datetime) -> BootstrapState:
    """앱 초기화·동기화에 필요한 전체 상태를 조회한다.

    완전한 조회 전용이며 DB에 어떤 쓰기도 하지 않는다(db.begin()을 호출하지 않음).
    profile/home/현재 SolarRequest 존재 여부는 각각의 기존 조회 전용 service를 그대로 재사용하고,
    이 함수 안에서 같은 SQL이나 상태 계산을 다시 만들지 않는다.
    """
    profile_row = profile_service.get_profile(db, user_id)
    email = profile_service.get_user_email(db, user_id)
    if email is None:
        # FK(user_profiles.id -> auth.users.id)와 Supabase Auth가 행 존재를 보장하므로
        # 정상 흐름에서는 발생하지 않아야 한다. 데이터 정합성 문제로 간주해 명확한 오류로 남긴다.
        raise RuntimeError("auth.users에서 사용자 이메일을 찾을 수 없다.")

    # 온보딩 전에는 user_profiles 행 자체가 없을 수 있다(PUT /me/onboarding에서 최초 생성).
    onboarding_completed = profile_row.onboarding_completed if profile_row else False
    nickname = profile_row.nickname if profile_row else None

    profile = BootstrapProfile(
        id=user_id, email=email, nickname=nickname, onboarding_completed=onboarding_completed
    )

    if not onboarding_completed:
        return BootstrapState(
            server_time=now,
            profile=profile,
            initial_screen=InitialScreen.NICKNAME_CREATION,
            active_cycle=None,
            plan_management_screen_mode=None,
            current_request=None,
            home_state=None,
        )

    home_state = home_service.get_home_current_state(db, user_id, now=now)
    current_request = solar_request_service.get_current_solar_request(db, user_id)

    if current_request is not None:
        screen_mode = solar_request_service.resolve_current_request_screen_mode(current_request)
        initial_screen = InitialScreen(screen_mode.value)
    else:
        screen_mode = solar_request_service.resolve_no_request_screen_mode(
            has_active_cycle=home_state.active_cycle is not None
        )
        initial_screen = InitialScreen(home_state.home_mode.value)

    return BootstrapState(
        server_time=now,
        profile=profile,
        initial_screen=initial_screen,
        active_cycle=home_state.active_cycle,
        plan_management_screen_mode=screen_mode,
        current_request=current_request,
        home_state=home_state,
    )
