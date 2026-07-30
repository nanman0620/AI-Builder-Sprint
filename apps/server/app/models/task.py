import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import AmountSource, EstimateSource, TaskStatus


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_tasks_id_user"),
        UniqueConstraint("id", "user_id", "plan_cycle_id", name="uq_tasks_id_user_cycle"),
        ForeignKeyConstraint(
            ["plan_cycle_id", "user_id"],
            ["planning_cycles.id", "planning_cycles.user_id"],
            name="fk_tasks_plan_cycle_id_user_id_planning_cycles",
            ondelete="RESTRICT",
        ),
        # PostgreSQL 15의 컬럼 지정형 ON DELETE SET NULL을 사용해 user_id는 유지하고
        # source_request_item_id만 NULL로 변경한다.
        ForeignKeyConstraint(
            ["source_request_item_id", "user_id"],
            ["solar_request_items.id", "solar_request_items.user_id"],
            name="fk_tasks_source_request_item_id_user_id_solar_request_items",
            ondelete="SET NULL (source_request_item_id)",
        ),
        CheckConstraint("initial_minutes >= 1", name="initial_minutes_positive"),
        CheckConstraint("estimated_minutes >= 1", name="estimated_minutes_positive"),
        CheckConstraint("remaining_minutes >= 0", name="remaining_minutes_non_negative"),
        CheckConstraint("btrim(title) <> ''", name="title_not_blank"),
        CheckConstraint(
            "(status = 'ACTIVE' AND remaining_minutes > 0 AND completed_at IS NULL AND cancelled_at IS NULL)"
            " OR (status = 'COMPLETED' AND remaining_minutes = 0 AND completed_at IS NOT NULL"
            "     AND cancelled_at IS NULL)"
            " OR (status = 'CANCELLED' AND remaining_minutes >= 0 AND completed_at IS NULL"
            "     AND cancelled_at IS NOT NULL)",
            name="status_consistency",
        ),
        CheckConstraint(
            "(amount_source = 'UNKNOWN' AND amount_text IS NULL)"
            " OR (amount_source IN ('USER', 'AI_ESTIMATED') AND amount_text IS NOT NULL"
            "     AND btrim(amount_text) <> '')",
            name="amount_source_consistency",
        ),
        Index(
            "uq_tasks_source_request_item",
            "source_request_item_id",
            unique=True,
            postgresql_where=text("source_request_item_id IS NOT NULL"),
        ),
        Index("ix_tasks_plan_cycle", "plan_cycle_id"),
        Index(
            "ix_tasks_active_deadline",
            "user_id",
            "plan_cycle_id",
            "deadline_at",
            postgresql_where=text(
                "status = 'ACTIVE' AND remaining_minutes > 0 AND deadline_at IS NOT NULL "
                "AND deadline_warning_acknowledged_at IS NULL"
            ),
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
    source_request_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    amount_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount_source: Mapped[AmountSource] = mapped_column(
        SAEnum(AmountSource, name="amount_source"), nullable=False
    )
    initial_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_minutes_source: Mapped[EstimateSource] = mapped_column(
        SAEnum(EstimateSource, name="estimate_source"), nullable=False
    )
    remaining_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[TaskStatus] = mapped_column(SAEnum(TaskStatus, name="task_status"), nullable=False)
    deadline_warning_acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
