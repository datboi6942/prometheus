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
    result = mcp_tools.filesystem_delete(path)

    if "error" in result:
        status_code = 404 if "not found" in result["error"].lower() else 500
        raise HTTPException(status_code=status_code, detail=result["error"])

    return result


@router.get("/search")
async def search_files(
    query: str = Query(..., description="Search query (filename or content)"),
    path: str = Query(default="", description="Relative path to search within (empty for root)"),
    search_content: bool = Query(default=False, description="Search file contents in addition to filenames"),
    mcp_tools: Annotated[MCPTools, Depends(get_mcp_tools)] = None,
) -> dict:
    """Search for files in the workspace.

    Args:
        query (str): Search query (filename or content).
        path (str): Relative path to search within (empty for root).
        search_content (bool): Whether to search file contents.
        mcp_tools (MCPTools): Injected MCP tools instance.

    Returns:
        dict: Search results with matching files.
    """
    import os
    from pathlib import Path
    
    workspace_path = mcp_tools.workspace_path
    search_path = workspace_path / path if path else workspace_path
    search_path = search_path.resolve()
    
    # Validate search path is within workspace
    if not str(search_path).startswith(str(workspace_path)):
        raise HTTPException(status_code=400, detail="Search path is outside workspace")
    
    if not search_path.exists():
        raise HTTPException(status_code=404, detail="Search path does not exist")
    
    results = []
    query_lower = query.lower()
    
    # Recursively search files
    for root, dirs, files in os.walk(search_path):
        # Skip hidden directories
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        
        for file in files:
            # Skip hidden files
            if file.startswith('.'):
                continue
            
            file_path = Path(root) / file
            rel_path = file_path.relative_to(workspace_path)
            
            # Check filename match
            if query_lower in file.lower():
                results.append({
                    "path": str(rel_path),
                    "name": file,
                    "match_type": "filename"
                })
                continue
            
            # Check content match if enabled
            if search_content:
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        if query_lower in content.lower():
                            # Find line numbers with matches
                            lines = content.split('\n')
                            matching_lines = []
                            for i, line in enumerate(lines, 1):
                                if query_lower in line.lower():
                                    matching_lines.append({
                                        "line": i,
                                        "content": line.strip()[:100]  # First 100 chars
                                    })
                            
                            results.append({
                                "path": str(rel_path),
                                "name": file,
                                "match_type": "content",
                                "matches": matching_lines[:10]  # Limit to first 10 matches
                            })
                except Exception:
                    # Skip files that can't be read (binary, permissions, etc.)
                    pass
    
    return {
        "query": query,
        "results": results,
        "count": len(results)
    }
