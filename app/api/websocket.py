import json
import logging
from typing import Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.core.agent import agent

logger = logging.getLogger("maxi.ws")
router = APIRouter()


class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"Client connected to Maxi WebSocket ({len(self.active_connections)} active)")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info(f"Client disconnected from Maxi WebSocket ({len(self.active_connections)} active)")

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.active_connections.discard(connection)


ws_manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Bidirectional WebSocket for low-latency streaming between frontend/voice plugins and Maxi."""
    await ws_manager.connect(websocket)

    try:
        while True:
            raw_data = await websocket.receive_text()
            try:
                payload = json.loads(raw_data)
                prompt = payload.get("text") or payload.get("prompt")
                source = payload.get("source", "websocket")

                if not prompt:
                    await websocket.send_json({"error": "Missing 'text' or 'prompt' in payload"})
                    continue

                # Stream response
                await websocket.send_json({"event": "start", "source": source})
                async for chunk in agent.run_stream(prompt, source=source):
                    await websocket.send_json({"event": "chunk", "data": chunk})
                
                await websocket.send_json({"event": "done"})

            except json.JSONDecodeError:
                await websocket.send_json({"error": "Invalid JSON format"})
            except Exception as e:
                logger.error(f"Error handling WebSocket message: {e}")
                await websocket.send_json({"error": str(e)})

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
