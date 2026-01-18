"""API routes for command permission management."""
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from prometheus import database as db

router = APIRouter(prefix="/api/v1/permissions")


# Request models
class ApproveCommandRequest(BaseModel):
    """Request model for approving a command."""

    command: str
    approved: bool
    workspace_path: str | None = None
    notes: str | None = None


@router.get("/commands")
async def list_command_permissions(workspace_path: str | None = None) -> dict[str, Any]:
    """List all command permissions.

    Args:
        workspace_path: Optional workspace path to filter by.

    Returns:
        dict: List of command permissions.
    """
    permissions = await db.get_all_command_permissions(workspace_path)
    return {"permissions": permissions}


@router.post("/commands/approve")
async def approve_command(request: ApproveCommandRequest) -> dict[str, Any]:
    """Approve or deny a command.

    Args:
        request: Command approval request.

    Returns:
        dict: The created/updated permission.
    """
    permission = await db.add_command_permission(
        command=request.command,
        approved=request.approved,
        workspace_path=request.workspace_path,
        notes=request.notes,
    )
    return {"permission": permission}


@router.delete("/commands/{command}")
async def delete_command_permission(
    command: str,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    """Delete a command permission.

    Args:
        command: Command to delete permission for.
        workspace_path: Optional workspace path.

    Returns:
        dict: Success status.
    """
    await db.delete_command_permission(command, workspace_path)
    return {"success": True}


@router.get("/commands/{command}")
async def check_command_permission(
    command: str,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    """Check if a command is approved.

    Args:
        command: Command to check.
        workspace_path: Optional workspace path.

    Returns:
        dict: Permission status.
    """
    permission = await db.check_command_permission(command, workspace_path)
    if not permission:
        return {"approved": False, "command": command}
    
    return {
        "approved": bool(permission.get("approved")),
        "command": command,
        "permission": permission,
    }
