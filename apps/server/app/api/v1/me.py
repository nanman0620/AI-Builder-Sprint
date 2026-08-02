import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import AuthenticatedUser, get_current_user
from app.db.session import get_db
from app.models.user_profile import UserProfile
from app.schemas.profile import (
    OnboardingRequest,
    ProfileOut,
    ProfileResponse,
    ProfileUpdateRequest,
)
from app.services import account_deletion_service, profile_service

router = APIRouter()


def to_profile_out(profile: UserProfile, email: str) -> ProfileOut:
    return ProfileOut(
        id=profile.id,
        email=email,
        nickname=profile.nickname,
        onboarding_completed=profile.onboarding_completed,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def get_required_email(db: Session, user_id: uuid.UUID) -> str:
    # 카카오 OAuth는 이메일 동의항목이 승인되지 않으면 auth.users.email이 NULL일 수 있다.
    # bootstrap_service.get_bootstrap_state와 동일하게 빈 문자열로 대체해 요청을 실패시키지 않는다.
    return profile_service.get_user_email(db, user_id) or ""


def upsert_onboarding_profile(db: Session, user_id: uuid.UUID, nickname: str) -> UserProfile:
    profile = db.get(UserProfile, user_id)
    if profile is None:
        profile = UserProfile(id=user_id, nickname=nickname, onboarding_completed=True)
        db.add(profile)
    else:
        profile.nickname = nickname
        profile.onboarding_completed = True

    db.flush()
    db.refresh(profile)
    return profile


@router.get("/me", response_model=ProfileResponse)
def get_me(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProfileResponse:
    profile = profile_service.get_profile(db, current_user.id)
    if profile is None:
        raise ApiError(404, "PROFILE_NOT_FOUND", "프로필을 찾을 수 없어요.")

    email = get_required_email(db, current_user.id)
    return ProfileResponse(data=to_profile_out(profile, email))


@router.put("/me/onboarding", response_model=ProfileResponse)
def update_onboarding(
    body: OnboardingRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProfileResponse:
    nickname = body.nickname.strip()
    if not nickname:
        raise ApiError(422, "INVALID_NICKNAME", "닉네임을 입력해 주세요.")

    with db.begin():
        profile = upsert_onboarding_profile(db, current_user.id, nickname)
        email = get_required_email(db, current_user.id)
        profile_out = to_profile_out(profile, email)

    return ProfileResponse(data=profile_out)


@router.patch("/me/profile", response_model=ProfileResponse)
def update_profile(
    body: ProfileUpdateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProfileResponse:
    nickname = body.nickname.strip()
    if not nickname:
        raise ApiError(422, "INVALID_NICKNAME", "닉네임을 입력해 주세요.")

    with db.begin():
        profile = profile_service.update_nickname(db, current_user.id, nickname)
        if profile is None:
            raise ApiError(404, "PROFILE_NOT_FOUND", "프로필을 찾을 수 없어요.")

        email = get_required_email(db, current_user.id)
        profile_out = to_profile_out(profile, email)

    return ProfileResponse(data=profile_out)


# 최종 API 명세서 §12는 회원탈퇴를 "시연용 로컬 처리, FastAPI 호출 없음(DELETE /me 없음)"으로
# 명시하지만, 사용자가 이를 확인한 뒤 명세서 범위를 넘어서는 추가 기능으로 명시적으로 요청해
# 만든 endpoint다(docs/ai/AI_USAGE_LOG.md 참고). 프로필·앱 데이터가 이미 없어도 멱등하게
# 동작하므로 get_current_user(JWT sub만 검증, 프로필 존재 비의존)를 그대로 쓴다.
@router.delete("/me", status_code=204)
def delete_me(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    account_deletion_service.delete_account(db, current_user.id)
    return Response(status_code=204)
