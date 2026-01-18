from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from prometheus.config import settings, translate_host_path_to_container
from prometheus.mcp.tools import MCPTools

router = APIRouter(prefix="/api/v1/files")


class FileContentRequest(BaseModel):
    """Request model for writing file content."""

    path: str
    content: str


class DeleteFileRequest(BaseModel):
    """Request model for deleting a file."""

    path: str


def get_mcp_tools(workspace_path: str | None = None) -> MCPTools:
    """Dependency provider for MCPTools.

    Args:
        workspace_path: Optional workspace path (will be translated for Docker).

    Returns:
        MCPTools: An instance of MCPTools.
    """
    raw_path = workspace_path or settings.workspace_path
    # Translate host paths to container paths (for Docker)
    translated_path = translate_host_path_to_container(raw_path)
    return MCPTools(translated_path)


@router.get("/list")
async def list_directory(
    path: str = Query(default="", description="Relative path within workspace"),
    workspace_path: str | None = Query(default=None, description="Workspace path (for Docker translation)"),
) -> dict:
    """List contents of a directory in the workspace.

    Args:
        path (str): Relative path within workspace (empty for root).
        workspace_path (str | None): Optional workspace path for Docker translation.

    Returns:
        dict: Directory listing with files and subdirectories.

    Raises:
        HTTPException: If directory listing fails.
    """
    mcp_tools = get_mcp_tools(workspace_path)
    result = mcp_tools.filesystem_list(path)

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return result


@router.get("/content")
async def read_file(
    path: str = Query(..., description="Relative path to file within workspace"),
    workspace_path: str | None = Query(default=None, description="Workspace path (for Docker translation)"),
) -> dict:
    """Read content of a file in the workspace.

    Args:
        path (str): Relative path to file within workspace.
        workspace_path (str | None): Optional workspace path for Docker translation.

    Returns:
        dict: File content and metadata.

    Raises:
        HTTPException: If file reading fails.
    """
    mcp_tools = get_mcp_tools(workspace_path)
    result = mcp_tools.filesystem_read(path)

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return result


class FileContentWriteRequest(BaseModel):
    """Request model for writing file content with optional workspace."""

    path: str
    content: str
    workspace_path: str | None = None


@router.put("/content")
async def write_file(
    request: FileContentWriteRequest,
) -> dict:
    """Write content to a file in the workspace.

    Args:
        request (FileContentWriteRequest): File path, content, and optional workspace.

    Returns:
        dict: Operation result.

    Raises:
        HTTPException: If file writing fails.
    """
    mcp_tools = get_mcp_tools(request.workspace_path)
    result = mcp_tools.filesystem_write(request.path, request.content)

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    return result


@router.delete("/")
async def delete_file(
    path: str = Query(..., description="Relative path to file within workspace"),
    workspace_path: str | None = Query(default=None, description="Workspace path (for Docker translation)"),
) -> dict:
    """Delete a file in the workspace.

    Args:
        path (str): Relative path to file within workspace.
        workspace_path (str | None): Optional workspace path for Docker translation.

    Returns:
        dict: Operation result.

    Raises:
        HTTPException: If file deletion fails.
    """
    mcp_tools = get_mcp_tools(workspace_path)
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
    workspace_path: str | None = Query(default=None, description="Workspace path (for Docker translation)"),
) -> dict:
    """Search for files in the workspace.

    Args:
        query (str): Search query (filename or content).
        path (str): Relative path to search within (empty for root).
        search_content (bool): Whether to search file contents.
        workspace_path (str | None): Optional workspace path for Docker translation.

    Returns:
        dict: Search results with matching files.
    """
    import os
    from pathlib import Path
    
    mcp_tools = get_mcp_tools(workspace_path)
    ws_path = mcp_tools.workspace_path
    search_path = ws_path / path if path else ws_path
    search_path = search_path.resolve()
    
    # Validate search path is within workspace
    if not str(search_path).startswith(str(ws_path)):
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
            rel_path = file_path.relative_to(ws_path)
            
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
