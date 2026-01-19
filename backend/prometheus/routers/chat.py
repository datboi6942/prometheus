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

    # System prompt - Claude Code inspired, focused and effective
    system_prompt = """You are Prometheus, an expert AI coding assistant. You help users with software engineering tasks by reading, writing, and modifying code.

TOOLS:
{tools_text}

TOOL FORMAT - Output exactly this JSON when using tools:
{{"tool": "TOOL_NAME", "args": {{"param": "value"}}}}

CORE PRINCIPLES:

1. ACT, DON'T JUST TALK
   - When you say "I'll do X" - DO IT IMMEDIATELY with a tool call
   - Never end a response with "Let me..." or "I'll..." without the actual tool call
   - Reading a file is step 1. Editing is step 2. Always complete both.

2. ONE TOOL AT A TIME
   - Call one tool, wait for results, then continue
   - You'll automatically receive tool results - no need to ask

3. USE THE RIGHT TOOL FOR EDITS
   - grep: Search for patterns across files (supports regex, recursive, case-insensitive)
   - filesystem_read: Read files (path required, optional: offset/limit for large files)
   - filesystem_replace_lines: Replace specific lines (use start_line, end_line, replacement)
   - filesystem_search_replace: Find and replace text patterns
   - filesystem_insert: Add new lines at a position
   - filesystem_write: ONLY for creating NEW files

   NEVER use filesystem_write on existing files - use targeted edits instead!

4. FIX ERRORS EFFICIENTLY
   - When you see an error, identify the exact line and fix it
   - Don't re-read files you just read - use the content you have
   - Don't create helper scripts - use your tools directly
   - If an edit fails, check the error message and adjust your approach

5. COMPLETE THE TASK
   - Keep making tool calls until the job is 100% done
   - Don't stop after reading - make the actual changes
   - Don't stop after one edit if more are needed
   - Summarize what you did only AFTER finishing

WORKFLOW EXAMPLE:
User: "Fix the syntax error in app.py"

{{"tool": "filesystem_read", "args": {{"path": "app.py"}}}}
[Results show line 42 has missing colon]

Found the issue on line 42. Fixing now.
{{"tool": "filesystem_replace_lines", "args": {{"path": "app.py", "start_line": 42, "end_line": 42, "replacement": "def process_data(x):\\n"}}}}
[Success]

Fixed the syntax error - added missing colon on line 42.

CRITICAL REMINDERS:
- filesystem_read supports optional offset/limit for large files, but usually just read the whole file
- Always use filesystem_replace_lines/search_replace/insert for existing files
- Never output partial tool JSON - complete the full {{"tool": ..., "args": ...}} structure
- Be concise - users want results, not lengthy explanations

🚨 ANTI-ANALYSIS-PARALYSIS RULES:
- After reading 1-2 files, you MUST start making edits. Do NOT read more than necessary.
- If you see an error, identify the line and FIX IT IMMEDIATELY in the same turn.
- DO NOT re-read a file you already read. Use the content you have.
- DO NOT explain what you "will" do - just DO IT with a tool call.
- Your job is to COMPLETE tasks, not just analyze them. Every response should include action.
- If the user shows an error, your FIRST read should be followed by an EDIT in the same turn.""".format(tools_text=tools_text)

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
        max_iterations = 50  # Allow enough iterations to complete complex tasks (large files, multi-step operations)
        iteration = 0
        lazy_kick_count = 0  # Track how many times we've kicked the agent for being lazy
        max_lazy_kicks = 3  # Don't kick more than 3 times per iteration to avoid infinite loops
        consecutive_lazy_kicks = 0  # Track consecutive lazy kicks (resets after tool execution)
        
        # Track read vs edit operations to detect analysis paralysis
        read_only_operations = 0  # filesystem_read, grep, filesystem_list
        edit_operations = 0  # filesystem_write, filesystem_replace_lines, filesystem_insert, etc.
        max_reads_before_nudge = 2  # After this many reads without edits, nudge the agent
        max_reads_before_block = 5  # After this many, REFUSE more reads and force edit
        task_started = False  # Track if the agent has started working on the task
        files_read = set()  # Track which files have been read to prevent re-reading
        
        # Cross-iteration deduplication for edits (prevent same edit being made multiple times)
        completed_edits = set()  # Track (path, start_line, end_line, content_hash) tuples

        # Helper to execute a single tool and yield results
        async def execute_and_yield_tool(tool_call: dict) -> tuple[str, dict, str, dict]:
            """Execute a tool call and yield results to frontend. Returns (result_text, result_dict)."""
            nonlocal completed_edits, read_only_operations, edit_operations, files_read
            
            tool_name = tool_call.get("tool")
            args = tool_call.get("args", {})
            
            # Block read operations if agent is in analysis paralysis mode
            read_tools = {'filesystem_read', 'grep', 'filesystem_list', 'filesystem_search'}
            if tool_name in read_tools and read_only_operations >= max_reads_before_block and edit_operations == 0:
                logger.warning("BLOCKING read operation - agent in analysis paralysis", 
                              tool=tool_name, read_ops=read_only_operations)
                return (
                    f"🛑 BLOCKED: {tool_name} is disabled. You have done {read_only_operations} reads with 0 edits.\n"
                    f"You MUST use an edit tool now: filesystem_replace_lines, filesystem_search_replace, or filesystem_insert.\n"
                    f"Make the fix based on what you've already read.",
                    {"success": False, "blocked": True, "reason": "analysis_paralysis"},
                    tool_name,
                    args
                )
            
            # Track and warn about re-reading the same file
            if tool_name == 'filesystem_read':
                file_path = args.get("path", "")
                if file_path in files_read:
                    logger.warning("Agent re-reading same file", path=file_path)
                    return (
                        f"⚠️ You already read '{file_path}'! Use the content you have.\n"
                        f"DO NOT read the same file twice. Make your edit NOW:\n"
                        f'{{"tool": "filesystem_replace_lines", "args": {{"path": "{file_path}", "start_line": N, "end_line": M, "replacement": "fixed code"}}}}',
                        {"success": True, "duplicate_read": True, "path": file_path},
                        tool_name,
                        args
                    )
                files_read.add(file_path)

            logger.info("Executing tool inline", tool=tool_name, args=args)
            
            # Check for duplicate edit operations
            edit_tools = {'filesystem_write', 'filesystem_replace_lines', 'filesystem_insert', 
                          'filesystem_search_replace'}
            if tool_name in edit_tools:
                # Create a signature for this edit
                path = args.get("path", "")
                start_line = args.get("start_line", 0)
                end_line = args.get("end_line", 0)
                content = args.get("content", args.get("replacement", args.get("replace", "")))
                content_hash = hash(content) if content else 0
                
                edit_signature = (path, start_line, end_line, content_hash)
                
                if edit_signature in completed_edits:
                    logger.warning("Skipping duplicate edit", tool=tool_name, path=path, 
                                  start_line=start_line, end_line=end_line)
                    return (
                        f"⚠️ DUPLICATE EDIT SKIPPED: You already made this exact edit to {path}. "
                        f"The file was already updated. Move on to the next task or verify the fix works.",
                        {"success": True, "skipped": True, "reason": "duplicate"},
                        tool_name,
                        args
                    )
                
                # Add to completed edits BEFORE executing (to prevent race conditions)
                completed_edits.add(edit_signature)

            # Execute tool
            from prometheus.services.tool_registry import get_registry
            registry = get_registry()
            translated_workspace = translate_host_path_to_container(
                request.workspace_path or settings.workspace_path
            )
            result = await registry.execute_tool(
                name=tool_name,
                args=args,
                context={"workspace_path": translated_workspace, "mcp_tools": mcp_tools},
            )

            logger.info("Tool execution result", tool=tool_name, success=result.get("success", False))

            # Format result text for model
            result_text = f"Tool {tool_name} executed successfully." if result.get("success") else f"Tool {tool_name} failed."

            if result.get("items"):
                items = result.get("items", [])
                result_text += f"\n\nDirectory listing ({len(items)} items):\n"
                for item in items[:50]:
                    item_type = "📁" if item.get("type") == "directory" else "📄"
                    result_text += f"{item_type} {item.get('name')}\n"
                if len(items) > 50:
                    result_text += f"... and {len(items) - 50} more items"

            # Format grep results
            if result.get("matches") is not None and tool_name == "grep":
                matches = result.get("matches", [])
                files_with_matches = result.get("files_with_matches", 0)
                total_matches = result.get("total_matches", 0)
                files_searched = result.get("files_searched", 0)

                result_text += f"\n\nGrep Results:"
                result_text += f"\n- Pattern: {result.get('pattern')}"
                result_text += f"\n- Searched: {files_searched} files"
                result_text += f"\n- Found: {total_matches} matches in {files_with_matches} files"

                if matches:
                    result_text += f"\n\nMatches:\n"
                    for file_match in matches[:20]:  # Limit to first 20 files
                        file_path = file_match.get("file")
                        match_count = file_match.get("match_count", 0)
                        result_text += f"\n{file_path} ({match_count} matches):\n"

                        if "matches" in file_match:
                            # Detailed matches with line numbers
                            for match in file_match["matches"][:10]:  # Limit to first 10 matches per file
                                line_num = match.get("line_number")
                                line = match.get("line", "")
                                result_text += f"  {line_num}: {line}\n"

                            if len(file_match["matches"]) > 10:
                                result_text += f"  ... and {len(file_match['matches']) - 10} more matches in this file\n"

                    if len(matches) > 20:
                        result_text += f"\n... and {len(matches) - 20} more files with matches"
                else:
                    result_text += f"\n\nNo matches found."

            if result.get("stdout"):
                result_text += f"\n\nOutput:\n{result.get('stdout')}"
            if result.get("stderr"):
                result_text += f"\n\nErrors:\n{result.get('stderr')}"
            if result.get("content"):
                content = result.get("content", "")
                result_text += f"\n\n🎯 ENTIRE FILE CONTENT BELOW - DO NOT READ AGAIN! START EDITING NOW! 🎯\n"
                result_text += f"File content ({len(content)} chars total):\n{content[:2000]}"
                if len(content) > 2000:
                    result_text += f"\n... (truncated for display, but you have the COMPLETE file)"
                result_text += f"\n\n✅ You now have the FULL file. Do NOT call filesystem_read again!"
                result_text += f"\n✅ Next step: Use filesystem_replace_lines, filesystem_search_replace, or filesystem_insert to make changes!"
            if result.get("error"):
                result_text += f"\n\nError: {result.get('error')}"
            if result.get("hint"):
                result_text += f"\n\nHint: {result.get('hint')}"
            if result.get("message"):
                result_text += f"\n\n{result.get('message')}"

            return result_text, result, tool_name, args

        try:
            while iteration < max_iterations:
                iteration += 1
                accumulated_response = ""
                accumulated_reasoning = ""
                reasoning_complete = False
                tool_calls_found = []
                tool_results = []  # Collect results for conversation continuation
                last_streamed_pos = 0  # Track what we've already streamed to frontend
                processed_tool_signatures = set()  # Track already processed tool calls

                # Detect if this is a reasoning model (streams thinking separately from content)
                model_is_reasoning = is_reasoning_model(request.model)
                is_ollama_reasoning = model_is_reasoning and "ollama" in request.model.lower()

                logger.info("Starting model stream", iteration=iteration, message_count=len(current_messages), model_is_reasoning=model_is_reasoning, is_ollama_reasoning=is_ollama_reasoning)

                # Stream iteration progress to frontend
                progress_data = json.dumps({
                    "iteration_progress": {
                        "current": iteration,
                        "max": max_iterations,
                        "message_count": len(current_messages),
                        "read_ops": read_only_operations,
                        "edit_ops": edit_operations
                    }
                })
                yield f"data: {progress_data}\n\n"

                # Stream model response with SMART BUFFERING to hide tool call JSON
                stream_buffer = ""  # Buffer for potentially unsafe content
                safe_to_stream_pos = 0  # Position in accumulated_response that's been streamed
                in_potential_json = False  # Whether we're inside potential JSON
                brace_depth = 0  # Track { } depth

                # For Ollama reasoning models, track <think> tags
                in_think_tag = False  # Whether we're inside <think>...</think>
                think_buffer = ""  # Buffer for thinking content
                pending_content = ""  # Content that might be part of opening/closing tag

                async for chunk in model_router.stream(
                    model=request.model,
                    messages=current_messages,
                    api_base=request.api_base,
                    api_key=api_key_to_use,
                ):
                    if chunk.choices and chunk.choices[0].delta:
                        delta = chunk.choices[0].delta

                        # Extract reasoning content from provider_specific_fields (DeepSeek R1)
                        if hasattr(delta, 'provider_specific_fields') and delta.provider_specific_fields:
                            reasoning_chunk = delta.provider_specific_fields.get("reasoning_content", "")
                            if reasoning_chunk:
                                accumulated_reasoning += reasoning_chunk
                                thinking_data = json.dumps({"thinking_chunk": reasoning_chunk})
                                yield f"data: {thinking_data}\n\n"

                        # Handle regular content
                        if delta.content:
                            content = delta.content

                            # For Ollama reasoning models, detect <think> tags in content
                            content_added_to_buffer = ""  # Track what we add to stream_buffer for brace tracking
                            if is_ollama_reasoning:
                                pending_content += content

                                # Process pending content for <think> tags
                                while pending_content:
                                    if not in_think_tag:
                                        # Look for opening <think> tag
                                        think_start = pending_content.find("<think>")
                                        if think_start != -1:
                                            # Content before <think> goes to regular response
                                            before_think = pending_content[:think_start]
                                            if before_think:
                                                accumulated_response += before_think
                                                stream_buffer += before_think
                                                content_added_to_buffer += before_think

                                            in_think_tag = True
                                            pending_content = pending_content[think_start + 7:]  # Skip <think>
                                            logger.info("Entered <think> tag")
                                        elif "<think" in pending_content and len(pending_content) < 10:
                                            # Might be partial tag, wait for more content
                                            break
                                        else:
                                            # No <think> tag, this is regular content
                                            accumulated_response += pending_content
                                            stream_buffer += pending_content
                                            content_added_to_buffer += pending_content
                                            pending_content = ""
                                    else:
                                        # Inside <think> tag, look for closing </think>
                                        think_end = pending_content.find("</think>")
                                        if think_end != -1:
                                            # Thinking content before </think>
                                            thinking_chunk = pending_content[:think_end]
                                            if thinking_chunk:
                                                accumulated_reasoning += thinking_chunk
                                                think_buffer += thinking_chunk
                                                # Stream thinking to frontend
                                                thinking_data = json.dumps({"thinking_chunk": thinking_chunk})
                                                yield f"data: {thinking_data}\n\n"

                                            in_think_tag = False
                                            pending_content = pending_content[think_end + 8:]  # Skip </think>
                                            logger.info("Exited </think> tag", reasoning_length=len(accumulated_reasoning))

                                            # Send thinking_complete if we have reasoning and are transitioning to content
                                            if accumulated_reasoning and not reasoning_complete and pending_content.strip():
                                                reasoning_complete = True
                                                summary = accumulated_reasoning[:100] + "..." if len(accumulated_reasoning) > 100 else accumulated_reasoning
                                                complete_data = json.dumps({
                                                    "thinking_complete": {
                                                        "summary": summary,
                                                        "full_content": accumulated_reasoning
                                                    }
                                                })
                                                yield f"data: {complete_data}\n\n"
                                                logger.info("Thinking complete (Ollama)", reasoning_length=len(accumulated_reasoning))
                                        elif "</think" in pending_content and len(pending_content) < 10:
                                            # Might be partial closing tag, wait for more content
                                            break
                                        else:
                                            # Still inside thinking, accumulate it
                                            accumulated_reasoning += pending_content
                                            think_buffer += pending_content
                                            # Stream thinking to frontend
                                            thinking_data = json.dumps({"thinking_chunk": pending_content})
                                            yield f"data: {thinking_data}\n\n"
                                            pending_content = ""

                                # Use content_added_to_buffer for brace tracking instead of original content
                                content = content_added_to_buffer

                            # If we have reasoning and this is the first regular content, send thinking_complete (for API models)
                            if content and accumulated_reasoning and not reasoning_complete:
                                reasoning_complete = True
                                summary = accumulated_reasoning[:100] + "..." if len(accumulated_reasoning) > 100 else accumulated_reasoning
                                complete_data = json.dumps({
                                    "thinking_complete": {
                                        "summary": summary,
                                        "full_content": accumulated_reasoning
                                    }
                                })
                                yield f"data: {complete_data}\n\n"
                                logger.info("Thinking complete, transitioning to response", reasoning_length=len(accumulated_reasoning))

                            if content:
                                accumulated_response += content
                                stream_buffer += content

                            # Track brace depth to detect JSON blocks
                            for char in content:
                                if char == '{':
                                    brace_depth += 1
                                    if brace_depth == 1:
                                        in_potential_json = True
                                elif char == '}':
                                    brace_depth = max(0, brace_depth - 1)
                                    if brace_depth == 0:
                                        in_potential_json = False

                            # SMART STREAMING STRATEGY:
                            # 1. If not in JSON and buffer has content, check for complete tool calls
                            # 2. Stream safe content (everything before tool calls)
                            # 3. Hold back potential JSON until we confirm it's a tool call or not

                            if not in_potential_json or brace_depth == 0:
                                # We're outside JSON or just closed a brace - safe to check for tools
                                tool_calls = extract_tool_calls(accumulated_response)

                                # Calculate what's safe to stream (everything up to first unprocessed tool call)
                                safe_end = len(accumulated_response)
                                for tool_call, start, end in tool_calls:
                                    tool_signature = json.dumps(tool_call, sort_keys=True)
                                    if tool_signature not in processed_tool_signatures:
                                        # Found new tool call - can only stream up to its start
                                        safe_end = min(safe_end, start)
                                        break

                                # Stream safe content
                                if safe_end > safe_to_stream_pos:
                                    safe_content = accumulated_response[safe_to_stream_pos:safe_end]
                                    if safe_content.strip():
                                        token_data = json.dumps({"token": safe_content})
                                        yield f"data: {token_data}\n\n"
                                    safe_to_stream_pos = safe_end
                                    stream_buffer = accumulated_response[safe_to_stream_pos:]

                                # Process any new tool calls found
                                for tool_call, start, end in tool_calls:
                                    tool_signature = json.dumps(tool_call, sort_keys=True)

                                    # Skip if already processed
                                    if tool_signature in processed_tool_signatures:
                                        continue

                                    processed_tool_signatures.add(tool_signature)
                                    safe_to_stream_pos = end  # Skip over the tool call JSON
                                    stream_buffer = accumulated_response[safe_to_stream_pos:]

                                    # Send tool call notification IMMEDIATELY
                                    tool_call_notification = json.dumps({
                                        "tool_call": {
                                            "tool": tool_call.get("tool"),
                                            "args": tool_call.get("args"),
                                        }
                                    })
                                    yield f"data: {tool_call_notification}\n\n"
                                    logger.info("Tool call detected during stream", tool=tool_call.get("tool"))

                                    # Execute tool IMMEDIATELY
                                    result_text, result, tool_name, args = await execute_and_yield_tool(tool_call)

                                    # Check if permission required
                                    if result.get("permission_required"):
                                        permission_data = json.dumps({
                                            "permission_request": {
                                                "command": result.get("command"),
                                                "full_command": result.get("full_command"),
                                                "tool": tool_name,
                                                "message": result.get("message"),
                                            }
                                        })
                                        yield f"data: {permission_data}\n\n"
                                        tool_results.append({
                                            "tool": tool_name,
                                            "result": f"⚠️ Permission required to run command: {result.get('command')}\n\nThis command needs your approval before it can be executed.",
                                        })
                                        continue

                                    # Send tool execution result to frontend IMMEDIATELY
                                    tool_data = json.dumps({
                                        "tool_execution": {
                                            "tool": tool_name,
                                            "args": args,
                                            "success": result.get("success", False),
                                            "path": result.get("path"),
                                            "file": result.get("file"),
                                            "command": result.get("command"),
                                            "action": result.get("action"),
                                            "stdout": result.get("stdout"),
                                            "stderr": result.get("stderr"),
                                            "content": result.get("content"),
                                            "diff": result.get("diff"),
                                            "error": result.get("error"),
                                            "return_code": result.get("return_code"),
                                            "hint": result.get("hint")
                                        }
                                    })
                                    yield f"data: {tool_data}\n\n"

                                    tool_calls_found.append({
                                        "call": tool_call,
                                        "signature": tool_signature
                                    })
                                    tool_results.append({
                                        "tool": tool_name,
                                        "result": result_text
                                    })

                            # If buffer gets too large and we're confident it's not a tool call, stream it
                            elif len(stream_buffer) > 200:
                                # Check for any tool-like patterns before streaming
                                tool_patterns = ['"tool"', "'tool'", "tool:", "{", "filesystem_", "shell_", "python_"]
                                has_tool_pattern = any(p in stream_buffer for p in tool_patterns)

                                if not has_tool_pattern:
                                    # No tool patterns at all - safe to stream everything except last 50 chars
                                    safe_amount = len(stream_buffer) - 50
                                    if safe_amount > 0:
                                        safe_content = stream_buffer[:safe_amount]
                                        token_data = json.dumps({"token": safe_content})
                                        yield f"data: {token_data}\n\n"
                                        safe_to_stream_pos += safe_amount
                                        stream_buffer = stream_buffer[safe_amount:]
                                elif brace_depth == 0 and '{' not in stream_buffer[-100:]:
                                    # Braces are balanced and no recent brace - safe to stream older content
                                    # Find the last occurrence of potential tool pattern
                                    last_tool_idx = -1
                                    for pattern in ['"tool"', "'tool'", '{"', '{']:
                                        idx = stream_buffer.rfind(pattern)
                                        if idx > last_tool_idx:
                                            last_tool_idx = idx

                                    if last_tool_idx > 0:
                                        # Only stream content before the last tool-like pattern
                                        safe_content = stream_buffer[:last_tool_idx]
                                        if safe_content.strip():
                                            token_data = json.dumps({"token": safe_content})
                                            yield f"data: {token_data}\n\n"
                                            safe_to_stream_pos += len(safe_content)
                                            stream_buffer = stream_buffer[len(safe_content):]

                # Handle any remaining pending content for Ollama reasoning models
                if is_ollama_reasoning and (pending_content or in_think_tag):
                    # If we ended while inside thinking, send the remaining as thinking and complete it
                    if in_think_tag:
                        if pending_content:
                            accumulated_reasoning += pending_content
                            thinking_data = json.dumps({"thinking_chunk": pending_content})
                            yield f"data: {thinking_data}\n\n"

                        # Send thinking_complete
                        if accumulated_reasoning and not reasoning_complete:
                            reasoning_complete = True
                            summary = accumulated_reasoning[:100] + "..." if len(accumulated_reasoning) > 100 else accumulated_reasoning
                            complete_data = json.dumps({
                                "thinking_complete": {
                                    "summary": summary,
                                    "full_content": accumulated_reasoning
                                }
                            })
                            yield f"data: {complete_data}\n\n"
                            logger.info("Thinking complete (end of stream)", reasoning_length=len(accumulated_reasoning))
                    else:
                        # Not in think tag, treat remaining as regular content
                        if pending_content:
                            accumulated_response += pending_content
                            stream_buffer += pending_content

                # After streaming completes, stream any remaining buffered content
                # (strip out any tool calls that might be in the buffer)
                if stream_buffer.strip():
                    # Check one final time for tool calls in the buffer
                    final_tool_calls = extract_tool_calls(accumulated_response)
                    buffer_start_pos = len(accumulated_response) - len(stream_buffer)

                    # Find if there are any tool calls in the buffer range
                    has_tool_in_buffer = False
                    tool_ranges = []  # Track ranges to exclude
                    for tool_call, start, end in final_tool_calls:
                        if start >= buffer_start_pos:
                            has_tool_in_buffer = True
                            tool_ranges.append((start - buffer_start_pos, end - buffer_start_pos))

                    if has_tool_in_buffer:
                        # Extract only the non-tool parts of the buffer
                        clean_parts = []
                        pos = 0
                        for tool_start, tool_end in sorted(tool_ranges):
                            if pos < tool_start:
                                clean_parts.append(stream_buffer[pos:tool_start])
                            pos = tool_end
                        if pos < len(stream_buffer):
                            clean_parts.append(stream_buffer[pos:])

                        clean_buffer = "".join(clean_parts).strip()
                    else:
                        # No tool calls - but still check for partial tool patterns
                        clean_buffer = stream_buffer.strip()

                        # Remove any obvious tool JSON patterns that weren't detected as complete
                        # Match partial tool call patterns: {"tool... or { "tool...
                        partial_pattern = r'\{\s*"tool"?\s*:?\s*[^}]*$'
                        clean_buffer = re.sub(partial_pattern, '', clean_buffer, flags=re.DOTALL)

                    if clean_buffer and clean_buffer.strip():
                        token_data = json.dumps({"token": clean_buffer.strip()})
                        yield f"data: {token_data}\n\n"

                # Get clean response for conversation history
                clean_response = strip_tool_calls(accumulated_response)

                # Add assistant response to conversation (without tool calls)
                if clean_response.strip():
                    current_messages.append({
                        "role": "assistant",
                        "content": clean_response.strip()
                    })

                # Add tool results to conversation if any tools were executed during streaming
                if tool_results:
                    # Reset consecutive lazy kicks since the model actually did something
                    consecutive_lazy_kicks = 0
                    
                    # Track read vs edit operations
                    read_tools = {'filesystem_read', 'grep', 'filesystem_list', 'filesystem_search'}
                    edit_tools = {'filesystem_write', 'filesystem_replace_lines', 'filesystem_insert', 
                                  'filesystem_search_replace', 'filesystem_delete', 'shell_execute', 'run_python'}
                    
                    for tr in tool_results:
                        tool_name = tr.get('tool', '')
                        if tool_name in read_tools:
                            read_only_operations += 1
                            task_started = True
                        elif tool_name in edit_tools:
                            edit_operations += 1
                            task_started = True
                            # Reset read counter when an edit is made
                            read_only_operations = 0
                    
                    tool_result_message = "Tool execution results:\n"
                    for tr in tool_results:
                        tool_result_message += f"\n{tr['tool']}: {tr['result']}\n"
                    
                    # HARD BLOCK: After too many reads, refuse to show results and force edit
                    if read_only_operations >= max_reads_before_block and edit_operations == 0:
                        tool_result_message = f"""
🛑 BLOCKED! {read_only_operations} READS WITH ZERO EDITS!

FURTHER READ RESULTS HIDDEN. You have seen enough.

You MUST output an edit tool call NOW. Pick one:

1. filesystem_replace_lines - Replace specific line range
   {{"tool": "filesystem_replace_lines", "args": {{"path": "file.py", "start_line": N, "end_line": M, "replacement": "fixed code"}}}}

2. filesystem_search_replace - Find and replace text
   {{"tool": "filesystem_search_replace", "args": {{"path": "file.py", "search": "broken", "replace": "fixed"}}}}

If you don't know what to fix, make your BEST GUESS based on the error message and the code you've seen.

🚫 Any further read/grep calls will return BLOCKED.
✅ Only edit tools will work now.

OUTPUT THE EDIT TOOL CALL. NOTHING ELSE."""
                        logger.warning("Agent BLOCKED from more reads, forcing edit", 
                                      read_ops=read_only_operations, edit_ops=edit_operations)
                    
                    # Nudge agent if stuck in analysis paralysis (many reads, no edits)
                    elif read_only_operations >= max_reads_before_nudge and edit_operations == 0:
                        nudge_message = f"""

⚠️ MANDATORY ACTION REQUIRED ⚠️

You've done {read_only_operations} read operations. That's ENOUGH analysis.

RULES:
1. Your NEXT output MUST be an EDIT tool call - NOT another read.
2. If you output another read/grep, it will be BLOCKED.
3. Use the file content you already have to make the fix NOW.

REQUIRED OUTPUT FORMAT (choose one):

{{"tool": "filesystem_replace_lines", "args": {{"path": "FILE", "start_line": N, "end_line": M, "replacement": "FIXED CODE"}}}}

{{"tool": "filesystem_search_replace", "args": {{"path": "FILE", "search": "BROKEN CODE", "replace": "FIXED CODE"}}}}

DO IT NOW. No more reading. No more explaining. Just the tool call."""
                        tool_result_message += nudge_message
                        logger.warning("Agent stuck in analysis paralysis, nudging to take action", 
                                      read_ops=read_only_operations, edit_ops=edit_operations)

                    current_messages.append({
                        "role": "user",
                        "content": tool_result_message
                    })

                    logger.info("Added tool results to conversation", result_count=len(tool_results), 
                               read_ops=read_only_operations, edit_ops=edit_operations)

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
                
                # No tool calls found - check if model is truly done or just being lazy
                lazy_patterns = [
                    "I'll ", "I will ", "Let me ", "I'm going to ", "I need to ",
                    "First, let me", "First I'll", "Now I'll", "Next I'll",
                    "I should ", "I can ", "I want to ", "I would like to ",
                    "Let's ", "We need to ", "We should ",
                ]
                response_lower = clean_response.strip().lower()
                response_text = clean_response.strip()

                # Check if response ends with lazy intent but no action
                is_lazy = any(pattern.lower() in response_lower for pattern in lazy_patterns)
                ends_with_colon = response_text.rstrip().endswith(':')
                
                # Only check the last 500 chars for lazy patterns (not the whole response)
                last_part = response_text[-500:] if len(response_text) > 500 else response_text
                is_lazy_ending = any(pattern.lower() in last_part.lower() for pattern in lazy_patterns)

                if (is_lazy_ending or ends_with_colon) and consecutive_lazy_kicks < max_lazy_kicks:
                    # Agent said it would do something but didn't - kick it to continue
                    lazy_kick_count += 1
                    consecutive_lazy_kicks += 1
                    logger.warning("Detected lazy response without tool call, forcing continuation",
                                   text_preview=response_text[:100], kick_count=lazy_kick_count, consecutive=consecutive_lazy_kicks)

                    kick_message = """🚨 STOP! You said you would do something but didn't actually do it!

Your last message ended with an intent like "I'll..." or "Let me..." but you didn't output any tool call.

YOU MUST OUTPUT A TOOL CALL RIGHT NOW. Do not explain, do not describe - just output the JSON:
{"tool": "...", "args": {...}}

If you were going to read a file, READ IT NOW.
If you were going to edit a file, EDIT IT NOW.
If you were going to insert code, INSERT IT NOW.

DO NOT RESPOND WITH TEXT. ONLY OUTPUT THE TOOL CALL JSON."""

                    current_messages.append({
                        "role": "user",
                        "content": kick_message
                    })

                    # Continue loop to force the model to actually do something
                    continue

                if consecutive_lazy_kicks >= max_lazy_kicks:
                    logger.warning("Max consecutive lazy kicks reached, ending conversation", consecutive=consecutive_lazy_kicks)

                # CRITICAL: Don't stop if we've only been reading and haven't made edits!
                # This prevents the agent from giving up before completing the task.
                if edit_operations == 0 and read_only_operations > 0 and iteration < max_iterations - 1:
                    logger.warning("Agent stopping without making any edits! Forcing continuation.",
                                  read_ops=read_only_operations, edit_ops=edit_operations)
                    
                    force_edit_message = f"""🛑 STOP! You have NOT completed the task!

You've read {read_only_operations} files but made ZERO edits. The user asked you to FIX something, not just analyze it.

Your response talked about what you found, but you MUST now take action.

DO NOT respond with text. Output a tool call to make the fix:

{{"tool": "filesystem_replace_lines", "args": {{"path": "FILENAME", "start_line": X, "end_line": Y, "replacement": "FIXED CODE"}}}}

or

{{"tool": "filesystem_search_replace", "args": {{"path": "FILENAME", "search": "OLD_TEXT", "replace": "NEW_TEXT"}}}}

MAKE THE EDIT NOW. NO MORE EXPLANATIONS."""

                    current_messages.append({
                        "role": "user", 
                        "content": force_edit_message
                    })
                    continue
                
                logger.info("No tool calls found, conversation complete", edit_ops=edit_operations, read_ops=read_only_operations)
                break
            
            # Check if we're approaching or hit the limit
            if iteration >= max_iterations - 5 and iteration < max_iterations:
                # Warn user we're approaching the limit
                warning_data = json.dumps({
                    "iteration_warning": {
                        "current": iteration,
                        "max": max_iterations,
                        "remaining": max_iterations - iteration,
                        "message": f"Agent is using many iterations ({iteration}/{max_iterations}). Complex task in progress..."
                    }
                })
                yield f"data: {warning_data}\n\n"
                
            if iteration >= max_iterations:
                logger.warning("Reached max iterations", max_iterations=max_iterations)
                yield f"data: {json.dumps({'error': 'Reached maximum iteration limit', 'iteration': iteration, 'max_iterations': max_iterations})}\n\n"

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
