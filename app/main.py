from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.routes import router as api_router
from app.api.websocket import router as ws_router
from app.core.mcp_client import mcp_manager

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
    yield
    # Shutdown
    logger.info("Shutting down Maxi daemon...")


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

# Register routes
app.include_router(api_router, prefix="/api")
app.include_router(ws_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)
