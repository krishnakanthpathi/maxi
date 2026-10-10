import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from app.config import settings

logger = logging.getLogger("maxi.mcp")


class MCPClientManager:
    """Manages connections to MCP servers defined in max_mcp.json and provides LangChain tools."""

    def __init__(self):
        self._client: Optional[MultiServerMCPClient] = None
        self._tools: List[BaseTool] = []

    def _parse_config(self) -> Dict[str, Any]:
        """Reads MCP server configuration from .maxi/mcp_config.json or max_mcp.json."""
        config_path = settings.get_mcp_config_file()
        servers_def = {}

        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Support both standard {"mcpServers": {...}} and flat {...}
                    servers_def = data.get("mcpServers", data)
                logger.info(f"Loaded MCP server definitions from {config_path}")
            except Exception as e:
                logger.error(f"Error reading {config_path}: {e}")
        elif settings.mcp_servers:
            servers_def = settings.mcp_servers

        connections = {}
        for name, cfg in servers_def.items():
            if not isinstance(cfg, dict):
                continue

            if "command" in cfg:
                # Stdio transport
                import os
                server_env = dict(os.environ)
                if isinstance(cfg.get("env"), dict):
                    server_env.update(cfg["env"])
                home = str(Path.home())
                extra_paths = [
                    f"{home}/.local/bin",
                    f"{home}/.lightmem/bin",
                    "/opt/homebrew/bin",
                    "/opt/homebrew/sbin",
                    "/usr/local/bin",
                    "/Library/Frameworks/Python.framework/Versions/3.14/bin",
                    "/Library/Frameworks/Python.framework/Versions/3.12/bin",
                ]
                existing_path = server_env.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
                server_env["PATH"] = ":".join(extra_paths) + ":" + existing_path
                server_env["HOME"] = home

                connections[name] = {
                    "transport": "stdio",
                    "command": cfg["command"],
                    "args": cfg.get("args", []),
                    "env": server_env,
                }
            elif "url" in cfg:
                # SSE transport
                connections[name] = {
                    "transport": "sse",
                    "url": cfg["url"],
                }

        return connections

    async def connect_all(self):
        """Initializes MultiServerMCPClient from max_mcp.json and loads all tools."""
        connections = self._parse_config()
        if not connections:
            logger.warning("No MCP servers configured in max_mcp.json.")
            self._tools = []
            return

        logger.info(f"Connecting to {len(connections)} MCP servers: {list(connections.keys())}")
        try:
            self._client = MultiServerMCPClient(connections)
            self._tools = await self._client.get_tools()
            logger.info(f"Successfully loaded {len(self._tools)} MCP tools across all servers.")
        except Exception as e:
            logger.error(f"Failed to load tools from MCP servers: {e}")
            self._tools = []

    async def ensure_connected(self):
        """Ensures MCP client is connected and tools are loaded."""
        if self._client is None:
            await self.connect_all()

    def get_tools(self) -> List[BaseTool]:
        """Returns all aggregated LangChain-compatible tools."""
        return self._tools


mcp_manager = MCPClientManager()
