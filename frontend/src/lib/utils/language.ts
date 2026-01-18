/**
 * Language detection from file path
 */

export function getLanguageFromPath(path: string): string {
	const ext = path.split('.').pop()?.toLowerCase() || '';
	const langMap: Record<string, string> = {
		'py': 'python',
		'js': 'javascript',
		'ts': 'typescript',
		'jsx': 'jsx',
		'tsx': 'tsx',
		'html': 'html',
		'css': 'css',
		'json': 'json',
		'md': 'markdown',
		'yaml': 'yaml',
		'yml': 'yaml',
		'sh': 'bash',
		'bash': 'bash',
		'rs': 'rust',
		'go': 'go',
		'java': 'java',
		'c': 'c',
		'cpp': 'cpp',
		'h': 'c',
		'hpp': 'cpp',
		'rb': 'ruby',
		'php': 'php',
		'sql': 'sql',
		'toml': 'toml',
		'xml': 'xml',
		'svelte': 'svelte'
	};
	return langMap[ext] || 'plaintext';
}
