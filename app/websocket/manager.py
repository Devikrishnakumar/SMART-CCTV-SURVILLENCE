import json
import logging
from typing import Dict, Set
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        # Maps client_id -> WebSocket
        self._active: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self._active[client_id] = websocket
        logger.info(f"WebSocket connected: {client_id}. Total: {len(self._active)}")

    def disconnect(self, client_id: str):
        self._active.pop(client_id, None)
        logger.info(f"WebSocket disconnected: {client_id}. Total: {len(self._active)}")

    async def send_personal(self, message: dict, client_id: str):
        ws = self._active.get(client_id)
        if ws:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send to {client_id}: {e}")
                self.disconnect(client_id)

    async def broadcast(self, message: dict):
        disconnected = []
        for client_id, ws in list(self._active.items()):
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.warning(f"Broadcast failed for {client_id}: {e}")
                disconnected.append(client_id)
        for cid in disconnected:
            self.disconnect(cid)

    @property
    def active_connections(self) -> int:
        return len(self._active)


# Singleton instance shared across the app
manager = ConnectionManager()
