import asyncio
from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.routes import router as api_router
from app.api.websocket import router as ws_router
from app.core.mcp_client import mcp_manager
from app.core.voice_service import voice_service

logging.basicConfig(
    level=logging.INFO if not settings.debug else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("maxi.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Connect to configured MCP servers
    logger.info("Initializing Maxi daemon and MCP tool connections...")
    await mcp_manager.connect_all()

    # Start embedded voice push-to-talk listener (Control + Space) if enabled
    loop = asyncio.get_running_loop()
    voice_service.start(loop=loop)

    yield

    # Shutdown
    logger.info("Shutting down Maxi daemon...")
    voice_service.stop()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Cross-platform background AI agent daemon with MCP tools and voice plugins",
    lifespan=lifespan
)

# Allow local desktop frontends (e.g. Tauri, local browser HUD)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from pathlib import Path
from fastapi.responses import HTMLResponse, FileResponse

# Register routes
app.include_router(api_router, prefix="/api")
app.include_router(ws_router)


@app.get("/favicon.ico")
@app.get("/favicon.svg")
async def serve_favicon():
    candidates = [
        Path(__file__).resolve().parent / "web" / "icons" / "favicon.svg",
        Path(__file__).resolve().parent.parent / "frontends" / "web" / "icons" / "favicon.svg",
    ]
    for p in candidates:
        if p.exists():
            return FileResponse(p, media_type="image/svg+xml")
    return HTMLResponse("")


@app.get("/icons/maxi-icon.svg")
async def serve_icon():
    candidates = [
        Path(__file__).resolve().parent / "web" / "icons" / "maxi-icon.svg",
        Path(__file__).resolve().parent.parent / "frontends" / "web" / "icons" / "maxi-icon.svg",
    ]
    for p in candidates:
        if p.exists():
            return FileResponse(p, media_type="image/svg+xml")
    return HTMLResponse("")


@app.get("/", response_class=HTMLResponse)
@app.get("/hud", response_class=HTMLResponse)
async def serve_hud():
    """Serves the modern Siri-style desktop HUD frontend."""
    candidates = [
        Path(__file__).resolve().parent.parent / "frontends" / "web" / "index.html",
        Path(__file__).resolve().parent / "web" / "index.html"
    ]
    for p in candidates:
        if p.exists():
            return FileResponse(p)
    return HTMLResponse("<h1>Maxi Daemon Live</h1>")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)
