import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import AuthenticatedUser, get_current_user
from app.db.external import auth_users
from app.db.session import get_db
from app.models.user_profile import UserProfile
from app.schemas.profile import OnboardingRequest, ProfileOut, ProfileResponse

router = APIRouter()


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

        email = db.execute(
            select(auth_users.c.email).where(auth_users.c.id == current_user.id)
        ).scalar_one_or_none()

        if email is None:
            # FK(user_profiles.id -> auth.users.id ON DELETE RESTRICT)가 행 존재를 보장하므로
            # 정상 흐름에서는 발생하지 않아야 한다. 데이터 정합성 문제로 간주해 명확한 오류로 남긴다.
            raise RuntimeError("auth.users에서 사용자 이메일을 찾을 수 없다.")

        profile_out = ProfileOut(
            id=profile.id,
            email=email,
            nickname=profile.nickname,
            onboarding_completed=profile.onboarding_completed,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )

    return ProfileResponse(data=profile_out)
