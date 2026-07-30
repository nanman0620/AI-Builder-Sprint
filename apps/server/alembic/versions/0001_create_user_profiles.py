"""create user_profiles

Revision ID: 0001_create_user_profiles
Revises:
Create Date: 2026-07-30

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001_create_user_profiles"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("nickname", sa.Text(), nullable=True),
        sa.Column(
            "onboarding_completed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "nickname IS NULL OR btrim(nickname) <> ''",
            name=op.f("ck_user_profiles_nickname_not_blank"),
        ),
        sa.CheckConstraint(
            "onboarding_completed = false OR nickname IS NOT NULL",
            name=op.f("ck_user_profiles_onboarding_requires_nickname"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_profiles")),
        sa.ForeignKeyConstraint(
            ["id"],
            ["auth.users.id"],
            name=op.f("fk_user_profiles_id_users"),
            ondelete="RESTRICT",
        ),
        schema="public",
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.set_updated_at()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER set_user_profiles_updated_at
        BEFORE UPDATE ON public.user_profiles
        FOR EACH ROW
        EXECUTE FUNCTION public.set_updated_at();
        """
    )

    op.execute("ALTER TABLE public.user_profiles ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY user_profiles_select_own
        ON public.user_profiles
        FOR SELECT
        TO authenticated
        USING (id = auth.uid());
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS set_user_profiles_updated_at ON public.user_profiles;"
    )
    op.execute(
        "DROP POLICY IF EXISTS user_profiles_select_own ON public.user_profiles;"
    )
    op.drop_table("user_profiles", schema="public")
    op.execute("DROP FUNCTION IF EXISTS public.set_updated_at();")
