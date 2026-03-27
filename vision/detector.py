"""
YOLO event detector for live CCTV streams.

This version matches the backend workflow more closely:
- controlled FPS ingestion
- reconnect handling for unstable streams
- multi-model inference by incident type
- temporal consistency before reporting
- evidence frame collection
- optional short clip export
"""

import argparse
import asyncio
import base64
import logging
import tempfile
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

import cv2
import httpx
from ultralytics import YOLO


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
log = logging.getLogger("vision.detector")

MODELS_DIR = Path(__file__).parent / "models"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
API_ENDPOINT = "/ai/report"
RECONNECT_DELAY_SECONDS = 3

MODEL_REGISTRY = {
    "yolov11_car.pt": "accident",
    "yolov11_bike.pt": "accident",
    "yolov8_fall.pt": "fallen_person",
    "yolov8_violence.pt": "violence",
    "fire.pt": "fire",
    "yolov8_fire.pt": "fire",
}


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


class Detector:
    def __init__(
        self,
        camera_id: str,
        source,
        api_base: str,
        fps: float = 5.0,
        threshold: float = 0.65,
        confirm_frames: int = 3,
        cooldown: int = 30,
        clip_seconds: int = 4,
        show: bool = False,
    ):
        self.camera_id = camera_id
        self.source = source
        self.api_base = api_base.rstrip("/")
        self.interval = 1.0 / fps
        self.threshold = threshold
        self.confirm_frames = max(1, confirm_frames)
        self.cooldown = cooldown
        self.clip_seconds = max(0, clip_seconds)
        self.show = show

        self.models: dict[str, list[YOLO]] = defaultdict(list)
        self.states: dict[str, EventState] = defaultdict(EventState)
        self.frame_buffer: deque = deque(maxlen=max(1, int(fps * max(1, clip_seconds))))

        self._load_models()

    def _load_models(self):
        found = False
        for filename, incident_type in MODEL_REGISTRY.items():
            path = MODELS_DIR / filename
            if not path.exists():
                path = PROJECT_ROOT / filename
            if not path.exists():
                continue
            log.info("Loading model: %s -> %s", filename, incident_type)
            self.models[incident_type].append(YOLO(str(path)))
            found = True

        if not found:
            raise SystemExit(f"No supported model weights found in {MODELS_DIR}")

    async def run(self):
        next_frame_at = 0.0
        while True:
            cap = cv2.VideoCapture(self.source)
            if not cap.isOpened():
                log.warning("Unable to open source %s. Retrying in %ss.", self.source, RECONNECT_DELAY_SECONDS)
                await asyncio.sleep(RECONNECT_DELAY_SECONDS)
                continue

            log.info(
                "Running detector camera_id=%s fps=%.1f threshold=%.2f confirm_frames=%s",
                self.camera_id,
                1 / self.interval,
                self.threshold,
                self.confirm_frames,
            )

            try:
                while True:
                    ok, frame = cap.read()
                    if not ok:
                        log.warning("Frame read failed. Reconnecting.")
                        break

                    now = time.time()
                    if now < next_frame_at:
                        await asyncio.sleep(next_frame_at - now)
                        continue
                    next_frame_at = now + self.interval

                    clean = frame.copy()
                    self.frame_buffer.append(clean)

                    detections = self._infer_frame(clean)
                    await self._process_detections(clean, detections)

                    if self.show:
                        annotated = self._annotate(frame.copy(), detections)
                        cv2.imshow(f"SMART-CCTV [{self.camera_id[:8]}]", annotated)
                        if cv2.waitKey(1) & 0xFF == ord("q"):
                            raise KeyboardInterrupt
            except KeyboardInterrupt:
                log.info("Interrupted, shutting down.")
                break
            finally:
                cap.release()

            await asyncio.sleep(RECONNECT_DELAY_SECONDS)

        if self.show:
            cv2.destroyAllWindows()

    def _infer_frame(self, frame) -> dict[str, DetectionSample]:
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
                hits[incident_type] = DetectionSample(
                    confidence=best_conf,
                    frame=frame.copy(),
                    labels=labels,
                )

        return hits

    async def _process_detections(self, frame, detections: dict[str, DetectionSample]):
        now = time.time()

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
                await self._report_event(incident_type, state, now)
                state.last_reported_at = now
                state.consecutive_hits = 0
                state.initial_frame = None
                state.recent_frames.clear()
                state.best_sample = None
                state.labels.clear()

    async def _report_event(self, incident_type: str, state: EventState, detected_at: float):
        evidence_frames = []
        if state.initial_frame is not None:
            evidence_frames.append(self._encode_jpeg(state.initial_frame))
        if state.best_sample is not None:
            evidence_frames.append(self._encode_jpeg(state.best_sample.frame))
        if state.recent_frames:
            evidence_frames.append(self._encode_jpeg(state.recent_frames[-1]))
        evidence_frames = [frame for frame in evidence_frames if frame]

        payload = {
            "event_id": f"{self.camera_id}-{incident_type}-{uuid4().hex[:12]}",
            "type": incident_type,
            "confidence": round(state.best_sample.confidence if state.best_sample else 0.0, 4),
            "peak_confidence": round(state.best_sample.confidence if state.best_sample else 0.0, 4),
            "camera_id": self.camera_id,
            "timestamp": datetime.fromtimestamp(detected_at, tz=timezone.utc).isoformat(),
            "snapshot_url": evidence_frames[1] if len(evidence_frames) > 1 else (evidence_frames[0] if evidence_frames else None),
            "video_clip_url": self._build_clip_data_uri(),
            "frames": evidence_frames,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(f"{self.api_base}{API_ENDPOINT}", json=payload)
            data = response.json()
            if data.get("accepted"):
                log.info(
                    "Reported %s event conf=%.2f incident_id=%s",
                    incident_type,
                    payload["confidence"],
                    data.get("incident_id"),
                )
            else:
                log.info("Backend rejected %s event: %s", incident_type, data.get("message"))
        except Exception as exc:
            log.error("Failed to report %s event: %s", incident_type, exc)

    def _build_clip_data_uri(self) -> Optional[str]:
        if self.clip_seconds <= 0 or not self.frame_buffer:
            return None

        height, width = self.frame_buffer[0].shape[:2]
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            temp_path = Path(tmp.name)

        writer = cv2.VideoWriter(
            str(temp_path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            max(1.0, 1 / self.interval),
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
        except OSError:
            return None
        finally:
            temp_path.unlink(missing_ok=True)

    def _encode_jpeg(self, frame) -> Optional[str]:
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not ok:
            return None
        return "data:image/jpeg;base64," + base64.b64encode(encoded).decode()

    def _annotate(self, frame, detections: dict[str, DetectionSample]):
        y = 32
        for incident_type, sample in detections.items():
            label = f"{incident_type.upper()} {sample.confidence:.0%}"
            cv2.putText(
                frame,
                label,
                (12, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.9,
                (0, 0, 255),
                2,
                cv2.LINE_AA,
            )
            y += 28

        cv2.putText(
            frame,
            f"CAM:{self.camera_id[:8]} {time.strftime('%H:%M:%S')}",
            (12, frame.shape[0] - 12),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (200, 200, 200),
            1,
            cv2.LINE_AA,
        )
        return frame


def parse_args():
    parser = argparse.ArgumentParser(description="SMART-CCTV YOLO event detector")
    parser.add_argument("--camera-id", required=True)
    parser.add_argument("--source", required=True, help="Video source: webcam index, file path, or RTSP URL")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--fps", type=float, default=5.0)
    parser.add_argument("--threshold", type=float, default=0.65)
    parser.add_argument("--confirm-frames", type=int, default=3)
    parser.add_argument("--cooldown", type=int, default=30)
    parser.add_argument("--clip-seconds", type=int, default=4)
    parser.add_argument("--show", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    source = int(args.source) if str(args.source).isdigit() else args.source
    detector = Detector(
        camera_id=args.camera_id,
        source=source,
        api_base=args.api,
        fps=args.fps,
        threshold=args.threshold,
        confirm_frames=args.confirm_frames,
        cooldown=args.cooldown,
        clip_seconds=args.clip_seconds,
        show=args.show,
    )
    asyncio.run(detector.run())
