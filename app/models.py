import uuid
import enum
from datetime import datetime
from sqlalchemy import (
    Column, String, Float, Boolean, DateTime, ForeignKey,
    Enum as SAEnum, Text, func
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


def gen_uuid():
    return str(uuid.uuid4())


class UserRole(str, enum.Enum):
    operator = "operator"
    dispatcher = "dispatcher"
    admin = "admin"


class IncidentType(str, enum.Enum):
    accident = "accident"
    violence = "violence"
    fallen_person = "fallen_person"
    fire = "fire"


class IncidentStatus(str, enum.Enum):
    pending = "pending"
    verified = "verified"
    dispatched = "dispatched"
    resolved = "resolved"
    closed = "closed"


class CameraStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"
    maintenance = "maintenance"


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    role = Column(SAEnum(UserRole), nullable=False, default=UserRole.operator)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    dispatch_logs = relationship("DispatchLog", back_populates="performed_by_user")


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    name = Column(String(128), nullable=False)
    location_name = Column(String(256), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    stream_url = Column(Text, nullable=True)
    status = Column(SAEnum(CameraStatus), nullable=False, default=CameraStatus.active)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    incidents = relationship("Incident", back_populates="camera")


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    event_id = Column(String(128), nullable=True, index=True)
    type = Column(SAEnum(IncidentType), nullable=False)
    confidence = Column(Float, nullable=False)
    peak_confidence = Column(Float, nullable=True)
    camera_id = Column(UUID(as_uuid=False), ForeignKey("cameras.id"), nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    snapshot_url = Column(Text, nullable=True)
    video_clip_url = Column(Text, nullable=True)
    evidence_frames = Column(Text, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    status = Column(SAEnum(IncidentStatus), nullable=False, default=IncidentStatus.pending, index=True)
    assigned_unit = Column(String(128), nullable=True)
    response_time = Column(Float, nullable=True)  # seconds
    notes = Column(Text, nullable=True)
    verification_source = Column(String(64), nullable=True)

    camera = relationship("Camera", back_populates="incidents")
    dispatch_logs = relationship("DispatchLog", back_populates="incident", cascade="all, delete-orphan")


class DispatchLog(Base):
    __tablename__ = "dispatch_logs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    incident_id = Column(UUID(as_uuid=False), ForeignKey("incidents.id"), nullable=False, index=True)
    action = Column(String(256), nullable=False)
    performed_by_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    metadata_ = Column("metadata", Text, nullable=True)

    incident = relationship("Incident", back_populates="dispatch_logs")
    performed_by_user = relationship("User", back_populates="dispatch_logs")
