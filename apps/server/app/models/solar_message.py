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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import SolarMessageKind, SolarMessageRole


class SolarMessage(Base):
    __tablename__ = "solar_messages"
    __table_args__ = (
        UniqueConstraint("solar_request_id", "sequence_no", name="uq_solar_messages_sequence"),
        ForeignKeyConstraint(
            ["solar_request_id", "user_id"],
            ["solar_requests.id", "solar_requests.user_id"],
            name="fk_solar_messages_solar_request_id_user_id_solar_requests",
            ondelete="CASCADE",
        ),
        CheckConstraint("btrim(content) <> ''", name="content_not_blank"),
        Index(
            "uq_solar_messages_client_event",
            "solar_request_id",
            "client_event_id",
            unique=True,
            postgresql_where=text("client_event_id IS NOT NULL"),
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
    client_event_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[SolarMessageRole] = mapped_column(
        SAEnum(SolarMessageRole, name="solar_message_role"), nullable=False
    )
    kind: Mapped[SolarMessageKind] = mapped_column(
        SAEnum(SolarMessageKind, name="solar_message_kind"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
