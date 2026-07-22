from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_session
from app.models.location import Location
from app.models.user import User
from app.schemas.location import LocationCreate, LocationRead

router = APIRouter(prefix="/locations", tags=["locations"])


def _round_coord(value: float) -> float:
    """Collapse nearby coordinates (~1.1km) onto the same Location row."""
    return round(value, 2)


@router.post("", response_model=LocationRead, status_code=status.HTTP_201_CREATED)
async def create_or_get_location(
    payload: LocationCreate,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
) -> Location:
    lat, lon = _round_coord(payload.latitude), _round_coord(payload.longitude)

    existing = await session.execute(select(Location).where(Location.latitude == lat, Location.longitude == lon))
    location = existing.scalars().first()
    if location:
        return location

    location = Location(name=payload.name, latitude=lat, longitude=lon, timezone=payload.timezone)
    session.add(location)
    await session.commit()
    await session.refresh(location)
    return location


@router.get("", response_model=list[LocationRead])
async def list_locations(
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
) -> list[Location]:
    result = await session.execute(select(Location).order_by(Location.name))
    return list(result.scalars().all())


@router.get("/{location_id}", response_model=LocationRead)
async def get_location(
    location_id: int,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(get_current_user),
) -> Location:
    location = await session.get(Location, location_id)
    if location is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Location not found")
    return location
