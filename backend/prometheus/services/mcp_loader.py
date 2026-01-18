"""MCP server loader and tool discovery."""
import asyncio
import json
import os
import subprocess
from typing import Any

import structlog

from prometheus.services.tool_registry import get_registry

logger = structlog.get_logger()


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
            
            # Get environment variables
            env = os.environ.copy()
            if "env" in config:
                env.update(config["env"])
            
            # Get working directory
            cwd = config.get("cwd")
            
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
                            # Add tool name and args
                            process = await asyncio.create_subprocess_exec(
                                *cmd,
                                "call",
                                tool_name,
                                json.dumps(args),
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE,
                                env=env_vars,
                                cwd=work_dir,
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
            
            tools_config = config.get("tools", [])
            
            for tool_config in tools_config:
                tool_name = tool_config.get("name")
                if not tool_name:
                    continue
                
                # Create HTTP handler
                async def create_http_handler(tool_name: str, server_url: str):
                    async def handler(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
                        try:
                            # Try to use httpx (FastAPI dependency) or fallback to requests
                            try:
                                import httpx
                                async with httpx.AsyncClient() as client:
                                    response = await client.post(
                                        f"{server_url}/tools/{tool_name}",
                                        json=args,
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
                                )
                                if response.status_code == 200:
                                    return response.json()
                                else:
                                    return {"error": response.text}
                        except Exception as e:
                            logger.error("MCP HTTP tool execution failed", tool=tool_name, error=str(e))
                            return {"error": str(e)}
                    
                    return handler
                
                handler = await create_http_handler(tool_name, url)
                
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
