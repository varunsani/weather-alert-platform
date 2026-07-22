from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.location import LocationRead


class SubscriptionCreate(BaseModel):
    location_id: int


class SubscriptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    location_id: int
    is_active: bool
    created_at: datetime
    location: LocationRead
