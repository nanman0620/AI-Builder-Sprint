import uuid
from unittest.mock import MagicMock

from app.models.user_profile import UserProfile
from app.services import profile_service


def test_get_profile_uses_authenticated_user_id():
    user_id = uuid.uuid4()
    profile = UserProfile(id=user_id, nickname="유림", onboarding_completed=True)
    db = MagicMock()
    db.get.return_value = profile

    result = profile_service.get_profile(db, user_id)

    assert result is profile
    db.get.assert_called_once_with(UserProfile, user_id)


def test_update_nickname_updates_only_requested_user_and_refreshes_latest_row():
    user_id = uuid.uuid4()
    profile = UserProfile(id=user_id, nickname="기존 닉네임", onboarding_completed=True)
    db = MagicMock()
    db.get.return_value = profile

    result = profile_service.update_nickname(db, user_id, "새 닉네임")

    assert result is profile
    assert profile.nickname == "새 닉네임"
    db.get.assert_called_once_with(UserProfile, user_id)
    db.flush.assert_called_once_with()
    db.refresh.assert_called_once_with(profile)


def test_update_nickname_returns_none_without_writing_when_profile_is_missing():
    user_id = uuid.uuid4()
    db = MagicMock()
    db.get.return_value = None

    result = profile_service.update_nickname(db, user_id, "유림")

    assert result is None
    db.flush.assert_not_called()
    db.refresh.assert_not_called()


def test_same_nickname_can_be_used_by_multiple_users():
    first_user_id = uuid.uuid4()
    second_user_id = uuid.uuid4()
    first_profile = UserProfile(
        id=first_user_id, nickname="첫 번째", onboarding_completed=True
    )
    second_profile = UserProfile(
        id=second_user_id, nickname="두 번째", onboarding_completed=True
    )
    first_db = MagicMock()
    first_db.get.return_value = first_profile
    second_db = MagicMock()
    second_db.get.return_value = second_profile

    profile_service.update_nickname(first_db, first_user_id, "같은 닉네임")
    profile_service.update_nickname(second_db, second_user_id, "같은 닉네임")

    assert first_profile.nickname == "같은 닉네임"
    assert second_profile.nickname == "같은 닉네임"
