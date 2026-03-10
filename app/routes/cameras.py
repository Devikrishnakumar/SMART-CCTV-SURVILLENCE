from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import Camera
from app.schemas import CameraCreate, CameraOut
from app.auth.dependencies import require_operator, require_admin

router = APIRouter(prefix="/cameras", tags=["cameras"])


@router.get("", response_model=List[CameraOut])
async def list_cameras(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_operator),
):
    result = await db.execute(select(Camera).order_by(Camera.created_at.desc()))
    return result.scalars().all()


@router.get("/{camera_id}", response_model=CameraOut)
async def get_camera(
    camera_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_operator),
):
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    return camera


@router.post("", response_model=CameraOut, status_code=201)
async def create_camera(
    payload: CameraCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    camera = Camera(**payload.model_dump())
    db.add(camera)
    await db.flush()
    return camera
