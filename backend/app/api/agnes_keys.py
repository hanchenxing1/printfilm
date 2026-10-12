from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas_api import AgnesKeyCreateRequest, AgnesKeyOut
from app.services import agnes_keys

router = APIRouter(prefix="/user/agnes-keys", tags=["agnes-keys"])


@router.get("", response_model=list[AgnesKeyOut])
async def list_keys(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[AgnesKeyOut]:
    rows = await agnes_keys.list_agnes_keys(db, user.id)
    return [AgnesKeyOut.model_validate(row) for row in rows]


@router.post("", response_model=AgnesKeyOut)
async def create_key(
    body: AgnesKeyCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AgnesKeyOut:
    try:
        row = await agnes_keys.add_agnes_key(db, user, body.name, body.key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(row)
    return AgnesKeyOut.model_validate(row)


@router.patch("/{key_id}")
async def toggle_key(
    key_id: int,
    active: bool,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    ok = await agnes_keys.set_active(db, user.id, key_id, active)
    if not ok:
        raise HTTPException(status_code=404, detail="Agnes Key 不存在")
    await db.commit()
    return {"ok": True, "active": active}


@router.delete("/{key_id}")
async def delete_key(
    key_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    ok = await agnes_keys.remove_agnes_key(db, user.id, key_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Agnes Key 不存在")
    await db.commit()
    return {"ok": True}
