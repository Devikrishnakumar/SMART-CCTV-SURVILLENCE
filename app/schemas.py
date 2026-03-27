from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime
import json
from app.models import UserRole, IncidentType, IncidentStatus, CameraStatus


# ─── Auth ────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: UserRole
    username: str


# ─── User ────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=8)
    role: UserRole = UserRole.operator


class UserOut(BaseModel):
    id: str
    username: str
    role: UserRole
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Camera ──────────────────────────────────────────────────────────────────

class CameraCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    location_name: str = Field(..., min_length=1, max_length=256)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    stream_url: Optional[str] = None
    status: CameraStatus = CameraStatus.active


class CameraOut(BaseModel):
    id: str
    name: str
    location_name: str
    latitude: float
    longitude: float
    stream_url: Optional[str]
    status: CameraStatus
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Incident ────────────────────────────────────────────────────────────────

class IncidentCreate(BaseModel):
    event_id: Optional[str] = Field(None, max_length=128)
    type: IncidentType
    confidence: float = Field(..., ge=0.0, le=1.0)
    peak_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    camera_id: str
    snapshot_url: Optional[str] = None
    video_clip_url: Optional[str] = None
    evidence_frames: List[str] = []
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    timestamp: Optional[datetime] = None


class IncidentVerify(BaseModel):
    notes: Optional[str] = None
    verification_source: str = Field(default="human", min_length=2, max_length=64)


class IncidentReject(BaseModel):
    notes: Optional[str] = None
    verification_source: str = Field(default="human", min_length=2, max_length=64)


class IncidentDispatch(BaseModel):
    assigned_unit: str = Field(..., min_length=1, max_length=128)
    notes: Optional[str] = None


class IncidentResolve(BaseModel):
    response_time: Optional[float] = Field(None, ge=0)
    notes: Optional[str] = None


class DispatchLogOut(BaseModel):
    id: str
    action: str
    performed_by_id: Optional[str]
    timestamp: datetime

    class Config:
        from_attributes = True


class IncidentOut(BaseModel):
    id: str
    event_id: Optional[str]
    type: IncidentType
    confidence: float
    peak_confidence: Optional[float]
    camera_id: str
    timestamp: datetime
    snapshot_url: Optional[str]
    video_clip_url: Optional[str]
    evidence_frames: List[str] = []
    latitude: Optional[float]
    longitude: Optional[float]
    status: IncidentStatus
    assigned_unit: Optional[str]
    response_time: Optional[float]
    notes: Optional[str]
    verification_source: Optional[str]
    dispatch_logs: List[DispatchLogOut] = []

    class Config:
        from_attributes = True

    @validator("evidence_frames", pre=True, always=True)
    def parse_evidence_frames(cls, value):
        if not value:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, list) else []
            except ValueError:
                return []
        return []


# ─── AI Report ───────────────────────────────────────────────────────────────

class AIReportRequest(BaseModel):
    event_id: Optional[str] = Field(None, max_length=128)
    type: IncidentType
    confidence: float = Field(..., ge=0.0, le=1.0)
    peak_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    camera_id: str
    timestamp: Optional[datetime] = None
    snapshot_url: Optional[str] = None
    video_clip_url: Optional[str] = None
    frames: List[str] = []
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)


class AIReportResponse(BaseModel):
    accepted: bool
    incident_id: Optional[str] = None
    message: str


# ─── WebSocket Alert ─────────────────────────────────────────────────────────

class AlertPayload(BaseModel):
    event: str = "new_incident"
    incident_id: str
    type: IncidentType
    confidence: float
    peak_confidence: Optional[float] = None
    camera_id: str
    timestamp: str
    snapshot_url: Optional[str] = None
    video_clip_url: Optional[str] = None
    evidence_frames: List[str] = []
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    status: IncidentStatus = IncidentStatus.pending
    notifications_sent: List[str] = []
