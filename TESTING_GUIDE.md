# Testing Guide for Prometheus AI Agent

## Quick Start Testing

### 1. Access the Application

Open your browser and navigate to:
```
http://localhost:3001
```

### 2. Configure Workspace

1. Click the **Settings** icon (gear) in the left sidebar
2. Set **Workspace Path** to `/tmp/prometheus_workspace` (or any valid path)
3. Click **Save & Close**

### 3. Test Agent File Creation

Click the **Deploy** button or type in chat:

```
create a hello.py file that prints "Hello, Prometheus!"
```

**Expected behavior:**
- Agent responds with a JSON tool call
- Tool execution appears in "Tool Activity" panel
- File appears in "Project Files" sidebar
- You can click the file to open it in the editor

### 4. Test File Browser

1. Look at the **Project Files** section on the right
2. You should see `hello.py` listed
3. Click the refresh button (the plus icon) to reload
4. Click on `hello.py` to open it

**Expected behavior:**
- Editor switches to "Forge" view
- File content loads in Monaco editor
- Filename appears in editor toolbar

### 5. Test Code Editor

1. With `hello.py` open, modify the code
2. Notice the "● Unsaved" indicator appears
3. Press **Ctrl+S** (or **Cmd+S** on Mac) or click **Save** button
4. See "File saved: hello.py" message in chat

**Expected behavior:**
- Unsaved indicator disappears
- File is saved to workspace
- Success message in chat

### 6. Test Shell Execution

Type in chat:
```
run the hello.py file with python
```

**Expected behavior:**
- Agent executes: `{"tool": "shell_execute", "args": {"command": "python hello.py"}}`
- Terminal panel opens automatically
- Output appears: "Hello, Prometheus!"

### 7. Test Directory Listing

Type in chat:
```
show me what files are in the workspace
```

**Expected behavior:**
- Agent uses `filesystem_list` tool
- Lists all files with metadata
- File browser updates automatically

## Advanced Testing Scenarios

### Multi-File Project

Try:
```
Create a Python calculator project with:
1. calculator.py with add, subtract, multiply, divide functions
2. test_calculator.py with test cases
3. README.md with usage instructions
```

### Complex File Operations

Try:
```
1. Read the calculator.py file
2. Add a power function to it
3. Run the tests
```

### Keyboard Shortcuts

- **Ctrl+S / Cmd+S**: Save current file
- **Enter**: Send chat message
- Terminal icon: Toggle terminal panel

## Troubleshooting

### File Browser Empty

**Problem**: No files showing in sidebar

**Solution**:
1. Check workspace path is set correctly
2. Click refresh button
3. Ask agent to create a file
4. Verify `/tmp/prometheus_workspace` exists and is writable

### Agent Not Creating Files

**Problem**: Agent responds but no files created

**Check**:
1. Tool Activity panel - does it show success?
2. Browser console for errors (F12)
3. Backend logs: `docker logs prometheus-backend-1`

### Editor Won't Open Files

**Problem**: Clicking files does nothing

**Check**:
1. Browser console for errors
2. Ensure file path is correct in file listing
3. Try refreshing the page

### Save Not Working

**Problem**: Save button does nothing or fails

**Check**:
1. Ensure a file is currently open
2. Check workspace path permissions
3. Look for error messages in chat

## API Testing (for developers)

### List Files
```bash
curl http://localhost:8000/api/v1/files/list?path=
```

### Read File
```bash
curl "http://localhost:8000/api/v1/files/content?path=hello.py"
```

### Write File
```bash
curl -X PUT http://localhost:8000/api/v1/files/content \
  -H "Content-Type: application/json" \
  -d '{"path": "test.txt", "content": "Hello from API!"}'
```

### Delete File
```bash
curl -X DELETE "http://localhost:8000/api/v1/files/?path=test.txt"
```

## Expected Tool Call Format

The agent should output tool calls in this exact format:

```json
{"tool": "filesystem_write", "args": {"path": "hello.py", "content": "print('Hello')"}}
```

If the agent is not creating files, check that it's outputting this JSON format correctly.

## Container Management

### Restart Containers
```bash
docker compose restart
```

### View Backend Logs
```bash
docker logs -f prometheus-backend-1
```

### View Frontend Logs
```bash
docker logs -f prometheus-frontend-1
```

### Rebuild After Code Changes
```bash
docker compose up --build -d
```

## Success Indicators

✅ **Everything Working If**:
1. Settings panel accepts workspace path
2. Deploy button sends message and gets response
3. Agent tool calls appear in Tool Activity
4. Files appear in Project Files sidebar
5. Clicking files opens them in editor
6. Ctrl+S saves files successfully
7. Terminal shows command output

## Known Limitations

1. **No nested folders**: File browser shows flat list (for now)
2. **No file deletion from UI**: Use agent commands
3. **Single file editing**: Can only edit one file at a time
4. **Local models**: May need prompt adjustments for best results

## Performance Tips

1. **Use local models** (Llama 3.2) for faster responses
2. **Clear old messages** if chat becomes slow
3. **Small files**: Editor works best with files < 10K lines
4. **Terminal**: Limit output to prevent slowdown
