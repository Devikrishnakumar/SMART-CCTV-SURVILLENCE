"""
NovaGuard Dashboard Server — FastAPI edition

Install deps:
    pip install fastapi uvicorn[standard] python-multipart

Run:
    python dashboard.py
"""

import os
import base64
import hmac
import time
import datetime
import threading
import asyncio
import json
import uuid
from typing import Literal, Optional
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import cv2
from fastapi import FastAPI, Response, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

INFERENCE_ENABLED = os.environ.get(
    "NOVAGUARD_ENABLE_INFERENCE",
    "false" if os.environ.get("RENDER") else "true",
).strip().lower() in {"1", "true", "yes", "on"}

if INFERENCE_ENABLED:
    import detection_engine
else:
    detection_engine = None

import features

# ─────────────────────────────────────────
# GLOBAL STATE (populated in lifespan)
# ─────────────────────────────────────────
state = None
camera_lock = threading.Lock()
camera_file = os.path.join(os.path.dirname(__file__), "cameras.json")
DEFAULT_CAMERA = {
    "id": "local-webcam-0",
    "name": "Local webcam",
    "kind": "webcam",
    "source": 0,
    "location": "This computer",
}
cameras = [dict(DEFAULT_CAMERA)]
active_camera_id = DEFAULT_CAMERA["id"]


class CameraInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["webcam", "rtsp"]
    source: Optional[str] = Field(default=None, max_length=2048)
    location: str = Field(default="", max_length=100)


def _save_cameras():
    """Persist camera definitions locally; API responses never include stream credentials."""
    with camera_lock:
        payload = {"active_camera_id": active_camera_id, "cameras": cameras}
        temp_file = camera_file + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(temp_file, camera_file)


