/**
 * Files API service
 * Handles file system operations
 */

const BASE_URL = 'http://localhost:8000/api/v1';

export interface FileItem {
	name: string;
	type: 'file' | 'directory';
	path: string;
	size?: number;
	expanded?: boolean;
	children?: FileItem[];
	level?: number;
}

/**
 * List files in a directory
 */
export async function listFiles(path: string = '', workspacePath?: string): Promise<FileItem[]> {
	const params = new URLSearchParams({ path });
	if (workspacePath) {
		params.append('workspace_path', workspacePath);
	}
	const response = await fetch(
		`${BASE_URL}/files/list?${params}`
	);
	if (!response.ok) throw new Error('Failed to list files');
	const data = await response.json();
	return data.items || [];
}

/**
 * Read file content
 */
export async function readFile(path: string, workspacePath?: string): Promise<string> {
	const params = new URLSearchParams({ path });
	if (workspacePath) {
		params.append('workspace_path', workspacePath);
	}
	const response = await fetch(
		`${BASE_URL}/files/content?${params}`
	);
	if (!response.ok) throw new Error('Failed to read file');
	const data = await response.json();
	return data.content || '';
}

/**
 * Write file content
 */
export async function writeFile(path: string, content: string, workspacePath?: string): Promise<void> {
	const response = await fetch(`${BASE_URL}/files/content`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ path, content, workspace_path: workspacePath })
	});
	if (!response.ok) throw new Error('Failed to write file');
}

/**
 * Delete a file or directory
 */
export async function deleteFile(path: string, workspacePath?: string): Promise<void> {
	const params = new URLSearchParams({ path });
	if (workspacePath) {
		params.append('workspace_path', workspacePath);
	}
	const response = await fetch(
		`${BASE_URL}/files/?${params}`,
		{ method: 'DELETE' }
	);
	if (!response.ok) throw new Error('Failed to delete file');
}

/**
 * Search files
 */
export async function searchFiles(
	query: string,
	searchContent: boolean = false,
	workspacePath?: string
): Promise<
	Array<{
		path: string;
		name: string;
		match_type: string;
		matches?: Array<{ line: number; content: string }>;
	}>
> {
	const params = new URLSearchParams({
		query,
		search_content: searchContent.toString()
	});
	if (workspacePath) {
		params.append('workspace_path', workspacePath);
	}
	const response = await fetch(`${BASE_URL}/files/search?${params}`);
	if (!response.ok) throw new Error('Failed to search files');
	const data = await response.json();
	return data.results || [];
}
