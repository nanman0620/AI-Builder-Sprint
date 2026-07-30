import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import SolarRequestPurpose, SolarRequestStatus


class SolarRequest(Base):
    __tablename__ = "solar_requests"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_solar_requests_id_user"),
        ForeignKeyConstraint(
            ["plan_cycle_id", "user_id"],
            ["planning_cycles.id", "planning_cycles.user_id"],
            name="fk_solar_requests_plan_cycle_id_user_id_planning_cycles",
            ondelete="RESTRICT",
        ),
        CheckConstraint("btrim(raw_input) <> ''", name="raw_input_not_blank"),
        CheckConstraint("execution_attempt_count >= 0", name="execution_attempt_count_non_negative"),
        CheckConstraint(
            "status <> 'EXECUTING' OR ("
            "execution_started_at IS NOT NULL AND execution_attempt_count >= 1 "
            "AND executed_at IS NULL AND execution_result IS NULL "
            "AND error_code IS NULL AND error_message IS NULL)",
            name="executing_state_consistency",
        ),
        CheckConstraint(
            "status <> 'COMPLETED' OR ("
            "execution_started_at IS NOT NULL AND execution_attempt_count >= 1 "
            "AND executed_at IS NOT NULL AND execution_result IS NOT NULL "
            "AND error_code IS NULL AND error_message IS NULL)",
            name="completed_state_consistency",
        ),
        CheckConstraint(
            "status <> 'FAILED' OR ("
            "execution_started_at IS NOT NULL AND execution_attempt_count >= 1 "
            "AND executed_at IS NULL AND execution_result IS NULL "
            "AND error_code IS NOT NULL AND error_message IS NOT NULL)",
            name="failed_state_consistency",
        ),
        CheckConstraint(
            "result_acknowledged_at IS NULL OR status = 'COMPLETED'",
            name="result_acknowledged_requires_completed",
        ),
        Index(
            "uq_solar_requests_one_current_per_user",
            "user_id",
            unique=True,
            postgresql_where=text(
                "status IN ('COLLECTING', 'CHANGE_CONFIRMATION', 'CHANGE_INPUT', "
                "'FINAL_REVIEW', 'EXECUTING', 'FAILED') "
                "OR (status = 'COMPLETED' AND result_acknowledged_at IS NULL)"
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
    plan_cycle_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    purpose: Mapped[SolarRequestPurpose] = mapped_column(
        SAEnum(SolarRequestPurpose, name="solar_request_purpose"), nullable=False
    )
    status: Mapped[SolarRequestStatus] = mapped_column(
        SAEnum(SolarRequestStatus, name="solar_request_status"), nullable=False
    )
    raw_input: Mapped[str] = mapped_column(Text, nullable=False)
    current_item_order: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    execution_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    execution_attempt_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    execution_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
