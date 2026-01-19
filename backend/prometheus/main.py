from typing import Any

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from prometheus.config import settings, translate_host_path_to_container
from prometheus.database import init_db, get_mcp_servers
from prometheus.mcp.tools import MCPTools
from prometheus.routers import chat, conversations, files, git, health, mcp, permissions
from prometheus.services.mcp_loader import load_mcp_server_tools
from prometheus.services.tool_registry import get_registry

# Configure structlog
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

app = FastAPI(
    title="Prometheus API",
    description="Backend for the Prometheus AI Agent IDE",
    version="0.1.0",
    debug=settings.debug,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router)
app.include_router(chat.router)
app.include_router(files.router)
app.include_router(conversations.router)
app.include_router(git.router)
app.include_router(mcp.router)
app.include_router(permissions.router)


@app.on_event("startup")
async def startup_event() -> None:
    """Run startup tasks."""
    logger.info("Starting Prometheus API", log_level=settings.log_level)
    # Initialize database
    await init_db()
    logger.info("Database initialized")
    
    # Initialize tool registry with fallback tools
    registry = get_registry()
    
    # Register fallback filesystem tools (basic functionality)
    def create_fallback_handler(tool_method: str):
        def handler(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
            # Translate host paths to container paths (for Docker)
            raw_workspace_path = context.get("workspace_path", settings.workspace_path)
            workspace_path = translate_host_path_to_container(raw_workspace_path)
            logger.debug(
                "Tool workspace path",
                raw_path=raw_workspace_path,
                translated_path=workspace_path,
                tool=tool_method,
            )
            mcp_tools = MCPTools(workspace_path)
            method = getattr(mcp_tools, tool_method)
            return method(**args)
        return handler
    
    # Register basic filesystem tools as fallbacks
    fallback_tools = {
        "filesystem_read": ("Read file from workspace. Optional: offset (start line, 1-indexed), limit (number of lines)", {"path": {"type": "string"}, "offset": {"type": "integer", "optional": True}, "limit": {"type": "integer", "optional": True}}),
        "filesystem_write": ("Write content to a file (creates new or replaces entire file)", {"path": {"type": "string"}, "content": {"type": "string"}}),
        "filesystem_replace_lines": ("Replace specific line range in a file", {"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}, "replacement": {"type": "string"}}),
        "filesystem_search_replace": ("Search and replace text in a file", {"path": {"type": "string"}, "search": {"type": "string"}, "replace": {"type": "string"}, "count": {"type": "integer", "default": -1}}),
        "filesystem_insert": ("Insert content at a specific line in a file", {"path": {"type": "string"}, "line_number": {"type": "integer"}, "content": {"type": "string"}}),
        "filesystem_list": ("List directory contents", {"path": {"type": "string", "default": ""}}),
        "filesystem_delete": ("Delete a file or directory", {"path": {"type": "string"}}),
        "grep": ("Search for pattern in files (like Linux grep). Supports regex, recursive search, case-insensitive matching", {"pattern": {"type": "string"}, "path": {"type": "string", "default": ""}, "recursive": {"type": "boolean", "default": False}, "case_insensitive": {"type": "boolean", "default": False}, "files_only": {"type": "boolean", "default": False}, "context_lines": {"type": "integer", "default": 0}}),
    }
    
    for tool_name, (description, params) in fallback_tools.items():
        registry.register_fallback_tool(
            name=tool_name,
            handler=create_fallback_handler(tool_name),
            description=description,
            parameters=params,
        )
    
    # Register other fallback tools
    registry.register_fallback_tool(
        name="run_python",
        handler=create_fallback_handler("run_python"),
        description="Run a Python file with optional stdin input",
        parameters={
            "file_path": {"type": "string"},
            "stdin_input": {"type": "string", "default": ""},
            "args": {"type": "string", "default": ""},
        },
    )
    
    registry.register_fallback_tool(
        name="run_tests",
        handler=create_fallback_handler("run_tests"),
        description="Run pytest on test files",
        parameters={"test_path": {"type": "string", "default": ""}},
    )
    
    registry.register_fallback_tool(
        name="shell_execute",
        handler=create_fallback_handler("shell_execute"),
        description="Execute a shell command (non-interactive only)",
        parameters={"command": {"type": "string"}, "cwd": {"type": "string", "default": None}},
    )
    
    logger.info("Registered fallback tools", count=len(registry.get_tool_names()))
    
    # Load MCP servers from database
    mcp_servers = await get_mcp_servers()
    for server in mcp_servers:
        if server.get("enabled"):
            await load_mcp_server_tools(server["name"], server["config"])
    
    logger.info("Loaded MCP servers", count=len(mcp_servers))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
