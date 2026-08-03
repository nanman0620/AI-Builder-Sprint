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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import PlanPeriod


class CheckIn(Base):
    __tablename__ = "check_ins"
    __table_args__ = (
        UniqueConstraint(
            "id", "user_id", "plan_cycle_id", "check_date", "period", name="uq_check_ins_full_identity"
        ),
        UniqueConstraint(
            "plan_cycle_id", "check_date", "period", name="uq_check_ins_cycle_date_period"
        ),
        ForeignKeyConstraint(
            ["plan_cycle_id", "user_id"],
            ["planning_cycles.id", "planning_cycles.user_id"],
            name="fk_check_ins_plan_cycle_id_user_id_planning_cycles",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "finalized_at IS NULL OR ("
            "total_plan_count IS NOT NULL "
            "AND completed_plan_count IS NOT NULL "
            "AND score IS NOT NULL "
            "AND replan_unplaced_minutes IS NOT NULL "
            "AND total_plan_count > 0 "
            "AND completed_plan_count BETWEEN 0 AND total_plan_count "
            "AND score BETWEEN 0 AND 100 "
            "AND replan_unplaced_minutes >= 0)",
            name="finalized_counts_consistency",
        ),
        CheckConstraint(
            "finalized_at IS NULL OR finalized_at >= finalization_started_at",
            name="finalized_at_after_start",
        ),
        CheckConstraint(
            "result_acknowledged_at IS NULL OR "
            "(finalized_at IS NOT NULL AND result_acknowledged_at >= finalized_at)",
            name="result_acknowledged_after_finalized",
        ),
        Index(
            "ix_check_ins_latest_unacknowledged",
            "user_id",
            text("finalized_at DESC"),
            text("id DESC"),
            postgresql_where=text("finalized_at IS NOT NULL AND result_acknowledged_at IS NULL"),
        ),
        Index(
            "ix_check_ins_finalizing",
            "user_id",
            text("finalization_started_at DESC"),
            postgresql_where=text("finalized_at IS NULL"),
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
    check_date: Mapped[date] = mapped_column(Date, nullable=False)
    period: Mapped[PlanPeriod] = mapped_column(SAEnum(PlanPeriod, name="plan_period"), nullable=False)
    total_plan_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_plan_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    replan_unplaced_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    finalization_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    replanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
