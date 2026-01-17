import json
import re
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from prometheus.config import settings
from prometheus.mcp.tools import MCPTools
from prometheus.routers.health import get_model_router
from prometheus.services.model_router import ModelRouter

router = APIRouter(prefix="/api/v1")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    api_base: str | None = None
    api_key: str | None = None
    workspace_path: str | None = None


class WorkspaceConfig(BaseModel):
    workspace_path: str


def get_mcp_tools(workspace: str | None = None) -> MCPTools:
    """Dependency to get MCP tools instance."""
    path = workspace or settings.workspace_path
    return MCPTools(path)


def extract_tool_calls(text: str) -> list[tuple[dict, int, int]]:
    """Extract tool calls from model response with their positions.
    
    Returns list of tuples: (tool_call_dict, start_index, end_index)
    """
    tool_calls = []
    i = 0
    
    while i < len(text):
        # Look for {"tool"
        if text[i:i+7] == '{"tool"':
            # Try to find matching closing brace
            start = i
            brace_count = 0
            j = i
            
            while j < len(text):
                if text[j] == '{':
                    brace_count += 1
                elif text[j] == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        # Found complete JSON
                        json_str = text[start:j+1]
                        try:
                            tool_call = json.loads(json_str)
                            if "tool" in tool_call and "args" in tool_call:
                                tool_calls.append((tool_call, start, j+1))
                        except json.JSONDecodeError:
                            pass
                        i = j
                        break
                j += 1
        i += 1
    
    return tool_calls


def strip_tool_calls(text: str) -> str:
    """Remove all tool call JSON from text."""
    tool_calls = extract_tool_calls(text)
    if not tool_calls:
        return text
    
    # Remove from end to start to preserve indices
    result = text
    for _, start, end in reversed(tool_calls):
        result = result[:start] + result[end:]
    
    return result.strip()


@router.post("/workspace/config")
async def configure_workspace(config: WorkspaceConfig) -> dict:
    """Configure the workspace path."""
    return {"success": True, "workspace_path": config.workspace_path}


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    model_router: Annotated[ModelRouter, Depends(get_model_router)],
) -> StreamingResponse:
    """Server-Sent Events endpoint for streaming with tool execution."""
    mcp_tools = get_mcp_tools(request.workspace_path)

    # Enhanced system prompt
    system_prompt = """You are Prometheus, an autonomous AI coding agent. You MUST use tools to perform actions.

AVAILABLE TOOLS:
1. filesystem_write(path, content) - Create or modify files
2. filesystem_read(path) - Read file contents
3. shell_execute(command) - Run shell commands

CRITICAL RULES:
- When user asks to create/modify code, you MUST use filesystem_write
- When user asks to run something, you MUST use shell_execute
- Format tool calls as: {"tool": "filesystem_write", "args": {"path": "file.py", "content": "code here"}}
- Use ONE tool call per message
- After tool call, explain what you did

Example:
User: "create a hello.py file"
You: {"tool": "filesystem_write", "args": {"path": "hello.py", "content": "print('Hello, World!')"}}"""

    messages_with_system = [{"role": "system", "content": system_prompt}]
    messages_with_system.extend([msg.model_dump() for msg in request.messages])

    async def event_generator():
        accumulated_response = ""
        tool_calls_executed: set[str] = set()
        last_sent_length = 0
        
        try:
            async for chunk in model_router.stream(
                model=request.model,
                messages=messages_with_system,
                api_base=request.api_base,
                api_key=request.api_key,
            ):
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    accumulated_response += content

                    # Check for complete tool calls
                    tool_calls = extract_tool_calls(accumulated_response)
                    
                    for tool_call, start, end in tool_calls:
                        # Skip if already executed
                        tool_signature = json.dumps(tool_call, sort_keys=True)
                        if tool_signature in tool_calls_executed:
                            continue
                        
                        tool_calls_executed.add(tool_signature)
                        tool_name = tool_call.get("tool")
                        args = tool_call.get("args", {})
                        
                        result = None
                        if tool_name == "filesystem_write":
                            result = mcp_tools.filesystem_write(
                                args.get("path", ""),
                                args.get("content", "")
                            )
                        elif tool_name == "filesystem_read":
                            result = mcp_tools.filesystem_read(args.get("path", ""))
                        elif tool_name == "shell_execute":
                            result = mcp_tools.shell_execute(args.get("command", ""))
                        
                        if result:
                            # Send tool execution result
                            tool_data = json.dumps({
                                "tool_execution": {
                                    "tool": tool_name,
                                    "success": result.get("success", False),
                                    "path": result.get("path"),
                                    "command": result.get("command"),
                                    "action": result.get("action"),
                                    "stdout": result.get("stdout"),
                                    "stderr": result.get("stderr"),
                                    "content": result.get("content"),
                                    "error": result.get("error")
                                }
                            })
                            yield f"data: {tool_data}\n\n"
                    
                    # Check if we're in the middle of a potential JSON object
                    # Count unmatched opening braces
                    open_braces = accumulated_response.count('{') - accumulated_response.count('}')
                    in_potential_json = '{"tool"' in accumulated_response[last_sent_length:] or open_braces > 0
                    
                    if not in_potential_json:
                        # Safe to send - strip any tool calls and send new content
                        clean_response = strip_tool_calls(accumulated_response)
                        new_content = clean_response[last_sent_length:]
                        
                        if new_content:
                            last_sent_length = len(clean_response)
                            data = json.dumps({"token": new_content})
                            yield f"data: {data}\n\n"
            
            # Final flush - send any remaining clean content
            clean_response = strip_tool_calls(accumulated_response)
            final_content = clean_response[last_sent_length:]
            if final_content:
                data = json.dumps({"token": final_content})
                yield f"data: {data}\n\n"

            yield "data: [DONE]\n\n"
            
        except Exception as e:
            error_data = json.dumps({"error": str(e)})
            yield f"data: {error_data}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
