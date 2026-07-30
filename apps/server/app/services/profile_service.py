import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.external import auth_users
from app.models.user_profile import UserProfile


def get_profile(db: Session, user_id: uuid.UUID) -> UserProfile | None:
    """user_profiles 조회 전용. 온보딩 전에는 행이 아직 없을 수 있으므로 None을 반환할 수 있다."""
    return db.get(UserProfile, user_id)


def get_user_email(db: Session, user_id: uuid.UUID) -> str | None:
    """auth.users.email 조회 전용. user_profiles에는 이메일을 중복 저장하지 않는다."""
    return db.execute(
        select(auth_users.c.email).where(auth_users.c.id == user_id)
    ).scalar_one_or_none()
