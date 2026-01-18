from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from prometheus.config import settings
from prometheus.mcp.tools import MCPTools

router = APIRouter(prefix="/api/v1/files")


class FileContentRequest(BaseModel):
    """Request model for writing file content."""

    path: str
    content: str


class DeleteFileRequest(BaseModel):
    """Request model for deleting a file."""

    path: str


def get_mcp_tools() -> MCPTools:
    """Dependency provider for MCPTools.

    Returns:
        MCPTools: An instance of MCPTools.
    """
    return MCPTools(settings.workspace_path)


@router.get("/list")
async def list_directory(
    path: str = Query(default="", description="Relative path within workspace"),
    mcp_tools: Annotated[MCPTools, Depends(get_mcp_tools)] = None,
) -> dict:
    """List contents of a directory in the workspace.

    Args:
        path (str): Relative path within workspace (empty for root).
        mcp_tools (MCPTools): Injected MCP tools instance.

    Returns:
        dict: Directory listing with files and subdirectories.

    Raises:
        HTTPException: If directory listing fails.
    """
    result = mcp_tools.filesystem_list(path)

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return result


@router.get("/content")
async def read_file(
    path: str = Query(..., description="Relative path to file within workspace"),
    mcp_tools: Annotated[MCPTools, Depends(get_mcp_tools)] = None,
) -> dict:
    """Read content of a file in the workspace.

    Args:
        path (str): Relative path to file within workspace.
        mcp_tools (MCPTools): Injected MCP tools instance.

    Returns:
        dict: File content and metadata.

    Raises:
        HTTPException: If file reading fails.
    """
    result = mcp_tools.filesystem_read(path)

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return result


@router.put("/content")
async def write_file(
    request: FileContentRequest,
    mcp_tools: Annotated[MCPTools, Depends(get_mcp_tools)] = None,
) -> dict:
    """Write content to a file in the workspace.

    Args:
        request (FileContentRequest): File path and content to write.
        mcp_tools (MCPTools): Injected MCP tools instance.

    Returns:
        dict: Operation result.

    Raises:
        HTTPException: If file writing fails.
    """
    result = mcp_tools.filesystem_write(request.path, request.content)

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    return result


@router.delete("/")
async def delete_file(
    path: str = Query(..., description="Relative path to file within workspace"),
    mcp_tools: Annotated[MCPTools, Depends(get_mcp_tools)] = None,
) -> dict:
    """Delete a file in the workspace.

    Args:
        path (str): Relative path to file within workspace.
        mcp_tools (MCPTools): Injected MCP tools instance.

    Returns:
        dict: Operation result.

    Raises:
        HTTPException: If file deletion fails.
    """
    try:
        from pathlib import Path

        full_path = mcp_tools._validate_path(path)

        if not full_path.exists():
            raise HTTPException(status_code=404, detail=f"File not found: {path}")

        if full_path.is_dir():
            full_path.rmdir()
        else:
            full_path.unlink()

        return {"success": True, "path": path, "action": "deleted"}

    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
