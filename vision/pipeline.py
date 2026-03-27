"""
Live CCTV vision pipeline.

This module makes the processing stages explicit:
camera stream -> frame extraction -> preprocessing -> YOLO inference ->
event aggregation -> AI report payload.
"""

from __future__ import annotations

import base64
import tempfile
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

import cv2
from ultralytics import YOLO


@dataclass
class DetectionSample:
    confidence: float
    frame: object
    labels: list[str] = field(default_factory=list)


@dataclass
class EventState:
    consecutive_hits: int = 0
    first_detected_at: float = 0.0
    best_sample: Optional[DetectionSample] = None
    initial_frame: Optional[object] = None
    recent_frames: deque = field(default_factory=lambda: deque(maxlen=3))
    labels: set[str] = field(default_factory=set)
    last_reported_at: float = 0.0


class FramePreprocessor:
    def __init__(self, width: int = 1280, height: int = 720):
        self.width = width
        self.height = height

    def __call__(self, frame):
        resized = cv2.resize(frame, (self.width, self.height))
        return cv2.GaussianBlur(resized, (3, 3), 0)


class StreamIngestor:
    def __init__(self, source, reconnect_delay: int = 3):
        self.source = source
        self.reconnect_delay = reconnect_delay

    def open(self):
        return cv2.VideoCapture(self.source)


class ModelRouter:
    def __init__(self, model_paths: dict[str, list[str]], threshold: float = 0.65):
        self.threshold = threshold
        self.models: dict[str, list[YOLO]] = defaultdict(list)
        for incident_type, paths in model_paths.items():
            for path in paths:
                p = Path(path)
                if p.exists():
                    self.models[incident_type].append(YOLO(str(p)))

        if not self.models:
            raise SystemExit("No YOLO model weights available")

    def infer(self, frame) -> dict[str, DetectionSample]:
        hits: dict[str, DetectionSample] = {}

        for incident_type, models in self.models.items():
            best_conf = 0.0
            labels: list[str] = []

            for model in models:
                results = model(frame, verbose=False)
                for result in results:
                    if result.boxes is None or len(result.boxes) == 0:
                        continue
                    confs = result.boxes.conf.cpu().numpy()
                    if len(confs) == 0:
                        continue
                    candidate = float(confs.max())
                    if candidate > best_conf:
                        best_conf = candidate
                    if result.boxes.cls is not None and hasattr(result, "names"):
                        cls_ids = result.boxes.cls.cpu().numpy().tolist()
                        labels = [result.names.get(int(cls_id), str(cls_id)) for cls_id in cls_ids]

            if best_conf >= self.threshold:
                hits[incident_type] = DetectionSample(confidence=best_conf, frame=frame.copy(), labels=labels)

        return hits


class TemporalEventAggregator:
    def __init__(self, confirm_frames: int = 3, cooldown: int = 30):
        self.confirm_frames = max(1, confirm_frames)
        self.cooldown = cooldown
        self.states: dict[str, EventState] = defaultdict(EventState)

    def step(self, detections: dict[str, DetectionSample]) -> list[tuple[str, EventState, float]]:
        now = time.time()
        emitted: list[tuple[str, EventState, float]] = []

        for incident_type, state in self.states.items():
            if incident_type not in detections:
                state.consecutive_hits = 0
                state.initial_frame = None
                state.recent_frames.clear()
                state.best_sample = None
                state.labels.clear()

        for incident_type, sample in detections.items():
            state = self.states[incident_type]
            if now - state.last_reported_at < self.cooldown:
                continue

            state.consecutive_hits += 1
            if state.consecutive_hits == 1:
                state.first_detected_at = now
                state.initial_frame = sample.frame.copy()

            state.recent_frames.append(sample.frame.copy())
            state.labels.update(sample.labels)

            if not state.best_sample or sample.confidence >= state.best_sample.confidence:
                state.best_sample = sample

            if state.consecutive_hits >= self.confirm_frames:
                emitted.append((incident_type, state, now))
                state.last_reported_at = now
                state.consecutive_hits = 0
                state.initial_frame = None
                state.recent_frames.clear()
                state.best_sample = None
                state.labels.clear()

        return emitted


class EvidenceBuilder:
    def __init__(self, clip_seconds: int = 4, fps: float = 5.0):
        self.clip_seconds = max(0, clip_seconds)
        self.fps = fps
        self.frame_buffer: deque = deque(maxlen=max(1, int(fps * max(1, clip_seconds))))

    def push(self, frame):
        self.frame_buffer.append(frame.copy())

    def snapshot_data_uri(self, frame) -> Optional[str]:
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not ok:
            return None
        return "data:image/jpeg;base64," + base64.b64encode(encoded).decode()

    def clip_data_uri(self) -> Optional[str]:
        if self.clip_seconds <= 0 or not self.frame_buffer:
            return None

        height, width = self.frame_buffer[0].shape[:2]
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            temp_path = Path(tmp.name)

        writer = cv2.VideoWriter(
            str(temp_path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            max(1.0, self.fps),
            (width, height),
        )

        try:
            for frame in self.frame_buffer:
                writer.write(frame)
        finally:
            writer.release()

        try:
            encoded = base64.b64encode(temp_path.read_bytes()).decode()
            return f"data:video/mp4;base64,{encoded}"
        finally:
            temp_path.unlink(missing_ok=True)

    def build_payload(
        self,
        camera_id: str,
        incident_type: str,
        state: EventState,
        detected_at: float,
    ) -> dict:
        evidence_frames = []
        if state.initial_frame is not None:
            evidence_frames.append(self.snapshot_data_uri(state.initial_frame))
        if state.best_sample is not None:
            evidence_frames.append(self.snapshot_data_uri(state.best_sample.frame))
        if state.recent_frames:
            evidence_frames.append(self.snapshot_data_uri(state.recent_frames[-1]))
        evidence_frames = [item for item in evidence_frames if item]

        peak = state.best_sample.confidence if state.best_sample else 0.0

        return {
            "event_id": f"{camera_id}-{incident_type}-{uuid4().hex[:12]}",
            "type": incident_type,
            "confidence": round(peak, 4),
            "peak_confidence": round(peak, 4),
            "camera_id": camera_id,
            "timestamp": datetime.fromtimestamp(detected_at, tz=timezone.utc).isoformat(),
            "snapshot_url": evidence_frames[1] if len(evidence_frames) > 1 else (evidence_frames[0] if evidence_frames else None),
            "video_clip_url": self.clip_data_uri(),
            "frames": evidence_frames,
        }
