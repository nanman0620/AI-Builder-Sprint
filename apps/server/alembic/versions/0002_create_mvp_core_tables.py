"""create mvp core tables

Revision ID: 0002_create_mvp_core_tables
Revises: 0001_create_user_profiles
Create Date: 2026-07-30

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0002_create_mvp_core_tables"
down_revision = "0001_create_user_profiles"
branch_labels = None
depends_on = None


ENUM_DEFINITIONS = [
    ("plan_cycle_status", ["ACTIVE", "ENDED"]),
    ("solar_request_purpose", ["NEW_CYCLE", "ACTIVE_CYCLE"]),
    (
        "solar_request_status",
        [
            "COLLECTING",
            "CHANGE_CONFIRMATION",
            "CHANGE_INPUT",
            "FINAL_REVIEW",
            "EXECUTING",
            "COMPLETED",
            "FAILED",
        ],
    ),
    ("solar_action", ["CREATE", "UPDATE", "DELETE"]),
    ("solar_entity_type", ["TASK", "FIXED_SCHEDULE"]),
    ("solar_item_status", ["INFO_MISSING", "READY", "EXECUTED"]),
    ("solar_message_role", ["USER", "ASSISTANT"]),
    ("solar_message_kind", ["TEXT", "QUESTION", "ERROR", "DECISION"]),
    ("plan_period", ["MORNING", "AFTERNOON", "EVENING"]),
    ("task_status", ["ACTIVE", "COMPLETED", "CANCELLED"]),
    ("plan_block_status", ["PLANNED", "CHECKED", "COMPLETED", "NOT_DONE"]),
    ("estimate_source", ["USER", "AI_ESTIMATED"]),
    ("amount_source", ["USER", "AI_ESTIMATED", "UNKNOWN"]),
]

# 이번 migration이 생성한 테이블 중 updated_at 트리거가 필요한 테이블
# (user_profiles는 0001에서 이미 처리했으므로 제외, solar_messages·check_ins는
# updated_at 컬럼 자체가 없으므로 제외)
UPDATED_AT_TRIGGER_TABLES = [
    "planning_cycles",
    "solar_requests",
    "solar_request_items",
    "tasks",
    "fixed_schedules",
    "plan_blocks",
]

# 이번 migration이 생성한 모든 앱 테이블 (RLS 활성화 + user_id 기반 SELECT 정책 대상)
RLS_TABLES = [
    "planning_cycles",
    "solar_requests",
    "solar_request_items",
    "solar_messages",
    "tasks",
    "fixed_schedules",
    "plan_blocks",
    "check_ins",
]


def _enum(name: str) -> postgresql.ENUM:
    values = dict(ENUM_DEFINITIONS)[name]
    return postgresql.ENUM(*values, name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()

    for name, values in ENUM_DEFINITIONS:
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)

    # 1. planning_cycles -----------------------------------------------------
    op.create_table(
        "planning_cycles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", _enum("plan_cycle_status"), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_planning_cycles")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_profiles.id"],
            name=op.f("fk_planning_cycles_user_id_user_profiles"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "user_id", name="uq_planning_cycles_id_user"),
        sa.CheckConstraint("end_date = start_date + 6", name="ck_planning_cycles_cycle_is_exactly_seven_days"),
        sa.CheckConstraint(
            "(status = 'ACTIVE' AND ended_at IS NULL) OR (status = 'ENDED' AND ended_at IS NOT NULL)",
            name="ck_planning_cycles_status_matches_ended_at",
        ),
        schema="public",
    )
    op.create_index(
        "uq_planning_cycles_one_active_per_user",
        "planning_cycles",
        ["user_id"],
        unique=True,
        schema="public",
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )

    # 2. solar_requests -------------------------------------------------------
    op.create_table(
        "solar_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_cycle_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("purpose", _enum("solar_request_purpose"), nullable=False),
        sa.Column("status", _enum("solar_request_status"), nullable=False),
        sa.Column("raw_input", sa.Text(), nullable=False),
        sa.Column("current_item_order", sa.SmallInteger(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "execution_attempt_count", sa.SmallInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("execution_result", postgresql.JSONB(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("result_acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_solar_requests")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_profiles.id"],
            name=op.f("fk_solar_requests_user_id_user_profiles"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["plan_cycle_id", "user_id"],
            ["planning_cycles.id", "planning_cycles.user_id"],
            name="fk_solar_requests_plan_cycle_id_user_id_planning_cycles",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "user_id", name="uq_solar_requests_id_user"),
        sa.CheckConstraint("btrim(raw_input) <> ''", name="ck_solar_requests_raw_input_not_blank"),
        sa.CheckConstraint(
            "execution_attempt_count >= 0", name="ck_solar_requests_execution_attempt_count_non_negative"
        ),
        sa.CheckConstraint(
            "status <> 'EXECUTING' OR ("
            "execution_started_at IS NOT NULL AND execution_attempt_count >= 1 "
            "AND executed_at IS NULL AND execution_result IS NULL "
            "AND error_code IS NULL AND error_message IS NULL)",
            name="ck_solar_requests_executing_state_consistency",
        ),
        sa.CheckConstraint(
            "status <> 'COMPLETED' OR ("
            "execution_started_at IS NOT NULL AND execution_attempt_count >= 1 "
            "AND executed_at IS NOT NULL AND execution_result IS NOT NULL "
            "AND error_code IS NULL AND error_message IS NULL)",
            name="ck_solar_requests_completed_state_consistency",
        ),
        sa.CheckConstraint(
            "status <> 'FAILED' OR ("
            "execution_started_at IS NOT NULL AND execution_attempt_count >= 1 "
            "AND executed_at IS NULL AND execution_result IS NULL "
            "AND error_code IS NOT NULL AND error_message IS NOT NULL)",
            name="ck_solar_requests_failed_state_consistency",
        ),
        sa.CheckConstraint(
            "result_acknowledged_at IS NULL OR status = 'COMPLETED'",
            name="ck_solar_requests_result_acknowledged_requires_completed",
        ),
        schema="public",
    )
    op.create_index(
        "uq_solar_requests_one_current_per_user",
        "solar_requests",
        ["user_id"],
        unique=True,
        schema="public",
        postgresql_where=sa.text(
            "status IN ('COLLECTING', 'CHANGE_CONFIRMATION', 'CHANGE_INPUT', "
            "'FINAL_REVIEW', 'EXECUTING', 'FAILED') "
            "OR (status = 'COMPLETED' AND result_acknowledged_at IS NULL)"
        ),
    )
    op.create_index(
        "ix_solar_requests_user_updated",
        "solar_requests",
        ["user_id", sa.text("updated_at DESC")],
        schema="public",
    )

    # 3. tasks (source_request_item_id FK는 solar_request_items 생성 후 추가) ----
    op.create_table(
        "tasks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_request_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("amount_text", sa.Text(), nullable=True),
        sa.Column("amount_source", _enum("amount_source"), nullable=False),
        sa.Column("initial_minutes", sa.Integer(), nullable=False),
        sa.Column("estimated_minutes", sa.Integer(), nullable=False),
        sa.Column("estimated_minutes_source", _enum("estimate_source"), nullable=False),
        sa.Column("remaining_minutes", sa.Integer(), nullable=False),
        sa.Column("status", _enum("task_status"), nullable=False),
        sa.Column("deadline_warning_acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user_profiles.id"], name=op.f("fk_tasks_user_id_user_profiles"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["plan_cycle_id", "user_id"],
            ["planning_cycles.id", "planning_cycles.user_id"],
            name="fk_tasks_plan_cycle_id_user_id_planning_cycles",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "user_id", name="uq_tasks_id_user"),
        sa.UniqueConstraint("id", "user_id", "plan_cycle_id", name="uq_tasks_id_user_cycle"),
        sa.CheckConstraint("initial_minutes >= 1", name="ck_tasks_initial_minutes_positive"),
        sa.CheckConstraint("estimated_minutes >= 1", name="ck_tasks_estimated_minutes_positive"),
        sa.CheckConstraint("remaining_minutes >= 0", name="ck_tasks_remaining_minutes_non_negative"),
        sa.CheckConstraint("btrim(title) <> ''", name="ck_tasks_title_not_blank"),
        sa.CheckConstraint(
            "(status = 'ACTIVE' AND remaining_minutes > 0 AND completed_at IS NULL AND cancelled_at IS NULL)"
            " OR (status = 'COMPLETED' AND remaining_minutes = 0 AND completed_at IS NOT NULL"
            "     AND cancelled_at IS NULL)"
            " OR (status = 'CANCELLED' AND remaining_minutes >= 0 AND completed_at IS NULL"
            "     AND cancelled_at IS NOT NULL)",
            name="ck_tasks_status_consistency",
        ),
        sa.CheckConstraint(
            "(amount_source = 'UNKNOWN' AND amount_text IS NULL)"
            " OR (amount_source IN ('USER', 'AI_ESTIMATED') AND amount_text IS NOT NULL"
            "     AND btrim(amount_text) <> '')",
            name="ck_tasks_amount_source_consistency",
        ),
        schema="public",
    )
    op.create_index(
        "uq_tasks_source_request_item",
        "tasks",
        ["source_request_item_id"],
        unique=True,
        schema="public",
        postgresql_where=sa.text("source_request_item_id IS NOT NULL"),
    )
    op.create_index("ix_tasks_plan_cycle", "tasks", ["plan_cycle_id"], schema="public")
    op.create_index(
        "ix_tasks_active_deadline",
        "tasks",
        ["user_id", "plan_cycle_id", "deadline_at"],
        schema="public",
        postgresql_where=sa.text(
            "status = 'ACTIVE' AND remaining_minutes > 0 AND deadline_at IS NOT NULL "
            "AND deadline_warning_acknowledged_at IS NULL"
        ),
    )

    # 4. fixed_schedules (source_request_item_id FK는 이후 추가) ----------------
    op.create_table(
        "fixed_schedules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_request_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fixed_schedules")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_profiles.id"],
            name=op.f("fk_fixed_schedules_user_id_user_profiles"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["plan_cycle_id", "user_id"],
            ["planning_cycles.id", "planning_cycles.user_id"],
            name="fk_fixed_schedules_plan_cycle_id_user_id_planning_cycles",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "user_id", name="uq_fixed_schedules_id_user"),
        sa.CheckConstraint("start_at < end_at", name="ck_fixed_schedules_start_before_end"),
        sa.CheckConstraint("btrim(title) <> ''", name="ck_fixed_schedules_title_not_blank"),
        schema="public",
    )
    op.create_index(
        "uq_fixed_schedules_source_request_item",
        "fixed_schedules",
        ["source_request_item_id"],
        unique=True,
        schema="public",
        postgresql_where=sa.text("source_request_item_id IS NOT NULL"),
    )
    op.create_index("ix_fixed_schedules_plan_cycle", "fixed_schedules", ["plan_cycle_id"], schema="public")
    op.create_index(
        "ix_fixed_schedules_range", "fixed_schedules", ["user_id", "start_at", "end_at"], schema="public"
    )

    # 5. solar_request_items ---------------------------------------------------
    op.create_table(
        "solar_request_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("solar_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_order", sa.SmallInteger(), nullable=False),
        sa.Column("action", _enum("solar_action"), nullable=False),
        sa.Column("entity_type", _enum("solar_entity_type"), nullable=False),
        sa.Column("status", _enum("solar_item_status"), nullable=False),
        sa.Column("raw_line_text", sa.Text(), nullable=False),
        sa.Column("normalized_payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "missing_fields",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("pending_question", postgresql.JSONB(), nullable=True),
        sa.Column("target_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_fixed_schedule_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_solar_request_items")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_profiles.id"],
            name=op.f("fk_solar_request_items_user_id_user_profiles"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["solar_request_id", "user_id"],
            ["solar_requests.id", "solar_requests.user_id"],
            name="fk_solar_request_items_solar_request_id_user_id_solar_requests",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_task_id", "user_id"],
            ["tasks.id", "tasks.user_id"],
            name="fk_solar_request_items_target_task_id_user_id_tasks",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_fixed_schedule_id", "user_id"],
            ["fixed_schedules.id", "fixed_schedules.user_id"],
            name="fk_solar_request_items_target_fixed_schedule_id",
            ondelete="SET NULL (target_fixed_schedule_id)",
        ),
        sa.UniqueConstraint("id", "user_id", name="uq_solar_request_items_id_user"),
        sa.UniqueConstraint("solar_request_id", "item_order", name="uq_solar_request_items_order"),
        sa.CheckConstraint(
            "(action = 'CREATE' AND target_task_id IS NULL AND target_fixed_schedule_id IS NULL)"
            " OR (action IN ('UPDATE', 'DELETE') AND entity_type = 'TASK'"
            "     AND target_task_id IS NOT NULL AND target_fixed_schedule_id IS NULL)"
            " OR (action = 'UPDATE' AND entity_type = 'FIXED_SCHEDULE'"
            "     AND target_task_id IS NULL AND target_fixed_schedule_id IS NOT NULL)"
            " OR (action = 'DELETE' AND entity_type = 'FIXED_SCHEDULE' AND status <> 'EXECUTED'"
            "     AND target_task_id IS NULL AND target_fixed_schedule_id IS NOT NULL)"
            " OR (action = 'DELETE' AND entity_type = 'FIXED_SCHEDULE' AND status = 'EXECUTED'"
            "     AND target_task_id IS NULL)",
            name="ck_solar_request_items_target_reference_integrity",
        ),
        sa.CheckConstraint(
            "(status = 'INFO_MISSING' AND array_length(missing_fields, 1) > 0 AND executed_at IS NULL)"
            " OR (status = 'READY' AND coalesce(array_length(missing_fields, 1), 0) = 0"
            "     AND executed_at IS NULL)"
            " OR (status = 'EXECUTED' AND coalesce(array_length(missing_fields, 1), 0) = 0"
            "     AND executed_at IS NOT NULL)",
            name="ck_solar_request_items_card_status_consistency",
        ),
        schema="public",
    )

    # tasks/fixed_schedules -> solar_request_items (순환 참조 해소: 이제 대상 테이블 존재) --
    op.create_foreign_key(
        "fk_tasks_source_request_item_id_user_id_solar_request_items",
        "tasks",
        "solar_request_items",
        ["source_request_item_id", "user_id"],
        ["id", "user_id"],
        source_schema="public",
        referent_schema="public",
        ondelete="SET NULL (source_request_item_id)",
    )
    op.create_foreign_key(
        "fk_fixed_schedules_source_request_item_id",
        "fixed_schedules",
        "solar_request_items",
        ["source_request_item_id", "user_id"],
        ["id", "user_id"],
        source_schema="public",
        referent_schema="public",
        ondelete="SET NULL (source_request_item_id)",
    )

    # 6. solar_messages ---------------------------------------------------------
    op.create_table(
        "solar_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("solar_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_event_id", sa.Text(), nullable=True),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("role", _enum("solar_message_role"), nullable=False),
        sa.Column("kind", _enum("solar_message_kind"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_solar_messages")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_profiles.id"],
            name=op.f("fk_solar_messages_user_id_user_profiles"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["solar_request_id", "user_id"],
            ["solar_requests.id", "solar_requests.user_id"],
            name="fk_solar_messages_solar_request_id_user_id_solar_requests",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("solar_request_id", "sequence_no", name="uq_solar_messages_sequence"),
        sa.CheckConstraint("btrim(content) <> ''", name="ck_solar_messages_content_not_blank"),
        schema="public",
    )
    op.create_index(
        "uq_solar_messages_client_event",
        "solar_messages",
        ["solar_request_id", "client_event_id"],
        unique=True,
        schema="public",
        postgresql_where=sa.text("client_event_id IS NOT NULL"),
    )

    # 7. check_ins ----------------------------------------------------------------
    op.create_table(
        "check_ins",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("check_date", sa.Date(), nullable=False),
        sa.Column("period", _enum("plan_period"), nullable=False),
        sa.Column("total_plan_count", sa.Integer(), nullable=True),
        sa.Column("completed_plan_count", sa.Integer(), nullable=True),
        sa.Column("score", sa.SmallInteger(), nullable=True),
        sa.Column("replan_unplaced_minutes", sa.Integer(), nullable=True),
        sa.Column(
            "finalization_started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("replanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_check_ins")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user_profiles.id"], name=op.f("fk_check_ins_user_id_user_profiles"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["plan_cycle_id", "user_id"],
            ["planning_cycles.id", "planning_cycles.user_id"],
            name="fk_check_ins_plan_cycle_id_user_id_planning_cycles",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "id", "user_id", "plan_cycle_id", "check_date", "period", name="uq_check_ins_full_identity"
        ),
        sa.UniqueConstraint(
            "plan_cycle_id", "check_date", "period", name="uq_check_ins_cycle_date_period"
        ),
        sa.CheckConstraint(
            "finalized_at IS NULL OR ("
            "total_plan_count IS NOT NULL "
            "AND completed_plan_count IS NOT NULL "
            "AND score IS NOT NULL "
            "AND replan_unplaced_minutes IS NOT NULL "
            "AND total_plan_count > 0 "
            "AND completed_plan_count BETWEEN 0 AND total_plan_count "
            "AND score BETWEEN 0 AND 100 "
            "AND replan_unplaced_minutes >= 0)",
            name="ck_check_ins_finalized_counts_consistency",
        ),
        sa.CheckConstraint(
            "finalized_at IS NULL OR finalized_at >= finalization_started_at",
            name="ck_check_ins_finalized_at_after_start",
        ),
        sa.CheckConstraint(
            "result_acknowledged_at IS NULL OR "
            "(finalized_at IS NOT NULL AND result_acknowledged_at >= finalized_at)",
            name="ck_check_ins_result_acknowledged_after_finalized",
        ),
        schema="public",
    )
    op.create_index(
        "ix_check_ins_latest_unacknowledged",
        "check_ins",
        ["user_id", sa.text("finalized_at DESC"), sa.text("id DESC")],
        schema="public",
        postgresql_where=sa.text("finalized_at IS NOT NULL AND result_acknowledged_at IS NULL"),
    )
    op.create_index(
        "ix_check_ins_finalizing",
        "check_ins",
        ["user_id", sa.text("finalization_started_at DESC")],
        schema="public",
        postgresql_where=sa.text("finalized_at IS NULL"),
    )

    # 8. plan_blocks ----------------------------------------------------------------
    op.create_table(
        "plan_blocks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_date", sa.Date(), nullable=False),
        sa.Column("period", _enum("plan_period"), nullable=False),
        sa.Column("allocated_minutes", sa.Integer(), nullable=False),
        sa.Column("allocated_amount_text", sa.Text(), nullable=True),
        sa.Column("display_title", sa.Text(), nullable=False),
        sa.Column("display_order", sa.SmallInteger(), nullable=False),
        sa.Column(
            "status",
            _enum("plan_block_status"),
            server_default=sa.text("'PLANNED'"),
            nullable=False,
        ),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("check_in_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rescheduled_from_block_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_blocks")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user_profiles.id"], name=op.f("fk_plan_blocks_user_id_user_profiles"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["plan_cycle_id", "user_id"],
            ["planning_cycles.id", "planning_cycles.user_id"],
            name="fk_plan_blocks_plan_cycle_id_user_id_planning_cycles",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "user_id", "plan_cycle_id"],
            ["tasks.id", "tasks.user_id", "tasks.plan_cycle_id"],
            name="fk_plan_blocks_task_id_user_id_plan_cycle_id_tasks",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["check_in_id", "user_id", "plan_cycle_id", "plan_date", "period"],
            [
                "check_ins.id",
                "check_ins.user_id",
                "check_ins.plan_cycle_id",
                "check_ins.check_date",
                "check_ins.period",
            ],
            name="fk_plan_blocks_check_in_id_check_ins",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rescheduled_from_block_id", "user_id", "plan_cycle_id", "task_id"],
            ["plan_blocks.id", "plan_blocks.user_id", "plan_blocks.plan_cycle_id", "plan_blocks.task_id"],
            name="fk_plan_blocks_rescheduled_from_plan_blocks",
            ondelete="SET NULL (rescheduled_from_block_id)",
        ),
        sa.UniqueConstraint(
            "id", "user_id", "plan_cycle_id", "task_id", name="uq_plan_blocks_id_user_cycle_task"
        ),
        sa.UniqueConstraint("task_id", "plan_date", "period", name="uq_plan_blocks_task_date_period"),
        sa.UniqueConstraint(
            "plan_cycle_id", "plan_date", "period", "display_order", name="uq_plan_blocks_display_order"
        ),
        sa.CheckConstraint("allocated_minutes >= 1", name="ck_plan_blocks_allocated_minutes_positive"),
        sa.CheckConstraint("allocated_minutes <= 240", name="ck_plan_blocks_allocated_minutes_max_240"),
        sa.CheckConstraint("display_order >= 0", name="ck_plan_blocks_display_order_non_negative"),
        sa.CheckConstraint("btrim(display_title) <> ''", name="ck_plan_blocks_display_title_not_blank"),
        sa.CheckConstraint(
            "allocated_amount_text IS NULL OR btrim(allocated_amount_text) <> ''",
            name="ck_plan_blocks_allocated_amount_text_not_blank",
        ),
        sa.CheckConstraint(
            "(status = 'PLANNED' AND checked_at IS NULL AND check_in_id IS NULL)"
            " OR (status = 'CHECKED' AND checked_at IS NOT NULL AND check_in_id IS NULL)"
            " OR (status = 'COMPLETED' AND checked_at IS NOT NULL AND check_in_id IS NOT NULL)"
            " OR (status = 'NOT_DONE' AND checked_at IS NULL AND check_in_id IS NOT NULL)",
            name="ck_plan_blocks_status_consistency",
        ),
        schema="public",
    )
    op.create_index(
        "ix_plan_blocks_user_date_period",
        "plan_blocks",
        ["user_id", "plan_date", "period", "status", "display_order"],
        schema="public",
    )
    op.create_index(
        "ix_plan_blocks_cycle_date_period",
        "plan_blocks",
        ["plan_cycle_id", "plan_date", "period", "status"],
        schema="public",
    )
    op.create_index(
        "ix_plan_blocks_check_in",
        "plan_blocks",
        ["check_in_id", "display_order"],
        schema="public",
        postgresql_where=sa.text("check_in_id IS NOT NULL"),
    )

    # updated_at 트리거 (set_updated_at() 함수는 0001에서 이미 생성됨, 재생성하지 않음) ----
    for table_name in UPDATED_AT_TRIGGER_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER set_{table_name}_updated_at
            BEFORE UPDATE ON public.{table_name}
            FOR EACH ROW
            EXECUTE FUNCTION public.set_updated_at();
            """
        )

    # RLS 활성화 + user_id 기반 SELECT 전용 정책 ------------------------------------
    for table_name in RLS_TABLES:
        op.execute(f"ALTER TABLE public.{table_name} ENABLE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY {table_name}_select_own
            ON public.{table_name}
            FOR SELECT
            TO authenticated
            USING (user_id = auth.uid());
            """
        )


def downgrade() -> None:
    for table_name in reversed(RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table_name}_select_own ON public.{table_name};")

    for table_name in reversed(UPDATED_AT_TRIGGER_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS set_{table_name}_updated_at ON public.{table_name};")

    # 자식 -> 부모 역순으로 제거
    op.drop_table("plan_blocks", schema="public")
    op.drop_table("check_ins", schema="public")
    op.drop_table("solar_messages", schema="public")

    op.drop_constraint(
        "fk_fixed_schedules_source_request_item_id",
        "fixed_schedules",
        schema="public",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_tasks_source_request_item_id_user_id_solar_request_items",
        "tasks",
        schema="public",
        type_="foreignkey",
    )
    op.drop_table("solar_request_items", schema="public")
    op.drop_table("fixed_schedules", schema="public")
    op.drop_table("tasks", schema="public")
    op.drop_table("solar_requests", schema="public")
    op.drop_table("planning_cycles", schema="public")

    bind = op.get_bind()
    for name, values in reversed(ENUM_DEFINITIONS):
        postgresql.ENUM(*values, name=name).drop(bind, checkfirst=True)
