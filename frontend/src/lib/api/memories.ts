/**
 * Memory API service
 * Handles memory bank operations
 */

const BASE_URL = 'http://localhost:8000/api/v1';

export interface Memory {
	id: number;
	content: string;
	source: string;
	tags: string | null;
	created_at: string;
	access_count: number;
}

/**
 * Load memories with optional filtering
 */
export async function loadMemories(
	workspacePath?: string,
	searchQuery?: string,
	limit: number = 100
): Promise<Memory[]> {
	const params = new URLSearchParams();
	if (workspacePath) params.append('workspace_path', workspacePath);
	if (searchQuery) params.append('search', searchQuery);
	params.append('limit', limit.toString());

	const response = await fetch(`${BASE_URL}/memories?${params.toString()}`);
	if (!response.ok) throw new Error('Failed to load memories');
	const data = await response.json();
	return data.memories || [];
}

/**
 * Delete a memory
 */
export async function deleteMemory(memoryId: number): Promise<void> {
	const response = await fetch(`${BASE_URL}/memories/${memoryId}`, {
		method: 'DELETE'
	});
	if (!response.ok) throw new Error('Failed to delete memory');
}
