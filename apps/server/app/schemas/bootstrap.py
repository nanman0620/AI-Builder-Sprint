import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import SolarRequestPurpose, SolarRequestStatus
from app.schemas.home import ActiveCycleOut, HomeCurrentOut, to_active_cycle_out, to_home_current_response
from app.services.bootstrap_service import BootstrapState, InitialScreen
from app.services.solar_request_service import PlanManagementScreenMode


class BootstrapProfileOut(BaseModel):
    id: uuid.UUID
    email: str
    nickname: str | None
    onboarding_completed: bool = Field(alias="onboardingCompleted")

    model_config = ConfigDict(populate_by_name=True)


class SolarRequestSummaryOut(BaseModel):
    """현재 SolarRequest의 최소 요약.

    messages/requestItems/currentQuestion/quickReplies/decisionPrompt 등 계획관리 채팅·카드
    상세 payload는 GET /plan-management/state 구현 전까지 포함하지 않는다(의도적 축소 스키마).
    """

    id: uuid.UUID
    purpose: SolarRequestPurpose
    status: SolarRequestStatus
    result_acknowledged_at: datetime | None = Field(alias="resultAcknowledgedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class PlanManagementOut(BaseModel):
    screen_mode: PlanManagementScreenMode = Field(alias="screenMode")
    active_cycle: ActiveCycleOut | None = Field(alias="activeCycle")
    request: SolarRequestSummaryOut | None

    model_config = ConfigDict(populate_by_name=True)


class BootstrapOut(BaseModel):
    server_time: datetime = Field(alias="serverTime")
    profile: BootstrapProfileOut
    initial_screen: InitialScreen = Field(alias="initialScreen")
    active_cycle: ActiveCycleOut | None = Field(alias="activeCycle")
    plan_management: PlanManagementOut | None = Field(alias="planManagement")
    home: HomeCurrentOut | None

    model_config = ConfigDict(populate_by_name=True)


class BootstrapResponse(BaseModel):
    data: BootstrapOut


def to_bootstrap_response(state: BootstrapState) -> BootstrapResponse:
    profile_out = BootstrapProfileOut(
        id=state.profile.id,
        email=state.profile.email,
        nickname=state.profile.nickname,
        onboarding_completed=state.profile.onboarding_completed,
    )

    if not state.profile.onboarding_completed:
        return BootstrapResponse(
            data=BootstrapOut(
                server_time=state.server_time,
                profile=profile_out,
                initial_screen=state.initial_screen,
                active_cycle=None,
                plan_management=None,
                home=None,
            )
        )

    active_cycle_out = to_active_cycle_out(state.active_cycle) if state.active_cycle else None

    plan_management_out = PlanManagementOut(
        screen_mode=state.plan_management_screen_mode,
        active_cycle=active_cycle_out,
        request=SolarRequestSummaryOut.model_validate(state.current_request)
        if state.current_request
        else None,
    )

    return BootstrapResponse(
        data=BootstrapOut(
            server_time=state.server_time,
            profile=profile_out,
            initial_screen=state.initial_screen,
            active_cycle=active_cycle_out,
            plan_management=plan_management_out,
            home=to_home_current_response(state.home_state).data,
        )
    )
