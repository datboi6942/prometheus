# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Prometheus is a model-agnostic AI Agent IDE that bridges local LLMs (via Ollama) with commercial APIs using LiteLLM and the Model Context Protocol (MCP). It provides a web-based interface for autonomous coding with tool execution capabilities.

## Architecture

### Three-Tier Structure

1. **Backend (FastAPI + Python 3.11+)**
   - `backend/prometheus/main.py` - FastAPI application entry point with CORS and router registration
   - `backend/prometheus/config.py` - Settings management via Pydantic, handles Docker path translation
   - `backend/prometheus/database.py` - SQLite database with aiosqlite for persistence
   - `backend/prometheus/routers/` - API route handlers (chat, files, git, mcp, conversations, permissions)
   - `backend/prometheus/services/` - Business logic (model routing via LiteLLM, MCP server loading, tool registry, git/GitHub integration)
   - `backend/prometheus/mcp/` - Model Context Protocol tool implementations

2. **Frontend (SvelteKit + TypeScript)**
   - `frontend/src/routes/+page.svelte` - Main application page (being modularized)
   - `frontend/src/lib/stores.ts` - Centralized Svelte stores for application state
   - `frontend/src/lib/api/` - Typed API client modules (chat, settings, files, git, rules, memories, mcp)
   - `frontend/src/lib/components/` - Reusable Svelte components (panels, sidebar)
   - `frontend/src/lib/utils/` - Utility functions (file tree operations, language detection)

3. **Database (SQLite)**
   - Location: `~/.prometheus/prometheus.db`
   - Tables: conversations, messages, global_rules, project_rules, settings, memories, mcp_servers, command_permissions
   - API key encryption via Fernet (PBKDF2 key derivation)

### Key Architectural Patterns

**Docker Path Translation**: The backend runs in Docker with host filesystem mounted at `/host_home`. The `translate_host_path_to_container()` function in `config.py` handles path mapping. Always use this when dealing with workspace paths.

**Tool Registry System**: Dynamic tool registration via `services/tool_registry.py`:
- Fallback tools (basic filesystem, Python, shell)
- MCP tools (loaded from database-stored server configs)
- Custom tools (extensible registration)

**MCP Server Integration**: MCP servers are stored in the database with configs (command, transport, env, tools). The `services/mcp_loader.py` handles:
- Command permission validation (prevents execution of unapproved commands)
- Environment variable sanitization (blocks dangerous vars like PATH, LD_PRELOAD)
- Working directory validation (prevents directory traversal)
- Both stdio and HTTP transport types

**Settings Encryption**: API keys and sensitive settings are automatically encrypted using Fernet. Keys matching patterns in `SENSITIVE_KEYS` are encrypted before storage and decrypted on retrieval.

**Memory Bank**: Persistent memory storage with access tracking, workspace scoping, and tag-based search. Memories are automatically injected into system prompts based on relevance.

## Common Commands

### Development

```bash
# Start full stack
docker compose up --build

# Backend only (from backend/)
poetry install
poetry run uvicorn prometheus.main:app --reload --host 0.0.0.0 --port 8000

# Frontend only (from frontend/)
npm install
npm run dev

# Testing backend
poetry run pytest
poetry run pytest tests/test_health.py -v

# Linting and formatting
poetry run ruff check .
poetry run black .
poetry run mypy prometheus/

# Frontend linting
npm run lint
npm run format
```

### Access Points

- Frontend: http://localhost:3001
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs
- Health Check: `curl http://localhost:8000/ping`

## Important Implementation Details

### Pull Request Workflow

**ALWAYS create pull requests for new features, bug fixes, and updates.** PRs are reviewed by Greptile for code quality, breaking changes, and improvement suggestions. Never make direct commits to main for non-trivial changes.

### Production Server Access

The production server is ONLY accessible via SSH. NEVER attempt to execute commands on or access the production database unless explicitly stated or clearly inferred from context. Local development should use the local Docker environment.

### Security Considerations

1. **Command Permissions**: The `command_permissions` table tracks approved commands. MCP server tools check permissions before execution. Unapproved commands return permission requests that must be handled in the UI.

2. **Environment Variable Sanitization**: `mcp_loader.py` blocks dangerous env vars (PATH, LD_PRELOAD, etc.) to prevent injection attacks.

3. **API Key Storage**: Use the settings table for API keys - they are automatically encrypted. Never store unencrypted keys.

4. **Workspace Path Validation**: Always validate and sanitize workspace paths to prevent directory traversal.

### Database Operations

All database functions are async and use `aiosqlite`. Connection pattern:
```python
async with aiosqlite.connect(DB_PATH) as db:
    # Use db.row_factory = aiosqlite.Row for dict results
    # Always await db.commit() for writes
```

### Chat Message Flow

1. Request hits `/api/v1/chat` with messages, model, workspace_path
2. System prompt augmented with:
   - Enabled global and project rules from database
   - Relevant memories from memory bank
3. LiteLLM routes to appropriate model (Ollama local or API)
4. Streaming response with tool call extraction
5. Tool calls executed via ToolRegistry
6. Results streamed back to frontend

### Frontend State Management

Use centralized Svelte stores (`lib/stores.ts`) instead of prop drilling. Import with:
```typescript
import { workspacePath, messages, showSettings } from '$lib/stores';
```

Access reactive values with `$` prefix in components:
```svelte
<input bind:value={$workspacePath} />
```

### Frontend Refactoring Status

The codebase is being modularized from a 3,196-line `+page.svelte` into reusable components. Current structure:
- API layer: Complete (6 modules in `lib/api/`)
- State management: Complete (`lib/stores.ts`)
- Panel components: Partially complete (4 components in `lib/components/panels/`)
- Core features: Still in main page (file explorer, git panel, chat interface, code editor)

When adding features, prefer creating new components in `lib/components/` over adding to `+page.svelte`.

## Testing Strategy

- Backend tests in `backend/tests/`
- Use `pytest-asyncio` for async tests
- FastAPI test client available for integration tests
- Test configuration in `pyproject.toml` under `[tool.pytest.ini_options]`

## Configuration Files

- `.env` - Local environment configuration (gitignored)
- `.env.example` - Template for environment variables
- `docker-compose.yml` - Docker orchestration with host networking for Ollama access
- `backend/pyproject.toml` - Python dependencies and tool configuration (Black, Ruff, MyPy)
- `frontend/package.json` - Node dependencies and scripts

## Model Support

LiteLLM supports 100+ models via unified interface. Common configurations:
- Local: `ollama/llama3.2`, `ollama/mistral`
- OpenAI: `gpt-4`, `gpt-3.5-turbo`
- Anthropic: `claude-3-opus`, `claude-3-sonnet`

Model selection is per-conversation and stored in the database.
