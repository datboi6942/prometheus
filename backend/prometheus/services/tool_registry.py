"""Dynamic tool registry for MCP servers and custom tools."""
import asyncio
import json
from typing import Any, Callable

import structlog

logger = structlog.get_logger()


class ToolRegistry:
    """Registry for dynamically registered tools from MCP servers and custom sources."""

    def __init__(self) -> None:
        """Initialize the tool registry."""
        self._tools: dict[str, dict[str, Any]] = {}
        self._fallback_tools: dict[str, Callable] = {}
        self._mcp_servers: dict[str, dict[str, Any]] = {}

    def register_fallback_tool(
        self,
        name: str,
        handler: Callable,
        description: str = "",
        parameters: dict[str, Any] | None = None,
    ) -> None:
        """Register a fallback tool (hardcoded basic functionality).

        Args:
            name: Tool name.
            handler: Tool handler function.
            description: Tool description.
            parameters: Tool parameters schema.
        """
        self._fallback_tools[name] = handler
        self._tools[name] = {
            "name": name,
            "description": description,
            "parameters": parameters or {},
            "source": "fallback",
            "handler": handler,
        }
        logger.info("Registered fallback tool", tool=name)

    def register_mcp_tool(
        self,
        name: str,
        server_name: str,
        description: str = "",
        parameters: dict[str, Any] | None = None,
        handler: Callable | None = None,
    ) -> None:
        """Register a tool from an MCP server.

        Args:
            name: Tool name.
            server_name: MCP server name.
            description: Tool description.
            parameters: Tool parameters schema.
            handler: Optional custom handler (otherwise uses MCP server).
        """
        self._tools[name] = {
            "name": name,
            "description": description,
            "parameters": parameters or {},
            "source": "mcp",
            "server": server_name,
            "handler": handler,
        }
        logger.info("Registered MCP tool", tool=name, server=server_name)

    def register_custom_tool(
        self,
        name: str,
        handler: Callable,
        description: str = "",
        parameters: dict[str, Any] | None = None,
    ) -> None:
        """Register a custom tool.

        Args:
            name: Tool name.
            handler: Tool handler function.
            description: Tool description.
            parameters: Tool parameters schema.
        """
        self._tools[name] = {
            "name": name,
            "description": description,
            "parameters": parameters or {},
            "source": "custom",
            "handler": handler,
        }
        logger.info("Registered custom tool", tool=name)

    def get_tool(self, name: str) -> dict[str, Any] | None:
        """Get tool information.

        Args:
            name: Tool name.

        Returns:
            dict: Tool information or None if not found.
        """
        return self._tools.get(name)

    def get_all_tools(self) -> list[dict[str, Any]]:
        """Get all registered tools.

        Returns:
            list: List of tool information dictionaries.
        """
        return [
            {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("parameters", {}),
                "source": tool.get("source", "unknown"),
                "server": tool.get("server"),
            }
            for tool in self._tools.values()
        ]

    def get_tool_names(self) -> list[str]:
        """Get list of all registered tool names.

        Returns:
            list: List of tool names.
        """
        return list(self._tools.keys())

    async def execute_tool(self, name: str, args: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a tool.

        Args:
            name: Tool name.
            args: Tool arguments.
            context: Optional execution context (e.g., workspace_path, mcp_tools).

        Returns:
            dict: Tool execution result.
        """
        tool = self._tools.get(name)
        if not tool:
            return {"error": f"Tool '{name}' not found"}

        handler = tool.get("handler")
        if not handler:
            return {"error": f"Tool '{name}' has no handler"}

        try:
            # Call handler with args and context
            if asyncio.iscoroutinefunction(handler):
                result = await handler(args, context or {})
            else:
                result = handler(args, context or {})
            return result if isinstance(result, dict) else {"success": True, "result": result}
        except Exception as e:
            logger.error("Tool execution failed", tool=name, error=str(e))
            return {"error": str(e)}

    def register_mcp_server(self, server_name: str, config: dict[str, Any]) -> None:
        """Register an MCP server configuration.

        Args:
            server_name: Server name.
            config: Server configuration.
        """
        self._mcp_servers[server_name] = config
        logger.info("Registered MCP server", server=server_name)

    def get_mcp_servers(self) -> dict[str, dict[str, Any]]:
        """Get all registered MCP servers.

        Returns:
            dict: Server configurations.
        """
        return self._mcp_servers.copy()

    def remove_mcp_server(self, server_name: str) -> None:
        """Remove an MCP server and its tools.

        Args:
            server_name: Server name.
        """
        if server_name in self._mcp_servers:
            del self._mcp_servers[server_name]
            # Remove tools from this server
            tools_to_remove = [
                name for name, tool in self._tools.items() if tool.get("server") == server_name
            ]
            for tool_name in tools_to_remove:
                del self._tools[tool_name]
            logger.info("Removed MCP server", server=server_name)


# Global tool registry instance
_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    """Get the global tool registry instance.

    Returns:
        ToolRegistry: Global tool registry.
    """
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
