# Prometheus

Prometheus is a model-agnostic AI Agent IDE that enables autonomous coding tasks by bridging local LLMs like Ollama with commercial APIs using LiteLLM and the Model Context Protocol.

## Install

```bash
docker compose up --build
```

## Hello, World

```bash
curl http://localhost:8000/ping
# Output: {"status": "ok"}
```

## Architecture

- **Backend**: FastAPI with LiteLLM for universal inference.
- **Frontend**: SvelteKit with Tailwind CSS, Monaco Editor, and xterm.js.
- **Protocol**: Model Context Protocol (MCP) for tool discovery and execution.

## Development

See [backend/README.md](backend/README.md) and [frontend/README.md](frontend/README.md) for specific instructions.
