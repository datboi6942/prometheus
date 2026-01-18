# Workspace Configuration

## How Workspaces Work

Prometheus uses a **dynamic workspace system** where each chat/conversation can specify its own workspace path.

### Database Location
- **Fixed location**: `~/.prometheus/` (your home directory)
- Contains:
  - `prometheus.db` - SQLite database with API keys, settings, conversations, command permissions
  - All persistent data survives container rebuilds

### Workspace Location
- **Dynamic per request** - Each API call can specify a different workspace
- The workspace is where the agent reads/writes files for that conversation
- Can be any directory you have access to

### Docker Volume Mounts

The `docker-compose.yml` mounts:

1. `~/.prometheus:/root/.prometheus` - Database directory (read/write)
2. `~:/host_home:ro` - Your entire home directory (read-only for safety)
3. `.:/default_workspace` - Current directory as default workspace

### How to Set Workspace

#### Option 1: Via Frontend UI
When starting a new conversation, you can specify the workspace path.

#### Option 2: Via API
Include `workspace_path` in your chat request:

```json
{
  "model": "ollama/llama3.2",
  "messages": [...],
  "workspace_path": "/path/to/your/project"
}
```

#### Option 3: Environment Variable
Set a default in `.env`:

```bash
WORKSPACE_PATH=/home/john/projects/my-project
```

### Security Considerations

1. **Home directory is read-only** by default to prevent accidental modifications
2. **Workspace must be explicitly specified** or use the default
3. **Command permissions** - Agent asks before running new commands
4. **Path traversal protection** - Validates all file paths

### Example Workflows

#### Local Development
```bash
# Set workspace to your current project
WORKSPACE_PATH=/home/john/projects/my-app
```

#### Multiple Projects
Each conversation can have its own workspace:
- Conversation 1: `/home/john/project-a`
- Conversation 2: `/home/john/project-b`
- Conversation 3: `/home/john/experiments`

#### Accessing User Files
Files in your home directory are accessible via:
- Direct path: `/host_home/username/documents/file.txt`
- Or use the workspace path if mounted

### Docker Volume Configuration

Current setup in `docker-compose.yml`:

```yaml
volumes:
  # Database persistence in ~/.prometheus
  - ~/.prometheus:/root/.prometheus
  
  # Access to home directory (read-only)
  - ~:/host_home:ro
  
  # Default workspace (current directory)
  - .:/default_workspace
```

To add more workspace locations, add volume mounts:

```yaml
volumes:
  - ~/.prometheus:/root/.prometheus
  - ~/projects:/projects
  - ~/documents:/documents
```

### Troubleshooting

**Q: Can't access files outside workspace?**  
A: Add the directory as a volume mount in `docker-compose.yml`

**Q: Database keeps resetting?**  
A: Check that `~/.prometheus` exists and has write permissions

**Q: Want to change default workspace?**  
A: Update `WORKSPACE_PATH` in `.env` file