def _load_cameras():
    global cameras, active_camera_id
    try:
        with open(camera_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
        loaded = payload.get("cameras", [])
        valid = []
        for item in loaded:
            if not isinstance(item, dict):
                continue
            if not isinstance(item.get("id"), str) or not isinstance(item.get("name"), str):
                continue
            if item.get("kind") not in ("webcam", "rtsp"):
                continue
            if not isinstance(item.get("source"), (int, str)):
                continue
            if item["kind"] == "webcam":
                try:
                    item["source"] = int(item["source"])
                except (TypeError, ValueError):
                    continue
                if item["source"] < 0 or item["source"] > 16:
                    continue
            else:
                try:
                    parsed = urlsplit(item["source"])
                    if parsed.scheme.lower() not in ("rtsp", "rtsps", "http", "https") or not parsed.hostname:
                        continue
                    _ = parsed.port
                except ValueError:
                    continue
            valid.append(item)
        cameras = valid or [dict(DEFAULT_CAMERA)]
        requested_active = payload.get("active_camera_id")
        active_camera_id = next(
            (item["id"] for item in cameras if item.get("id") == requested_active),
            cameras[0]["id"],
        )
    except (OSError, ValueError, TypeError):
        cameras = [dict(DEFAULT_CAMERA)]
        active_camera_id = DEFAULT_CAMERA["id"]


def _public_camera(camera, active=False):
    """Return display-safe camera metadata without RTSP credentials or full URL paths."""
    if camera["kind"] == "webcam":
        source_label = f"Camera index {camera['source']}"
    else:
        try:
            parsed = urlsplit(camera["source"])
            host = parsed.hostname or "network stream"
            port = f":{parsed.port}" if parsed.port else ""
            source_label = f"{parsed.scheme.upper()} · {host}{port}"
        except ValueError:
            source_label = "Network stream"
    return {
        "id": camera["id"],
        "name": camera["name"],
        "kind": camera["kind"],
        "location": camera.get("location", ""),
        "source_label": source_label,
        "active": active,
    }


def _find_camera(camera_id):
    with camera_lock:
        return next((dict(camera) for camera in cameras if camera["id"] == camera_id), None)


def _activate_camera(camera):
    global active_camera_id
    with camera_lock:
        active_camera_id = camera["id"]
    _save_cameras()
    if state is not None:
        detection_engine.change_source(
            state, camera["source"], camera["id"], camera["name"], camera["kind"], camera.get("location", "")
        )

# ─────────────────────────────────────────
# BACKGROUND: evidence + email alert loop
# ─────────────────────────────────────────
def alert_loop():
    while True:
        time.sleep(1)
        try:
            if state is None:
                continue
            with state.lock:
                frame = state.annotated_frame.copy() if state.annotated_frame is not None else None
                risk = state.risk_level
                fire = dict(state.fire)
                violence = dict(state.violence)
                weapon = dict(state.weapon)
                accident = dict(state.accident)

            if frame is None:
                continue

            all_results = {
                "fire": fire,
                "violence": violence,
                "weapon": weapon,
                "accident": accident,
            }

            if risk in ("HIGH", "CRITICAL"):
                for dtype, res in all_results.items():
                    if res.get("detected"):
                        inc = features.record_evidence(dtype, frame, state, all_results)
                        if inc:
                            state.total_alerts += 1
                            features.send_email(
                                dtype,
                                res.get("confidence", 0.0),
                                risk,
                                inc["screenshots"][0] if inc["screenshots"] else None,
                            )

            features.write_evidence_frame(frame)

        except Exception as e:
            print(f"[Alert loop] {e}")

# ─────────────────────────────────────────
# LIFESPAN — fires ONCE, prevents double-init
# ─────────────────────────────────────────
@asynccontextmanager
async def lifespan(application: FastAPI):
    global state
    features.init()
    _load_cameras()
    if not INFERENCE_ENABLED:
        state = None
        print("AI inference disabled; running dashboard-only mode")
        yield
        return

    camera = _find_camera(active_camera_id) or dict(DEFAULT_CAMERA)
    state = detection_engine.start(
        source=camera["source"], camera_id=camera["id"],
        camera_name=camera["name"], camera_kind=camera["kind"],
        camera_location=camera.get("location", ""),
    )
    threading.Thread(target=alert_loop, daemon=True, name="alert").start()
    yield
    if state:
        state.running = False

app = FastAPI(title="NovaGuard", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.middleware("http")
async def protect_public_dashboard(request, call_next):
    if request.url.path == "/health":
        return await call_next(request)

    username = os.environ.get("NOVAGUARD_ACCESS_USERNAME", "")
    password = os.environ.get("NOVAGUARD_ACCESS_PASSWORD", "")
    if not os.environ.get("RENDER") and not password:
        return await call_next(request)
    if not username or not password:
        return JSONResponse({"detail": "Dashboard access is not configured."}, status_code=503)

    scheme = ""
    separator = ""
    supplied_username = ""
    supplied_password = ""
    authorization = request.headers.get("authorization", "")
    try:
        scheme, encoded = authorization.split(" ", 1)
        supplied = base64.b64decode(encoded, validate=True).decode("utf-8")
        supplied_username, separator, supplied_password = supplied.partition(":")
    except (ValueError, UnicodeDecodeError):
        pass

    if (
        scheme.lower() != "basic"
        or not separator
        or not hmac.compare_digest(supplied_username, username)
        or not hmac.compare_digest(supplied_password, password)
    ):
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="NovaGuard", charset="UTF-8"'},
        )
    return await call_next(request)


landing_dist = os.path.join(os.path.dirname(__file__), "designpro", "dist")
landing_assets = os.path.join(landing_dist, "assets")
if os.path.isdir(landing_assets):
    app.mount("/assets", StaticFiles(directory=landing_assets), name="landing-assets")

# ─────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────

@app.get("/health")
async def health():
    return JSONResponse({"status": "ok", "inference_enabled": INFERENCE_ENABLED})


@app.get("/", response_class=HTMLResponse)
async def index():
    landing_index = os.path.join(landing_dist, "index.html")
    if os.path.isfile(landing_index):
        return FileResponse(landing_index)
    project_landing = os.path.join(os.path.dirname(__file__), "index (3).html")
    if os.path.isfile(project_landing):
        return FileResponse(project_landing)
    landing_fallback = os.path.join(os.path.dirname(__file__), "designpro", "landing.html")
    if os.path.isfile(landing_fallback):
        return FileResponse(landing_fallback)
    html_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    html_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()


# ── MJPEG video stream ──────────────────
async def _mjpeg_generator():
    boundary = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
    while True:
        if state is not None:
            with state.lock:
                data = state.jpeg_bytes
            if data:
                yield boundary + data + b"\r\n"
        await asyncio.sleep(0.033)


@app.get("/video_feed")
async def video_feed():
    return StreamingResponse(
        _mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache"},
    )


# ── Status JSON ─────────────────────────
@app.get("/api/status")
async def api_status():
    if state is None:
        message = "AI inference is disabled on this service." if not INFERENCE_ENABLED else "starting up"
        return JSONResponse({"error": message}, status_code=503)
    with state.lock:
        uptime_secs = int(time.time() - state.uptime_start)
        return JSONResponse({
            "risk_level": state.risk_level,
            "risk_score": round(state.risk_score * 100),
            "fps": state.fps,
            "uptime": uptime_secs,
            "total_alerts": state.total_alerts,
            "camera": {
                "id": state.camera_id,
                "name": state.camera_name,
                "kind": state.camera_kind,
                "location": state.camera_location,
                "status": state.camera_status,
                "error": state.camera_error,
            },
            "fire": {
                "detected": state.fire["detected"],
                "confidence": round(state.fire["confidence"] * 100),
                "label": state.fire["label"],
            },
            "violence": {
                "detected": state.violence["detected"],
                "confidence": round(state.violence["confidence"] * 100),
                "label": state.violence["last_result"],
            },
            "weapon": {
                "detected": state.weapon["detected"],
                "confidence": round(state.weapon["confidence"] * 100),
                "label": state.weapon["label"],
            },
            "accident": {
                "detected": state.accident["detected"],
                "confidence": round(state.accident["confidence"] * 100),
                "label": state.accident["label"],
            },
        })


@app.get("/api/cameras")
async def api_cameras():
    with camera_lock:
        items = [_public_camera(camera, camera["id"] == active_camera_id) for camera in cameras]
        selected = active_camera_id
    return JSONResponse({"cameras": items, "active_id": selected})


@app.post("/api/cameras")
async def api_add_camera(payload: CameraInput):
    global cameras
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Enter a camera name.")

    location = payload.location.strip()
    if payload.kind == "webcam":
        raw_index = (payload.source or "0").strip()
        try:
            source = int(raw_index)
        except ValueError:
            raise HTTPException(status_code=422, detail="Webcam index must be a number, such as 0.")
        if source < 0 or source > 16:
            raise HTTPException(status_code=422, detail="Webcam index must be between 0 and 16.")
    else:
        source = (payload.source or "").strip()
        try:
            parsed = urlsplit(source)
            if parsed.scheme.lower() not in ("rtsp", "rtsps", "http", "https") or not parsed.hostname:
                raise ValueError
            _ = parsed.port
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="Use a valid RTSP/RTSPS/HTTP stream URL from the camera or NVR.",
            )

    camera = {
        "id": uuid.uuid4().hex[:10],
        "name": name,
        "kind": payload.kind,
        "source": source,
        "location": location,
    }
    with camera_lock:
        cameras.append(camera)
    _activate_camera(camera)
    return JSONResponse({"camera": _public_camera(camera, True), "status": "connecting"}, status_code=201)


