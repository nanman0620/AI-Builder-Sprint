import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import PlanCycleStatus


class PlanningCycle(Base):
    __tablename__ = "planning_cycles"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_planning_cycles_id_user"),
        CheckConstraint(
            "end_date = start_date + 6",
            name="cycle_is_exactly_seven_days",
        ),
        CheckConstraint(
            "(status = 'ACTIVE' AND ended_at IS NULL) OR (status = 'ENDED' AND ended_at IS NOT NULL)",
            name="status_matches_ended_at",
        ),
        Index(
            "uq_planning_cycles_one_active_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
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
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[PlanCycleStatus] = mapped_column(
        SAEnum(PlanCycleStatus, name="plan_cycle_status"), nullable=False
    )
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
