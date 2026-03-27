"""
vision/reporter.py
==================
Standalone reporter — send a test detection to the backend
without running the full YOLO inference loop.

Usage:
  python3 vision/reporter.py \\
    --camera-id <uuid> \\
    --type accident \\
    --confidence 0.91 \\
    --api http://localhost:8000
"""

import argparse
import asyncio
import httpx
import logging

log = logging.getLogger("vision.reporter")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

INCIDENT_TYPES = ["accident", "violence", "fallen_person", "fire"]


async def send_report(api: str, camera_id: str, incident_type: str, confidence: float):
    payload = {
        "type":       incident_type,
        "confidence": confidence,
        "camera_id":  camera_id,
    }
    log.info(f"Sending report: {payload}")
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.post(f"{api.rstrip('/')}/ai/report", json=payload)
    log.info(f"Response [{r.status_code}]: {r.json()}")


def parse_args():
    p = argparse.ArgumentParser(description="Test reporter — send a single detection to backend")
    p.add_argument("--camera-id",  required=True)
    p.add_argument("--type",       required=True, choices=INCIDENT_TYPES)
    p.add_argument("--confidence", type=float, default=0.87)
    p.add_argument("--api",        default="http://localhost:8000")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(send_report(args.api, args.camera_id, args.type, args.confidence))
