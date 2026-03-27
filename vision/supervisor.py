"""
Launch and monitor live detector workers for configured cameras.

This turns the detector into an automatic live service:
active camera with stream_url -> detector process -> backend alerts.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Camera, CameraStatus


logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("vision.supervisor")


@dataclass
class Worker:
    camera_id: str
    stream_url: str
    process: asyncio.subprocess.Process


class Supervisor:
    def __init__(self, api_base: str = "http://127.0.0.1:8000", poll_seconds: int = 15):
        self.api_base = api_base
        self.poll_seconds = poll_seconds
        self.workers: Dict[str, Worker] = {}
        self.detector_script = Path(__file__).with_name("detector.py")

    async def run(self):
        while True:
            await self._sync_workers()
            await asyncio.sleep(self.poll_seconds)

    async def _sync_workers(self):
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Camera).where(
                    Camera.status == CameraStatus.active,
                    Camera.stream_url.is_not(None),
                )
            )
            cameras = result.scalars().all()

        active_ids = {camera.id for camera in cameras}

        for camera in cameras:
            if camera.id in self.workers and self.workers[camera.id].process.returncode is None:
                continue
            await self._start_worker(camera.id, camera.stream_url)

        for camera_id in list(self.workers.keys()):
            worker = self.workers[camera_id]
            if camera_id not in active_ids:
                await self._stop_worker(worker)
                del self.workers[camera_id]
            elif worker.process.returncode is not None:
                log.warning("Detector exited for camera %s, restarting", camera_id)
                del self.workers[camera_id]

    async def _start_worker(self, camera_id: str, stream_url: str):
        log.info("Starting detector for camera %s", camera_id)
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(self.detector_script),
            "--camera-id",
            camera_id,
            "--source",
            stream_url,
            "--api",
            self.api_base,
            "--fps",
            "5",
            "--threshold",
            "0.65",
            "--confirm-frames",
            "3",
            "--cooldown",
            "30",
        )
        self.workers[camera_id] = Worker(camera_id=camera_id, stream_url=stream_url, process=proc)

    async def _stop_worker(self, worker: Worker):
        if worker.process.returncode is not None:
            return
        log.info("Stopping detector for camera %s", worker.camera_id)
        worker.process.terminate()
        try:
            await asyncio.wait_for(worker.process.wait(), timeout=5)
        except asyncio.TimeoutError:
            worker.process.kill()


if __name__ == "__main__":
    supervisor = Supervisor()
    asyncio.run(supervisor.run())
