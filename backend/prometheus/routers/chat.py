import json
import asyncio
import os
import re
from pathlib import Path
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

# ReAct intelligence services (Phase 1)
from prometheus.services.task_planner import TaskPlannerService, TaskComplexity
from prometheus.services.self_corrector import SelfCorrectorService
from prometheus.services.prompt_builder import PromptBuilder, TaskType
from prometheus.services.react_executor import ReActExecutor

# Code quality services (Phase 2)
from prometheus.services.code_validator import CodeValidatorService, ValidationStage
from prometheus.services.verification_loop import VerificationLoopService
from prometheus.services.incremental_builder import IncrementalBuilderService, CodeSection, SectionType
from prometheus.services.smart_editor import SmartEditorService
from prometheus.services.checkpoint_service import CheckpointService

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


def extract_tool_calls(text: str, log_results: bool = False) -> list[tuple[dict, int, int]]:
    """Extract tool calls from model response with their positions.
    
    Uses multiple strategies to find tool calls in model output.
    
    Args:
        text: The model response text to parse
        log_results: Whether to log extraction results (only set True for final extraction)
    
    Returns list of tuples: (tool_call_dict, start_index, end_index)
    """
    import structlog
    logger = structlog.get_logger()
    
    tool_calls = []
    truncation_detected = False
    
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
                                        tool_calls.append((tool_call, start, j+1))
                            except json.JSONDecodeError as e:
                                # JSON parsing failed - try to repair it
                                # This commonly happens when models generate unescaped content
                                tool_name_match = re.search(r'"tool"\s*:\s*"([^"]+)"', json_str)
                                tool_name = tool_name_match.group(1) if tool_name_match else None
                                
                                if tool_name:
                                    # Try to manually extract the tool call
                                    write_tools = {'filesystem_write', 'filesystem_replace_lines', 
                                                   'filesystem_insert', 'filesystem_search_replace'}
                                    
                                    if tool_name in write_tools:
                                        # Extract path
                                        path_match = re.search(r'"path"\s*:\s*"([^"]+)"', json_str)
                                        path = path_match.group(1) if path_match else None
                                        
                                        if path:
                                            # Extract content using the same logic as truncation repair
                                            content_key = "content" if tool_name == "filesystem_write" else "replacement"
                                            content_pattern = rf'"{content_key}"\s*:\s*"'
                                            content_match = re.search(content_pattern, json_str)
                                            
                                            if content_match:
                                                content_start = content_match.end()
                                                content = ""
                                                i = content_start
                                                while i < len(json_str) - 2:  # -2 to leave room for closing braces
                                                    char = json_str[i]
                                                    if char == '\\' and i + 1 < len(json_str):
                                                        next_char = json_str[i + 1]
                                                        if next_char == 'n':
                                                            content += '\n'
                                                        elif next_char == 't':
                                                            content += '\t'
                                                        elif next_char == 'r':
                                                            content += '\r'
                                                        elif next_char == '"':
                                                            content += '"'
                                                        elif next_char == '\\':
                                                            content += '\\'
                                                        else:
                                                            content += char + next_char
                                                        i += 2
                                                    elif char == '"':
                                                        # End of string (unescaped quote)
                                                        break
                                                    else:
                                                        content += char
                                                        i += 1
                                                
                                                if content:
                                                    # Build repaired tool call
                                                    if tool_name == "filesystem_write":
                                                        repaired_tool = {"tool": tool_name, "args": {"path": path, "content": content}}
                                                    elif tool_name == "filesystem_replace_lines":
                                                        start_line_match = re.search(r'"start_line"\s*:\s*(\d+)', json_str)
                                                        end_line_match = re.search(r'"end_line"\s*:\s*(\d+)', json_str)
                                                        start_line = int(start_line_match.group(1)) if start_line_match else 1
                                                        end_line = int(end_line_match.group(1)) if end_line_match else 9999
                                                        repaired_tool = {"tool": tool_name, "args": {"path": path, "start_line": start_line, "end_line": end_line, "replacement": content}}
                                                    else:
                                                        repaired_tool = {"tool": tool_name, "args": {"path": path, content_key: content}}
                                                    
                                                    logger.info(
                                                        "REPAIRED malformed JSON tool call",
                                                        tool=tool_name,
                                                        path=path,
                                                        content_length=len(content),
                                                        original_error=str(e)
                                                    )
                                                    already_found = any(tc[1] == start for tc in tool_calls)
                                                    if not already_found:
                                                        tool_calls.append((repaired_tool, start, j+1))
                                    else:
                                        # For non-write tools, log the error for debugging
                                        if log_results:
                                            logger.warning(
                                                "JSON parse failed for tool call",
                                                tool=tool_name,
                                                error=str(e),
                                                json_start=json_str[:100] if len(json_str) > 100 else json_str
                                            )
                            break
                j += 1
            
            # Check if we reached the end without finding closing brace (truncated JSON)
            if j >= len(text) and brace_count > 0:
                truncation_detected = True
                tool_name_match = re.search(r'"tool"\s*:\s*"([^"]+)"', text[start:])
                tool_name = tool_name_match.group(1) if tool_name_match else "unknown"
                
                if log_results:
                    logger.warning(
                        "TRUNCATED JSON DETECTED - model output was cut off",
                        tool=tool_name,
                        brace_depth=brace_count,
                        text_length=len(text),
                        hint="Model likely hit max_tokens limit."
                    )
                
                # CRITICAL FIX: Try to repair truncated file write tool calls
                # These are the most common to get truncated due to large content
                write_tools = {'filesystem_write', 'filesystem_replace_lines', 'filesystem_insert', 'filesystem_search_replace'}
                if tool_name in write_tools:
                    truncated_json = text[start:]
                    try:
                        # Extract path - look for "path": "..." pattern
                        path_match = re.search(r'"path"\s*:\s*"([^"]+)"', truncated_json)
                        path = path_match.group(1) if path_match else None
                        
                        if path:
                            # Extract content - this is the tricky part
                            # For filesystem_write, look for "content": "..."
                            # For filesystem_replace_lines, look for "replacement": "..."
                            content_key = "content" if tool_name == "filesystem_write" else "replacement"
                            content_pattern = rf'"{content_key}"\s*:\s*"'
                            content_match = re.search(content_pattern, truncated_json)
                            
                            if content_match:
                                content_start = content_match.end()
                                # Find all content until the end, handling escape sequences
                                content = ""
                                i = content_start
                                while i < len(truncated_json):
                                    char = truncated_json[i]
                                    if char == '\\' and i + 1 < len(truncated_json):
                                        # Handle escape sequences
                                        next_char = truncated_json[i + 1]
                                        if next_char == 'n':
                                            content += '\n'
                                        elif next_char == 't':
                                            content += '\t'
                                        elif next_char == '"':
                                            content += '"'
                                        elif next_char == '\\':
                                            content += '\\'
                                        else:
                                            content += char + next_char
                                        i += 2
                                    elif char == '"':
                                        # End of string (unescaped quote)
                                        break
                                    else:
                                        content += char
                                        i += 1
                                
                                if content and path:
                                    # Build repaired tool call
                                    if tool_name == "filesystem_write":
                                        repaired_tool = {"tool": tool_name, "args": {"path": path, "content": content}}
                                    elif tool_name == "filesystem_replace_lines":
                                        # Extract start_line and end_line
                                        start_line_match = re.search(r'"start_line"\s*:\s*(\d+)', truncated_json)
                                        end_line_match = re.search(r'"end_line"\s*:\s*(\d+)', truncated_json)
                                        start_line = int(start_line_match.group(1)) if start_line_match else 1
                                        end_line = int(end_line_match.group(1)) if end_line_match else 9999
                                        repaired_tool = {"tool": tool_name, "args": {"path": path, "start_line": start_line, "end_line": end_line, "replacement": content}}
                                    else:
                                        repaired_tool = {"tool": tool_name, "args": {"path": path, content_key: content}}
                                    
                                    if log_results:
                                        logger.info(
                                            "REPAIRED truncated tool call",
                                            tool=tool_name,
                                            path=path,
                                            content_length=len(content)
                                        )
                                    tool_calls.append((repaired_tool, start, len(text)))
                    except Exception as e:
                        if log_results:
                            logger.error("Failed to repair truncated tool call", tool=tool_name, error=str(e))
    
    # Strategy 2: Try to find JSON objects that look like tool calls using simple search
    if not tool_calls:
        from prometheus.services.tool_registry import get_registry
        
        registry = get_registry()
        tool_names = registry.get_tool_names()
        for tool_name in tool_names:
            idx = text.find(f'"tool": "{tool_name}"')
            if idx == -1:
                idx = text.find(f'"tool":"{tool_name}"')
            
            if idx != -1:
                brace_start = text.rfind('{', 0, idx)
                if brace_start != -1:
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
                                                tool_calls.append((tool_call, brace_start, j+1))
                                    except json.JSONDecodeError as e:
                                        # Same repair logic for Strategy 2
                                        write_tools = {'filesystem_write', 'filesystem_replace_lines', 
                                                       'filesystem_insert', 'filesystem_search_replace'}
                                        if tool_name in write_tools:
                                            path_match = re.search(r'"path"\s*:\s*"([^"]+)"', json_str)
                                            path = path_match.group(1) if path_match else None
                                            if path:
                                                content_key = "content" if tool_name == "filesystem_write" else "replacement"
                                                content_pattern = rf'"{content_key}"\s*:\s*"'
                                                content_match = re.search(content_pattern, json_str)
                                                if content_match:
                                                    content_start = content_match.end()
                                                    content = ""
                                                    i = content_start
                                                    while i < len(json_str) - 2:
                                                        char = json_str[i]
                                                        if char == '\\' and i + 1 < len(json_str):
                                                            next_char = json_str[i + 1]
                                                            if next_char == 'n':
                                                                content += '\n'
                                                            elif next_char == 't':
                                                                content += '\t'
                                                            elif next_char == 'r':
                                                                content += '\r'
                                                            elif next_char == '"':
                                                                content += '"'
                                                            elif next_char == '\\':
                                                                content += '\\'
                                                            else:
                                                                content += char + next_char
                                                            i += 2
                                                        elif char == '"':
                                                            break
                                                        else:
                                                            content += char
                                                            i += 1
                                                    if content:
                                                        if tool_name == "filesystem_write":
                                                            repaired_tool = {"tool": tool_name, "args": {"path": path, "content": content}}
                                                        elif tool_name == "filesystem_replace_lines":
                                                            start_line_match = re.search(r'"start_line"\s*:\s*(\d+)', json_str)
                                                            end_line_match = re.search(r'"end_line"\s*:\s*(\d+)', json_str)
                                                            start_line = int(start_line_match.group(1)) if start_line_match else 1
                                                            end_line = int(end_line_match.group(1)) if end_line_match else 9999
                                                            repaired_tool = {"tool": tool_name, "args": {"path": path, "start_line": start_line, "end_line": end_line, "replacement": content}}
                                                        else:
                                                            repaired_tool = {"tool": tool_name, "args": {"path": path, content_key: content}}
                                                        logger.info("REPAIRED malformed JSON (Strategy 2)", tool=tool_name, path=path, content_length=len(content))
                                                        already_found = any(tc[1] == brace_start for tc in tool_calls)
                                                        if not already_found:
                                                            tool_calls.append((repaired_tool, brace_start, j+1))
                                    break
                        j += 1
    
    # Only log on final extraction (not during streaming checks)
    if log_results:
        if truncation_detected and not tool_calls:
            logger.error("Tool extraction failed due to truncation", found=0)
        elif tool_calls:
            logger.info("Tool extraction complete", found=len(tool_calls), tools=[tc[0].get("tool") for tc in tool_calls])
    
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

    # System prompt - emphasizing parallel tool calls and key tools
    system_prompt = """You are Prometheus, an expert AI coding assistant.

🚀 PARALLEL TOOL CALLING (CRITICAL - USE THIS!):
You can output MULTIPLE tool calls in a SINGLE response! When you need to do multiple independent operations, output ALL tool calls at once:

{{"tool": "codebase_search", "args": {{"query": "authentication logic", "limit": 10}}}}
{{"tool": "glob_search", "args": {{"pattern": "**/*.py", "path": "."}}}}
{{"tool": "filesystem_list", "args": {{"path": "."}}}}

All three will execute IN PARALLEL. This is MUCH faster than calling one at a time!

🔍 TIER 1 TOOLS (USE FIRST - HIGHEST PRIORITY):
• codebase_search: SEMANTIC SEARCH - finds code by meaning, not just text matching
  Use FIRST when exploring a codebase or finding where something is implemented
  Example: {{"tool": "codebase_search", "args": {{"query": "where is user authentication handled", "limit": 10}}}}

• read_diagnostics: LINTER ERROR CHECK - shows syntax errors, type errors, undefined variables
  Use AFTER EVERY EDIT to verify your changes don't introduce errors
  Example: {{"tool": "read_diagnostics", "args": {{"path": "file.py"}}}}

AVAILABLE TOOLS:
{tools_text}

TOOL FORMAT:
{{"tool": "TOOL_NAME", "args": {{"param": "value"}}}}

WORKFLOW FOR EXPLORING CODE:
1. Use codebase_search FIRST to find relevant code by meaning
2. Use grep for exact text/pattern matching
3. Use filesystem_read to read specific files you found
4. Make edits with filesystem_replace_lines or filesystem_search_replace
5. Use read_diagnostics AFTER edits to check for errors

WORKFLOW FOR FIXING BUGS:
1. Read the file with the error
2. Make the fix with filesystem_replace_lines
3. Run read_diagnostics to verify no new errors
4. Done!

CRITICAL RULES:
1. USE PARALLEL TOOL CALLS! Output multiple {{"tool":...}} in one response when operations are independent
2. Use codebase_search FIRST to understand code semantically
3. Use read_diagnostics AFTER EVERY EDIT - this is mandatory
4. Don't say "I'll do X" without actually doing it - include the tool call
5. After reading 1-2 files, START EDITING. Don't over-analyze.
6. Complete the task fully before summarizing

⚠️ FILE CREATION BEST PRACTICES (PREVENT SYNTAX ERRORS!):

📝 PYTHON FILES - CRITICAL RULES:
1. ALWAYS use 4 spaces for indentation (NEVER tabs)
2. ALWAYS close all brackets (), [], {{}}, quotes "", and docstrings \"\"\" 
3. ALWAYS end function/class definitions with a colon :
4. When creating test files, keep them SHORT (under 100 lines per file)
5. If a syntax error occurs, you will get a detailed error with line numbers - FIX IT, don't re-read the file

🔧 CHUNKED FILE CREATION (for files > 100 lines):
Instead of writing one massive file, build incrementally:

Step 1 - Create skeleton:
{{"tool": "filesystem_write", "args": {{"path": "myfile.py", "content": "#!/usr/bin/env python3\\n\\\"\\\"\\\"Module docstring\\\"\\\"\\\"\\n\\nimport unittest\\n\\n# TODO: Add TestClass1\\n# TODO: Add TestClass2\\n"}}}}

Step 2 - Add first class:
{{"tool": "filesystem_replace_lines", "args": {{"path": "myfile.py", "start_line": 6, "end_line": 6, "replacement": "class TestClass1(unittest.TestCase):\\n    def test_example(self):\\n        self.assertTrue(True)\\n\\n# TODO: Add TestClass2"}}}}

Step 3 - Add second class:
{{"tool": "filesystem_replace_lines", "args": {{"path": "myfile.py", "start_line": 10, "end_line": 10, "replacement": "class TestClass2(unittest.TestCase):\\n    def test_another(self):\\n        self.assertEqual(1, 1)"}}}}

This approach:
- Prevents truncation (JSON won't be cut off)  
- Validates syntax at each step
- Makes debugging easier if something fails
- Allows recovery without rewriting everything

🚫 COMMON MISTAKES TO AVOID:
- DON'T use triple backticks ``` in file content - use actual code
- DON'T copy-paste markdown code blocks - extract the code only
- DON'T include line numbers in file content (1|, 2|, etc.)
- DON'T mix tabs and spaces
- DON'T forget newlines (\\n) between definitions
- DON'T write 500+ line files in one call - WILL FAIL

✅ ESCAPE SEQUENCES IN JSON:
When writing files, remember these escapes:
- Newline: \\n
- Tab: \\t  
- Backslash: \\\\
- Double quote: \\\"
- Single quotes don't need escaping in JSON: '

⚠️ FILE SIZE LIMITS:
When writing or creating files, keep each file under 150 lines in a SINGLE tool call.
If a file needs to be larger, use the chunked approach above.
NEVER output a single file with 300+ lines - it will timeout and fail!""".format(tools_text=tools_text)

    # Inject user-defined rules
    rules_text = await get_enabled_rules_text(request.workspace_path or "")
    
    # Inject relevant memories based on conversation context
    # Extract keywords from recent messages for memory relevance
    context_keywords = " ".join([msg.content[:200] for msg in request.messages[-3:]])
    memories_text = await get_memories_text(
        workspace_path=request.workspace_path,
        context=context_keywords,
    )
    
    # Feature flags for Phase 1 (ReAct intelligence)
    ENABLE_REACT_LOOP = os.getenv("ENABLE_REACT_LOOP", "false").lower() == "true"
    ENABLE_PROMPT_BUILDER = os.getenv("ENABLE_PROMPT_BUILDER", "false").lower() == "true"
    ENABLE_TASK_PLANNING = os.getenv("ENABLE_TASK_PLANNING", "false").lower() == "true"

    # Feature flags for Phase 2 (Code quality)
    ENABLE_CODE_VALIDATION = os.getenv("ENABLE_CODE_VALIDATION", "false").lower() == "true"
    ENABLE_VERIFICATION_LOOP = os.getenv("ENABLE_VERIFICATION_LOOP", "false").lower() == "true"
    ENABLE_INCREMENTAL_BUILDER = os.getenv("ENABLE_INCREMENTAL_BUILDER", "false").lower() == "true"
    ENABLE_SMART_EDITOR = os.getenv("ENABLE_SMART_EDITOR", "false").lower() == "true"

    # Build system prompt (with PromptBuilder if enabled)
    if ENABLE_PROMPT_BUILDER:
        prompt_builder = PromptBuilder()
        task_type = prompt_builder.detect_task_type([msg.model_dump() for msg in request.messages])
        full_system_prompt = prompt_builder.build(
            task_type=task_type,
            model=request.model,
            tools_description=tools_text,
            rules_text=rules_text,
            memories_text=memories_text
        )
        logger.info("Using PromptBuilder", task_type=task_type.value)
    else:
        # Original prompt building
        full_system_prompt = system_prompt + rules_text + memories_text

    messages_with_system = [{"role": "system", "content": full_system_prompt}]
    messages_with_system.extend([msg.model_dump() for msg in request.messages])

    # Check context usage and apply compression if needed
    messages_to_use, context_info = await check_and_compress_if_needed(
        messages=messages_with_system,
        model=request.model,
        auto_compress=True
    )

    # Task planning phase (if enabled)
    execution_plan = None
    if ENABLE_TASK_PLANNING:
        try:
            task_planner = TaskPlannerService(model_router=model_router)

            # Get user's task from last message
            user_task = request.messages[-1].content if request.messages else ""

            # Analyze complexity
            complexity = await task_planner.analyze_complexity(user_task)

            # Create execution plan
            execution_plan = await task_planner.create_plan(
                task=user_task,
                complexity=complexity,
                context={"workspace_path": request.workspace_path}
            )

            logger.info(
                "Task plan created",
                plan_id=execution_plan.plan_id,
                complexity=complexity.value,
                steps=len(execution_plan.steps),
                approval_required=execution_plan.approval_required
            )

            # TODO: Send plan to frontend and wait for approval if needed
            # For now, just log it

        except Exception as e:
            logger.error("Task planning failed", error=str(e))
            execution_plan = None

    async def event_generator():
        """Multi-turn conversation loop that continues until model is done."""
        import structlog
        logger = structlog.get_logger()

        # Send context information to frontend
        context_data = json.dumps({"context_info": context_info})
        yield f"data: {context_data}\n\n"

        # Maintain conversation state (use compressed messages)
        current_messages = messages_to_use.copy()
        max_iterations = 50  # Blocking logic prevents infinite loops, so 50 iterations is sufficient
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
        file_read_attempts: dict[str, int] = {}  # Track how many times agent tried to read SAME file
        total_blocked_reads = 0  # Total blocked read attempts across all files
        max_blocked_reads = 10  # Abort conversation after this many blocked reads
        consecutive_blocked_reads = 0  # Track consecutive blocks without progress
        max_consecutive_blocked = 3  # Abort if agent makes 3 blocked reads in a row
        
        # Cross-iteration deduplication for edits (prevent same edit being made multiple times)
        completed_edits = set()  # Track (path, start_line, end_line, content_hash) tuples
        
        # Incremental checkpointing - track successful tool executions and modified files
        successful_tool_count = 0
        modified_files = set()  # Files that have been edited in this session
        
        # Track stream retries to prevent infinite retry loops
        empty_stream_retries = 0
        max_empty_stream_retries = 3  # Max consecutive empty streams before giving up
        
        # CRITICAL: Track syntax errors to detect fix loops
        # If agent keeps generating syntax errors for the same file, we need to intervene
        syntax_error_counts: dict[str, int] = {}  # path -> count of syntax errors
        max_syntax_errors_per_file = 3  # After this many, provide detailed guidance
        total_syntax_errors = 0  # Total across all files
        max_total_syntax_errors = 8  # Abort if too many syntax errors overall
        last_syntax_error_file: str | None = None  # Track last file with syntax error
        consecutive_syntax_errors = 0  # Track consecutive syntax errors (reset on success)

        # ===== PHASE 2 CODE QUALITY SERVICES INITIALIZATION =====
        # Initialize Phase 2 services if enabled
        code_validator = None
        verification_loop = None
        incremental_builder = None
        smart_editor = None

        # Translate workspace path for Phase 2 services
        translated_workspace = translate_host_path_to_container(
            request.workspace_path or settings.workspace_path
        )

        # Create code validator if any code quality service is enabled
        if ENABLE_CODE_VALIDATION or ENABLE_VERIFICATION_LOOP or ENABLE_INCREMENTAL_BUILDER:
            logger.info("Code validator created for code quality services")
            code_validator = CodeValidatorService(workspace_path=translated_workspace)

        if ENABLE_VERIFICATION_LOOP:
            logger.info("Verification loop enabled")
            verification_loop = VerificationLoopService(code_validator=code_validator, workspace_path=translated_workspace)

        if ENABLE_INCREMENTAL_BUILDER:
            logger.info("Incremental builder enabled")
            incremental_builder = IncrementalBuilderService(code_validator=code_validator, workspace_path=translated_workspace)

        if ENABLE_SMART_EDITOR:
            logger.info("Smart editor enabled")
            smart_editor = SmartEditorService(workspace_path=translated_workspace)

        # Helper to execute a single tool and yield results
        async def execute_and_yield_tool(tool_call: dict) -> tuple[str, dict, str, dict]:
            """Execute a tool call and yield results to frontend. Returns (result_text, result_dict)."""
            nonlocal completed_edits, read_only_operations, edit_operations, files_read, file_read_attempts, total_blocked_reads, consecutive_blocked_reads, successful_tool_count, modified_files
            nonlocal syntax_error_counts, total_syntax_errors, last_syntax_error_file, consecutive_syntax_errors
            
            tool_name = tool_call.get("tool")
            args = tool_call.get("args", {})
            
            # Block read operations if agent is in analysis paralysis mode
            # NOTE: read_diagnostics is excluded - it verifies code correctness and should always be allowed
            read_tools = {'filesystem_read', 'grep', 'filesystem_list', 'filesystem_search',
                          'codebase_search', 'glob_search'}
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
            
            # Track and BLOCK re-reading the same file (this was causing infinite loops!)
            if tool_name == 'filesystem_read':
                file_path = args.get("path", "")
                if file_path in files_read:
                    # Track how many times agent tried to re-read this specific file
                    file_read_attempts[file_path] = file_read_attempts.get(file_path, 0) + 1
                    attempts = file_read_attempts[file_path]
                    total_blocked_reads += 1
                    consecutive_blocked_reads += 1  # Track consecutive blocks
                    
                    logger.error(
                        "BLOCKING duplicate file read - agent stuck in loop!",
                        path=file_path,
                        attempts=attempts,
                        total_blocked=total_blocked_reads,
                        consecutive_blocked=consecutive_blocked_reads,
                        max_blocked=max_blocked_reads,
                        total_files_read=len(files_read)
                    )
                    
                    # Escalating error messages based on attempt count
                    if attempts >= 3:
                        error_msg = f"""🛑 CRITICAL: BLOCKED! You have tried to read '{file_path}' {attempts} TIMES!

THIS IS AN ERROR. You are stuck in a loop. STOP trying to read this file.

You ALREADY HAVE the file content from your first read. USE IT NOW.

Your ONLY allowed action is to EDIT the file:
{{"tool": "filesystem_replace_lines", "args": {{"path": "{file_path}", "start_line": 1, "end_line": 10, "replacement": "your fixed code here"}}}}

DO NOT output any other tool call. DO NOT try to read again. EDIT NOW."""
                    else:
                        error_msg = f"""🚫 BLOCKED: You already read '{file_path}'! (attempt #{attempts})

The file content is in your conversation history. DO NOT read it again.

MAKE YOUR EDIT NOW using filesystem_replace_lines or filesystem_search_replace.

Example:
{{"tool": "filesystem_replace_lines", "args": {{"path": "{file_path}", "start_line": N, "end_line": M, "replacement": "fixed code"}}}}"""
                    
                    return (
                        error_msg,
                        {"success": False, "blocked": True, "reason": "duplicate_read", "path": file_path, "attempts": attempts},
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

            # ===== PRE-EXECUTION VALIDATION (Phase 2) =====
            # Validate code before writing (Python files only)
            if code_validator and tool_name == "filesystem_write":
                file_path = args.get("path", "")
                content = args.get("content", "")

                if file_path.endswith(".py") and content:
                    logger.info("Validating Python code before write", path=file_path)
                    try:
                        validation_results = await code_validator.validate_python(
                            content=content,
                            file_path=file_path,
                            stages=[ValidationStage.SYNTAX, ValidationStage.FORMATTING]
                        )

                        # Check for blocking errors
                        blocking_errors = [r for r in validation_results if not r.passed and r.level == "error"]
                        if blocking_errors:
                            # Auto-fix if available
                            fixed_result = next((r for r in validation_results if r.auto_fixed_content), None)
                            if fixed_result:
                                logger.info("Auto-fixed validation errors", path=file_path)
                                args["content"] = fixed_result.auto_fixed_content
                            else:
                                logger.warning("Validation failed", path=file_path, errors=len(blocking_errors))
                    except Exception as e:
                        logger.error("Validation failed", path=file_path, error=str(e))

            # Execute tool
            from prometheus.services.tool_registry import get_registry
            registry = get_registry()
            translated_workspace = translate_host_path_to_container(
                request.workspace_path or settings.workspace_path
            )
            # Execute tool with timeout
            try:
                result = await asyncio.wait_for(
                    registry.execute_tool(
                        name=tool_name,
                        args=args,
                        context={"workspace_path": translated_workspace, "mcp_tools": mcp_tools},
                    ),
                    timeout=60.0  # 60 second timeout per tool execution
                )
            except asyncio.TimeoutError:
                logger.error("Tool execution timed out", tool=tool_name, timeout=60)
                result = {
                    "success": False,
                    "error": f"Tool {tool_name} timed out after 60 seconds. The operation may be too complex or stuck. Try a simpler approach.",
                    "timeout": True
                }

            logger.info("Tool execution result", tool=tool_name, success=result.get("success", False))

            # Reset consecutive blocked reads on successful tool execution (agent made progress)
            if result.get("success") and not result.get("blocked"):
                consecutive_blocked_reads = 0
                consecutive_syntax_errors = 0  # Also reset syntax error streak
                
                # Increment successful tool count and track modified files
                successful_tool_count += 1
                edit_tools = {'filesystem_write', 'filesystem_replace_lines', 'filesystem_insert', 'filesystem_search_replace'}
                if tool_name in edit_tools:
                    file_path = args.get("path", "")
                    if file_path:
                        modified_files.add(file_path)
                
                # Create incremental checkpoint every 10 successful tool executions
                if successful_tool_count % 10 == 0 and modified_files:
                    try:
                        checkpoint_service = CheckpointService()
                        checkpoint_id = await checkpoint_service.create_checkpoint(
                            workspace_path=translated_workspace,
                            file_paths=list(modified_files),
                            description=f"Incremental checkpoint after {successful_tool_count} successful tools",
                            conversation_id=None,  # TODO: Get conversation ID if available
                            auto_prune=True,
                            keep_last=5
                        )
                        logger.info("Created incremental checkpoint", 
                                   checkpoint_id=checkpoint_id, 
                                   successful_tools=successful_tool_count,
                                   files=len(modified_files))
                    except Exception as e:
                        logger.error("Failed to create incremental checkpoint", error=str(e))

            # ===== POST-EXECUTION VERIFICATION (Phase 2) =====
            # Verify changes after successful edit
            edit_tools = {'filesystem_write', 'filesystem_replace_lines', 'filesystem_insert',
                          'filesystem_search_replace'}
            if verification_loop and result.get("success") and tool_name in edit_tools:
                file_path = args.get("path", "")
                if file_path and file_path.endswith(".py"):
                    logger.info("Verifying changes", path=file_path)
                    try:
                        verification_results = await verification_loop.verify_changes([file_path])

                        # Check for blocking issues
                        blocking_issues = []
                        warnings = []
                        for verify_result in verification_results:
                            for check in verify_result.checks:
                                if not check.passed and check.blocking:
                                    blocking_issues.append(check)
                                elif not check.passed:
                                    warnings.append(check)

                        # Add verification feedback to result
                        if blocking_issues:
                            result["verification_failed"] = True
                            result["verification_issues"] = [
                                f"{check.check_type}: {check.message}" for check in blocking_issues
                            ]
                            logger.warning("Verification blocking issues found",
                                         path=file_path, issues=len(blocking_issues))

                        if warnings:
                            result["verification_warnings"] = [
                                f"{check.check_type}: {check.message}" for check in warnings
                            ]
                            logger.info("Verification warnings found",
                                      path=file_path, warnings=len(warnings))

                    except Exception as e:
                        logger.error("Verification failed", path=file_path, error=str(e))

            # CRITICAL: Track syntax errors to detect infinite fix loops
            if result.get("syntax_error"):
                file_path = args.get("path", "unknown")
                syntax_error_counts[file_path] = syntax_error_counts.get(file_path, 0) + 1
                total_syntax_errors += 1
                consecutive_syntax_errors += 1
                last_syntax_error_file = file_path
                
                logger.warning(
                    "SYNTAX ERROR detected in tool result",
                    path=file_path,
                    count_for_file=syntax_error_counts[file_path],
                    total_errors=total_syntax_errors,
                    consecutive=consecutive_syntax_errors
                )
                
                # If too many syntax errors for this file, provide detailed guidance
                if syntax_error_counts[file_path] >= max_syntax_errors_per_file:
                    result["hint"] = f"""
🚨 CRITICAL: You have made {syntax_error_counts[file_path]} syntax errors on '{file_path}'!

You are stuck in a loop. STOP and think carefully:

1. Check your INDENTATION - Python uses 4 spaces (NOT tabs)
2. Check for UNCLOSED brackets (), [], {{}}
3. Check for UNCLOSED quotes ' or "
4. Check for MISSING colons after if/for/while/def/class
5. DO NOT copy-paste markdown code blocks - extract code only

RECOMMENDED: Delete the file and start fresh with a MINIMAL version:
{{"tool": "filesystem_delete", "args": {{"path": "{file_path}"}}}}

Then write a SMALL skeleton first and build incrementally."""

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

        # ===== REACT INTELLIGENCE INTEGRATION =====
        # Initialize ReAct services if enabled
        react_executor = None
        if ENABLE_REACT_LOOP:
            logger.info("ReAct intelligence enabled")
            self_corrector = SelfCorrectorService()
            react_executor = ReActExecutor(
                tool_registry=registry,
                self_corrector=self_corrector,
                workspace_path=translated_workspace,
                max_iterations=max_iterations
            )

        # ===== MAIN EXECUTION LOOP =====
        try:
            while iteration < max_iterations:
                iteration += 1
                
                # SAFETY: Abort if agent is stuck in a read loop
                if total_blocked_reads >= max_blocked_reads:
                    logger.error(
                        "ABORTING: Agent stuck in infinite read loop!",
                        total_blocked=total_blocked_reads,
                        files_attempted=list(file_read_attempts.keys()),
                        iteration=iteration
                    )
                    abort_data = json.dumps({
                        "error": f"Agent stuck in loop: {total_blocked_reads} blocked file re-reads. "
                                 f"The agent kept trying to read the same files instead of making edits. "
                                 f"Files: {list(file_read_attempts.keys())[:5]}",
                        "type": "read_loop_detected",
                        "blocked_reads": total_blocked_reads
                    })
                    yield f"data: {abort_data}\n\n"
                    break
                
                # SAFETY: Abort if too many syntax errors (agent stuck in fix loop)
                if total_syntax_errors >= max_total_syntax_errors:
                    logger.error(
                        "ABORTING: Agent stuck in syntax error loop!",
                        total_errors=total_syntax_errors,
                        files_with_errors=list(syntax_error_counts.keys()),
                        iteration=iteration
                    )
                    abort_data = json.dumps({
                        "error": f"Agent stuck in syntax error loop: {total_syntax_errors} syntax errors across files. "
                                 f"The agent keeps generating broken Python code. "
                                 f"Try a simpler approach or break the task into smaller steps. "
                                 f"Files with errors: {list(syntax_error_counts.keys())[:3]}",
                        "type": "syntax_loop_detected",
                        "syntax_errors": total_syntax_errors,
                        "files": dict(list(syntax_error_counts.items())[:5])
                    })
                    yield f"data: {abort_data}\n\n"
                    break
                
                # SAFETY: Also abort on consecutive blocked reads (faster detection)
                if consecutive_blocked_reads >= max_consecutive_blocked:
                    logger.error(
                        "ABORTING: Agent making consecutive blocked reads!",
                        consecutive_blocked=consecutive_blocked_reads,
                        total_blocked=total_blocked_reads,
                        iteration=iteration
                    )
                    abort_data = json.dumps({
                        "error": f"Agent stuck: {consecutive_blocked_reads} consecutive blocked reads. "
                                 f"The agent is not making progress. Consider breaking down the task.",
                        "type": "no_progress_detected",
                        "consecutive_blocks": consecutive_blocked_reads
                    })
                    yield f"data: {abort_data}\n\n"
                    break
                
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

                logger.info(
                    "Starting model stream for iteration",
                    iteration=iteration,
                    message_count=len(current_messages),
                    model=request.model,
                    model_is_reasoning=model_is_reasoning
                )

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
                
                # Track if we received any chunks from the model
                chunks_received = 0

                # Track if we've detected a tool call being generated
                detected_tool_in_progress = None
                last_progress_update = 0
                last_file_preview_update = 0
                last_preview_content_length = 0
                
                # CRITICAL: Save preview content for fallback tool execution
                # This is used when JSON parsing fails but we successfully extracted content during streaming
                preview_content_cache = []  # List[Dict[str, Any]] to support multiple tool calls in one turn
                
                async for chunk in model_router.stream(
                    model=request.model,
                    messages=current_messages,
                    api_base=request.api_base,
                    api_key=api_key_to_use,
                ):
                    chunks_received += 1
                    
                    # Try to detect tool being generated (check frequently for early preview)
                    # For reasoning models, check BOTH accumulated_response AND accumulated_reasoning
                    content_to_check = accumulated_response
                    if model_is_reasoning and accumulated_reasoning:
                        content_to_check = accumulated_reasoning + accumulated_response
                    
                    if detected_tool_in_progress is None and '{"tool"' in content_to_check:
                        # Extract the tool name from the content
                        tool_match = re.search(r'\{"tool"\s*:\s*"([^"]+)"', content_to_check)
                        if tool_match:
                            detected_tool_in_progress = tool_match.group(1)
                            logger.info("Tool generation detected", tool=detected_tool_in_progress, chunks=chunks_received,
                                       in_reasoning=('{"tool"' in accumulated_reasoning if accumulated_reasoning else False))
                            
                            # Send early preview for file write tools
                            if detected_tool_in_progress in ["filesystem_write", "filesystem_replace_lines", "filesystem_search_replace", "filesystem_insert"]:
                                # Try to get the file path early (check both response and reasoning)
                                path_match = re.search(r'"path"\s*:\s*"([^"]+)"', content_to_check)
                                file_path = path_match.group(1) if path_match else "..."
                                
                                # Detect language from file extension
                                ext = file_path.rsplit('.', 1)[-1] if '.' in file_path else ''
                                lang_map = {'py': 'python', 'js': 'javascript', 'ts': 'typescript', 'jsx': 'javascript', 'tsx': 'typescript', 'rs': 'rust', 'go': 'go', 'java': 'java', 'cpp': 'cpp', 'c': 'c', 'rb': 'ruby', 'php': 'php', 'swift': 'swift', 'kt': 'kotlin', 'scala': 'scala', 'sh': 'bash', 'bash': 'bash', 'zsh': 'bash', 'css': 'css', 'scss': 'scss', 'html': 'html', 'xml': 'xml', 'json': 'json', 'yaml': 'yaml', 'yml': 'yaml', 'md': 'markdown', 'sql': 'sql', 'svelte': 'svelte', 'vue': 'vue'}
                                detected_language = lang_map.get(ext, 'text')
                                
                                early_preview = json.dumps({
                                    "file_write_preview": {
                                        "path": file_path,
                                        "content": f"# Generating {file_path}...\n# Please wait while content streams in...",
                                        "language": detected_language,
                                        "is_complete": False,
                                        "bytes_written": 0
                                    }
                                })
                                yield f"data: {early_preview}\n\n"
                                logger.info("Sent early file preview", path=file_path, language=detected_language)
                                # Force immediate preview check on next iteration
                                last_file_preview_update = 0
                    
                    # Send progress updates to frontend every 200 chunks so user knows agent is working
                    if chunks_received - last_progress_update >= 200:
                        last_progress_update = chunks_received
                        
                        # Send progress event to frontend
                        status_msg = "Generating response..."
                        if detected_tool_in_progress:
                            if "write" in detected_tool_in_progress.lower():
                                status_msg = f"Writing file content..."
                            elif "replace" in detected_tool_in_progress.lower():
                                status_msg = f"Preparing code changes..."
                            else:
                                status_msg = f"Preparing {detected_tool_in_progress}..."
                        
                        stream_progress = json.dumps({
                            "stream_progress": {
                                "chunks": chunks_received,
                                "response_length": len(accumulated_response),
                                "status": status_msg,
                                "tool_in_progress": detected_tool_in_progress
                            }
                        })
                        yield f"data: {stream_progress}\n\n"
                        
                        logger.info(
                            "Model streaming progress",
                            iteration=iteration,
                            chunks=chunks_received,
                            response_length=len(accumulated_response),
                            detected_tool=detected_tool_in_progress
                        )
                    
                    # Stream file write preview if we're generating a file write tool
                    # Check EVERY 5 chunks for smoother real-time animation (was 10)
                    # Also check if we have content growing even if tool not detected yet
                    should_check_preview = (
                        chunks_received - last_file_preview_update >= 5 and 
                        detected_tool_in_progress in ["filesystem_write", "filesystem_replace_lines", "filesystem_search_replace", "filesystem_insert"]
                    )
                    
                    # For reasoning models, also check for content patterns even before tool is detected
                    # This enables preview to start as soon as file content appears
                    if not should_check_preview and model_is_reasoning and chunks_received - last_file_preview_update >= 5:
                        combined_content = (accumulated_reasoning or "") + (accumulated_response or "")
                        # Check for content field starting to be written
                        if '"content"' in combined_content or '"replacement"' in combined_content:
                            # Try to detect tool name if not already detected
                            if detected_tool_in_progress is None:
                                tool_match = re.search(r'"tool"\s*:\s*"([^"]+)"', combined_content)
                                if tool_match:
                                    detected_tool_in_progress = tool_match.group(1)
                                    logger.info("Late tool detection for preview", tool=detected_tool_in_progress)
                            if detected_tool_in_progress in ["filesystem_write", "filesystem_replace_lines", "filesystem_search_replace", "filesystem_insert"]:
                                should_check_preview = True
                    
                    if should_check_preview:
                        # For reasoning models, check both response and reasoning content
                        preview_content_source = accumulated_response
                        if model_is_reasoning and accumulated_reasoning:
                            preview_content_source = accumulated_reasoning + accumulated_response
                        
                        # Try to extract file path and partial content from the response
                        path_match = re.search(r'"path"\s*:\s*"([^"]+)"', preview_content_source)
                        
                        # Better content extraction - find the start of content or replacement and grab everything after
                        content_start = preview_content_source.find('"content"')
                        replacement_start = preview_content_source.find('"replacement"')
                        # Also check for "new_content" used by search_replace
                        new_content_start = preview_content_source.find('"new_content"')
                        
                        # Use whichever field is present (content for write, replacement/new_content for edit)
                        if content_start != -1:
                            field_start = content_start
                            field_name_len = 9  # len('"content"')
                        elif replacement_start != -1:
                            field_start = replacement_start
                            field_name_len = 13  # len('"replacement"')
                        elif new_content_start != -1:
                            field_start = new_content_start
                            field_name_len = 13  # len('"new_content"')
                        else:
                            field_start = -1
                            field_name_len = 0
                        
                        # Log when we can't find expected patterns (debugging)
                        if chunks_received % 100 == 0 and (not path_match or field_start == -1):
                            logger.debug(
                                "File preview: waiting for content pattern",
                                has_path=bool(path_match),
                                field_start=field_start,
                                source_len=len(preview_content_source),
                                has_content_field=('"content"' in preview_content_source),
                                has_replacement_field=('"replacement"' in preview_content_source),
                                tool=detected_tool_in_progress
                            )
                        
                        if path_match and field_start != -1:
                            file_path = path_match.group(1)
                            
                            # More robust content extraction using regex to find the content value
                            # This handles various JSON formatting (spaces, no spaces, etc.)
                            field_names = ['"content"', '"replacement"', '"new_content"']
                            field_name = field_names[0] if content_start != -1 else (field_names[1] if replacement_start != -1 else field_names[2])
                            
                            # Use regex to find the field and its value start
                            # Match: "content" followed by optional whitespace, colon, optional whitespace, and opening quote
                            content_pattern = re.escape(field_name) + r'\s*:\s*"'
                            content_match = re.search(content_pattern, preview_content_source)
                            
                            if content_match:
                                # raw_content starts right after the opening quote
                                raw_content = preview_content_source[content_match.end():]
                                
                                # FIX: Some models output malformed JSON with extra quotes at the start
                                # e.g., "content": """actual content..." (triple quotes)
                                # Skip leading quotes to find the actual content
                                skip_count = 0
                                while skip_count < len(raw_content) and raw_content[skip_count] == '"':
                                    skip_count += 1
                                if skip_count > 0:
                                    raw_content = raw_content[skip_count:]
                                    if chunks_received < 10:
                                        logger.info(
                                            "Skipped leading quotes in content",
                                            skip_count=skip_count,
                                            new_start=repr(raw_content[:50]) if len(raw_content) > 50 else repr(raw_content)
                                        )
                                
                                # Debug: log the first few characters of raw_content every 100 chunks
                                if chunks_received % 100 == 0 or chunks_received < 10:
                                    logger.info(
                                        "Raw content extraction debug",
                                        raw_start=repr(raw_content[:80]) if len(raw_content) > 80 else repr(raw_content),
                                        raw_len=len(raw_content),
                                        match_end=content_match.end(),
                                        match_group=content_match.group()
                                    )
                                
                                # Parse the JSON string, handling escape sequences
                                # NOTE: For streaming preview, we DON'T try to detect the end of the JSON string
                                # because code content has quotes, braces, commas that look like JSON endings.
                                # We just accumulate everything for the live preview - it's not meant to be perfect.
                                partial_content = ""
                                i = 0
                                while i < len(raw_content):
                                    if raw_content[i] == '\\' and i + 1 < len(raw_content):
                                        # Handle escape sequences
                                        next_char = raw_content[i + 1]
                                        if next_char == 'n':
                                            partial_content += '\n'
                                        elif next_char == 't':
                                            partial_content += '\t'
                                        elif next_char == '"':
                                            partial_content += '"'
                                        elif next_char == '\\':
                                            partial_content += '\\'
                                        elif next_char == 'r':
                                            pass  # Skip \r
                                        else:
                                            partial_content += raw_content[i:i+2]
                                        i += 2
                                    elif raw_content[i] == '"':
                                        # For streaming preview, treat unescaped quotes as literal quotes
                                        # The model often doesn't escape quotes in code content
                                        # We'll include them and continue accumulating
                                        partial_content += '"'
                                        i += 1
                                    else:
                                        partial_content += raw_content[i]
                                        i += 1
                                
                                # Log the extraction progress every 50 chunks for better debugging
                                if chunks_received % 50 == 0:
                                    # Also log first few parsed chars to debug issues
                                    first_char = repr(raw_content[0]) if raw_content else "EMPTY"
                                    logger.info(
                                        "File preview extraction progress",
                                        path=file_path,
                                        content_len=len(partial_content),
                                        last_len=last_preview_content_length,
                                        raw_len=len(raw_content),
                                        first_char=first_char,
                                        partial_preview=repr(partial_content[:30]) if partial_content else "EMPTY",
                                        is_reasoning=model_is_reasoning,
                                        reasoning_len=len(accumulated_reasoning) if accumulated_reasoning else 0
                                    )
                                
                                # Send if content has grown (at least 15 chars for more responsive updates)
                                # Reduced from 30 to be more real-time
                                if len(partial_content) > last_preview_content_length + 15:
                                    last_file_preview_update = chunks_received
                                    last_preview_content_length = len(partial_content)
                                    
                                    # Detect language from file extension
                                    ext = file_path.rsplit('.', 1)[-1] if '.' in file_path else ''
                                    lang_map = {'py': 'python', 'js': 'javascript', 'ts': 'typescript', 'jsx': 'javascript', 'tsx': 'typescript', 'rs': 'rust', 'go': 'go', 'java': 'java', 'cpp': 'cpp', 'c': 'c', 'rb': 'ruby', 'php': 'php', 'swift': 'swift', 'kt': 'kotlin', 'scala': 'scala', 'sh': 'bash', 'bash': 'bash', 'zsh': 'bash', 'css': 'css', 'scss': 'scss', 'html': 'html', 'xml': 'xml', 'json': 'json', 'yaml': 'yaml', 'yml': 'yaml', 'md': 'markdown', 'sql': 'sql', 'svelte': 'svelte', 'vue': 'vue'}
                                    language = lang_map.get(ext, 'text')
                                    
                                    logger.info(
                                        "Sending file preview update",
                                        path=file_path,
                                        content_len=len(partial_content),
                                        language=language,
                                        chunks=chunks_received
                                    )
                                    
                                    # CRITICAL: Save to cache for fallback tool execution
                                    # Use a list to support multiple tool calls for the same file in one response
                                    found_entry = False
                                    if preview_content_cache:
                                        last_entry = preview_content_cache[-1]
                                        if last_entry.get("path") == file_path and last_entry.get("tool") == detected_tool_in_progress:
                                            last_entry["content"] = partial_content
                                            found_entry = True
                                    
                                    if not found_entry:
                                        preview_content_cache.append({
                                            "path": file_path,
                                            "content": partial_content,
                                            "tool": detected_tool_in_progress
                                        })
                                    
                                    file_preview = json.dumps({
                                        "file_write_preview": {
                                            "path": file_path,
                                            "content": partial_content,
                                            "language": language,
                                            "is_complete": False,
                                            "bytes_written": len(partial_content)
                                        }
                                    })
                                    yield f"data: {file_preview}\n\n"
                    
                    if chunk.choices and chunk.choices[0].delta:
                        delta = chunk.choices[0].delta

                        # Extract reasoning content from provider_specific_fields (DeepSeek R1)
                        if hasattr(delta, 'provider_specific_fields') and delta.provider_specific_fields:
                            reasoning_chunk = delta.provider_specific_fields.get("reasoning_content", "")
                            if reasoning_chunk:
                                accumulated_reasoning += reasoning_chunk
                                # Log first reasoning chunk to confirm it's working
                                if len(accumulated_reasoning) == len(reasoning_chunk):
                                    logger.info("Started receiving reasoning content from model", model=request.model)
                                thinking_data = json.dumps({"thinking_chunk": reasoning_chunk})
                                yield f"data: {thinking_data}\n\n"
                        
                        # ALSO check for reasoning_content directly on delta (some LiteLLM versions)
                        if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                            reasoning_chunk = delta.reasoning_content
                            accumulated_reasoning += reasoning_chunk
                            if len(accumulated_reasoning) == len(reasoning_chunk):
                                logger.info("Started receiving reasoning_content (direct attr)", model=request.model)
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
                            # 4. For reasoning models, also check reasoning content for tool calls!

                            if not in_potential_json or brace_depth == 0:
                                # We're outside JSON or just closed a brace - safe to check for tools
                                # Check BOTH regular response AND reasoning content for tool calls
                                # DeepSeek Reasoner often puts tool calls in its thinking
                                tool_calls = extract_tool_calls(accumulated_response)
                                
                                # For reasoning models, ALSO check reasoning content for tool calls
                                if model_is_reasoning and accumulated_reasoning:
                                    reasoning_tool_calls = extract_tool_calls(accumulated_reasoning)
                                    if reasoning_tool_calls:
                                        logger.info("Found tool calls in reasoning content!", count=len(reasoning_tool_calls))
                                        # Merge with regular tool calls (adjust positions to indicate they're from reasoning)
                                        for tc, start, end in reasoning_tool_calls:
                                            # Use negative positions to indicate from reasoning
                                            tool_calls.append((tc, -1, -1))

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

                                # Collect tool calls for parallel execution after stream completes
                                for tool_call, start, end in tool_calls:
                                    tool_signature = json.dumps(tool_call, sort_keys=True)

                                    # Skip if already collected
                                    if tool_signature in processed_tool_signatures:
                                        continue

                                    processed_tool_signatures.add(tool_signature)
                                    safe_to_stream_pos = end  # Skip over the tool call JSON
                                    stream_buffer = accumulated_response[safe_to_stream_pos:]

                                    # Send tool call notification to frontend
                                    tool_call_notification = json.dumps({
                                        "tool_call": {
                                            "tool": tool_call.get("tool"),
                                            "args": tool_call.get("args"),
                                        }
                                    })
                                    yield f"data: {tool_call_notification}\n\n"
                                    logger.info("Tool call detected during stream", tool=tool_call.get("tool"))

                                    # Collect for parallel execution (don't execute yet)
                                    tool_calls_found.append({
                                        "call": tool_call,
                                        "signature": tool_signature
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
                
                # CRITICAL: For reasoning models, do a FINAL check for tool calls in reasoning content
                # DeepSeek Reasoner often finishes thinking before emitting tool calls
                if model_is_reasoning and accumulated_reasoning and not tool_calls_found:
                    logger.info("Reasoning model finished - checking reasoning for tool calls", 
                               reasoning_length=len(accumulated_reasoning))
                    reasoning_tool_calls = extract_tool_calls(accumulated_reasoning, log_results=True)
                    for tool_call, start, end in reasoning_tool_calls:
                        tool_signature = json.dumps(tool_call, sort_keys=True)
                        if tool_signature not in processed_tool_signatures:
                            processed_tool_signatures.add(tool_signature)
                            # Send tool call notification to frontend
                            tool_call_notification = json.dumps({
                                "tool_call": {
                                    "tool": tool_call.get("tool"),
                                    "args": tool_call.get("args"),
                                }
                            })
                            yield f"data: {tool_call_notification}\n\n"
                            logger.info("Tool call found in reasoning content (post-stream)", tool=tool_call.get("tool"))
                            tool_calls_found.append({
                                "call": tool_call,
                                "signature": tool_signature
                            })
                
                if stream_buffer.strip():
                    # Check one final time for tool calls in the buffer (with logging)
                    final_tool_calls = extract_tool_calls(accumulated_response, log_results=True)
                    buffer_start_pos = len(accumulated_response) - len(stream_buffer)

                    # Find if there are any tool calls in the buffer range
                    has_tool_in_buffer = False
                    tool_ranges = []  # Track ranges to exclude
                    for tool_call, start, end in final_tool_calls:
                        if start >= buffer_start_pos:
                            has_tool_in_buffer = True
                            tool_ranges.append((start - buffer_start_pos, end - buffer_start_pos))
                            
                            # !! CRITICAL FIX: Add these tool calls to tool_calls_found !!
                            # This was the bug - tool calls in the final buffer were detected but never executed!
                            tool_signature = json.dumps(tool_call, sort_keys=True)
                            if tool_signature not in processed_tool_signatures:
                                processed_tool_signatures.add(tool_signature)
                                logger.info("Tool call found in final buffer (will be executed)", tool=tool_call.get("tool"))
                                tool_calls_found.append({
                                    "call": tool_call,
                                    "signature": tool_signature
                                })

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

                # Log stream completion with comprehensive info for debugging
                logger.info(
                    "Model stream completed",
                    iteration=iteration,
                    chunks_received=chunks_received,
                    response_length=len(accumulated_response),
                    reasoning_length=len(accumulated_reasoning),
                    tool_calls_found=len(tool_calls_found),
                    is_reasoning_model=model_is_reasoning,
                    model=request.model
                )
                
                # Debug: If no tool calls found but we have accumulated content, log it
                if not tool_calls_found and (accumulated_response or accumulated_reasoning):
                    logger.warning(
                        "No tool calls extracted from model output",
                        response_preview=accumulated_response[:500] if accumulated_response else "empty",
                        reasoning_preview=accumulated_reasoning[:500] if accumulated_reasoning else "empty"
                    )
                
                # CRITICAL FALLBACK: Check if any previewed files are MISSING from extracted tool calls
                # This handles the case where filesystem_write JSON parsing fails but shell_execute succeeds
                if preview_content_cache:
                    # Map of (path, tool) -> count to track multiple calls for same file/tool
                    extracted_tool_counts = {}
                    for tc in tool_calls_found:
                        call = tc.get("call", {})
                        tool_name = call.get("tool", "")
                        path = call.get("args", {}).get("path", "")
                        if path and tool_name:
                            key = (path, tool_name)
                            extracted_tool_counts[key] = extracted_tool_counts.get(key, 0) + 1
                    
                    # Track what we've synthesized
                    synthesized_tool_counts = {}
                    
                    for cache_data in preview_content_cache:
                        path = cache_data.get("path")
                        tool_name = cache_data.get("tool", "filesystem_write")
                        content = cache_data.get("content", "")
                        
                        if not path or not content or len(content) < 50:
                            continue
                            
                        key = (path, tool_name)
                        extracted_count = extracted_tool_counts.get(key, 0)
                        synthesized_count = synthesized_tool_counts.get(key, 0)
                        
                        # If we have more cached entries than extracted ones, synthesize the missing ones
                        if synthesized_count + extracted_count < 1: # Basic case: missing entirely
                            # For now, just synthesize if completely missing to be safe
                            # In the future we could do synthesized_count + extracted_count < total_cached_count
                            logger.warning(
                                "CRITICAL: Previewed tool call missing from extracted list! Creating synthetic call.",
                                tool=tool_name,
                                path=path,
                                content_len=len(content)
                            )
                            
                            # Create a synthetic tool call from the cached preview
                            synthetic_tool_call = {
                                "tool": tool_name,
                                "args": {"path": path, "content": content}
                            }
                            # Add replacement-specific args for replace tools
                            if tool_name == "filesystem_replace_lines":
                                # If it's a replacement but we don't have lines, check if it looks like a full file
                                if content.startswith("#!") or "import " in content:
                                    # Full file write masquerading as replace
                                    synthetic_tool_call["args"]["start_line"] = 1
                                    synthetic_tool_call["args"]["end_line"] = 9999
                                else:
                                    # It's a fragment, but we don't know where it goes. 
                                    # THIS IS DANGEROUS. Let's try to search for where it might go?
                                    # For now, let's just NOT synthesize partial replaces as full files.
                                    logger.error("Refusing to synthesize partial replacement as full file write", path=path)
                                    continue
                                synthetic_tool_call["args"]["replacement"] = content
                                if "content" in synthetic_tool_call["args"]:
                                    del synthetic_tool_call["args"]["content"]
                            
                            tool_signature = json.dumps(synthetic_tool_call, sort_keys=True)
                            if tool_signature not in processed_tool_signatures:
                                processed_tool_signatures.add(tool_signature)
                                tool_calls_found.append({
                                    "call": synthetic_tool_call,
                                    "signature": tool_signature
                                })
                                synthesized_tool_counts[key] = synthesized_count + 1
                                logger.info(
                                    "Created SYNTHETIC tool call from preview cache (JSON parse failed)",
                                    tool=tool_name,
                                    path=path,
                                    content_length=len(content)
                                )

                # ========== HANDLE STREAM TIMEOUT/FAILURE ==========
                # If we didn't receive any chunks, the stream likely timed out or failed silently
                if chunks_received == 0:
                    empty_stream_retries += 1
                    logger.warning(
                        "Model stream returned no chunks - possible timeout or API issue",
                        iteration=iteration,
                        model=request.model,
                        message_count=len(current_messages),
                        retry_count=empty_stream_retries,
                        max_retries=max_empty_stream_retries
                    )
                    
                    if empty_stream_retries >= max_empty_stream_retries:
                        # Too many retries - give up and report error
                        error_data = json.dumps({
                            "error": f"Model failed to respond after {max_empty_stream_retries} attempts. "
                                     f"Check your API key, network connection, or try a different model.",
                            "type": "stream_failure"
                        })
                        yield f"data: {error_data}\n\n"
                        break
                    
                    # Notify frontend about the stream failure
                    stream_warning = json.dumps({
                        "warning": {
                            "type": "stream_timeout",
                            "message": f"Model did not respond (attempt {empty_stream_retries}/{max_empty_stream_retries}). Retrying...",
                            "iteration": iteration
                        }
                    })
                    yield f"data: {stream_warning}\n\n"
                    
                    # Add a brief delay before retrying to avoid hammering the API
                    await asyncio.sleep(2.0 ** empty_stream_retries)  # Exponential backoff: 2s, 4s, 8s
                    
                    # Continue to next iteration (retry the model call)
                    continue
                else:
                    # Successful stream - reset retry counter
                    empty_stream_retries = 0

                # ========== PARALLEL TOOL EXECUTION ==========
                # Execute all collected tool calls in parallel (with limits)
                if tool_calls_found:
                    import asyncio
                    
                    MAX_CONCURRENT_TOOLS = 3  # Limit concurrent tool execution
                    TOOL_TIMEOUT_SECONDS = 60  # Timeout per tool
                    
                    logger.info("Executing tool calls", count=len(tool_calls_found), max_concurrent=MAX_CONCURRENT_TOOLS)
                    
                    # Semaphore to limit concurrency
                    semaphore = asyncio.Semaphore(MAX_CONCURRENT_TOOLS)
                    
                    # Create tasks for all tool calls with semaphore and timeout
                    async def execute_single_tool(tc_info):
                        """Execute a single tool with concurrency limit and timeout."""
                        tool_call = tc_info["call"]
                        tool_name = tool_call.get("tool", "unknown")
                        
                        async with semaphore:
                            try:
                                logger.debug("Starting tool execution", tool=tool_name)
                                result_text, result, tool_name, args = await asyncio.wait_for(
                                    execute_and_yield_tool(tool_call),
                                    timeout=TOOL_TIMEOUT_SECONDS
                                )
                                logger.debug("Tool execution completed", tool=tool_name)
                                return {
                                    "tool_call": tool_call,
                                    "result_text": result_text,
                                    "result": result,
                                    "tool_name": tool_name,
                                    "args": args
                                }
                            except asyncio.TimeoutError:
                                logger.error("Tool execution timed out", tool=tool_name, timeout=TOOL_TIMEOUT_SECONDS)
                                return {
                                    "tool_call": tool_call,
                                    "result_text": f"Tool {tool_name} timed out after {TOOL_TIMEOUT_SECONDS} seconds",
                                    "result": {"success": False, "error": f"Timeout after {TOOL_TIMEOUT_SECONDS}s"},
                                    "tool_name": tool_name,
                                    "args": tool_call.get("args", {}),
                                    "timed_out": True
                                }
                    
                    # Execute all tools in parallel (limited by semaphore)
                    tasks = [execute_single_tool(tc) for tc in tool_calls_found]
                    parallel_results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    # Process results and send to frontend
                    for pr in parallel_results:
                        if isinstance(pr, Exception):
                            logger.error("Tool execution failed", error=str(pr))
                            tool_results.append({
                                "tool": "unknown",
                                "result": f"Tool execution failed: {str(pr)}"
                            })
                            continue
                        
                        # Handle timed out tools
                        if pr.get("timed_out"):
                            tool_name = pr["tool_name"]
                            args = pr["args"]
                            timeout_data = json.dumps({
                                "tool_execution": {
                                    "tool": tool_name,
                                    "args": args,
                                    "success": False,
                                    "error": pr["result_text"],
                                    "timed_out": True
                                }
                            })
                            yield f"data: {timeout_data}\n\n"
                            tool_results.append({
                                "tool": tool_name,
                                "result": pr["result_text"]
                            })
                            continue
                        
                        tool_name = pr["tool_name"]
                        args = pr["args"]
                        result = pr["result"]
                        result_text = pr["result_text"]
                        
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
                        
                        # Send tool execution result to frontend
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
                                "hint": result.get("hint"),
                                "verified": result.get("verified")  # Include verification flag
                            }
                        })
                        yield f"data: {tool_data}\n\n"
                        
                        # Send file_write_complete event for file write tools after actual execution
                        if tool_name in ["filesystem_write", "filesystem_replace_lines", "filesystem_search_replace", "filesystem_insert"]:
                            if result.get("success"):
                                logger.info("File write completed and verified", 
                                          tool=tool_name, 
                                          path=result.get("path"),
                                          verified=result.get("verified", False))
                                file_complete_data = json.dumps({
                                    "file_write_complete": {
                                        "tool": tool_name,
                                        "path": result.get("path"),
                                        "action": result.get("action"),
                                        "verified": result.get("verified", False),
                                        "success": True
                                    }
                                })
                                yield f"data: {file_complete_data}\n\n"
                            else:
                                logger.warning("File write failed", 
                                             tool=tool_name, 
                                             path=result.get("path"),
                                             error=result.get("error"))
                        
                        tool_results.append({
                            "tool": tool_name,
                            "result": result_text
                        })

                # Get clean response for conversation history
                clean_response = strip_tool_calls(accumulated_response)

                # Add assistant response to conversation (without tool calls)
                if clean_response.strip():
                    current_messages.append({
                        "role": "assistant",
                        "content": clean_response.strip()
                    })

                # Add tool results to conversation if any tools were executed
                if tool_results:
                    # Reset consecutive lazy kicks since the model actually did something
                    consecutive_lazy_kicks = 0
                    
                    # Track read vs edit operations
                    read_tools = {'filesystem_read', 'grep', 'filesystem_list', 'filesystem_search', 
                                  'codebase_search', 'glob_search', 'read_diagnostics'}
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
                
                # Check for truncated tool call JSON (model output was cut off)
                # This happens when max_tokens is hit during a large file write
                truncation_patterns = [
                    r'\{"tool"\s*:\s*"[^"]+"\s*,\s*"args"\s*:\s*\{[^}]*$',  # Tool call started but never closed
                    r'"content"\s*:\s*"[^"]*$',  # Content string never closed
                ]
                response_might_be_truncated = any(
                    re.search(p, accumulated_response[-500:] if len(accumulated_response) > 500 else accumulated_response)
                    for p in truncation_patterns
                )
                
                if response_might_be_truncated and consecutive_lazy_kicks < max_lazy_kicks:
                    consecutive_lazy_kicks += 1
                    logger.warning(
                        "Detected truncated tool call - model output was cut off",
                        response_length=len(accumulated_response),
                        consecutive=consecutive_lazy_kicks
                    )
                    
                    truncation_message = """⚠️ YOUR OUTPUT WAS TRUNCATED!

Your tool call JSON was cut off mid-stream (likely hit the output token limit).

DO NOT try to write large files in a single tool call. Instead:

1. For NEW FILES: Write in smaller chunks or use filesystem_insert multiple times
2. For EDITS: Use filesystem_replace_lines to edit specific line ranges instead of rewriting entire files
3. For TEST FILES: Create a minimal test first, then add more tests incrementally

RETRY with a SMALLER output. Example:
{"tool": "filesystem_write", "args": {"path": "test_file.py", "content": "# Basic test file\\nimport unittest\\n\\nclass TestBasic(unittest.TestCase):\\n    def test_example(self):\\n        self.assertTrue(True)\\n"}}

Keep the content SHORT. Do NOT include the full file."""
                    
                    current_messages.append({
                        "role": "user",
                        "content": truncation_message
                    })
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
            
            # CRITICAL: Even on error, try to write any previewed files
            # This ensures files shown to user actually get written
            if preview_content_cache:
                logger.warning("Writing previewed files on error cleanup", 
                              count=len(preview_content_cache))
                for cache_data in preview_content_cache:
                    try:
                        path = cache_data.get("path")
                        content = cache_data.get("content", "")
                        if content and path and len(content) > 100:  # Only if substantial content
                            translated_workspace = translate_host_path_to_container(
                                request.workspace_path or settings.workspace_path
                            )
                            mcp_tools_cleanup = MCPTools(translated_workspace)
                            result = mcp_tools_cleanup.filesystem_write(path, content)
                            logger.info("Emergency file write on cleanup", path=path, 
                                       success=result.get("success"), content_len=len(content))
                    except Exception as write_err:
                        logger.error("Failed emergency file write", error=str(write_err))
        finally:
            # FINAL SAFETY NET: Write any previewed files that weren't executed as tool calls
            # This handles cases where stream completes but tool parsing failed silently
            try:
                if preview_content_cache:
                    logger.info("Final cleanup: checking for unwritten previewed files",
                               count=len(preview_content_cache))
                    for cache_data in preview_content_cache:
                        path = cache_data.get("path")
                        content = cache_data.get("content", "")
                        # Only write if substantial content and file doesn't exist with same content
                        if content and path and len(content) > 100:
                            translated_workspace = translate_host_path_to_container(
                                request.workspace_path or settings.workspace_path
                            )
                            full_path = Path(translated_workspace) / path
                            
                            # Check if file already exists with this content (was written by tool)
                            should_write = True
                            if full_path.exists():
                                try:
                                    existing_content = full_path.read_text()
                                    if existing_content == content:
                                        should_write = False
                                        logger.debug("File already written correctly", path=path)
                                except Exception:
                                    pass  # If we can't read, try to write anyway
                            
                            if should_write:
                                mcp_tools_cleanup = MCPTools(translated_workspace)
                                result = mcp_tools_cleanup.filesystem_write(path, content)
                                if result.get("success"):
                                    logger.info("Final cleanup: wrote previewed file", 
                                               path=path, content_len=len(content))
                                    # Notify frontend
                                    cleanup_notification = json.dumps({
                                        "file_write_complete": {
                                            "tool": "filesystem_write",
                                            "path": path,
                                            "action": "created" if not full_path.exists() else "updated",
                                            "verified": True,
                                            "success": True,
                                            "source": "cleanup"
                                        }
                                    })
                                    yield f"data: {cleanup_notification}\n\n"
            except Exception as cleanup_err:
                logger.error("Final cleanup failed", error=str(cleanup_err))

    return StreamingResponse(event_generator(), media_type="text/event-stream")
