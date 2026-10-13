"""
NovaGuard Features
- Evidence Recorder (video + screenshots)
- Email Notifier (routed per type)
- PDF Report Generator (daily + per-incident)
"""

import os
import cv2
import json
import time
import smtplib
import datetime
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

# ─────────────────────────────────────────
# EMAIL CONFIG
# ─────────────────────────────────────────

EMAIL_SENDER = os.environ.get("NOVAGUARD_EMAIL_SENDER", "")
EMAIL_PASSWORD = os.environ.get("NOVAGUARD_EMAIL_PASSWORD", "")  # Set via environment variable

FIRE_EMAIL = os.environ.get("NOVAGUARD_FIRE_EMAIL", "")
ACCIDENT_EMAIL = os.environ.get("NOVAGUARD_ACCIDENT_EMAIL", "")
VIOLENCE_EMAIL = os.environ.get("NOVAGUARD_VIOLENCE_EMAIL", "")
WEAPON_EMAIL = os.environ.get("NOVAGUARD_WEAPON_EMAIL", "")

EMAIL_ROUTING = {
    "fire": FIRE_EMAIL,
    "violence": VIOLENCE_EMAIL,
    "weapon": WEAPON_EMAIL,
    "accident": ACCIDENT_EMAIL,
}

# ─────────────────────────────────────────
# EVIDENCE BASE FOLDER
# ─────────────────────────────────────────
EVIDENCE_BASE = "evidence"

# ─────────────────────────────────────────
# COOLDOWNS
# ─────────────────────────────────────────
_evidence_cooldown = {}
_email_cooldown = {}
EVIDENCE_COOLDOWN_SECS = 30
EMAIL_COOLDOWN_SECS = 60

_active_recordings = {}
_recordings_lock = threading.Lock()  # Thread-safe access to recordings

# ─────────────────────────────────────────
# INIT
# ─────────────────────────────────────────
def init():
    for t in ["FIRE", "VIOLENCE", "WEAPON", "ACCIDENT"]:
        os.makedirs(os.path.join(EVIDENCE_BASE, t), exist_ok=True)
    print("✅ Evidence folders ready")

# ─────────────────────────────────────────
# EVIDENCE RECORDER
# ─────────────────────────────────────────
def record_evidence(detection_type: str, frame, shared_state, all_results: dict):
    """
    Call every frame when risk is HIGH or CRITICAL.
    detection_type: "fire" | "violence" | "weapon" | "accident"
    """
    dtype = detection_type.upper()
    now = time.time()

    # Cooldown check
    last = _evidence_cooldown.get(dtype, 0)
    if now - last < EVIDENCE_COOLDOWN_SECS:
        return None

    _evidence_cooldown[dtype] = now

    # Create incident folder
    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    incident_id = f"{dtype}_{timestamp_str}"
    folder = os.path.join(EVIDENCE_BASE, dtype, incident_id)
    os.makedirs(folder, exist_ok=True)

    confidence = all_results.get(detection_type, {}).get("confidence", 0.0)
    risk_level = getattr(shared_state, 'risk_level', 'HIGH')
    risk_score = getattr(shared_state, 'risk_score', 0.0)

    # Save 3 screenshots
    screenshots = []
    for i in range(1, 4):
        path = os.path.join(folder, f"screenshot_{i}.jpg")
        cv2.imwrite(path, frame)
        screenshots.append(path)

    # Start video recording in background
    video_path = os.path.join(folder, "video_clip.mp4")
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    h, w = frame.shape[:2]
    writer = cv2.VideoWriter(video_path, fourcc, 20.0, (w, h))

    with _recordings_lock:
        _active_recordings[dtype] = {
            "writer": writer,
            "start": now,
            "folder": folder,
            "video_path": video_path,
            "duration": 10,
        }

    # Log
    log_data = {
        "incident_id": incident_id,
        "type": detection_type,
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "confidence": round(confidence, 4),
        "risk_level": risk_level,
        "risk_score": round(risk_score, 4),
        "other_triggers": [k for k, v in all_results.items()
                          if v.get("detected") and k != detection_type],
        "clip_duration": 10,
        "screenshots": 3,
        "alert_sent": False,
        "alert_sent_to": EMAIL_ROUTING.get(detection_type, ""),
    }

    log_path = os.path.join(folder, "incident_log.json")
    with open(log_path, "w") as f:
        json.dump(log_data, f, indent=2)

    # Auto-generate PDF
    pdf_path = generate_pdf(log_data, screenshots, folder)

    print(f"📁 Evidence saved: {incident_id}")

    return {
        "incident_id": incident_id,
        "folder": folder,
        "screenshots": screenshots,
        "video_path": video_path,
        "pdf_path": pdf_path,
        "log": log_data,
    }


