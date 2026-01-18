"""MCP server loader and tool discovery with dynamic command permissions."""
import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import structlog

from prometheus.services.tool_registry import get_registry

logger = structlog.get_logger()

# Dangerous environment variables that should never be set from user input
DANGEROUS_ENV_VARS = {
    "PATH",
    "LD_PRELOAD",
    "LD_LIBRARY_PATH",
    "PYTHONPATH",
    "NODE_PATH",
    "GOPATH",
    "RUST_BACKTRACE",
    "HOME",
    "USER",
    "SHELL",
    "TERM",
    "DISPLAY",
    "XAUTHORITY",
}


async def check_command_approved(cmd_list: list[str], workspace_path: str | None = None) -> tuple[bool, str]:
    """Check if a command has been approved by the user.
    
    Args:
        cmd_list: Command as list of strings.
        workspace_path: Optional workspace path for context.
        
    Returns:
        tuple: (is_approved, base_command)
    """
    if not cmd_list:
        return False, ""
    
    # Import here to avoid circular dependency
    from prometheus.database import check_command_permission
    
    # Get the base command (first element)
    base_cmd = Path(cmd_list[0]).name.lower()
    
    # Check if command is approved
    permission = await check_command_permission(base_cmd, workspace_path)
    
    if permission and permission.get("approved"):
        return True, base_cmd
    
    return False, base_cmd


def _sanitize_env_vars(user_env: dict[str, str]) -> dict[str, str]:
    """Sanitize environment variables from user input.
    
    Removes dangerous environment variables that could be used for injection.
    
    Args:
        user_env: User-provided environment variables.
        
    Returns:
        dict: Sanitized environment variables.
    """
    sanitized = {}
    for key, value in user_env.items():
        # Block dangerous environment variables
        if key.upper() in DANGEROUS_ENV_VARS:
            logger.warning("Blocked dangerous environment variable", key=key)
            continue
        
        # Validate key format (alphanumeric and underscore only)
        if not key.replace("_", "").isalnum():
            logger.warning("Invalid environment variable key format", key=key)
            continue
        
        sanitized[key] = value
    
    return sanitized


def _validate_working_directory(cwd: str | None, workspace_path: str | None = None) -> str | None:
    """Validate and normalize working directory path.
    
    Prevents directory traversal attacks by ensuring the path is within
    allowed boundaries.
    
    Args:
        cwd: User-provided working directory.
        workspace_path: Optional workspace path to use as base.
        
    Returns:
        str or None: Validated working directory path, or None if invalid.
    """
    if not cwd:
        return None
    
    try:
        # Resolve to absolute path
        cwd_path = Path(cwd).resolve()
        
        # If workspace_path is provided, ensure cwd is within it
        if workspace_path:
            workspace_path_obj = Path(workspace_path).resolve()
            try:
                # Check if cwd is within workspace
                cwd_path.relative_to(workspace_path_obj)
            except ValueError:
                logger.warning("Working directory outside workspace", cwd=str(cwd_path), workspace=str(workspace_path_obj))
                return None
        
        # Ensure the directory exists
        if not cwd_path.exists() or not cwd_path.is_dir():
            logger.warning("Working directory does not exist or is not a directory", cwd=str(cwd_path))
            return None
        
        return str(cwd_path)
    except Exception as e:
        logger.error("Error validating working directory", cwd=cwd, error=str(e))
        return None


