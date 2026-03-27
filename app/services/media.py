import base64
import binascii
from pathlib import Path
from typing import Iterable, Optional
from uuid import uuid4


DATA_URI_PREFIX = "data:"
EVIDENCE_ROOT = Path("data") / "evidence"


def persist_evidence_bundle(
    incident_id: str,
    snapshot_url: Optional[str],
    video_clip_url: Optional[str],
    frames: Iterable[str],
) -> tuple[Optional[str], Optional[str], list[str]]:
    incident_dir = EVIDENCE_ROOT / incident_id
    incident_dir.mkdir(parents=True, exist_ok=True)

    stored_snapshot = _persist_data_uri(snapshot_url, incident_dir, "snapshot")
    stored_clip = _persist_data_uri(video_clip_url, incident_dir, "clip")

    stored_frames = []
    for index, frame in enumerate(frames):
        saved = _persist_data_uri(frame, incident_dir, f"frame-{index + 1}")
        if saved:
            stored_frames.append(saved)

    return stored_snapshot or snapshot_url, stored_clip or video_clip_url, stored_frames


def _persist_data_uri(data: Optional[str], directory: Path, stem: str) -> Optional[str]:
    if not data or not isinstance(data, str) or not data.startswith(DATA_URI_PREFIX):
        return None

    try:
        header, payload = data.split(",", 1)
    except ValueError:
        return None

    suffix = _guess_suffix(header)
    try:
        binary = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        return None

    path = directory / f"{stem}-{uuid4().hex[:8]}{suffix}"
    path.write_bytes(binary)
    return path.as_posix()


def _guess_suffix(header: str) -> str:
    if "image/png" in header:
        return ".png"
    if "video/mp4" in header:
        return ".mp4"
    if "video/webm" in header:
        return ".webm"
    return ".jpg"
