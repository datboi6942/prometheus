"""API routes for conversations and rules management."""
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from prometheus import database as db

router = APIRouter(prefix="/api/v1")


# Request/Response models
class CreateConversationRequest(BaseModel):
    """Request model for creating a conversation."""

    title: str
    workspace_path: str
    model: str


class AddMessageRequest(BaseModel):
    """Request model for adding a message."""

    role: str
    content: str


class CreateRuleRequest(BaseModel):
    """Request model for creating a rule."""

    name: str
    content: str
    workspace_path: str | None = None  # None for global rules


class UpdateRuleRequest(BaseModel):
    """Request model for updating a rule."""

    name: str
    content: str
    enabled: bool


class SaveSettingRequest(BaseModel):
    """Request model for saving a setting."""

    key: str
    value: str


# Conversation endpoints
@router.get("/conversations")
async def list_conversations() -> dict[str, Any]:
    """List all conversations.

    Returns:
        dict: List of conversations.
    """
    conversations = await db.get_conversations()
    return {"conversations": conversations}


@router.post("/conversations")
async def create_conversation(request: CreateConversationRequest) -> dict[str, Any]:
    """Create a new conversation.

    Args:
        request: Conversation details.

    Returns:
        dict: Created conversation.
    """
    conv_id = str(uuid.uuid4())
    conversation = await db.create_conversation(
        conv_id=conv_id,
        title=request.title,
        workspace_path=request.workspace_path,
        model=request.model,
    )
    return {"conversation": conversation}


@router.get("/conversations/{conv_id}")
async def get_conversation(conv_id: str) -> dict[str, Any]:
    """Get a conversation with its messages.

    Args:
        conv_id: Conversation ID.

    Returns:
        dict: Conversation with messages.

    Raises:
        HTTPException: If conversation not found.
    """
    conversation = await db.get_conversation(conv_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = await db.get_messages(conv_id)
    return {"conversation": conversation, "messages": messages}


@router.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str) -> dict[str, Any]:
    """Delete a conversation.

    Args:
        conv_id: Conversation ID.

    Returns:
        dict: Success status.
    """
    await db.delete_conversation(conv_id)
    return {"success": True}


@router.post("/conversations/{conv_id}/messages")
async def add_message(conv_id: str, request: AddMessageRequest) -> dict[str, Any]:
    """Add a message to a conversation.

    Args:
        conv_id: Conversation ID.
        request: Message details.

    Returns:
        dict: Created message.
    """
    message = await db.add_message(
        conversation_id=conv_id,
        role=request.role,
        content=request.content,
    )
    return {"message": message}


# Rules endpoints
@router.get("/rules/global")
async def list_global_rules() -> dict[str, Any]:
    """List all global rules.

    Returns:
        dict: List of global rules.
    """
    rules = await db.get_global_rules()
    return {"rules": rules}


@router.post("/rules/global")
async def create_global_rule(request: CreateRuleRequest) -> dict[str, Any]:
    """Create a global rule.

    Args:
        request: Rule details.

    Returns:
        dict: Created rule.
    """
    rule = await db.add_global_rule(name=request.name, content=request.content)
    return {"rule": rule}


@router.put("/rules/global/{rule_id}")
async def update_global_rule(rule_id: int, request: UpdateRuleRequest) -> dict[str, Any]:
    """Update a global rule.

    Args:
        rule_id: Rule ID.
        request: Updated rule details.

    Returns:
        dict: Success status.
    """
    await db.update_global_rule(
        rule_id=rule_id,
        name=request.name,
        content=request.content,
        enabled=request.enabled,
    )
    return {"success": True}


@router.delete("/rules/global/{rule_id}")
async def delete_global_rule(rule_id: int) -> dict[str, Any]:
    """Delete a global rule.

    Args:
        rule_id: Rule ID.

    Returns:
        dict: Success status.
    """
    await db.delete_global_rule(rule_id)
    return {"success": True}


@router.get("/rules/project")
async def list_project_rules(workspace_path: str) -> dict[str, Any]:
    """List project rules for a workspace.

    Args:
        workspace_path: Workspace path.

    Returns:
        dict: List of project rules.
    """
    rules = await db.get_project_rules(workspace_path)
    return {"rules": rules}


@router.post("/rules/project")
async def create_project_rule(request: CreateRuleRequest) -> dict[str, Any]:
    """Create a project rule.

    Args:
        request: Rule details with workspace_path.

    Returns:
        dict: Created rule.

    Raises:
        HTTPException: If workspace_path is missing.
    """
    if not request.workspace_path:
        raise HTTPException(status_code=400, detail="workspace_path is required")

    rule = await db.add_project_rule(
        workspace_path=request.workspace_path,
        name=request.name,
        content=request.content,
    )
    return {"rule": rule}


@router.delete("/rules/project/{rule_id}")
async def delete_project_rule(rule_id: int) -> dict[str, Any]:
    """Delete a project rule.

    Args:
        rule_id: Rule ID.

    Returns:
        dict: Success status.
    """
    await db.delete_project_rule(rule_id)
    return {"success": True}


# Settings endpoints
@router.get("/settings")
async def get_settings() -> dict[str, Any]:
    """Get all settings.

    Returns:
        dict: All settings.
    """
    settings = await db.get_all_settings()
    return {"settings": settings}


@router.get("/settings/{key}")
async def get_setting(key: str) -> dict[str, Any]:
    """Get a setting by key.

    Args:
        key: Setting key.

    Returns:
        dict: Setting value.
    """
    value = await db.get_setting(key)
    return {"key": key, "value": value}


@router.post("/settings")
async def save_setting(request: SaveSettingRequest) -> dict[str, Any]:
    """Save a setting.

    Args:
        request: Setting key and value.

    Returns:
        dict: Success status.
    """
    await db.set_setting(request.key, request.value)
    return {"success": True}


@router.delete("/settings/{key}")
async def delete_setting(key: str) -> dict[str, Any]:
    """Delete a setting.

    Args:
        key: Setting key.

    Returns:
        dict: Success status.
    """
    await db.delete_setting(key)
    return {"success": True}