@app.post("/api/cameras/{camera_id}/connect")
async def api_connect_camera(camera_id: str):
    camera = _find_camera(camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found.")
    _activate_camera(camera)
    return JSONResponse({"camera": _public_camera(camera, True), "status": "connecting"})


@app.delete("/api/cameras/{camera_id}")
async def api_delete_camera(camera_id: str):
    global cameras, active_camera_id
    with camera_lock:
        if not any(camera["id"] == camera_id for camera in cameras):
            raise HTTPException(status_code=404, detail="Camera not found.")
        if len(cameras) == 1:
            raise HTTPException(status_code=409, detail="Keep at least one camera configured.")
        cameras = [camera for camera in cameras if camera["id"] != camera_id]
        replacement = None
        if active_camera_id == camera_id:
            replacement = cameras[0]
            active_camera_id = replacement["id"]
    _save_cameras()
    if replacement and state is not None:
        detection_engine.change_source(
            state, replacement["source"], replacement["id"],
            replacement["name"], replacement["kind"], replacement.get("location", ""),
        )
    return JSONResponse({"ok": True, "active_id": active_camera_id})


# ── Incidents list ───────────────────────
@app.get("/api/incidents")
async def api_incidents():
    return JSONResponse(features.get_all_incidents())


# ── Download single incident PDF ─────────
@app.get("/api/download_incident/{incident_id}")
async def download_incident(incident_id: str):
    pdf_bytes = features.get_incident_pdf_bytes(incident_id)
    if not pdf_bytes:
        return Response("Not found", status_code=404)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={incident_id}_report.pdf"},
    )


# ── Download daily report PDF ─────────────
@app.get("/api/download_daily")
async def download_daily():
    pdf_bytes = features.generate_daily_report()
    if not pdf_bytes:
        return Response("No report available", status_code=404)
    today = datetime.date.today().strftime("%Y%m%d")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=novaguard_daily_{today}.pdf"},
    )


# ── Download latest incident PDF ──────────
@app.get("/api/download_latest")
async def download_latest():
    incidents = features.get_all_incidents()
    if not incidents:
        return Response("No incidents recorded yet", status_code=404)
    latest = incidents[0]
    pdf_bytes = features.get_incident_pdf_bytes(latest["incident_id"])
    if not pdf_bytes:
        return Response("PDF not found", status_code=404)
    name = latest["incident_id"]
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={name}_report.pdf"},
    )


# ─────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────
if __name__ == "__main__":
    default_host = "0.0.0.0" if os.environ.get("RENDER") else "127.0.0.1"
    host = os.environ.get("NOVAGUARD_HOST", default_host)
    port = int(os.environ.get("PORT", "5000"))
    print(f"NovaGuard starting at http://{host}:{port}")
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
    )
