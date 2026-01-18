/**
 * File tree utility functions
 */

import type { FileItem } from '$lib/api/files';

/**
 * Build hierarchical tree from flat list
 */
export function buildFileTree(items: FileItem[]): FileItem[] {
	const tree: FileItem[] = [];
	const dirMap = new Map<string, FileItem>();
	
	// First pass: create directory entries
	for (const item of items) {
		if (item.type === 'directory') {
			const dirItem: FileItem = {
				...item,
				children: [],
				expanded: false,
				level: 0
			};
			dirMap.set(item.path, dirItem);
			tree.push(dirItem);
		}
	}
	
	// Second pass: add files to root
	for (const item of items) {
		if (item.type === 'file') {
			tree.push({ ...item, level: 0 });
		}
	}
	
	// Sort: directories first, then alphabetically
	return tree.sort((a, b) => {
		if (a.type !== b.type) {
			return a.type === 'directory' ? -1 : 1;
		}
		return a.name.localeCompare(b.name);
	});
}

/**
 * Flatten tree for rendering
 */
export function flattenTree(items: FileItem[]): FileItem[] {
	const result: FileItem[] = [];
	for (const item of items) {
		result.push(item);
		if (item.type === 'directory' && item.expanded && item.children) {
			result.push(...flattenTree(item.children));
		}
	}
	return result;
}

/**
 * Find a file in the tree by path
 */
export function findFileInTree(fileTree: FileItem[], targetPath: string): FileItem | null {
	for (const item of flattenTree(fileTree)) {
		if (item.path === targetPath) {
			return item;
		}
	}
	return null;
}
