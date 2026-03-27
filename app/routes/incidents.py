from typing import List, Optional
from fastapi import APIRouter, Depends, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.models import Incident, IncidentStatus, User
from app.schemas import (
    IncidentCreate, IncidentOut, IncidentVerify, IncidentDispatch, IncidentResolve, IncidentReject
)
from app.auth.dependencies import require_operator, require_dispatcher, get_current_user
from app.services.incident import (
    create_incident, verify_incident, reject_incident, dispatch_incident, resolve_incident, get_incident_or_404
)

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.post("", response_model=IncidentOut, status_code=201)
async def post_incident(
    payload: IncidentCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_operator),
):
    return await create_incident(db, payload, background_tasks)


@router.get("", response_model=List[IncidentOut])
async def list_incidents(
    status: Optional[IncidentStatus] = Query(None),
    camera_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_operator),
):
    q = select(Incident).options(selectinload(Incident.dispatch_logs)).order_by(Incident.timestamp.desc())
    if status:
        q = q.where(Incident.status == status)
    if camera_id:
        q = q.where(Incident.camera_id == camera_id)
    q = q.limit(limit).offset(offset)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/{incident_id}", response_model=IncidentOut)
async def get_incident(
    incident_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_operator),
):
    return await get_incident_or_404(db, incident_id)


@router.put("/{incident_id}/verify", response_model=IncidentOut)
async def verify(
    incident_id: str,
    payload: IncidentVerify = IncidentVerify(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_operator),
):
    return await verify_incident(db, incident_id, payload, current_user)


@router.put("/{incident_id}/reject", response_model=IncidentOut)
async def reject(
    incident_id: str,
    payload: IncidentReject = IncidentReject(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_operator),
):
    return await reject_incident(db, incident_id, payload, current_user)


@router.put("/{incident_id}/dispatch", response_model=IncidentOut)
async def dispatch(
    incident_id: str,
    payload: IncidentDispatch,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_dispatcher),
):
    return await dispatch_incident(db, incident_id, payload, current_user)


@router.put("/{incident_id}/resolve", response_model=IncidentOut)
async def resolve(
    incident_id: str,
    payload: IncidentResolve = IncidentResolve(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_dispatcher),
):
    return await resolve_incident(db, incident_id, payload, current_user)
