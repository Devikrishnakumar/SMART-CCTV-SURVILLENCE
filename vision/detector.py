"""
vision/detector.py
==================
YOLO inference loop for SMART-CCTV-SURVILLENCE.

Models used (drop .pt files into vision/models/):
  yolov11_bike.pt   — detects bicycle/motorcycle crashes  → accident
  yolov11_car.pt    — detects car/bus/truck crashes       → accident

Fallen-person and violence models can be added to MODEL_REGISTRY below.

Usage:
  python3 vision/detector.py \\
    --camera-id <uuid>  \\    # camera UUID registered in backend
    --source 0          \\    # 0 = webcam, or RTSP URL / video file path
    --api http://localhost:8000 \\
    --fps 2             \\    # inference rate (frames per second)
    --show              \\    # display live annotated feed (requires display)
    --threshold 0.65         # override confidence threshold
"""

import argparse
import asyncio
import base64
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

import cv2
import httpx
from ultralytics import YOLO

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
log = logging.getLogger("vision.detector")

# ─── Constants ───────────────────────────────────────────────────────────────
MODELS_DIR = Path(__file__).parent / "models"
API_ENDPOINT = "/ai/report"

# Map model-file → incident type sent to backend
# Add more models here as you train / download them
MODEL_REGISTRY = {
    "yolov11_car.pt":    "accident",      # car / truck / bus crash
    "yolov11_bike.pt":   "accident",      # bike / motorcycle crash
    # "yolov8_violence.pt": "violence",   # uncomment when you have the weight
    # "yolov5_fall.pt":    "fallen_person",
}

# Cooldown: don't spam the same incident type from same camera
# (seconds before re-reporting the same type)
COOLDOWN_SECONDS = 30


class Detector:
    def __init__(
        self,
        camera_id: str,
        source,
        api_base: str,
        fps: float = 2.0,
        threshold: float = 0.65,
        show: bool = False,
    ):
        self.camera_id  = camera_id
        self.source     = source
        self.api_base   = api_base.rstrip("/")
        self.interval   = 1.0 / fps
        self.threshold  = threshold
        self.show       = show
        self.models     = {}          # {incident_type: YOLO model}
        self.last_report: dict = {}   # {incident_type: timestamp}

        self._load_models()

    def _load_models(self):
        """Load all .pt files found in vision/models/"""
        found = False
        for filename, incident_type in MODEL_REGISTRY.items():
            path = MODELS_DIR / filename
            if path.exists():
                log.info(f"Loading model: {filename} → type={incident_type}")
                self.models[incident_type] = YOLO(str(path))
                found = True
            else:
                log.warning(f"Model not found (skipping): {path}")

        if not found:
            log.error(
                f"No models found in {MODELS_DIR}. "
                "Drop .pt files there and restart."
            )
            sys.exit(1)

    def _encode_frame(self, frame) -> Optional[str]:
        """JPEG-encode frame and return base64 string (for snapshot_url)."""
        try:
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            return "data:image/jpeg;base64," + base64.b64encode(buf).decode()
        except Exception:
            return None

    def _can_report(self, incident_type: str) -> bool:
        last = self.last_report.get(incident_type, 0)
        return (time.time() - last) >= COOLDOWN_SECONDS

    async def _report(self, incident_type: str, confidence: float, snapshot_b64: Optional[str]):
        """POST detection to FastAPI backend."""
        payload = {
            "type":         incident_type,
            "confidence":   round(confidence, 4),
            "camera_id":    self.camera_id,
            "snapshot_url": snapshot_b64,   # base64 data-URI (or None)
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.post(
                    self.api_base + API_ENDPOINT,
                    json=payload,
                )
            data = r.json()
            if data.get("accepted"):
                log.info(
                    f"✅ Reported {incident_type} (conf={confidence:.2f}) → "
                    f"incident_id={data.get('incident_id','?')}"
                )
                self.last_report[incident_type] = time.time()
            else:
                log.debug(f"Backend rejected: {data.get('message')}")
        except Exception as e:
            log.error(f"Failed to report to backend: {e}")

    def _infer_frame(self, frame) -> list[tuple[str, float]]:
        """
        Run all loaded models on a single frame.
        Returns list of (incident_type, max_confidence) for detections
        that exceed the threshold.
        """
        detections = []
        for incident_type, model in self.models.items():
            results = model(frame, verbose=False)
            for r in results:
                if r.boxes is None or len(r.boxes) == 0:
                    continue
                confs = r.boxes.conf.cpu().numpy()
                max_conf = float(confs.max()) if len(confs) else 0.0
                if max_conf >= self.threshold:
                    detections.append((incident_type, max_conf))
        return detections

    def _annotate(self, frame, detections: list[tuple[str, float]]):
        """Draw detection overlays on frame."""
        for incident_type, conf in detections:
            label = f"{incident_type.upper()} {conf:.0%}"
            cv2.putText(
                frame, label, (12, 36),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2, cv2.LINE_AA
            )
        ts = time.strftime("%H:%M:%S")
        cv2.putText(
            frame, f"CAM:{self.camera_id[:8]} {ts}", (12, frame.shape[0] - 12),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA
        )
        return frame

    async def run(self):
        """Main capture + inference loop."""
        log.info(f"Opening source: {self.source}")
        cap = cv2.VideoCapture(self.source)
        if not cap.isOpened():
            log.error(f"Cannot open video source: {self.source}")
            sys.exit(1)

        log.info(
            f"🎥 Running — camera_id={self.camera_id} | "
            f"fps={1/self.interval:.1f} | threshold={self.threshold}"
        )

        next_frame = time.time()

        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    log.warning("Frame read failed — retrying...")
                    await asyncio.sleep(1.0)
                    continue

                now = time.time()
                if now < next_frame:
                    await asyncio.sleep(next_frame - now)
                    continue
                next_frame = now + self.interval

                # Inference
                detections = self._infer_frame(frame)

                # Report detections above threshold (with cooldown)
                for incident_type, conf in detections:
                    if self._can_report(incident_type):
                        snap = self._encode_frame(frame)
                        await self._report(incident_type, conf, snap)

                # Optional live display
                if self.show:
                    annotated = self._annotate(frame.copy(), detections)
                    cv2.imshow(f"SMART-CCTV [{self.camera_id[:8]}]", annotated)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        log.info("User quit (q pressed)")
                        break

        except KeyboardInterrupt:
            log.info("Interrupted — shutting down.")
        finally:
            cap.release()
            if self.show:
                cv2.destroyAllWindows()


# ─── CLI ─────────────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(description="SMART-CCTV YOLO Inference Module")
    p.add_argument("--camera-id",  required=True, help="Camera UUID (registered in backend)")
    p.add_argument("--source",     default=0,     help="Video source: 0=webcam, RTSP URL, or file path")
    p.add_argument("--api",        default="http://localhost:8000", help="Backend API base URL")
    p.add_argument("--fps",        type=float, default=2.0, help="Inference frames per second (default 2)")
    p.add_argument("--threshold",  type=float, default=0.65, help="Confidence threshold (default 0.65)")
    p.add_argument("--show",       action="store_true", help="Display annotated video feed")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    detector = Detector(
        camera_id  = args.camera_id,
        source     = int(args.source) if str(args.source).isdigit() else args.source,
        api_base   = args.api,
        fps        = args.fps,
        threshold  = args.threshold,
        show       = args.show,
    )
    asyncio.run(detector.run())
