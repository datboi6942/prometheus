import json
import re
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from prometheus.config import settings
from prometheus.database import (
    add_memory,
    get_enabled_rules_text,
    get_memories_text,
)
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
    
    Uses multiple strategies to find tool calls in model output.
    
    Returns list of tuples: (tool_call_dict, start_index, end_index)
    """
    import structlog
    logger = structlog.get_logger()
    
    tool_calls = []
    
    # Strategy 1: Look for {"tool" pattern with regex
    patterns = [
        r'\{"tool"\s*:\s*"[^"]+"\s*,\s*"args"\s*:\s*\{',  # {"tool": "name", "args": {
        r'\{\s*"tool"\s*:\s*"[^"]+"\s*,\s*"args"\s*:\s*\{',  # { "tool": "name", "args": {
    ]
    
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            start = match.start()
            # Find the matching closing brace
            j = start
            brace_count = 0
            in_string = False
            escape_next = False
            
            while j < len(text):
                char = text[j]
                
                if escape_next:
                    escape_next = False
                    j += 1
                    continue
                    
                if char == '\\':
                    escape_next = True
                elif char == '"':
                    in_string = not in_string
                elif not in_string:
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            # Found complete JSON
                            json_str = text[start:j+1]
                            try:
                                tool_call = json.loads(json_str)
                                if "tool" in tool_call and "args" in tool_call:
                                    # Check if already found
                                    already_found = any(tc[1] == start for tc in tool_calls)
                                    if not already_found:
                                        logger.info("Found tool call", tool=tool_call.get("tool"), start=start, end=j+1)
                                        tool_calls.append((tool_call, start, j+1))
                            except json.JSONDecodeError as e:
                                logger.warning("JSON decode failed", error=str(e), json_preview=json_str[:100])
                            break
                j += 1
    
    # Strategy 2: Try to find JSON objects that look like tool calls using simple search
    if not tool_calls:
        # Get tool names dynamically from registry
        from prometheus.services.tool_registry import get_registry
        
        registry = get_registry()
        tool_names = registry.get_tool_names()
        for tool_name in tool_names:
            idx = text.find(f'"tool": "{tool_name}"')
            if idx == -1:
                idx = text.find(f'"tool":"{tool_name}"')
            
            if idx != -1:
                # Find the opening brace before this
                brace_start = text.rfind('{', 0, idx)
                if brace_start != -1:
                    # Find matching closing brace
                    j = brace_start
                    brace_count = 0
                    in_string = False
                    escape_next = False
                    
                    while j < len(text):
                        char = text[j]
                        
                        if escape_next:
                            escape_next = False
                            j += 1
                            continue
                            
                        if char == '\\':
                            escape_next = True
                        elif char == '"':
                            in_string = not in_string
                        elif not in_string:
                            if char == '{':
                                brace_count += 1
                            elif char == '}':
                                brace_count -= 1
                                if brace_count == 0:
                                    json_str = text[brace_start:j+1]
                                    try:
                                        tool_call = json.loads(json_str)
                                        if "tool" in tool_call and "args" in tool_call:
                                            already_found = any(tc[1] == brace_start for tc in tool_calls)
                                            if not already_found:
                                                logger.info("Found tool call (strategy 2)", tool=tool_call.get("tool"))
                                                tool_calls.append((tool_call, brace_start, j+1))
                                    except json.JSONDecodeError:
                                        pass
                                    break
                        j += 1
    
    logger.info("Tool extraction complete", found=len(tool_calls), text_preview=text[:200] if text else "")
    
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


def extract_memory_requests(text: str, source: str = "user") -> list[dict[str, str]]:
    """Extract memory requests from text.
    
    Detects patterns like:
    - "remember that..." / "remember this..."
    - "I want you to remember..."
    - Model-generated memory indicators
    
    Args:
        text: Text to analyze.
        source: Source of the memory request ('user' or 'model').
        
    Returns:
        list: List of memory dictionaries with 'content' and 'tags'.
    """
    memories = []
    import re
    
    # User memory patterns
    if source == "user":
        patterns = [
            r"(?:remember|save|store)\s+(?:that|this|the\s+fact\s+that)\s+(.+?)(?:\.|$)",
            r"i\s+(?:want\s+you\s+to\s+)?remember\s+(.+?)(?:\.|$)",
            r"don't\s+forget\s+(?:that|about)\s+(.+?)(?:\.|$)",
            r"keep\s+in\s+mind\s+(?:that|the\s+fact\s+that)\s+(.+?)(?:\.|$)",
        ]
        for pattern in patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                content = match.group(1).strip()
                if len(content) > 10:  # Minimum length for a meaningful memory
                    # Extract potential tags from the memory content
                    words = content.split()[:5]  # First 5 words as tags
                    tags = ",".join([w.lower().strip(".,!?") for w in words if len(w) > 3])
                    memories.append({"content": content, "tags": tags})
    
    # Model memory patterns (when model decides to remember something)
    elif source == "model":
        # Look for explicit memory indicators in model response
        patterns = [
            r"\[MEMORY\]:\s*(.+?)(?:\n|$)",
            r"\[REMEMBER\]:\s*(.+?)(?:\n|$)",
            r"important\s+to\s+remember:\s*(.+?)(?:\.|$)",
        ]
        for pattern in patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                content = match.group(1).strip()
                if len(content) > 10:
                    words = content.split()[:5]
                    tags = ",".join([w.lower().strip(".,!?") for w in words if len(w) > 3])
                    memories.append({"content": content, "tags": tags})
    
    return memories


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

    # Get available tools dynamically from registry
    from prometheus.services.tool_registry import get_registry
    
    registry = get_registry()
    all_tools = registry.get_all_tools()
    
    # Build tools list for system prompt
    tools_list = []
    for i, tool in enumerate(all_tools, 1):
        tool_desc = f"{i}. {tool['name']}"
        if tool.get("description"):
            tool_desc += f" - {tool['description']}"
        if tool.get("parameters"):
            params = ", ".join(tool["parameters"].keys())
            tool_desc += f"({params})"
        tools_list.append(tool_desc)
    
    tools_text = "\n".join(tools_list) if tools_list else "No tools available"

    # Enhanced system prompt for autonomous coding
    system_prompt = f"""You are Prometheus, an autonomous AI coding agent. You have tools to create, read, modify, and TEST files.

