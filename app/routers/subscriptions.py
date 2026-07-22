from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user
from app.database import get_session
from app.models.location import Location
from app.models.subscription import Subscription
from app.models.user import User
from app.schemas.subscription import SubscriptionCreate, SubscriptionRead

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.post("", response_model=SubscriptionRead, status_code=status.HTTP_201_CREATED)
async def subscribe(
    payload: SubscriptionCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> Subscription:
    location = await session.get(Location, payload.location_id)
    if location is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Location not found")

    existing = await session.execute(
        select(Subscription).where(
            Subscription.user_id == current_user.id,
            Subscription.location_id == payload.location_id,
        )
    )
    subscription = existing.scalars().first()
    if subscription:
        if not subscription.is_active:
            subscription.is_active = True
            session.add(subscription)
            await session.commit()
            await session.refresh(subscription)
    else:
        subscription = Subscription(user_id=current_user.id, location_id=payload.location_id)
        session.add(subscription)
        await session.commit()
        await session.refresh(subscription)

    # Reload with the location eager-loaded for the response schema.
    result = await session.execute(
        select(Subscription).options(selectinload(Subscription.location)).where(Subscription.id == subscription.id)
    )
    return result.scalars().one()


@router.get("", response_model=list[SubscriptionRead])
async def list_my_subscriptions(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[Subscription]:
    result = await session.execute(
        select(Subscription)
        .options(selectinload(Subscription.location))
        .where(Subscription.user_id == current_user.id, Subscription.is_active.is_(True))
    )
    return list(result.scalars().all())


@router.delete("/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(
    location_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> None:
    result = await session.execute(
        select(Subscription).where(
            Subscription.user_id == current_user.id,
            Subscription.location_id == location_id,
        )
    )
    subscription = result.scalars().first()
    if subscription is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")

    subscription.is_active = False
    session.add(subscription)
    await session.commit()
