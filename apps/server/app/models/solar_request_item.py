import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
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
from app.models.enums import SolarAction, SolarEntityType, SolarItemStatus


class SolarRequestItem(Base):
    __tablename__ = "solar_request_items"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_solar_request_items_id_user"),
        UniqueConstraint("solar_request_id", "item_order", name="uq_solar_request_items_order"),
        ForeignKeyConstraint(
            ["solar_request_id", "user_id"],
            ["solar_requests.id", "solar_requests.user_id"],
            name="fk_solar_request_items_solar_request_id_user_id_solar_requests",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["target_task_id", "user_id"],
            ["tasks.id", "tasks.user_id"],
            name="fk_solar_request_items_target_task_id_user_id_tasks",
            ondelete="RESTRICT",
        ),
        # PostgreSQL 15의 컬럼 지정형 ON DELETE SET NULL을 사용해 user_id는 유지하고
        # target_fixed_schedule_id만 NULL로 변경한다.
        ForeignKeyConstraint(
            ["target_fixed_schedule_id", "user_id"],
            ["fixed_schedules.id", "fixed_schedules.user_id"],
            name="fk_solar_request_items_target_fixed_schedule_id",
            ondelete="SET NULL (target_fixed_schedule_id)",
        ),
        CheckConstraint(
            "(action = 'CREATE' AND target_task_id IS NULL AND target_fixed_schedule_id IS NULL)"
            " OR (action IN ('UPDATE', 'DELETE') AND entity_type = 'TASK'"
            "     AND target_task_id IS NOT NULL AND target_fixed_schedule_id IS NULL)"
            " OR (action = 'UPDATE' AND entity_type = 'FIXED_SCHEDULE'"
            "     AND target_task_id IS NULL AND target_fixed_schedule_id IS NOT NULL)"
            " OR (action = 'DELETE' AND entity_type = 'FIXED_SCHEDULE' AND status <> 'EXECUTED'"
            "     AND target_task_id IS NULL AND target_fixed_schedule_id IS NOT NULL)"
            " OR (action = 'DELETE' AND entity_type = 'FIXED_SCHEDULE' AND status = 'EXECUTED'"
            "     AND target_task_id IS NULL)",
            name="target_reference_integrity",
        ),
        CheckConstraint(
            "(status = 'INFO_MISSING' AND array_length(missing_fields, 1) > 0 AND executed_at IS NULL)"
            " OR (status = 'READY' AND coalesce(array_length(missing_fields, 1), 0) = 0"
            "     AND executed_at IS NULL)"
            " OR (status = 'EXECUTED' AND coalesce(array_length(missing_fields, 1), 0) = 0"
            "     AND executed_at IS NOT NULL)",
            name="card_status_consistency",
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
    solar_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    item_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    action: Mapped[SolarAction] = mapped_column(SAEnum(SolarAction, name="solar_action"), nullable=False)
    entity_type: Mapped[SolarEntityType] = mapped_column(
        SAEnum(SolarEntityType, name="solar_entity_type"), nullable=False
    )
    status: Mapped[SolarItemStatus] = mapped_column(
        SAEnum(SolarItemStatus, name="solar_item_status"), nullable=False
    )
    raw_line_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    missing_fields: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    pending_question: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    target_task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    target_fixed_schedule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