TOOLS AVAILABLE:
{tools_text}

TOOL FORMAT - Use this exact JSON format:
{"tool": "TOOL_NAME", "args": {"param": "value"}}

CRITICAL RULES:
1. When asked to CREATE code - use filesystem_write IMMEDIATELY
2. When asked to TEST/RUN Python - use run_python with stdin_input for interactive scripts
3. When asked to READ/SHOW code - use filesystem_read
4. Do NOT ask permission - just do it
5. Write complete, working code - not pseudocode
6. After the tool JSON, briefly explain what you created/did
7. For interactive programs, provide test input via stdin_input parameter

TESTING EXAMPLES:

Example 1 - Run a non-interactive script:
{"tool": "run_python", "args": {"file_path": "hello.py"}}

Example 2 - Run interactive script with test input:
{"tool": "run_python", "args": {"file_path": "calculator.py", "stdin_input": "5 + 3\\nquit\\n"}}

Example 3 - Run with command line args:
{"tool": "run_python", "args": {"file_path": "script.py", "args": "--input data.txt"}}

Example 4 - Run pytest:
{"tool": "run_tests", "args": {"test_path": "test_calculator.py"}}

WHEN WRITING CODE FOR TESTING:
- Add a simple test mode: if __name__ == '__main__' should demonstrate the code works
- Include print statements showing results
- For calculators/converters: print example calculations
- Avoid infinite loops in test mode

EXAMPLE - Create and test a calculator:

{"tool": "filesystem_write", "args": {"path": "calc.py", "content": "#!/usr/bin/env python3\\n\\ndef add(a, b): return a + b\\ndef sub(a, b): return a - b\\ndef mul(a, b): return a * b\\ndef div(a, b): return a / b if b else 'Error'\\n\\nif __name__ == '__main__':\\n    print('Testing calculator...')\\n    print(f'5 + 3 = {add(5, 3)}')\\n    print(f'10 - 4 = {sub(10, 4)}')\\n    print(f'6 * 7 = {mul(6, 7)}')\\n    print(f'15 / 3 = {div(15, 3)}')\\n    print('All tests passed!')\\n"}}

Then test it:
{"tool": "run_python", "args": {"file_path": "calc.py"}}

