import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import PlanBlockStatus, PlanPeriod


class PlanBlock(Base):
    __tablename__ = "plan_blocks"
    __table_args__ = (
        UniqueConstraint(
            "id", "user_id", "plan_cycle_id", "task_id", name="uq_plan_blocks_id_user_cycle_task"
        ),
        UniqueConstraint("task_id", "plan_date", "period", name="uq_plan_blocks_task_date_period"),
        UniqueConstraint(
            "plan_cycle_id", "plan_date", "period", "display_order", name="uq_plan_blocks_display_order"
        ),
        ForeignKeyConstraint(
            ["plan_cycle_id", "user_id"],
            ["planning_cycles.id", "planning_cycles.user_id"],
            name="fk_plan_blocks_plan_cycle_id_user_id_planning_cycles",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["task_id", "user_id", "plan_cycle_id"],
            ["tasks.id", "tasks.user_id", "tasks.plan_cycle_id"],
            name="fk_plan_blocks_task_id_user_id_plan_cycle_id_tasks",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["check_in_id", "user_id", "plan_cycle_id", "plan_date", "period"],
            ["check_ins.id", "check_ins.user_id", "check_ins.plan_cycle_id", "check_ins.check_date", "check_ins.period"],
            name="fk_plan_blocks_check_in_id_check_ins",
            ondelete="RESTRICT",
        ),
        # PostgreSQL 15의 컬럼 지정형 ON DELETE SET NULL을 사용해 user_id/plan_cycle_id/task_id는
        # 유지하고 rescheduled_from_block_id만 NULL로 변경한다.
        ForeignKeyConstraint(
            ["rescheduled_from_block_id", "user_id", "plan_cycle_id", "task_id"],
            ["plan_blocks.id", "plan_blocks.user_id", "plan_blocks.plan_cycle_id", "plan_blocks.task_id"],
            name="fk_plan_blocks_rescheduled_from_plan_blocks",
            ondelete="SET NULL (rescheduled_from_block_id)",
        ),
        CheckConstraint("allocated_minutes >= 1", name="allocated_minutes_positive"),
        CheckConstraint("allocated_minutes <= 240", name="allocated_minutes_max_240"),
        CheckConstraint("display_order >= 0", name="display_order_non_negative"),
        CheckConstraint("btrim(display_title) <> ''", name="display_title_not_blank"),
        CheckConstraint(
            "allocated_amount_text IS NULL OR btrim(allocated_amount_text) <> ''",
            name="allocated_amount_text_not_blank",
        ),
        CheckConstraint(
            "(status = 'PLANNED' AND checked_at IS NULL AND check_in_id IS NULL)"
            " OR (status = 'CHECKED' AND checked_at IS NOT NULL AND check_in_id IS NULL)"
            " OR (status = 'COMPLETED' AND checked_at IS NOT NULL AND check_in_id IS NOT NULL)"
            " OR (status = 'NOT_DONE' AND checked_at IS NULL AND check_in_id IS NOT NULL)",
            name="status_consistency",
        ),
        Index(
            "ix_plan_blocks_user_date_period",
            "user_id",
            "plan_date",
            "period",
            "status",
            "display_order",
        ),
        Index(
            "ix_plan_blocks_cycle_date_period",
            "plan_cycle_id",
            "plan_date",
            "period",
            "status",
        ),
        Index(
            "ix_plan_blocks_check_in",
            "check_in_id",
            "display_order",
            postgresql_where=text("check_in_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    plan_cycle_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    period: Mapped[PlanPeriod] = mapped_column(SAEnum(PlanPeriod, name="plan_period"), nullable=False)
    allocated_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    allocated_amount_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_title: Mapped[str] = mapped_column(Text, nullable=False)
    display_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[PlanBlockStatus] = mapped_column(
        SAEnum(PlanBlockStatus, name="plan_block_status"),
        nullable=False,
        server_default=text("'PLANNED'"),
    )
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    check_in_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    rescheduled_from_block_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