async def load_mcp_server_tools(server_name: str, config: dict[str, Any]) -> None:
    """Load tools from an MCP server.

    Args:
        server_name: Server name.
        config: Server configuration with command, transport, env, etc.
    """
    registry = get_registry()
    
    try:
        transport = config.get("transport", "stdio")
        
        if transport == "stdio":
            # Handle stdio transport
            command = config.get("command")
            if not command:
                logger.warning("MCP server missing command", server=server_name)
                return
            
            # Normalize command to list
            if isinstance(command, str):
                cmd_list = [command]
            else:
                cmd_list = list(command)
            
            # Check if command is approved (dynamic permission system)
            is_approved, base_cmd = await check_command_approved(cmd_list, config.get("workspace_path"))
            if not is_approved:
                logger.warning(
                    "Command not approved by user",
                    server=server_name,
                    command=base_cmd,
                    message="This command needs user approval before it can be executed",
                )
                # Don't load tools if command not approved - they will need approval on first use
                # Continue loading but mark tools as requiring approval
                pass
            
            # Get environment variables and sanitize
            env = os.environ.copy()
            if "env" in config:
                sanitized_env = _sanitize_env_vars(config["env"])
                env.update(sanitized_env)
            
            # Get and validate working directory
            cwd = _validate_working_directory(config.get("cwd"), config.get("workspace_path"))
            
            # Discover tools by calling the MCP server
            # This is a simplified version - real MCP protocol is more complex
            # For now, we'll register tools based on config
            tools_config = config.get("tools", [])
            
            for tool_config in tools_config:
                tool_name = tool_config.get("name")
                if not tool_name:
                    continue
                    
                # Create handler that calls the MCP server
                async def create_mcp_handler(
                    tool_name: str, 
                    server_config: dict[str, Any],
                    cmd: list[str],
                    env_vars: dict[str, str],
                    work_dir: str | None
                ):
                    async def handler(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
                        # Execute MCP server command with tool call
                        # This is simplified - real MCP uses stdio protocol
                        try:
                            # Check command approval on each execution
                            is_approved, base_cmd = await check_command_approved(cmd, context.get("workspace_path"))
                            
                            if not is_approved:
                                # Return permission request - chat handler will prompt user
                                return {
                                    "permission_required": True,
                                    "command": base_cmd,
                                    "full_command": " ".join(cmd),
                                    "tool": tool_name,
                                    "message": f"Permission required to run command: {base_cmd}",
                                }
                            
                            # Re-validate working directory
                            validated_cwd = _validate_working_directory(work_dir, context.get("workspace_path"))
                            
                            # Add tool name and args
                            process = await asyncio.create_subprocess_exec(
                                *cmd,
                                "call",
                                tool_name,
                                json.dumps(args),
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE,
                                env=env_vars,
                                cwd=validated_cwd,
                            )
                            stdout, stderr = await process.communicate()
                            
                            if process.returncode == 0:
                                try:
                                    result = json.loads(stdout.decode())
                                    return result
                                except Exception:
                                    return {"success": True, "output": stdout.decode()}
                            else:
                                return {"error": stderr.decode()}
                        except Exception as e:
                            logger.error("MCP tool execution failed", tool=tool_name, error=str(e))
                            return {"error": str(e)}
                    
                    return handler
                
                handler = await create_mcp_handler(tool_name, config, cmd_list, env, cwd)
                
                registry.register_mcp_tool(
                    name=tool_name,
                    server_name=server_name,
                    description=tool_config.get("description", ""),
                    parameters=tool_config.get("parameters", {}),
                    handler=handler,
                )
                
            logger.info("Loaded MCP server tools", server=server_name, tools=len(tools_config))
            
        elif transport == "http":
            # Handle HTTP transport
            url = config.get("url")
            if not url:
                logger.warning("MCP server missing URL", server=server_name)
                return
            
            # Get per-server authentication config (optional)
            # Most local servers don't need auth, but remote ones might
            auth_config = config.get("auth", {})
            server_auth_type = auth_config.get("type")  # "api_key", "bearer", "basic", etc.
            server_auth_value = auth_config.get("value")  # The actual token/key
            server_auth_header_name = auth_config.get("header_name", "X-API-Key")  # For api_key type
            
            tools_config = config.get("tools", [])
            
            for tool_config in tools_config:
                tool_name = tool_config.get("name")
                if not tool_name:
                    continue
                
                # Create HTTP handler with per-server auth support
                # Capture auth config in closure properly by using captured_ prefix
                captured_tool_name = tool_name
                captured_auth_type = server_auth_type
                captured_auth_value = server_auth_value
                captured_auth_header_name = server_auth_header_name
                
                async def create_http_handler(
                    tool_name: str,
                    server_url: str,
                    auth_type: str | None = None,
                    auth_value: str | None = None,
                    auth_header_name: str = "X-API-Key",
                ):
                    async def handler(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
                        try:
                            # Build headers with per-server auth if configured
                            headers = {}
                            if auth_type and auth_value:
                                if auth_type == "api_key":
                                    # API key in header (configurable header name)
                                    headers[auth_header_name] = auth_value
                                elif auth_type == "bearer":
                                    headers["Authorization"] = f"Bearer {auth_value}"
                                elif auth_type == "basic":
                                    # Basic auth (username:password encoded)
                                    import base64
                                    encoded = base64.b64encode(auth_value.encode()).decode()
                                    headers["Authorization"] = f"Basic {encoded}"
                            
                            # Try to use httpx (FastAPI dependency) or fallback to requests
                            try:
                                import httpx
                                async with httpx.AsyncClient() as client:
                                    response = await client.post(
                                        f"{server_url}/tools/{tool_name}",
                                        json=args,
                                        headers=headers,
                                    )
                                    if response.status_code == 200:
                                        return response.json()
                                    else:
                                        return {"error": response.text}
                            except ImportError:
                                import requests
                                response = requests.post(
                                    f"{server_url}/tools/{tool_name}",
                                    json=args,
                                    headers=headers,
                                )
                                if response.status_code == 200:
                                    return response.json()
                                else:
                                    return {"error": response.text}
                        except Exception as e:
                            logger.error("MCP HTTP tool execution failed", tool=tool_name, error=str(e))
                            return {"error": str(e)}
                    
                    return handler
                
                handler = await create_http_handler(
                    captured_tool_name, url, captured_auth_type, captured_auth_value, captured_auth_header_name
                )
                
                registry.register_mcp_tool(
                    name=tool_name,
                    server_name=server_name,
                    description=tool_config.get("description", ""),
                    parameters=tool_config.get("parameters", {}),
                    handler=handler,
                )
            
            logger.info("Loaded MCP server tools (HTTP)", server=server_name, tools=len(tools_config))
            
        else:
            logger.warning("Unsupported transport type", server=server_name, transport=transport)
            
    except Exception as e:
        logger.error("Failed to load MCP server", server=server_name, error=str(e))