REMEMBER: Take action immediately. Create testable code with example output."""

    # Inject user-defined rules
    rules_text = await get_enabled_rules_text(request.workspace_path or "")
    
    # Inject relevant memories based on conversation context
    # Extract keywords from recent messages for memory relevance
    context_keywords = " ".join([msg.content[:200] for msg in request.messages[-3:]])
    memories_text = await get_memories_text(
        workspace_path=request.workspace_path,
        context=context_keywords,
    )
    
    full_system_prompt = system_prompt + rules_text + memories_text

    messages_with_system = [{"role": "system", "content": full_system_prompt}]
    messages_with_system.extend([msg.model_dump() for msg in request.messages])

    async def event_generator():
        accumulated_response = ""
        tool_calls_executed: set[str] = set()
        last_sent_length = 0
        
        import structlog
        logger = structlog.get_logger()
        
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
                    
                    logger.info("Tool calls detected", count=len(tool_calls), response_length=len(accumulated_response))
                    
                    for tool_call, start, end in tool_calls:
                        # Skip if already executed
                        tool_signature = json.dumps(tool_call, sort_keys=True)
                        if tool_signature in tool_calls_executed:
                            continue
                        
                        tool_calls_executed.add(tool_signature)
                        tool_name = tool_call.get("tool")
                        args = tool_call.get("args", {})
                        
                        logger.info("Executing tool", tool=tool_name, args=args)
                        
                        # Use dynamic tool registry
                        from prometheus.services.tool_registry import get_registry
                        
                        registry = get_registry()
                        result = await registry.execute_tool(
                            name=tool_name,
                            args=args,
                            context={"workspace_path": request.workspace_path, "mcp_tools": mcp_tools},
                        )
                        
                        logger.info("Tool execution result", result=result)
                        
                        if result:
                            # Send tool execution result
                            tool_data = json.dumps({
                                "tool_execution": {
                                    "tool": tool_name,
                                    "success": result.get("success", False),
                                    "path": result.get("path"),
                                    "file": result.get("file"),
                                    "command": result.get("command"),
                                    "action": result.get("action"),
                                    "stdout": result.get("stdout"),
                                    "stderr": result.get("stderr"),
                                    "content": result.get("content"),
                                    "error": result.get("error"),
                                    "return_code": result.get("return_code"),
                                    "hint": result.get("hint")
                                }
                            })
                            yield f"data: {tool_data}\n\n"
                    
                    # Check if we're in the middle of a potential JSON object
                    # Count unmatched opening braces
                    open_braces = accumulated_response.count('{') - accumulated_response.count('}')
                    
                    # More aggressive streaming - only hold back if we're actively mid-JSON
                    # Check for both "tool" and "args" to be more confident it's a tool call
                    recent_chunk = accumulated_response[max(0, len(accumulated_response) - 50):]
                    has_tool = '{"tool"' in recent_chunk or '"tool"' in recent_chunk
                    has_args = '"args"' in recent_chunk
                    looks_like_json_start = has_tool and has_args and open_braces > 0
                    
                    if not looks_like_json_start:
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

            # Extract and save memories from the conversation
            # Check user messages for memory requests
            for msg in request.messages:
                if msg.role == "user":
                    user_memories = extract_memory_requests(msg.content, source="user")
                    for memory in user_memories:
                        try:
                            await add_memory(
                                content=memory["content"],
                                source="user",
                                workspace_path=request.workspace_path,
                                conversation_id=request.conversation_id,
                                tags=memory.get("tags"),
                            )
                            logger.info("Saved user memory", content=memory["content"][:50])
                        except Exception as e:
                            logger.warning("Failed to save memory", error=str(e))
            
            # Check model response for memory indicators
            model_memories = extract_memory_requests(clean_response, source="model")
            for memory in model_memories:
                try:
                    await add_memory(
                        content=memory["content"],
                        source="model",
                        workspace_path=request.workspace_path,
                        conversation_id=request.conversation_id,
                        tags=memory.get("tags"),
                    )
                    logger.info("Saved model memory", content=memory["content"][:50])
                except Exception as e:
                    logger.warning("Failed to save model memory", error=str(e))

            yield "data: [DONE]\n\n"
            
        except Exception as e:
            error_data = json.dumps({"error": str(e)})
            yield f"data: {error_data}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
