/**
 * MCP (Model Context Protocol) API service
 * Handles MCP server and tool management
 */

const BASE_URL = 'http://localhost:8000/api/v1';

export interface MCPServer {
	id: number;
	name: string;
	config: any;
	enabled: number;
}

export interface Tool {
	name: string;
	description: string;
	source: string;
}

/**
 * Load all MCP servers
 */
export async function loadMCPServers(): Promise<MCPServer[]> {
	const response = await fetch(`${BASE_URL}/mcp/servers`);
	if (!response.ok) throw new Error('Failed to load MCP servers');
	const data = await response.json();
	return data.servers || [];
}

/**
 * Load available tools
 */
export async function loadAvailableTools(): Promise<Tool[]> {
	const response = await fetch(`${BASE_URL}/mcp/tools`);
	if (!response.ok) throw new Error('Failed to load tools');
	const data = await response.json();
	return data.tools || [];
}

/**
 * Create a new MCP server
 */
export async function createMCPServer(
	name: string,
	config: any,
	enabled: boolean = true
): Promise<void> {
	const response = await fetch(`${BASE_URL}/mcp/servers`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ name, config, enabled })
	});
	if (!response.ok) {
		const error = await response.json();
		throw new Error(error.detail || 'Failed to create MCP server');
	}
}

/**
 * Delete an MCP server
 */
export async function deleteMCPServer(name: string): Promise<void> {
	const response = await fetch(`${BASE_URL}/mcp/servers/${name}`, {
		method: 'DELETE'
	});
	if (!response.ok) throw new Error('Failed to delete MCP server');
}

/**
 * Reload an MCP server
 */
export async function reloadMCPServer(name: string): Promise<void> {
	const response = await fetch(`${BASE_URL}/mcp/servers/${name}/reload`, {
		method: 'POST'
	});
	if (!response.ok) throw new Error('Failed to reload MCP server');
}
