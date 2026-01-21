# Agent Workflow Improvements

## Overview

This document describes the improvements made to the Prometheus AI agent workflow to prevent:
1. **Syntax errors when creating/editing files** (especially Python)
2. **Infinite loops** (read loops, syntax fix loops)
3. **Truncated file writes** (JSON getting cut off)
4. **Analysis paralysis** (reading without editing)

---

## 1. Python Syntax Validation (Pre-Write)

### Location: `backend/prometheus/mcp/tools.py`

**Problem:** Agent would create Python files with syntax errors, then get stuck in infinite loops trying to fix them.

**Solution:** Added `_validate_python_syntax()` method that:
- Validates Python code **before** writing to disk
- Attempts automatic fixes for common issues:
  - Truncated trailing lines
  - Missing closing brackets `()`, `[]`, `{}`
  - Unclosed triple-quote strings
  - Uses `autopep8` if available for indentation fixes
- Provides detailed error messages with context:
  - Exact line and column of error
  - 5-line code context around the error
  - Specific instructions for common fixes

### Affected Tools:
- `filesystem_write` - Full validation + auto-fix
- `filesystem_replace_lines` - Validates result before saving
- `filesystem_search_replace` - Validates result before saving

### Error Response Example:
```json
{
  "success": false,
  "error": "PYTHON SYNTAX ERROR in test.py\n\nError: expected ':'\nLocation: Line 5, Column 15\n\nContext:\n    3 |     def test_one(self):\n    4 |         pass\n>>> 5 |     def test_two(self)\n    6 |         pass",
  "hint": "Fix the syntax error and try again. Do NOT re-read the file.",
  "syntax_error": true
}
```

---

## 2. New `filesystem_append` Tool

### Location: `backend/prometheus/mcp/tools.py`, `backend/prometheus/main.py`

**Problem:** Large files (300+ lines) would cause JSON truncation, leading to incomplete file writes.

**Solution:** Added `filesystem_append` tool for incremental file building:
- Appends content to end of file
- Creates file if it doesn't exist
- Validates Python syntax after append
- Returns line count info for tracking progress

### Usage Pattern (System Prompt):
```
Step 1: Create skeleton with filesystem_write (small file)
Step 2: Add functionality with filesystem_append
Step 3: Continue appending until complete
```

---

## 3. Enhanced System Prompt

### Location: `backend/prometheus/routers/chat.py`

Added detailed guidance for file creation:

### Python-Specific Rules:
- Always use 4 spaces (never tabs)
- Always close brackets and quotes
- Always end definitions with colons
- Keep test files under 100 lines

### Chunked Write Pattern:
```
1. filesystem_write - Create skeleton
2. filesystem_replace_lines - Add first section
3. filesystem_replace_lines - Add second section
...
```

### Escape Sequence Reference:
- `\n` for newlines
- `\t` for tabs
- `\\` for backslash
- `\"` for double quotes

### Common Mistakes to Avoid:
- Don't use markdown code fences in file content
- Don't include line number prefixes
- Don't mix tabs and spaces
- Don't write 300+ lines in one call

---

## 4. Syntax Error Loop Detection

### Location: `backend/prometheus/routers/chat.py`

**Problem:** Agent would get stuck repeatedly trying to fix the same syntax error.

**Solution:** Added tracking variables:
- `syntax_error_counts: dict[str, int]` - Errors per file
- `total_syntax_errors: int` - Total errors across all files
- `consecutive_syntax_errors: int` - Streak without success
- `max_syntax_errors_per_file = 3` - Guidance threshold
- `max_total_syntax_errors = 8` - Abort threshold

### Behavior:
1. **After 3 errors on same file:** Provide detailed guidance suggesting to delete and start fresh
2. **After 8 total errors:** Abort conversation with helpful error message

### Error Escalation:
```
Error 1-2: Standard syntax error message with fix hints
Error 3: "You are stuck in a loop. Consider deleting the file and starting fresh."
Error 8+: "ABORTING: Agent stuck in syntax error loop! Try a simpler approach."
```

---

## 5. Existing Loop Detection (Enhanced)

### Read Loop Detection (Already existed):
- Blocks re-reading the same file
- Escalating messages after 1, 2, 3+ attempts
- Aborts after 10 blocked reads total
- Aborts after 3 consecutive blocked reads

### Analysis Paralysis Detection (Already existed):
- Nudges after 2 reads without edits
- Blocks reads after 5 without edits
- Forces edit tool calls

---

## Summary of Files Changed

| File | Changes |
|------|---------|
| `backend/prometheus/mcp/tools.py` | Added `_validate_python_syntax()`, updated `filesystem_write`, `filesystem_replace_lines`, `filesystem_search_replace`, added `filesystem_append` |
| `backend/prometheus/main.py` | Registered `filesystem_append` tool |
| `backend/prometheus/routers/chat.py` | Enhanced system prompt, added syntax error tracking, added syntax loop abort |

---

## Testing Recommendations

1. **Test syntax validation:**
   ```python
   # Should fail with helpful error
   {"tool": "filesystem_write", "args": {"path": "test.py", "content": "def foo(\n    pass"}}
   ```

2. **Test incremental writes:**
   ```python
   # Step 1: Skeleton
   {"tool": "filesystem_write", "args": {"path": "test.py", "content": "# Tests\nimport unittest\n"}}
   # Step 2: Append
   {"tool": "filesystem_append", "args": {"path": "test.py", "content": "class TestOne(unittest.TestCase):\n    pass\n"}}
   ```

3. **Test loop detection:**
   - Try to read the same file multiple times
   - Generate syntax errors repeatedly

---

## Future Improvements (Suggestions)

1. **JavaScript/TypeScript validation** using `esprima` or Node.js
2. **Auto-formatter integration** for more languages
3. **Rollback to last working version** when syntax error detected
4. **Diff preview** before write to catch obvious issues