def write_evidence_frame(frame):
    """Call every frame to append to any active video recordings."""
    now = time.time()
    to_remove = []

    with _recordings_lock:
        for dtype, rec in _active_recordings.items():
            rec["writer"].write(frame)
            if now - rec["start"] > rec["duration"]:
                rec["writer"].release()
                to_remove.append(dtype)
        for dtype in to_remove:
            del _active_recordings[dtype]


# ─────────────────────────────────────────
# EMAIL NOTIFIER
# ─────────────────────────────────────────
def send_email(detection_type: str, confidence: float, risk_level: str,
               screenshot_path: str = None):
    dtype = detection_type.upper()
    now = time.time()

    last = _email_cooldown.get(dtype, 0)
    if now - last < EMAIL_COOLDOWN_SECS:
        return False
    _email_cooldown[dtype] = now

    recipient = EMAIL_ROUTING.get(detection_type, "")
    if not recipient:
        return False

    if not EMAIL_PASSWORD or EMAIL_PASSWORD == "xxxx xxxx xxxx xxxx":
        print(f"⚠️  Email not sent ({dtype}): EMAIL_PASSWORD not configured")
        return False

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subject = f"🚨 NovaGuard ALERT: {dtype} DETECTED — {risk_level} RISK [{timestamp}]"

    descriptions = {
        "fire": "A fire hazard has been detected by the NovaGuard AI surveillance system.",
        "violence": "Violent activity has been detected by the NovaGuard AI surveillance system.",
        "weapon": "A weapon (knife or gun) has been detected by the NovaGuard AI surveillance system.",
        "accident": "A vehicle accident or collision has been detected by the NovaGuard AI surveillance system.",
    }

    body = f"""
NovaGuard — AI Surveillance Alert
──────────────────────────────────

TYPE       : {dtype}
RISK LEVEL : {risk_level}
CONFIDENCE : {confidence * 100:.1f}%
TIMESTAMP  : {timestamp}
CAMERA     : WEBCAM-01

DESCRIPTION:
{descriptions.get(detection_type, 'Threat detected.')}

Immediate attention may be required. Please review the attached screenshot and
check the evidence folder for full video footage and detailed incident logs.

──────────────────────────────────
This is an automated alert from NovaGuard.
Sent by: {EMAIL_SENDER}
"""

    msg = MIMEMultipart()
    msg["From"] = EMAIL_SENDER
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    # Attach screenshot
    if screenshot_path and os.path.exists(screenshot_path):
        with open(screenshot_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition",
                        f"attachment; filename=screenshot_{dtype}.jpg")
        msg.attach(part)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, recipient, msg.as_string())
        print(f"📧 Alert sent to {recipient} ({dtype})")
        return True
    except Exception as e:
        print(f"❌ Email failed ({dtype}): {e}")
        return False


