from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import SolarRequestPurpose


class CreateSolarRequestBody(BaseModel):
    purpose: SolarRequestPurpose
    client_event_id: str = Field(alias="clientEventId")
    message: str

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("client_event_id", "message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("공백일 수 없다.")
        return value
