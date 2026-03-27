from datetime import datetime
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status, BackgroundTasks
from app.models import Incident, Camera, DispatchLog, IncidentStatus, User
from app.schemas import (
    IncidentCreate, IncidentVerify, IncidentDispatch, IncidentResolve, IncidentReject
)
from app.websocket.manager import manager
from app.services.notification import notify_emergency_services
from app.services.media import persist_evidence_bundle
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
        event_id=data.event_id,
        type=data.type,
        confidence=data.confidence,
        peak_confidence=data.peak_confidence or data.confidence,
        camera_id=data.camera_id,
        timestamp=data.timestamp or datetime.utcnow(),
        snapshot_url=data.snapshot_url,
        video_clip_url=data.video_clip_url,
        evidence_frames=json.dumps([]),
        latitude=data.latitude or camera.latitude,
        longitude=data.longitude or camera.longitude,
        status=IncidentStatus.pending,
    )
    db.add(incident)
    await db.flush()  # get ID before commit

    # Re-save evidence into the final incident directory once the ID exists.
    incident.snapshot_url, incident.video_clip_url, stored_frames = persist_evidence_bundle(
        str(incident.id),
        data.snapshot_url,
        data.video_clip_url,
        data.evidence_frames,
    )
    if stored_frames:
        incident.evidence_frames = json.dumps(stored_frames)

    db.add(DispatchLog(
        incident_id=incident.id,
        action="detected",
        metadata_=json.dumps({
            "event_id": data.event_id,
            "confidence": data.confidence,
            "peak_confidence": data.peak_confidence or data.confidence,
            "evidence_frames": json.loads(incident.evidence_frames or "[]"),
        }),
    ))

    # Schedule background broadcast + notification
    background_tasks.add_task(_broadcast_pending_alert, incident)
    return incident


async def _broadcast_pending_alert(incident: Incident):
    """Background task: broadcast a new pending-verification alert."""
    alert = {
        "event": "new_incident",
        "incident_id": str(incident.id),
        "type": incident.type.value,
        "confidence": incident.confidence,
        "peak_confidence": incident.peak_confidence or incident.confidence,
        "camera_id": str(incident.camera_id),
        "timestamp": incident.timestamp.isoformat() if incident.timestamp else datetime.utcnow().isoformat(),
        "snapshot_url": incident.snapshot_url,
        "video_clip_url": incident.video_clip_url,
        "evidence_frames": json.loads(incident.evidence_frames or "[]"),
        "latitude": incident.latitude,
        "longitude": incident.longitude,
        "status": incident.status.value,
        "notifications_sent": [],
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
    incident.verification_source = data.verification_source

    log = DispatchLog(
        incident_id=incident.id,
        action="verified",
        performed_by_id=current_user.id,
        metadata_=json.dumps({"verification_source": data.verification_source}),
    )
    db.add(log)
    await db.flush()

    location = {"latitude": incident.latitude, "longitude": incident.longitude}
    notified = await notify_emergency_services(str(incident.id), incident.type, location)

    await manager.broadcast({
        "event": "incident_updated",
        "incident_id": str(incident.id),
        "status": incident.status.value,
        "action": "verified",
        "by": current_user.username,
        "notifications_sent": notified,
    })
    return incident


async def reject_incident(
    db: AsyncSession,
    incident_id: str,
    data: IncidentReject,
    current_user: User,
) -> Incident:
    incident = await get_incident_or_404(db, incident_id)
    if incident.status != IncidentStatus.pending:
        raise HTTPException(400, f"Cannot reject incident in status '{incident.status.value}'")

    incident.status = IncidentStatus.closed
    incident.notes = data.notes or incident.notes
    incident.verification_source = data.verification_source

    log = DispatchLog(
        incident_id=incident.id,
        action="rejected",
        performed_by_id=current_user.id,
        metadata_=json.dumps({"verification_source": data.verification_source}),
    )
    db.add(log)
    await db.flush()

    await manager.broadcast({
        "event": "incident_updated",
        "incident_id": str(incident.id),
        "status": incident.status.value,
        "action": "rejected",
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
    if incident.status != IncidentStatus.verified:
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