# ─────────────────────────────────────────
# PDF REPORT GENERATOR
# ─────────────────────────────────────────
def generate_pdf(log_data: dict, screenshots: list, folder: str) -> str:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import cm
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                        Table, TableStyle, Image as RLImage,
                                        HRFlowable)
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
    except ImportError:
        print("⚠ reportlab not installed — skipping PDF")
        return ""

    pdf_path = os.path.join(folder, "report.pdf")
    doc = SimpleDocTemplate(pdf_path, pagesize=A4,
                            topMargin=1.5*cm, bottomMargin=1.5*cm,
                            leftMargin=2*cm, rightMargin=2*cm)

    styles = getSampleStyleSheet()

    DARK = colors.HexColor("#060a0f")
    ACCENT = colors.HexColor("#00d4ff")
    RED = colors.HexColor("#ff4444")
    ORANGE = colors.HexColor("#ff6600")
    YELLOW = colors.HexColor("#ffbb00")
    GREEN = colors.HexColor("#00ff88")
    PURPLE = colors.HexColor("#cc44ff")
    GREY = colors.HexColor("#4a6070")
    WHITE = colors.HexColor("#c8d8e8")

    risk_colors = {
        "LOW": GREEN, "MEDIUM": YELLOW, "HIGH": ORANGE, "CRITICAL": RED
    }
    type_colors = {
        "fire": ORANGE, "violence": RED, "weapon": PURPLE, "accident": YELLOW
    }

    risk_level = log_data.get("risk_level", "HIGH")
    dtype = log_data.get("type", "unknown")
    incident_id = log_data.get("incident_id", "N/A")
    timestamp_str = log_data.get("timestamp", "N/A")
    confidence = log_data.get("confidence", 0.0)
    risk_score = log_data.get("risk_score", 0.0)

    risk_color = risk_colors.get(risk_level, RED)
    type_color = type_colors.get(dtype, ACCENT)

    title_style = ParagraphStyle("title", fontSize=22, textColor=ACCENT,
                                 alignment=TA_CENTER, fontName="Helvetica-Bold",
                                 spaceAfter=4)
    sub_style = ParagraphStyle("sub", fontSize=10, textColor=GREY,
                               alignment=TA_CENTER, fontName="Helvetica",
                               spaceAfter=6)
    h2_style = ParagraphStyle("h2", fontSize=13, textColor=ACCENT,
                              fontName="Helvetica-Bold", spaceBefore=12,
                              spaceAfter=6)
    body_style = ParagraphStyle("body", fontSize=9, textColor=WHITE,
                                fontName="Helvetica", leading=14)
    footer_style = ParagraphStyle("footer", fontSize=8, textColor=GREY,
                                  alignment=TA_CENTER, fontName="Helvetica")

    story = []

    # Cover
    story.append(Paragraph("NOVAGUARD", title_style))
    story.append(Paragraph("OFFICIAL INCIDENT REPORT", sub_style))
    story.append(HRFlowable(width="100%", thickness=1, color=ACCENT))
    story.append(Spacer(1, 0.4*cm))

    # Risk badge table
    badge_data = [[Paragraph(f"● {risk_level} RISK",
                             ParagraphStyle("badge", fontSize=14,
                                            textColor=risk_color,
                                            fontName="Helvetica-Bold",
                                            alignment=TA_CENTER))]]
    badge_table = Table(badge_data, colWidths=[12*cm])
    badge_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#0b1118")),
        ("BOX", (0, 0), (-1, -1), 1.5, risk_color),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(badge_table)
    story.append(Spacer(1, 0.4*cm))

    # Incident details table
    info_data = [
        ["Incident ID", incident_id],
        ["Type", dtype.upper()],
        ["Timestamp", timestamp_str],
        ["Confidence", f"{confidence * 100:.1f}%"],
        ["Risk Score", f"{risk_score * 100:.0f} / 100"],
        ["Other Triggers", ", ".join(log_data.get("other_triggers", [])) or "None"],
        ["Alert Sent To", log_data.get("alert_sent_to", "N/A")],
    ]
    info_table = Table(info_data, colWidths=[4.5*cm, 10.5*cm])
    info_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#0b1118")),
        ("BACKGROUND", (1, 0), (1, -1), colors.HexColor("#060a0f")),
        ("TEXTCOLOR", (0, 0), (0, -1), ACCENT),
        ("TEXTCOLOR", (1, 0), (1, -1), WHITE),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, GREY),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 0.5*cm))

    # Detection summary
    story.append(Paragraph("DETECTION SUMMARY", h2_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GREY))
    story.append(Spacer(1, 0.2*cm))

    headers = [["Model", "Status", "Confidence"]]
    det_rows = [
        ["Fire", "DETECTED" if dtype == "fire" else "Not Found",
         f"{confidence*100:.0f}%" if dtype == "fire" else "0%"],
        ["Violence", "DETECTED" if dtype == "violence" else "Not Found",
         f"{confidence*100:.0f}%" if dtype == "violence" else "0%"],
        ["Weapon", "DETECTED" if dtype == "weapon" else "Not Found",
         f"{confidence*100:.0f}%" if dtype == "weapon" else "0%"],
        ["Accident", "DETECTED" if dtype == "accident" else "Not Found",
         f"{confidence*100:.0f}%" if dtype == "accident" else "0%"],
    ]
    det_table = Table(headers + det_rows, colWidths=[5*cm, 5*cm, 5*cm])
    det_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b1118")),
        ("TEXTCOLOR", (0, 0), (-1, 0), ACCENT),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, GREY),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]
    for row_i, row in enumerate(det_rows, 1):
        if row[1] == "DETECTED":
            det_style.append(("TEXTCOLOR", (1, row_i), (1, row_i), type_color))
            det_style.append(("FONTNAME", (1, row_i), (1, row_i), "Helvetica-Bold"))
    det_table.setStyle(TableStyle(det_style))
    story.append(det_table)
    story.append(Spacer(1, 0.5*cm))

    # Screenshots
    valid_shots = [p for p in screenshots if os.path.exists(p)]
    if valid_shots:
        story.append(Paragraph("EVIDENCE SCREENSHOTS", h2_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=GREY))
        story.append(Spacer(1, 0.2*cm))

        img_row = []
        for i, shot in enumerate(valid_shots[:3]):
            try:
                img = RLImage(shot, width=5*cm, height=3.5*cm)
                img_row.append(img)
            except Exception:
                img_row.append(Paragraph(f"[Screenshot {i+1}]", body_style))
        while len(img_row) < 3:
            img_row.append("")

        img_table = Table([img_row], colWidths=[5.2*cm, 5.2*cm, 5.2*cm])
        img_table.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.5, GREY),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, GREY),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(img_table)
        story.append(Spacer(1, 0.5*cm))

    # Incident log
    story.append(Paragraph("INCIDENT LOG", h2_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GREY))
    story.append(Spacer(1, 0.2*cm))

    log_lines = [
        f"Incident ID   : {incident_id}",
        f"Detection Type: {dtype.upper()}",
        f"Timestamp     : {timestamp_str}",
        f"Confidence    : {confidence * 100:.1f}%",
        f"Risk Level    : {risk_level}",
        f"Risk Score    : {risk_score * 100:.0f}/100",
        f"Evidence Path : {folder}",
        f"Video Clip    : video_clip.mp4 (10 seconds)",
        f"Screenshots   : 3 annotated frames saved",
        f"Alert Status  : Sent to {log_data.get('alert_sent_to', 'N/A')}",
        f"Other Threats : {', '.join(log_data.get('other_triggers', [])) or 'None'}",
    ]
    for line in log_lines:
        story.append(Paragraph(line, body_style))

    story.append(Spacer(1, 1.0*cm))
    story.append(HRFlowable(width="100%", thickness=1, color=GREY))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(
        "FOR OFFICIAL USE ONLY · NovaGuard AI Surveillance System · "
        f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        footer_style))

    doc.build(story)
    print(f"📄 PDF report saved: {pdf_path}")
    return pdf_path


