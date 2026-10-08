import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.core.agent import agent

logger = logging.getLogger("maxi.ws")
router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Bidirectional WebSocket for low-latency streaming between frontend/voice plugins and Maxi."""
    await websocket.accept()
    logger.info("Client connected to Maxi WebSocket")

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
        logger.info("Client disconnected from Max WebSocket")
