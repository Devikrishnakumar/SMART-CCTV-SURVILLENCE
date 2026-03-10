from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status, BackgroundTasks
from app.models import Incident, Camera, DispatchLog, IncidentStatus, User
from app.schemas import (
    IncidentCreate, IncidentVerify, IncidentDispatch, IncidentResolve
)
from app.websocket.manager import manager
from app.services.notification import notify_emergency_services
import logging

logger = logging.getLogger(__name__)


async def get_incident_or_404(db: AsyncSession, incident_id: str) -> Incident:
    result = await db.execute(
        select(Incident)
        .where(Incident.id == incident_id)
        .options(selectinload(Incident.dispatch_logs))
    )
    incident = result.scalar_one_or_none()
    if not incident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    return incident


async def create_incident(
    db: AsyncSession,
    data: IncidentCreate,
    background_tasks: BackgroundTasks,
) -> Incident:
    # Validate camera exists
    cam_result = await db.execute(select(Camera).where(Camera.id == data.camera_id))
    camera = cam_result.scalar_one_or_none()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    incident = Incident(
        type=data.type,
        confidence=data.confidence,
        camera_id=data.camera_id,
        snapshot_url=data.snapshot_url,
        video_clip_url=data.video_clip_url,
        latitude=data.latitude or camera.latitude,
        longitude=data.longitude or camera.longitude,
        status=IncidentStatus.pending,
    )
    db.add(incident)
    await db.flush()  # get ID before commit

    # Schedule background broadcast + notification
    background_tasks.add_task(_broadcast_and_notify, incident)
    return incident


async def _broadcast_and_notify(incident: Incident):
    """Background task: WebSocket broadcast + emergency notifications."""
    location = {"latitude": incident.latitude, "longitude": incident.longitude}

    notified = await notify_emergency_services(
        str(incident.id), incident.type, location
    )

    alert = {
        "event": "new_incident",
        "incident_id": str(incident.id),
        "type": incident.type.value,
        "confidence": incident.confidence,
        "camera_id": str(incident.camera_id),
        "timestamp": incident.timestamp.isoformat() if incident.timestamp else datetime.utcnow().isoformat(),
        "snapshot_url": incident.snapshot_url,
        "latitude": incident.latitude,
        "longitude": incident.longitude,
        "notifications_sent": notified,
    }
    await manager.broadcast(alert)
    logger.info(f"Broadcast alert for incident {incident.id} to {manager.active_connections} clients")


async def verify_incident(
    db: AsyncSession,
    incident_id: str,
    data: IncidentVerify,
    current_user: User,
) -> Incident:
    incident = await get_incident_or_404(db, incident_id)
    if incident.status != IncidentStatus.pending:
        raise HTTPException(400, f"Cannot verify incident in status '{incident.status.value}'")

    incident.status = IncidentStatus.verified
    if data.notes:
        incident.notes = data.notes

    log = DispatchLog(
        incident_id=incident.id,
        action="verified",
        performed_by_id=current_user.id,
    )
    db.add(log)
    await db.flush()

    await manager.broadcast({
        "event": "incident_updated",
        "incident_id": str(incident.id),
        "status": incident.status.value,
        "action": "verified",
        "by": current_user.username,
    })
    return incident


async def dispatch_incident(
    db: AsyncSession,
    incident_id: str,
    data: IncidentDispatch,
    current_user: User,
) -> Incident:
    incident = await get_incident_or_404(db, incident_id)
    if incident.status not in (IncidentStatus.pending, IncidentStatus.verified):
        raise HTTPException(400, f"Cannot dispatch incident in status '{incident.status.value}'")

    incident.status = IncidentStatus.dispatched
    incident.assigned_unit = data.assigned_unit
    if data.notes:
        incident.notes = data.notes

    log = DispatchLog(
        incident_id=incident.id,
        action=f"dispatched → unit: {data.assigned_unit}",
        performed_by_id=current_user.id,
    )
    db.add(log)
    await db.flush()

    await manager.broadcast({
        "event": "incident_updated",
        "incident_id": str(incident.id),
        "status": incident.status.value,
        "action": "dispatched",
        "assigned_unit": incident.assigned_unit,
        "by": current_user.username,
    })
    return incident


async def resolve_incident(
    db: AsyncSession,
    incident_id: str,
    data: IncidentResolve,
    current_user: User,
) -> Incident:
    incident = await get_incident_or_404(db, incident_id)
    if incident.status != IncidentStatus.dispatched:
        raise HTTPException(400, f"Cannot resolve incident in status '{incident.status.value}'")

    incident.status = IncidentStatus.resolved
    if data.response_time is not None:
        incident.response_time = data.response_time
    if data.notes:
        incident.notes = data.notes

    log = DispatchLog(
        incident_id=incident.id,
        action="resolved",
        performed_by_id=current_user.id,
    )
    db.add(log)
    await db.flush()

    await manager.broadcast({
        "event": "incident_updated",
        "incident_id": str(incident.id),
        "status": incident.status.value,
        "action": "resolved",
        "by": current_user.username,
    })
    return incident
