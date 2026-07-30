from sqlalchemy import Boolean, CheckConstraint, DateTime, Text

from app.models.user_profile import UserProfile


def test_table_name():
    assert UserProfile.__tablename__ == "user_profiles"


def test_id_is_primary_key_and_foreign_key_to_auth_users():
    id_column = UserProfile.__table__.c.id

    assert id_column.primary_key is True
    assert id_column.nullable is False

    foreign_keys = list(id_column.foreign_keys)
    assert len(foreign_keys) == 1
    assert foreign_keys[0].target_fullname == "auth.users.id"
    assert foreign_keys[0].ondelete == "RESTRICT"


def test_nickname_column_is_nullable_text():
    nickname_column = UserProfile.__table__.c.nickname

    assert isinstance(nickname_column.type, Text)
    assert nickname_column.nullable is True
    assert nickname_column.unique is not True


def test_onboarding_completed_column():
    column = UserProfile.__table__.c.onboarding_completed

    assert isinstance(column.type, Boolean)
    assert column.nullable is False
    assert column.server_default is not None
    assert "false" in str(column.server_default.arg).lower()


def test_created_at_and_updated_at_columns():
    created_at = UserProfile.__table__.c.created_at
    updated_at = UserProfile.__table__.c.updated_at

    for column in (created_at, updated_at):
        assert isinstance(column.type, DateTime)
        assert column.type.timezone is True
        assert column.nullable is False
        assert column.server_default is not None


def test_check_constraints_are_registered():
    check_constraint_names = {
        constraint.name
        for constraint in UserProfile.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert any(
        name and name.endswith("nickname_not_blank")
        for name in check_constraint_names
    )
    assert any(
        name and name.endswith("onboarding_requires_nickname")
        for name in check_constraint_names
    )
