import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OnboardingRequest(BaseModel):
    nickname: str

    model_config = ConfigDict(extra="forbid")


class ProfileOut(BaseModel):
    id: uuid.UUID
    email: str
    nickname: str
    onboarding_completed: bool = Field(alias="onboardingCompleted")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class ProfileResponse(BaseModel):
    data: ProfileOut
