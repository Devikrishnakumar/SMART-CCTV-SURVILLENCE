from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas import AIReportRequest, AIReportResponse, IncidentCreate
from app.services.incident import create_incident
from app.config import settings
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["ai-integration"])

# Optional: a dedicated AI module API key separate from JWT
# Set AI_MODULE_KEY in .env for production; omit header check to use open endpoint
AI_MODULE_KEY_HEADER = "X-AI-Module-Key"


@router.post("/report", response_model=AIReportResponse)
async def ai_report(
    payload: AIReportRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    # Optional API key auth for the AI module (not JWT)
    # x_ai_module_key: str = Header(None, alias=AI_MODULE_KEY_HEADER),
):
    """
    Endpoint called by the YOLO-based vision module to report a detection.
    Validates confidence threshold, stores incident, and broadcasts alert.
    """
    if payload.confidence < settings.CONFIDENCE_THRESHOLD:
        logger.info(
            f"AI report rejected: confidence {payload.confidence:.2f} < "
            f"threshold {settings.CONFIDENCE_THRESHOLD}"
        )
        return AIReportResponse(
            accepted=False,
            message=f"Confidence {payload.confidence:.2f} below threshold {settings.CONFIDENCE_THRESHOLD}",
        )

    incident_data = IncidentCreate(
        event_id=payload.event_id,
        type=payload.type,
        confidence=payload.confidence,
        peak_confidence=payload.peak_confidence,
        camera_id=payload.camera_id,
        snapshot_url=payload.snapshot_url,
        video_clip_url=payload.video_clip_url,
        evidence_frames=payload.frames,
        latitude=payload.latitude,
        longitude=payload.longitude,
        timestamp=payload.timestamp,
    )

    try:
        incident = await create_incident(db, incident_data, background_tasks)
    except HTTPException as e:
        return AIReportResponse(accepted=False, message=e.detail)

    logger.info(f"AI report accepted: incident {incident.id} created")
    return AIReportResponse(
        accepted=True,
        incident_id=str(incident.id),
        message="Incident created and alert broadcast initiated",
    )
