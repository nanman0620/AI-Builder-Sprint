import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FixedSchedule(Base):
    __tablename__ = "fixed_schedules"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_fixed_schedules_id_user"),
        ForeignKeyConstraint(
            ["plan_cycle_id", "user_id"],
            ["planning_cycles.id", "planning_cycles.user_id"],
            name="fk_fixed_schedules_plan_cycle_id_user_id_planning_cycles",
            ondelete="RESTRICT",
        ),
        # PostgreSQL 15의 컬럼 지정형 ON DELETE SET NULL을 사용해 user_id는 유지하고
        # source_request_item_id만 NULL로 변경한다.
        ForeignKeyConstraint(
            ["source_request_item_id", "user_id"],
            ["solar_request_items.id", "solar_request_items.user_id"],
            name="fk_fixed_schedules_source_request_item_id",
            ondelete="SET NULL (source_request_item_id)",
        ),
        CheckConstraint("start_at < end_at", name="start_before_end"),
        CheckConstraint("btrim(title) <> ''", name="title_not_blank"),
        Index(
            "uq_fixed_schedules_source_request_item",
            "source_request_item_id",
            unique=True,
            postgresql_where=text("source_request_item_id IS NOT NULL"),
        ),
        Index("ix_fixed_schedules_plan_cycle", "plan_cycle_id"),
        Index("ix_fixed_schedules_range", "user_id", "start_at", "end_at"),
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
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
