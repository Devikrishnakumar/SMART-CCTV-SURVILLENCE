from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime
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
    status: CameraStatus = CameraStatus.active


class CameraOut(BaseModel):
    id: str
    name: str
    location_name: str
    latitude: float
    longitude: float
    status: CameraStatus
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Incident ────────────────────────────────────────────────────────────────

class IncidentCreate(BaseModel):
    type: IncidentType
    confidence: float = Field(..., ge=0.0, le=1.0)
    camera_id: str
    snapshot_url: Optional[str] = None
    video_clip_url: Optional[str] = None
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)


class IncidentVerify(BaseModel):
    notes: Optional[str] = None


class IncidentDispatch(BaseModel):
    assigned_unit: str = Field(..., min_length=1, max_length=128)
    notes: Optional[str] = None


class IncidentResolve(BaseModel):
    response_time: Optional[float] = Field(None, ge=0)
    notes: Optional[str] = None


class DispatchLogOut(BaseModel):
    id: str
    action: str
    performed_by_id: str
    timestamp: datetime

    class Config:
        from_attributes = True


class IncidentOut(BaseModel):
    id: str
    type: IncidentType
    confidence: float
    camera_id: str
    timestamp: datetime
    snapshot_url: Optional[str]
    video_clip_url: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    status: IncidentStatus
    assigned_unit: Optional[str]
    response_time: Optional[float]
    notes: Optional[str]
    dispatch_logs: List[DispatchLogOut] = []

    class Config:
        from_attributes = True


# ─── AI Report ───────────────────────────────────────────────────────────────

class AIReportRequest(BaseModel):
    type: IncidentType
    confidence: float = Field(..., ge=0.0, le=1.0)
    camera_id: str
    snapshot_url: Optional[str] = None
    video_clip_url: Optional[str] = None


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
    camera_id: str
    timestamp: str
    snapshot_url: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    notifications_sent: List[str] = []
