from typing import Any

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from prometheus.config import settings, translate_host_path_to_container
from prometheus.database import init_db, get_mcp_servers
from prometheus.mcp.tools import MCPTools
from prometheus.routers import chat, conversations, files, git, health, mcp, permissions, index
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
app.include_router(index.router)


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
            # Handle special tools that use session services
            if tool_method == "todo_write":
                if "todo_tracker" in context:
                    return context["todo_tracker"].write_todos(args["todos"])
            elif tool_method == "todo_update":
                if "todo_tracker" in context:
                    return context["todo_tracker"].update_todo(args["todo_id"], args["status"])

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
    # Tool descriptions are ACTION-ORIENTED to guide agent behavior
    fallback_tools = {
        # ===== TIER 1: USE THESE FIRST =====
        "codebase_search": (
            "🔍 SEMANTIC SEARCH - USE THIS FIRST! Find code by meaning/intent across the entire codebase. "
            "Much faster than reading multiple files. Query examples: 'where is authentication handled', 'function that validates emails'",
            {"query": {"type": "string", "description": "Natural language query"}, "limit": {"type": "integer", "default": 10}}
        ),
        "read_diagnostics": (
            "🔴 LINTER CHECK - USE AFTER EVERY EDIT! Returns syntax errors, type errors, and warnings. "
            "MANDATORY after any file modification. Catches bugs immediately.",
            {"path": {"type": "string", "description": "File path to check"}}
        ),
        "filesystem_read": (
            "Read file contents with line numbers for editing. Use codebase_search first if you don't know which file.",
            {"path": {"type": "string"}, "offset": {"type": "integer", "optional": True, "description": "Start line (1-indexed)"}, "limit": {"type": "integer", "optional": True, "description": "Number of lines"}}
        ),
        # ===== TIER 2: EDIT TOOLS =====
        "filesystem_replace_lines": (
            "✏️ SURGICAL EDIT - PREFERRED for modifying existing files. Replace specific line range with new content.",
            {"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}, "replacement": {"type": "string"}}
        ),
        "filesystem_search_replace": (
            "Find and replace exact text in a file. Good for renaming variables or fixing patterns.",
            {"path": {"type": "string"}, "search": {"type": "string"}, "replace": {"type": "string"}, "count": {"type": "integer", "default": -1}}
        ),
        "filesystem_insert": (
            "Insert content at a specific line (before that line number).",
            {"path": {"type": "string"}, "line_number": {"type": "integer"}, "content": {"type": "string"}}
        ),
        "filesystem_write": (
            "Write/overwrite entire file. Use filesystem_replace_lines for edits to existing files.",
            {"path": {"type": "string"}, "content": {"type": "string"}}
        ),
        "filesystem_delete": (
            "Delete a file or empty directory.",
            {"path": {"type": "string"}}
        ),
        # ===== TIER 3: NAVIGATION =====
        "filesystem_list": (
            "List directory contents. Use codebase_search instead if looking for specific code.",
            {"path": {"type": "string", "default": ""}}
        ),
        "grep": (
            "Regex search in files. Use codebase_search for semantic/meaning search instead.",
            {"pattern": {"type": "string"}, "path": {"type": "string", "default": ""}, "recursive": {"type": "boolean", "default": False}, "case_insensitive": {"type": "boolean", "default": False}, "files_only": {"type": "boolean", "default": False}, "context_lines": {"type": "integer", "default": 0}}
        ),
        "glob_search": (
            "Find files matching glob pattern (e.g., **/*.py).",
            {"pattern": {"type": "string"}, "path": {"type": "string", "default": ""}}
        ),
        # ===== TIER 4: VERIFICATION =====
        "verify_changes": (
            "🔒 MULTI-CHECK - Run lint, test, import checks at once. Use before reporting completion.",
            {"verification_steps": {"type": "array", "items": {"type": "string"}, "description": "Format: 'lint:path', 'test:path', 'run:cmd', 'import:module'"}}
        ),
        # ===== TIER 5: TASK MANAGEMENT =====
        "todo_write": (
            "📋 TASK LIST - Create/update task list for complex tasks (3+ steps).",
            {"todos": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"}, "content": {"type": "string"}, "status": {"type": "string"}}}}}
        ),
        "todo_update": (
            "Update status of a specific todo item.",
            {"todo_id": {"type": "string"}, "status": {"type": "string"}}
        ),
        "checkpoint_create": (
            "📸 SNAPSHOT - Create checkpoint before risky changes for easy rollback.",
            {"paths": {"type": "array", "items": {"type": "string"}}, "description": {"type": "string", "default": ""}}
        ),
        "checkpoint_restore": (
            "Restore files from a previous checkpoint.",
            {"checkpoint_id": {"type": "string"}}
        ),
        "checkpoint_list": (
            "List recent checkpoints.",
            {"limit": {"type": "integer", "default": 10}}
        ),
        # ===== TIER 6: WEB =====
        "web_fetch": (
            "Fetch content from a URL (docs, API specs).",
            {"url": {"type": "string"}}
        ),
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
