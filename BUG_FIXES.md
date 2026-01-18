# Bug Fixes - Streaming, File Writing, and Hierarchical File Tree

## Issues Fixed

### 1. ✅ Streaming Output Not Displaying

**Problem**: Text was not appearing token-by-token as the LLM generated it.

**Root Cause**: The streaming logic in `chat.py` was too conservative. It was checking if `'{"tool"'` appeared *anywhere* in the accumulated response, which would block ALL output once the agent started generating a tool call.

**Solution**: Changed the logic to only hold back streaming when we're *actively* in the middle of a JSON object:

```python
# Before: Too conservative
in_potential_json = '{"tool"' in accumulated_response[last_sent_length:] or open_braces > 0

# After: More aggressive, only blocks when mid-JSON
recent_chunk = accumulated_response[max(0, len(accumulated_response) - 50):]
looks_like_json_start = '{"tool"' in recent_chunk and open_braces > 0
```

**File**: `backend/prometheus/routers/chat.py`

### 2. ✅ Hierarchical File Tree (VS Code Style)

**Problem**: File browser showed a flat list instead of an expandable tree structure.

**Solution**: Implemented a complete hierarchical file system with:

- **Tree building logic** that converts flat API responses into nested structures
- **Expand/collapse functionality** for directories (click to toggle)
- **Lazy loading** of subdirectories (only loads children when expanded)
- **Proper indentation** based on nesting level
- **Animated chevron rotation** when expanding/collapsing
- **Sorting**: Directories first, then files, both alphabetically

**New Functions Added**:
- `buildFileTree()` - Converts flat list to hierarchical tree
- `toggleDirectory()` - Handles expand/collapse with lazy loading
- `flattenTree()` - Flattens tree for rendering

**Visual Features**:
- Dynamic left padding based on nesting level: `padding-left: {(file.level || 0) * 12 + 12}px`
- Chevron rotates 90° when folder is expanded
- File size display (B for bytes, KB for kilobytes)
- Current file highlighting in editor

**File**: `frontend/src/routes/+page.svelte`

### 3. ✅ Enhanced File Writing Debugging

**Problem**: Unclear why files weren't being created by the agent.

**Solution**: Added comprehensive logging to track:
- Number of tool calls detected
- Tool execution attempts with arguments
- Tool execution results

This will help identify if the issue is:
- LLM not generating proper JSON format
- Tool extraction failing
- Tool execution failing
- Workspace path misconfiguration

**File**: `backend/prometheus/routers/chat.py`

## Technical Details

### Hierarchical Tree Implementation

```typescript
interface FileItem {
  name: string;
  type: 'file' | 'directory';
  path: string;
  size?: number;
  expanded?: boolean;    // New: Track expansion state
  children?: FileItem[]; // New: Nested children
  level?: number;        // New: Indentation level
}
```

**Algorithm**:
1. Root level loads from `fetchFileTree('')`
2. Items are sorted (directories first, then alphabetically)
3. When a directory is clicked:
   - If not expanded: Load children from API, set `expanded = true`
   - If expanded: Set `expanded = false` (collapse)
4. `flattenTree()` recursively builds a flat array for rendering, only including expanded branches

### Streaming Fix Details

The key insight is that we only need to block streaming when:
1. `{"tool"` appears in the **recent** output (last 50 chars)
2. **AND** there are unmatched opening braces

This allows normal text to stream through while still catching tool calls.

### UI/UX Improvements

1. **File browser now matches VS Code**:
   - Chevron indicates expandable folders
   - Proper tree indentation
   - Click folder name to expand/collapse
   - Click file to open in editor

2. **File sizes display intelligently**:
   - < 1024 bytes: Show as "XB"
   - >= 1024 bytes: Show as "X.XKB"

3. **Visual feedback**:
   - Currently open file is highlighted
   - Hover states on file/folder items
   - Loading spinner during file tree fetch
   - Smooth chevron rotation animation

## Testing

After rebuilding containers:

```bash
docker compose up --build -d
```

**Test streaming**:
1. Open http://localhost:3001
2. Send a message like "tell me a story"
3. You should see text appearing word-by-word

**Test file tree**:
1. Ask agent to create files: "create a folder called src with a main.py file"
2. See "src" folder appear in sidebar with collapse/expand chevron
3. Click "src" to expand and see "main.py" inside
4. Click "main.py" to open in editor

**Test file creation**:
1. Check backend logs: `docker logs -f prometheus-backend-1`
2. Look for log entries showing tool detection and execution
3. If you see "Tool calls detected" with count > 0, the LLM is generating tools correctly
4. If you see "Executing tool" with filesystem_write, the tool is being called
5. If you see success=True in the result, files are being created

## Files Modified

| File | Changes |
|------|---------|
| `backend/prometheus/routers/chat.py` | Fixed streaming logic, added debug logging |
| `frontend/src/routes/+page.svelte` | Added hierarchical tree, expand/collapse, lazy loading |

## Deployment Status

✅ Backend rebuilt successfully
✅ Frontend rebuilt successfully
✅ Both containers running on ports 8000 and 3001
✅ No compilation errors

## Next Steps for Debugging File Writing

If files still aren't being created after these fixes:

1. **Check logs**: `docker logs -f prometheus-backend-1`
   - Look for "Tool calls detected" messages
   - Check if count > 0 when you ask to create files
   
2. **Verify workspace path**: Make sure the path in Settings is valid and writable
   
3. **Test LLM output**: Look at the raw text the LLM generates to see if it's producing the correct JSON format

4. **Manual API test**:
   ```bash
   curl -X PUT http://localhost:8000/api/v1/files/content \
     -H "Content-Type: application/json" \
     -d '{"path": "test.txt", "content": "Hello!"}'
   ```
   
If this works, the problem is in tool call extraction/execution, not the MCP tools themselves.
