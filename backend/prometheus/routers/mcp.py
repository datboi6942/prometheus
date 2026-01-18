"""API routes for MCP server management."""
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from prometheus import database as db
from prometheus.services.mcp_loader import load_mcp_server_tools
from prometheus.services.tool_registry import get_registry

router = APIRouter(prefix="/api/v1/mcp")


# Request models
class CreateMCPServerRequest(BaseModel):
    """Request model for creating an MCP server."""

    name: str
    config: dict[str, Any]
    enabled: bool = True


class UpdateMCPServerRequest(BaseModel):
    """Request model for updating an MCP server."""

    config: dict[str, Any]
    enabled: bool = True


@router.get("/servers")
async def list_mcp_servers() -> dict[str, Any]:
    """List all MCP servers.

    Returns:
        dict: List of MCP servers.
    """
    servers = await db.get_mcp_servers()
    return {"servers": servers}


@router.get("/servers/{name}")
async def get_mcp_server(name: str) -> dict[str, Any]:
    """Get an MCP server by name.

    Args:
        name: Server name.

    Returns:
        dict: Server configuration.

    Raises:
        HTTPException: If server not found.
    """
    server = await db.get_mcp_server(name)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return {"server": server}


@router.post("/servers")
async def create_mcp_server(request: CreateMCPServerRequest) -> dict[str, Any]:
    """Create a new MCP server.

    Args:
        request: Server configuration.

    Returns:
        dict: Created server.
    """
    server = await db.add_mcp_server(request.name, request.config)
    
    # Load tools from the server
    if request.enabled:
        await load_mcp_server_tools(request.name, request.config)
    
    return {"server": server}


@router.put("/servers/{name}")
async def update_mcp_server(name: str, request: UpdateMCPServerRequest) -> dict[str, Any]:
    """Update an MCP server.

    Args:
        name: Server name.
        request: Updated configuration.

    Returns:
        dict: Success status.
    """
    await db.update_mcp_server(name, request.config, request.enabled)
    
    # Reload tools if enabled
    if request.enabled:
        await load_mcp_server_tools(name, request.config)
    else:
        # Remove tools if disabled
        registry = get_registry()
        registry.remove_mcp_server(name)
    
    return {"success": True}


@router.delete("/servers/{name}")
async def delete_mcp_server(name: str) -> dict[str, Any]:
    """Delete an MCP server.

    Args:
        name: Server name.

    Returns:
        dict: Success status.
    """
    await db.delete_mcp_server(name)
    
    # Remove from registry
    registry = get_registry()
    registry.remove_mcp_server(name)
    
    return {"success": True}


@router.get("/tools")
async def list_tools() -> dict[str, Any]:
    """List all available tools.

    Returns:
        dict: List of tools.
    """
    registry = get_registry()
    tools = registry.get_all_tools()
    return {"tools": tools}


@router.post("/servers/{name}/reload")
async def reload_mcp_server(name: str) -> dict[str, Any]:
    """Reload tools from an MCP server.

    Args:
        name: Server name.

    Returns:
        dict: Success status.
    """
    server = await db.get_mcp_server(name)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    
    if server.get("enabled"):
        await load_mcp_server_tools(name, server["config"])
    
    return {"success": True}
