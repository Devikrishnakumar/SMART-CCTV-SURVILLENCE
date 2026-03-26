import uuid
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from jose import JWTError
from app.auth.security import decode_token
from app.websocket.manager import manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


@router.websocket("/ws/alerts")
async def websocket_alerts(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token for authentication"),
):
    """
    WebSocket endpoint for real-time incident alerts.
    Connect with: ws://host/ws/alerts?token=<jwt>
    """
    # Authenticate via token query param
    try:
        payload = decode_token(token)
        user_id = payload.get("sub")
        if not user_id:
            await websocket.close(code=4001, reason="Invalid token")
            return
    except JWTError:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    client_id = f"{user_id}:{uuid.uuid4().hex[:8]}"
    await manager.connect(websocket, client_id)

    try:
        await websocket.send_json({
            "event": "connected",
            "client_id": client_id,
            "message": "Connected to emergency alert stream",
            "active_connections": manager.active_connections,
        })

        # Keep connection alive, handle ping/pong
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"event": "pong"})

    except WebSocketDisconnect:
        manager.disconnect(client_id)
        logger.info(f"Client {client_id} disconnected")
    except Exception as e:
        logger.error(f"WebSocket error for {client_id}: {e}")
        manager.disconnect(client_id)
