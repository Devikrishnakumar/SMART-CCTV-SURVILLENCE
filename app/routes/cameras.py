import cv2
import time
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import Camera
from app.schemas import CameraCreate, CameraOut
from app.auth.dependencies import require_operator, require_admin
from app.auth.security import decode_token
from app.models import User

router = APIRouter(prefix="/cameras", tags=["cameras"])


def _mjpeg_stream(source: str):
    cap = cv2.VideoCapture(source)
    try:
        while True:
            if not cap.isOpened():
                cap.release()
                time.sleep(1.0)
                cap = cv2.VideoCapture(source)
                continue

            ok, frame = cap.read()
            if not ok:
                time.sleep(0.5)
                continue

            ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ok:
                continue

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" +
                bytearray(encoded) +
                b"\r\n"
            )
    finally:
        cap.release()


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


@router.get("/{camera_id}/live")
async def live_camera_stream(
    camera_id: str,
    token: Optional[str] = Query(None, description="JWT access token"),
    db: AsyncSession = Depends(get_db),
):
    if not token:
        raise HTTPException(status_code=401, detail="Token required")

    try:
        payload = decode_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Unauthorized")
    except Exception:
        raise HTTPException(status_code=401, detail="Unauthorized")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Unauthorized")

    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    if not camera.stream_url:
        raise HTTPException(status_code=400, detail="Camera stream_url is not configured")

    return StreamingResponse(
        _mjpeg_stream(camera.stream_url),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )
