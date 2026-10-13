

import cv2
import torch
import numpy as np
import threading
import time
from collections import deque
from ultralytics import YOLO
import torch.nn.functional as F

# ─────────────────────────────────────────
# SHARED STATE
# ─────────────────────────────────────────
class SharedState:
    def __init__(self):
        self.lock = threading.Lock()
        self.frame          = None
        self.annotated_frame = None
        self.jpeg_bytes     = None

        self.fire     = {"detected": False, "confidence": 0.0, "label": "SAFE",         "event_status": "SAFE"}
        self.violence = {"detected": False, "confidence": 0.0, "label": "NOT VIOLENCE", "last_result":  "NOT VIOLENCE"}
        self.weapon   = {"detected": False, "confidence": 0.0, "label": "CLEAR",        "detection_count": 0}
        self.accident = {"detected": False, "confidence": 0.0, "label": "NORMAL",       "accident_memory": 0, "traffic": False}

        self.risk_level   = "LOW"
        self.risk_score   = 0.0
        self.fps          = 0.0
        self.running      = True
        self.uptime_start = time.time()
        self.total_alerts = 0
        self.source = 0
        self.source_generation = 0
        self.camera_id = "local-webcam-0"
        self.camera_name = "Local webcam"
        self.camera_kind = "webcam"
        self.camera_location = "This computer"
        self.camera_status = "connecting"
        self.camera_error = None

# ─────────────────────────────────────────
# DEVICE
# ─────────────────────────────────────────
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"🖥  Torch device: {device}")

# ─────────────────────────────────────────
# FIRE DETECTION  (exact logic from fire.py)
# ─────────────────────────────────────────
def fire_thread(shared: SharedState):
    model = YOLO("fire.pt")
    print("🔥 Fire model loaded")

    while shared.running:
        with shared.lock:
            frame = shared.frame.copy() if shared.frame is not None else None
        if frame is None:
            time.sleep(0.01)
            continue

        results = model(frame, conf=0.85, verbose=False)

        event_status = "SAFE"
        confidence   = 0.0

        for r in results:
            if len(r.boxes) > 0:
                cls          = int(r.boxes.cls[0])
                event_status = model.names[cls]
                confidence   = float(r.boxes.conf[0])

        detected = event_status != "SAFE"

        with shared.lock:
            shared.fire["detected"]     = detected
            shared.fire["confidence"]   = confidence
            shared.fire["label"]        = event_status
            shared.fire["event_status"] = event_status

        time.sleep(0.05)

# ─────────────────────────────────────────
# VIOLENCE DETECTION
# Uses SlowFast R50 + motion gate + top-k scoring
# ─────────────────────────────────────────
def violence_thread(shared: SharedState):
    from pytorchvideo.models.hub import slowfast_r50

    CLIP_LEN    = 32
    IMG_SIZE    = 224
    INFER_EVERY = 6

    # All keywords that map to violent actions in Kinetics-400
    VIOLENCE_KEYWORDS = [
        "punch", "punching", "kick", "kicking", "slap", "slapping",
        "headbutt", "wrestling", "fight", "fighting", "boxing",
        "brawl", "assault", "attack", "hitting", "choking", "stabbing",
        "sword", "martial art", "karate", "judo", "taekwondo",
        "shooting", "gun", "knife",
    ]


    FALSE_POSITIVE_KEYWORDS = [
        "shaving", "hair", "curling", "grooming", "brushing",
        "cutting vegetables", "cooking", "cleaning", "beatboxing",
    ]

    def motion_level(frames: list) -> float:
        """Returns mean absolute pixel diff between first and last frame of clip."""
        if len(frames) < 2:
            return 0.0
        f1 = cv2.cvtColor(cv2.resize(frames[0],  (64, 64)), cv2.COLOR_BGR2GRAY).astype(np.float32)
        f2 = cv2.cvtColor(cv2.resize(frames[-1], (64, 64)), cv2.COLOR_BGR2GRAY).astype(np.float32)
        return float(np.mean(np.abs(f1 - f2)))

    def score_violence(probs_tensor, labels_list) -> tuple:
        """
        Sums probability across ALL violence-keyword classes in top-20.
        Much more reliable than argmax alone.
        Returns (cumulative_score, top_matched_label).
        """
        top_k = min(20, probs_tensor.shape[1])
        top_probs, top_idxs = torch.topk(probs_tensor[0], top_k)

        violence_score = 0.0
        top_violence_label = ""

        for prob, idx in zip(top_probs.tolist(), top_idxs.tolist()):
            lbl = labels_list[idx].lower() if idx < len(labels_list) else ""


            if any(fp in lbl for fp in FALSE_POSITIVE_KEYWORDS):
                continue

            if any(kw in lbl for kw in VIOLENCE_KEYWORDS):
                violence_score += prob
                if not top_violence_label:
                    top_violence_label = labels_list[idx]

        return violence_score, top_violence_label

    def preprocess(frames):
        frames = [cv2.resize(f, (IMG_SIZE, IMG_SIZE)) for f in frames]
        clip   = np.array(frames, dtype=np.float32)
        clip   = clip / 255.0
        clip   = (clip - 0.45) / 0.225
        clip   = clip.transpose(3, 0, 1, 2)
        clip   = torch.tensor(clip).unsqueeze(0).to(device)
        slow   = clip[:, :, ::4, :, :]
        fast   = clip
        return [slow, fast]

    model = slowfast_r50(pretrained=True).to(device).eval()
    print("\u26a1 Violence model loaded (SlowFast R50)")

    try:
        with open("label_map.txt") as f:
            labels = [line.strip() for line in f.readlines()]
    except FileNotFoundError:
        labels = [f"label_{i}" for i in range(400)]
        print("\u26a0\ufe0f  label_map.txt not found \u2014 using generic labels")

    frame_buffer = deque(maxlen=CLIP_LEN)
    pred_buffer  = deque(maxlen=3)
    last_result  = "NOT VIOLENCE"
    frame_count  = 0
    last_conf    = 0.0

    # Thresholds
    MOTION_THRESHOLD         = 4.0
    VIOLENCE_SCORE_THRESHOLD = 0.08

    while shared.running:
        with shared.lock:
            frame = shared.frame.copy() if shared.frame is not None else None
        if frame is None:
            time.sleep(0.01)
            continue

        frame_buffer.append(frame)
        frame_count += 1

        if len(frame_buffer) == CLIP_LEN and frame_count % INFER_EVERY == 0:
            try:
                # Motion gate: skip inference on still scenes — kills grooming false positives
                motion = motion_level(list(frame_buffer))
                if motion < MOTION_THRESHOLD:
                    pred_buffer.append(False)
                    last_result = "NOT VIOLENCE"
                    last_conf   = 0.0
                    print(f"[Violence] still scene (motion={motion:.1f}) \u2192 skipping")
                else:
                    inputs = preprocess(list(frame_buffer))
                    with torch.no_grad():
                        outputs = model(inputs)
                    probs = F.softmax(outputs, dim=1)

                    violence_score, top_label = score_violence(probs, labels)
                    is_violent = violence_score >= VIOLENCE_SCORE_THRESHOLD

                    pred_buffer.append(is_violent)
                    # Trigger on ANY single positive in the 3-frame window for fast response
                    last_result = "VIOLENCE" if any(pred_buffer) else "NOT VIOLENCE"
                    last_conf   = violence_score if last_result == "VIOLENCE" else 0.0

                    print(f"[Violence] score={violence_score:.3f} top='{top_label}' motion={motion:.1f} \u2192 {last_result}")

            except Exception as e:
                print(f"[Violence] inference error: {e}")

        detected = last_result == "VIOLENCE"

        with shared.lock:
            shared.violence["detected"]    = detected
            shared.violence["confidence"]  = last_conf
            shared.violence["label"]       = last_result
            shared.violence["last_result"] = last_result

        time.sleep(0.01)

# ─────────────────────────────────────────
# WEAPON DETECTION  (exact logic from weapon.py)
# ─────────────────────────────────────────
def weapon_thread(shared: SharedState):
    CONF_THRESHOLD    = 0.67
    IOU_THRESHOLD     = 0.5
    VALID_CLASSES     = ["knife", "gun"]
    DETECTION_REQUIRED = 3   # 3 consecutive frames — same as original

    model = YOLO("weapon.pt")
    print("🔫 Weapon model loaded")

    detection_count = 0

    while shared.running:
        with shared.lock:
            frame = shared.frame.copy() if shared.frame is not None else None
        if frame is None:
            time.sleep(0.01)
            continue

        results = model(frame, conf=CONF_THRESHOLD, iou=IOU_THRESHOLD, verbose=False)

        weapon_found = False
        max_conf     = 0.0
        found_label  = "CLEAR"

        for r in results:
            for box in r.boxes:
                cls   = int(box.cls[0])
                conf  = float(box.conf[0])
                label = model.names[cls]

                if label not in VALID_CLASSES:
                    continue
                if conf < CONF_THRESHOLD:
                    continue

                weapon_found = True
                if conf > max_conf:
                    max_conf    = conf
                    found_label = label

        if weapon_found:
            detection_count += 1
        else:
            detection_count = 0

        stable_detected = detection_count >= DETECTION_REQUIRED

        with shared.lock:
            shared.weapon["detected"]        = stable_detected
            shared.weapon["confidence"]      = max_conf if stable_detected else 0.0
            shared.weapon["label"]           = found_label if stable_detected else "CLEAR"
            shared.weapon["detection_count"] = detection_count

        time.sleep(0.05)

# ─────────────────────────────────────────
# ACCIDENT DETECTION  (exact logic from accident.py)
# ─────────────────────────────────────────
def accident_thread(shared: SharedState):
    VEHICLES         = ["car", "truck", "bus", "motorcycle"]
    PERSON_MIN_FRAMES = 40    # ~2 sec at 20fps
    PERSON_MAX_FRAMES = 140   # ~7 sec

    def center(box):
        x1, y1, x2, y2 = box
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    def dist(a, b):
        return np.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)

    def is_real_accident(id1, id2, speeds, prev_speeds):
        s1, s2   = speeds.get(id1, 0),     speeds.get(id2, 0)
        ps1, ps2 = prev_speeds.get(id1, 0), prev_speeds.get(id2, 0)
        if ps1 > 8 and s1 < 2:           return True
        if ps2 > 8 and s2 < 2:           return True
        if ps1 > 8 and s1 < ps1 * 0.4:  return True
        if ps2 > 8 and s2 < ps2 * 0.4:  return True
        return False

    def is_motionless(pid, speeds):
        return speeds.get(pid, 0) < 2

    model = YOLO("yolov8m.pt")
    print("🚗 Accident model loaded (YOLOv8m)")

    prev_positions  = {}
    prev_speeds     = {}
    person_hit_timer = {}
    accident_memory  = 0

    while shared.running:
        with shared.lock:
            frame = shared.frame.copy() if shared.frame is not None else None
        if frame is None:
            time.sleep(0.01)
            continue

        frame = cv2.resize(frame, (640, 480))
        results = model(frame, conf=0.4, verbose=False)

        vehicle_boxes = []
        person_boxes  = []
        centers       = {}
        speeds        = {}

        for r in results:
            for i, box in enumerate(r.boxes):
                cls   = int(box.cls[0])
                label = model.names[cls]
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                c = center((x1, y1, x2, y2))
                centers[i] = c
                if label in VEHICLES:
                    vehicle_boxes.append((i, (x1, y1, x2, y2)))
                elif label == "person":
                    person_boxes.append((i, (x1, y1, x2, y2)))

        moving_count = 0
        for i in centers:
            if i in prev_positions:
                speed = dist(prev_positions[i], centers[i])
                speeds[i] = speed
                if speed > 5:
                    moving_count += 1
            else:
                speeds[i] = 0

        accident = False
        traffic  = False

        # Traffic jam check
        if len(vehicle_boxes) >= 4 and moving_count <= 1:
            traffic = True

        # Vehicle ↔ Vehicle collision
        if not traffic and 2 <= len(vehicle_boxes) <= 3:
            for i in range(len(vehicle_boxes)):
                for j in range(i + 1, len(vehicle_boxes)):
                    id1, (x1, y1, x2, y2) = vehicle_boxes[i]
                    id2, (x3, y3, x4, y4) = vehicle_boxes[j]
                    overlap = (x1 < x4 and x2 > x3 and y1 < y4 and y2 > y3)
                    if overlap and is_real_accident(id1, id2, speeds, prev_speeds):
                        accident = True

        # Person ↔ Vehicle collision
        if not traffic:
            for _vid, (x1, y1, x2, y2) in vehicle_boxes:
                for pid, (x3, y3, x4, y4) in person_boxes:
                    overlap = (x1 < x4 and x2 > x3 and y1 < y4 and y2 > y3)
                    if overlap:
                        if pid not in person_hit_timer:
                            person_hit_timer[pid] = 0
                    if pid in person_hit_timer:
                        if is_motionless(pid, speeds):
                            person_hit_timer[pid] += 1
                        else:
                            del person_hit_timer[pid]
                            continue
                        if PERSON_MIN_FRAMES <= person_hit_timer[pid] <= PERSON_MAX_FRAMES:
                            accident = True

        # Clean up stale person IDs
        valid_ids = {pid for pid, _ in person_boxes}
        person_hit_timer = {k: v for k, v in person_hit_timer.items() if k in valid_ids}

        # Memory — keeps detection alive for 30 frames after last event
        if accident:
            accident_memory = 30
        if accident_memory > 0:
            accident_memory -= 1

        prev_positions = centers.copy()
        prev_speeds    = speeds.copy()

        if traffic:
            label = "TRAFFIC"
        elif accident_memory > 0:
            label = "ACCIDENT DETECTED!"
        else:
            label = "NORMAL"

        detected = accident_memory > 0

        with shared.lock:
            shared.accident["detected"]        = detected
            shared.accident["confidence"]      = 0.9 if detected else 0.0
            shared.accident["label"]           = label
            shared.accident["accident_memory"] = accident_memory
            shared.accident["traffic"]         = traffic

        time.sleep(0.03)

# ─────────────────────────────────────────
# RISK CALCULATOR
# ─────────────────────────────────────────
def compute_risk(shared: SharedState):
    with shared.lock:
        fire     = shared.fire["detected"]
        violence = shared.violence["detected"]
        weapon   = shared.weapon["detected"]
        accident = shared.accident["detected"]

        fire_conf     = shared.fire["confidence"]
        violence_conf = shared.violence["confidence"]
        weapon_conf   = shared.weapon["confidence"]

    count = sum([fire, violence, weapon, accident])

    if weapon and count >= 2:       return "CRITICAL", 1.0
    if weapon:                      return "CRITICAL", 0.9
    if count >= 2:                  return "HIGH",     0.80
    if fire and fire_conf >= 0.75:  return "HIGH",     0.70
    if violence and violence_conf >= 0.75: return "HIGH", 0.70
    if accident:                    return "HIGH",     0.65
    if count == 1:                  return "MEDIUM",   0.40
    return "LOW", 0.0

# ─────────────────────────────────────────
# ANNOTATED FRAME BUILDER
# ─────────────────────────────────────────
_COLOR = {
    "LOW":      (0, 255, 136),
    "MEDIUM":   (0, 187, 255),
    "HIGH":     (0, 100, 255),
    "CRITICAL": (0, 0, 255),
}

def _build_annotated(frame, shared: SharedState) -> np.ndarray:
    display = frame.copy()

    with shared.lock:
        fire_det     = shared.fire["detected"]
        fire_lbl     = shared.fire["label"]
        viol_lbl     = shared.violence["last_result"]
        weapon_det   = shared.weapon["detected"]
        weapon_lbl   = shared.weapon["label"]
        weapon_conf  = shared.weapon["confidence"]
        acc_lbl      = shared.accident["label"]
        acc_mem      = shared.accident["accident_memory"]
        traffic      = shared.accident["traffic"]
        risk         = shared.risk_level

    y = 40
    if fire_det:
        cv2.putText(display, f"FIRE: {fire_lbl}", (10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 100, 255), 2)
        y += 40
    if viol_lbl == "VIOLENCE":
        cv2.putText(display, "VIOLENCE DETECTED", (10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        y += 40
    if weapon_det:
        cv2.putText(display, f"WEAPON: {weapon_lbl} ({weapon_conf:.0%})", (10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        y += 40
    if traffic:
        cv2.putText(display, "TRAFFIC", (10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        y += 40
    elif acc_mem > 0:
        cv2.putText(display, "ACCIDENT DETECTED!", (10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

    h = display.shape[0]
    cv2.putText(display, f"RISK: {risk}", (10, h - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, _COLOR.get(risk, (255, 255, 255)), 2)

    return display

# ─────────────────────────────────────────
# CAMERA LOOP
# ─────────────────────────────────────────
def _open_video_source(source):
    """Open a local camera or network stream with a bounded network timeout."""
    import sys

    if isinstance(source, int):
        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        cap = cv2.VideoCapture(source, backend)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(source)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        return cap

    # OpenCV's FFmpeg backend understands RTSP/HTTP camera streams. Timeout
    # parameters prevent a dead network camera from holding the worker forever.
    open_timeout = getattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC", None)
    read_timeout = getattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC", None)
    params = []
    if open_timeout is not None:
        params.extend([open_timeout, 5000])
    if read_timeout is not None:
        params.extend([read_timeout, 5000])
    try:
        cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG, params) if params else cv2.VideoCapture(source, cv2.CAP_FFMPEG)
    except (TypeError, cv2.error):
        cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        cap.release()
        cap = cv2.VideoCapture(source)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def change_source(shared: SharedState, source, camera_id: str, name: str, kind: str, location: str = ""):
    """Ask the camera worker to switch on its next loop iteration."""
    with shared.lock:
        shared.source = source
        shared.camera_id = camera_id
        shared.camera_name = name
        shared.camera_kind = kind
        shared.camera_location = location
        shared.camera_status = "connecting"
        shared.camera_error = None
        shared.frame = None
        shared.annotated_frame = None
        shared.jpeg_bytes = None
        shared.fps = 0.0
        shared.risk_level = "LOW"
        shared.risk_score = 0.0
        shared.fire.update({"detected": False, "confidence": 0.0, "label": "SAFE", "event_status": "SAFE"})
        shared.violence.update({"detected": False, "confidence": 0.0, "label": "NOT VIOLENCE", "last_result": "NOT VIOLENCE"})
        shared.weapon.update({"detected": False, "confidence": 0.0, "label": "CLEAR", "detection_count": 0})
        shared.accident.update({"detected": False, "confidence": 0.0, "label": "NORMAL", "accident_memory": 0, "traffic": False})
        shared.source_generation += 1


def camera_loop(shared: SharedState, source=0):
    fps_counter = 0
    fps_timer = time.time()
    generation = -1
    cap = None
    retry_at = 0.0

    while shared.running:
        with shared.lock:
            requested_source = shared.source
            requested_generation = shared.source_generation

        if requested_generation != generation:
            if cap is not None:
                cap.release()
                cap = None
            generation = requested_generation
            retry_at = 0.0

        if cap is None:
            if time.time() < retry_at:
                time.sleep(0.15)
                continue
            try:
                cap = _open_video_source(requested_source)
            except Exception:
                cap = None
                with shared.lock:
                    if shared.source_generation == generation:
                        shared.camera_status = "disconnected"
                        shared.camera_error = "Stream could not open. Check the URL, credentials, and supported video format."
                        shared.frame = None
                        shared.annotated_frame = None
                        shared.jpeg_bytes = None
                retry_at = time.time() + 3.0
                continue
            if not cap.isOpened():
                cap.release()
                cap = None
                with shared.lock:
                    if shared.source_generation == generation:
                        shared.camera_status = "disconnected"
                        shared.camera_error = "Stream could not be opened. Check the camera URL, credentials, and network."
                        shared.frame = None
                        shared.annotated_frame = None
                        shared.jpeg_bytes = None
                retry_at = time.time() + 3.0
                continue
            print(f"📷 Camera source opened")

        ret, frame = cap.read()
        if not ret or frame is None:
            cap.release()
            cap = None
            with shared.lock:
                if shared.source_generation == generation:
                    shared.camera_status = "reconnecting"
                    shared.camera_error = "Stream stopped responding. Retrying…"
                    shared.frame = None
                    shared.annotated_frame = None
                    shared.jpeg_bytes = None
            retry_at = time.time() + 2.0
            continue

        fps_counter += 1
        now = time.time()
        with shared.lock:
            if shared.source_generation != generation:
                continue
            if now - fps_timer >= 1.0:
                shared.fps = fps_counter
                fps_counter = 0
                fps_timer = now
            shared.camera_status = "connected"
            shared.camera_error = None
            shared.frame = frame.copy()

        # Risk + annotated frame
        risk, score = compute_risk(shared)
        with shared.lock:
            if shared.source_generation != generation:
                continue
            shared.risk_level = risk
            shared.risk_score = score

        display = _build_annotated(frame, shared)

        ret2, buf = cv2.imencode('.jpg', display, [cv2.IMWRITE_JPEG_QUALITY, 82])
        if ret2:
            with shared.lock:
                if shared.source_generation == generation:
                    shared.jpeg_bytes = buf.tobytes()
                    shared.annotated_frame = display.copy()

    if cap is not None:
        cap.release()
    print("📷 Camera released")

# ─────────────────────────────────────────
# START
# ─────────────────────────────────────────
_state: SharedState = None

def start(source=0, camera_id="local-webcam-0", camera_name="Local webcam", camera_kind="webcam", camera_location="") -> SharedState:
    global _state
    _state = SharedState()
    _state.source = source
    _state.camera_id = camera_id
    _state.camera_name = camera_name
    _state.camera_kind = camera_kind
    _state.camera_location = camera_location

    threading.Thread(target=camera_loop,    args=(_state, source), daemon=True, name="cam").start()
    threading.Thread(target=fire_thread,    args=(_state,),         daemon=True, name="fire").start()
    threading.Thread(target=violence_thread,args=(_state,),         daemon=True, name="violence").start()
    threading.Thread(target=weapon_thread,  args=(_state,),         daemon=True, name="weapon").start()
    threading.Thread(target=accident_thread,args=(_state,),         daemon=True, name="accident").start()

    print("🚀 NovaGuard Detection Engine started — 5 threads running")
    return _state
