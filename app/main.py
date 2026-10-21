import asyncio
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app import __version__
from app.api.routes import router as api_router
from app.api.websocket import router as ws_router
from app.core.mcp_client import mcp_manager
from app.core.voice_service import voice_service

_log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_log_level = logging.INFO if not settings.debug else logging.DEBUG
_handlers: list[logging.Handler] = [logging.StreamHandler()]

if not os.environ.get("MAXI_DAEMON_REDIRECTED"):
    try:
        _log_file = Path.home() / ".maxi" / "daemon.log"
        _log_file.parent.mkdir(parents=True, exist_ok=True)
        _handlers.append(logging.FileHandler(_log_file, encoding="utf-8"))
    except Exception:
        pass

logging.basicConfig(
    level=_log_level,
    format=_log_format,
    handlers=_handlers,
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
    version=__version__,
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

# Register routes
app.include_router(api_router, prefix="/api")
app.include_router(ws_router)


@app.get("/")
async def root():
    return {"status": "ok", "service": settings.app_name, "version": __version__}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)
