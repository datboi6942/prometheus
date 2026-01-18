import json
import re
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from prometheus.config import settings, translate_host_path_to_container
from prometheus.database import (
    add_memory,
    get_enabled_rules_text,
    get_memories_text,
)
from prometheus.mcp.tools import MCPTools
from prometheus.routers.health import get_model_router
from prometheus.services.model_router import ModelRouter
from prometheus.services.context_manager import check_and_compress_if_needed, is_reasoning_model

router = APIRouter(prefix="/api/v1")
logger = structlog.get_logger()


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
    raw_path = workspace or settings.workspace_path
    # Translate host paths to container paths (for Docker)
    path = translate_host_path_to_container(raw_path)
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

    # Get API key from database based on model provider
    from prometheus.database import get_setting
    
    api_key_to_use = request.api_key
    
    # If no API key provided in request, try to get it from database
    if not api_key_to_use and request.model:
        model_provider = request.model.split('/')[0].lower()
        
        # Map model providers to their database keys
        provider_key_map = {
            'openai': 'openai_api_key',
            'anthropic': 'anthropic_api_key',
            'deepseek': 'deepseek_api_key',
            'grok': 'grok_api_key',
            'xai': 'grok_api_key',  # xAI also uses grok key
            'google': 'google_api_key',
            'gemini': 'google_api_key',
            'litellm': 'litellm_api_key',
        }
        
        key_name = provider_key_map.get(model_provider, f'{model_provider}_api_key')
        stored_key = await get_setting(key_name)
        
        if stored_key:
            api_key_to_use = stored_key
            logger.info("Using API key from database", provider=model_provider)
        else:
            # Fallback to legacy apiKey for backward compatibility
            legacy_key = await get_setting('apiKey')
            if legacy_key:
                api_key_to_use = legacy_key
                logger.info("Using legacy API key from database")

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

    # System prompt - kept simple and clear
    system_prompt = """You are Prometheus, a helpful AI coding assistant with access to tools.

AVAILABLE TOOLS:
{tools_text}

HOW TO USE TOOLS:
When you need to use a tool, output this JSON format:
{{"tool": "TOOL_NAME", "args": {{"param": "value"}}}}

After you use a tool, you will receive the results automatically. You can then continue with more tool calls if needed, or explain the results to the user.

IMPORTANT GUIDELINES:
1. For greetings or simple questions - just respond, no tools needed
2. Use ONE tool at a time - you will get results automatically, then you can continue
3. For tasks requiring multiple operations (like deleting multiple files), make sequential tool calls
4. After each tool result, either make another tool call OR explain the results to the user
5. Don't repeat tool calls unnecessarily

FILE EDITING BEST PRACTICES:
CRITICAL: When modifying existing files, ALWAYS use targeted edit tools instead of rewriting entire files:

1. For replacing specific code sections:
   - ALWAYS use filesystem_read FIRST to see the current file content
   - Identify the exact lines to modify (line numbers from the read output)
   - Use filesystem_replace_lines to replace ONLY those specific lines
   Example: To fix a function, replace just lines 45-60 instead of rewriting the whole file

2. For simple text replacements:
   - Use filesystem_search_replace to find and replace specific text
   - This is perfect for renaming variables, fixing typos, or updating values

3. For adding new code:
   - Use filesystem_insert to add code at a specific line number
   - Perfect for adding imports, new functions, or config entries

4. Only use filesystem_write when:
   - Creating brand new files
   - The file needs complete restructuring (very rare)

Why this matters: Targeted edits are faster, clearer, and less error-prone than rewriting entire files.

EXAMPLE FLOW:
User: "List the files"
You: I'll list the files for you.
{{"tool": "filesystem_list", "args": {{"path": ""}}}}
[You receive results automatically]
You: Here are the files in your directory: [summarize the results]

EXAMPLE MULTI-STEP FLOW:
User: "Delete all .txt files"
You: I'll delete all .txt files. First, let me list them.
{{"tool": "filesystem_list", "args": {{"path": ""}}}}
[You receive results showing file1.txt, file2.txt]
You: {{"tool": "filesystem_delete", "args": {{"path": "file1.txt"}}}}
[You receive results]
You: {{"tool": "filesystem_delete", "args": {{"path": "file2.txt"}}}}
[You receive results]
You: I've successfully deleted both .txt files.

EXAMPLE FILE EDITING FLOW (CORRECT):
User: "Fix the bug in calculate_total function in utils.py"
You: Let me read the file first to see the current implementation.
{{"tool": "filesystem_read", "args": {{"path": "utils.py"}}}}
[You receive file content with line numbers showing the bug is in lines 42-45]
You: I found the issue - the function is missing a return statement. I'll fix lines 42-45.
{{"tool": "filesystem_replace_lines", "args": {{"path": "utils.py", "start_line": 42, "end_line": 45, "replacement": "    total = sum(items)\\n    return total"}}}}
[You receive success with diff showing the change]
You: Fixed! The calculate_total function now properly returns the total value.

WRONG APPROACH (DON'T DO THIS):
User: "Fix the bug in calculate_total function"
You: {{"tool": "filesystem_write", "args": {{"path": "utils.py", "content": "[entire 300-line file contents with one line changed]"}}}}
^^ This rewrites the ENTIRE file when only 2 lines needed changing!

Remember: Be helpful, be concise, and continue making tool calls until the task is complete.""".format(tools_text=tools_text)

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

    # Check context usage and apply compression if needed
    messages_to_use, context_info = await check_and_compress_if_needed(
        messages=messages_with_system,
        model=request.model,
        auto_compress=True
    )

    async def event_generator():
        """Multi-turn conversation loop that continues until model is done."""
        import structlog
        logger = structlog.get_logger()

        # Send context information to frontend
        context_data = json.dumps({"context_info": context_info})
        yield f"data: {context_data}\n\n"

        # Maintain conversation state (use compressed messages)
        current_messages = messages_to_use.copy()
        max_iterations = 5  # Limit iterations to prevent over-eager behavior
        iteration = 0

        try:
            while iteration < max_iterations:
                iteration += 1
                accumulated_response = ""
                accumulated_reasoning = ""
                reasoning_complete = False
                tool_calls_found = []

                # Detect if this is a reasoning model (streams thinking separately from content)
                model_is_reasoning = is_reasoning_model(request.model)

                logger.info("Starting model stream", iteration=iteration, message_count=len(current_messages), model_is_reasoning=model_is_reasoning)

                # Stream model response - buffer entire response to prevent tool JSON from leaking
                async for chunk in model_router.stream(
                    model=request.model,
                    messages=current_messages,
                    api_base=request.api_base,
                    api_key=api_key_to_use,  # Use the determined API key
                ):
                    if chunk.choices and chunk.choices[0].delta:
                        delta = chunk.choices[0].delta

                        # Extract reasoning content from provider_specific_fields (DeepSeek R1)
                        if hasattr(delta, 'provider_specific_fields') and delta.provider_specific_fields:
                            reasoning_chunk = delta.provider_specific_fields.get("reasoning_content", "")
                            if reasoning_chunk:
                                accumulated_reasoning += reasoning_chunk
                                # Stream thinking chunk to frontend
                                thinking_data = json.dumps({"thinking_chunk": reasoning_chunk})
                                yield f"data: {thinking_data}\n\n"

                        # Handle regular content
                        if delta.content:
                            content = delta.content

                            # If we have reasoning and this is the first regular content, send thinking_complete
                            if accumulated_reasoning and not reasoning_complete:
                                reasoning_complete = True
                                # Generate summary (first 100 chars)
                                summary = accumulated_reasoning[:100] + "..." if len(accumulated_reasoning) > 100 else accumulated_reasoning
                                complete_data = json.dumps({
                                    "thinking_complete": {
                                        "summary": summary,
                                        "full_content": accumulated_reasoning
                                    }
                                })
                                yield f"data: {complete_data}\n\n"
                                logger.info("Thinking complete, transitioning to response", reasoning_length=len(accumulated_reasoning))

                            accumulated_response += content

                            # Stream content immediately for reasoning models (they don't use tools)
                            # Buffer for regular models to extract/strip tool calls
                            if model_is_reasoning:
                                token_data = json.dumps({"token": content})
                                yield f"data: {token_data}\n\n"

                # Extract tool calls ONCE after streaming completes (not on every chunk!)
                tool_calls = extract_tool_calls(accumulated_response)

                # Track tool calls
                for tool_call, start, end in tool_calls:
                    tool_signature = json.dumps(tool_call, sort_keys=True)
                    if not any(tc["signature"] == tool_signature for tc in tool_calls_found):
                        tool_calls_found.append({
                            "call": tool_call,
                            "start": start,
                            "end": end,
                            "signature": tool_signature
                        })

                        # Send tool call notification to frontend for animation
                        tool_call_notification = json.dumps({
                            "tool_call": {
                                "tool": tool_call.get("tool"),
                                "args": tool_call.get("args"),
                            }
                        })
                        yield f"data: {tool_call_notification}\n\n"

                # Strip tool calls from the complete response
                clean_response = strip_tool_calls(accumulated_response)

                # Send the clean response (all at once, after stripping tool calls)
                # Skip this for reasoning models since we already streamed the content
                if clean_response.strip() and not model_is_reasoning:
                    final_data = json.dumps({"token": clean_response})
                    yield f"data: {final_data}\n\n"
                
                # Add assistant response to conversation (without tool calls)
                if clean_response.strip():
                    current_messages.append({
                        "role": "assistant",
                        "content": clean_response.strip()
                    })
                
                # Execute any tool calls found
                if tool_calls_found:
                    logger.info("Executing tool calls", count=len(tool_calls_found))
                    
                    # Collect all tool results
                    tool_results = []
                    
                    for tool_info in tool_calls_found:
                        tool_call = tool_info["call"]
                        tool_name = tool_call.get("tool")
                        args = tool_call.get("args", {})
                        
                        logger.info("Executing tool", tool=tool_name, args=args)
                        
                        # Execute tool
                        from prometheus.services.tool_registry import get_registry
                        registry = get_registry()
                        # Translate workspace path for Docker container
                        translated_workspace = translate_host_path_to_container(
                            request.workspace_path or settings.workspace_path
                        )
                        result = await registry.execute_tool(
                            name=tool_name,
                            args=args,
                            context={"workspace_path": translated_workspace, "mcp_tools": mcp_tools},
                        )
                        
                        logger.info("Tool execution result", tool=tool_name, success=result.get("success", False))
                        
                        # Check if tool requires permission
                        if result.get("permission_required"):
                            # Send permission request to frontend
                            permission_data = json.dumps({
                                "permission_request": {
                                    "command": result.get("command"),
                                    "full_command": result.get("full_command"),
                                    "tool": tool_name,
                                    "message": result.get("message"),
                                }
                            })
                            yield f"data: {permission_data}\n\n"
                            
                            # Stop execution and wait for user to approve
                            # The conversation will pause here until user approves the command
                            # and sends a new message
                            logger.info("Tool execution requires permission", tool=tool_name, command=result.get("command"))
                            tool_results.append({
                                "tool": tool_name,
                                "result": f"⚠️ Permission required to run command: {result.get('command')}\n\nThis command needs your approval before it can be executed. Please approve or deny this command to continue.",
                            })
                            continue
                        
                        # Send tool execution result to frontend
                        if result:
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
                        
                        # Format tool result for model
                        if result:
                            result_text = f"Tool {tool_name} executed successfully." if result.get("success") else f"Tool {tool_name} failed."
                            
                            # Handle different result types
                            if result.get("items"):
                                # filesystem_list returns items
                                items = result.get("items", [])
                                result_text += f"\n\nDirectory listing ({len(items)} items):\n"
                                for item in items[:50]:  # Limit to 50 items
                                    item_type = "📁" if item.get("type") == "directory" else "📄"
                                    result_text += f"{item_type} {item.get('name')}\n"
                                if len(items) > 50:
                                    result_text += f"... and {len(items) - 50} more items"
                            
                            if result.get("stdout"):
                                result_text += f"\n\nOutput:\n{result.get('stdout')}"
                            if result.get("stderr"):
                                result_text += f"\n\nErrors:\n{result.get('stderr')}"
                            if result.get("content"):
                                content = result.get("content", "")
                                result_text += f"\n\nFile content:\n{content[:2000]}"  # Limit length
                                if len(content) > 2000:
                                    result_text += f"\n... (truncated, {len(content)} total chars)"
                            if result.get("error"):
                                result_text += f"\n\nError: {result.get('error')}"
                            if result.get("hint"):
                                result_text += f"\n\nHint: {result.get('hint')}"
                            if result.get("message"):
                                result_text += f"\n\n{result.get('message')}"
                            
                            tool_results.append({
                                "tool": tool_name,
                                "result": result_text
                            })
                    
                    # Add tool results to conversation so model can continue
                    if tool_results:
                        tool_result_message = "Tool execution results:\n"
                        for tr in tool_results:
                            tool_result_message += f"\n{tr['tool']}: {tr['result']}\n"

                        current_messages.append({
                            "role": "user",
                            "content": tool_result_message
                        })

                        logger.info("Added tool results to conversation", result_count=len(tool_results))

                        # Check if we need to compress after adding tool results
                        current_messages, updated_context_info = await check_and_compress_if_needed(
                            messages=current_messages,
                            model=request.model,
                            auto_compress=True
                        )

                        # If compression occurred, notify frontend
                        if updated_context_info.get("compressed"):
                            logger.info("Compressed during multi-turn loop", **updated_context_info)
                            compression_notification = json.dumps({"context_info": updated_context_info})
                            yield f"data: {compression_notification}\n\n"

                        # Continue loop to get model's next response
                        continue
                
                # No tool calls found - model is done
                logger.info("No tool calls found, conversation complete")
                break
            
            if iteration >= max_iterations:
                logger.warning("Reached max iterations", max_iterations=max_iterations)
                yield f"data: {json.dumps({'error': 'Reached maximum iteration limit'})}\n\n"

            # Extract and save memories from the conversation
            for msg in request.messages:
                if msg.role == "user":
                    user_memories = extract_memory_requests(msg.content, source="user")
                    for memory in user_memories:
                        try:
                            await add_memory(
                                content=memory["content"],
                                source="user",
                                workspace_path=request.workspace_path,
                                conversation_id=getattr(request, "conversation_id", None),
                                tags=memory.get("tags"),
                            )
                            logger.info("Saved user memory", content=memory["content"][:50])
                        except Exception as e:
                            logger.warning("Failed to save memory", error=str(e))
            
            # Check final model response for memory indicators
            if current_messages:
                last_assistant_msg = None
                for msg in reversed(current_messages):
                    if msg.get("role") == "assistant":
                        last_assistant_msg = msg.get("content", "")
                        break
                
                if last_assistant_msg:
                    model_memories = extract_memory_requests(last_assistant_msg, source="model")
                    for memory in model_memories:
                        try:
                            await add_memory(
                                content=memory["content"],
                                source="model",
                                workspace_path=request.workspace_path,
                                conversation_id=getattr(request, "conversation_id", None),
                                tags=memory.get("tags"),
                            )
                            logger.info("Saved model memory", content=memory["content"][:50])
                        except Exception as e:
                            logger.warning("Failed to save model memory", error=str(e))

            yield "data: [DONE]\n\n"
            
        except Exception as e:
            logger.exception("Error in event generator")
            error_data = json.dumps({"error": str(e)})
            yield f"data: {error_data}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