# ─────────────────────────────────────────
# DAILY REPORT
# ─────────────────────────────────────────
def generate_daily_report() -> bytes:
    """Generate a daily summary PDF of all incidents today. Returns bytes."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import cm
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                        Table, TableStyle, HRFlowable)
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER
        from io import BytesIO
    except ImportError:
        return b""

    today = datetime.date.today().strftime("%Y%m%d")
    all_incidents = []

    for dtype in ["FIRE", "VIOLENCE", "WEAPON", "ACCIDENT"]:
        type_dir = os.path.join(EVIDENCE_BASE, dtype)
        if not os.path.exists(type_dir):
            continue
        for inc in os.listdir(type_dir):
            if not inc.startswith(dtype + "_" + today):
                continue
            log_path = os.path.join(type_dir, inc, "incident_log.json")
            if os.path.exists(log_path):
                with open(log_path) as f:
                    try:
                        all_incidents.append(json.load(f))
                    except Exception:
                        pass

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            topMargin=1.5*cm, bottomMargin=1.5*cm,
                            leftMargin=2*cm, rightMargin=2*cm)

    ACCENT = colors.HexColor("#00d4ff")
    GREY = colors.HexColor("#4a6070")
    WHITE = colors.HexColor("#c8d8e8")
    RED = colors.HexColor("#ff4444")

    title_style = ParagraphStyle("t", fontSize=20, textColor=ACCENT,
                                 alignment=TA_CENTER, fontName="Helvetica-Bold")
    sub_style = ParagraphStyle("s", fontSize=10, textColor=GREY,
                               alignment=TA_CENTER, fontName="Helvetica")
    h2_style = ParagraphStyle("h2", fontSize=12, textColor=ACCENT,
                              fontName="Helvetica-Bold", spaceBefore=12, spaceAfter=6)
    body_style = ParagraphStyle("b", fontSize=9, textColor=WHITE,
                                fontName="Helvetica", leading=14)

    story = []
    story.append(Paragraph("NOVAGUARD", title_style))
    story.append(Paragraph(f"DAILY INCIDENT REPORT — {datetime.date.today().strftime('%B %d, %Y')}",
                           sub_style))
    story.append(HRFlowable(width="100%", thickness=1, color=ACCENT))
    story.append(Spacer(1, 0.3*cm))

    # Summary counts
    counts = {"FIRE": 0, "VIOLENCE": 0, "WEAPON": 0, "ACCIDENT": 0}
    for inc in all_incidents:
        t = inc.get("type", "").upper()
        if t in counts:
            counts[t] += 1

    summary_data = [["Type", "Incidents"]] + [[k, str(v)] for k, v in counts.items()]
    summary_data.append(["TOTAL", str(len(all_incidents))])
    s_table = Table(summary_data, colWidths=[6*cm, 6*cm])
    s_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b1118")),
        ("TEXTCOLOR", (0, 0), (-1, 0), ACCENT),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, GREY),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, -1), (-1, -1), RED),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ]))
    story.append(s_table)
    story.append(Spacer(1, 0.4*cm))

    # All incidents
    story.append(Paragraph("ALL INCIDENTS TODAY", h2_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GREY))
    story.append(Spacer(1, 0.2*cm))

    if not all_incidents:
        story.append(Paragraph("No incidents recorded today.", body_style))
    else:
        rows = [["ID", "Type", "Time", "Confidence", "Risk"]]
        for inc in all_incidents:
            ts = inc.get("timestamp", "")
            time_only = ts.split(" ")[-1] if " " in ts else ts
            rows.append([
                inc.get("incident_id", "")[:20],
                inc.get("type", "").upper(),
                time_only,
                f"{inc.get('confidence', 0) * 100:.0f}%",
                inc.get("risk_level", ""),
            ])
        inc_table = Table(rows, colWidths=[5.5*cm, 2.5*cm, 2.5*cm, 2.5*cm, 3*cm])
        inc_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b1118")),
            ("TEXTCOLOR", (0, 0), (-1, 0), ACCENT),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, GREY),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.HexColor("#0b1118"), colors.HexColor("#060a0f")]),
            ("TEXTCOLOR", (0, 1), (-1, -1), WHITE),
        ]))
        story.append(inc_table)

    story.append(Spacer(1, 1*cm))
    footer_style = ParagraphStyle("f", fontSize=8, textColor=GREY,
                                  alignment=TA_CENTER, fontName="Helvetica")
    story.append(HRFlowable(width="100%", thickness=1, color=GREY))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(
        f"NovaGuard Daily Report · Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · FOR OFFICIAL USE ONLY",
        footer_style))

    doc.build(story)
    return buf.getvalue()


def get_all_incidents() -> list:
    """Return list of all incident log dicts across all types."""
    incidents = []
    for dtype in ["FIRE", "VIOLENCE", "WEAPON", "ACCIDENT"]:
        type_dir = os.path.join(EVIDENCE_BASE, dtype)
        if not os.path.exists(type_dir):
            continue
        for inc in sorted(os.listdir(type_dir), reverse=True):
            log_path = os.path.join(type_dir, inc, "incident_log.json")
            pdf_path = os.path.join(type_dir, inc, "report.pdf")
            if os.path.exists(log_path):
                with open(log_path) as f:
                    try:
                        data = json.load(f)
                        data["has_pdf"] = os.path.exists(pdf_path)
                        data["pdf_path"] = pdf_path if data["has_pdf"] else ""
                        incidents.append(data)
                    except Exception:
                        pass
    incidents.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return incidents


def get_incident_pdf_bytes(incident_id: str) -> bytes:
    """Return the PDF bytes for a given incident_id."""
    for dtype in ["FIRE", "VIOLENCE", "WEAPON", "ACCIDENT"]:
        pdf_path = os.path.join(EVIDENCE_BASE, dtype, incident_id, "report.pdf")
        if os.path.exists(pdf_path):
            with open(pdf_path, "rb") as f:
                return f.read()
    return b""
