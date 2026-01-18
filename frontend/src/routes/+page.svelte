<script lang="ts">
	import { onMount } from 'svelte';
	import { 
		Cpu, Terminal as TerminalIcon, Code2, Zap, Settings as SettingsIcon, 
		Globe, Shield, MessageSquare, FileCode, History, Play, Sparkles,
		FolderOpen, Plus, ChevronRight, X, Check, AlertCircle, Loader2,
		Search, GitBranch, RefreshCw, Trash2, FilePlus, FolderPlus, Edit3,
		ChevronDown, File, Folder, BookOpen
	} from 'lucide-svelte';
	
	// VS Code style explorer
	let explorerWidth = 280;
	let activeExplorerTab: 'files' | 'search' | 'git' = 'files';
	let showExplorer = true;
	let isCreatingFile = false;
	let isCreatingFolder = false;
	let newItemName = '';
	let newItemParentPath = '';
	let contextMenuFile: FileItem | null = null;
	let contextMenuPos = { x: 0, y: 0 };
	let renamingFile: FileItem | null = null;
	let renameValue = '';

	let selectedModel = 'ollama/llama3.2';
	let customEndpoint = '';
	let customApiKey = '';
	let workspacePath = '/tmp/prometheus_workspace';
	let verboseMode = false;
	let autoApproveEdits = true; // Always allow edits without asking
	
	// Chat history and rules
	let conversations: Array<{id: string, title: string, updated_at: string}> = [];
	let currentConversationId: string | null = null;
	let globalRules: Array<{id: number, name: string, content: string, enabled: number}> = [];
	let projectRules: Array<{id: number, name: string, content: string, enabled: number}> = [];
	let showRulesPanel = false;
	let newRuleName = '';
	let newRuleContent = '';
	let isGlobalRule = true;
	let settingsLoaded = false; // Prevent saving during initial load
	let showSettings = false;
	let activeView = 'chat'; // 'chat', 'forge'
	let showTerminalPanel = false; // Bottom terminal panel
	let isConnected = false;
	let isLoading = false;
	let chatInput = '';
	let abortController: AbortController | null = null;
	let terminalElement: HTMLElement;
	let editorElement: HTMLElement;
	let terminalInstance: any = null;
	let monacoEditor: any = null;
	let currentOpenFile: string | null = null;
	let editorHasUnsavedChanges = false;
	
	// Tool executions log
	let toolExecutions: Array<{
		type: string, 
		path?: string, 
		file?: string,
		command?: string, 
		stdout?: string,
		stderr?: string,
		status: string, 
		timestamp: Date,
		return_code?: number,
		hint?: string
	}> = [];
	
	// Chat messages
	let messages: Array<{
		role: string;
		content: string;
		timestamp: Date;
		codeWrites?: Array<{
			path: string;
			content: string;
			language: string;
			animatedContent: string;
			isComplete: boolean;
		}>;
	}> = [
		{ role: 'system', content: 'Prometheus AI Agent initialized. How can I assist you today?', timestamp: new Date() }
	];
	
	// Active code writing animations
	let activeCodeAnimations: Map<string, {
		fullContent: string;
		displayedLines: number;
		totalLines: number;
		intervalId: any;
	}> = new Map();

	// Detect file extension for syntax highlighting
	function getLanguageFromPath(path: string): string {
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

	// Parse message content to extract code writes
	function parseCodeWrites(content: string): { cleanContent: string; codeWrites: Array<{ path: string; content: string; language: string }> } {
		const codeWrites: Array<{ path: string; content: string; language: string }> = [];
		
		// Match filesystem_write tool calls
		const toolPattern = /\{"tool":\s*"filesystem_write",\s*"args":\s*\{"path":\s*"([^"]+)",\s*"content":\s*"((?:[^"\\]|\\.)*)"\}\}/g;
		
		let cleanContent = content;
		let match;
		
		while ((match = toolPattern.exec(content)) !== null) {
			const path = match[1];
			// Decode escaped characters in content
			let codeContent = match[2]
				.replace(/\\n/g, '\n')
				.replace(/\\t/g, '\t')
				.replace(/\\"/g, '"')
				.replace(/\\\\/g, '\\');
			
			codeWrites.push({
				path,
				content: codeContent,
				language: getLanguageFromPath(path)
			});
			
			// Remove the JSON from the displayed content
			cleanContent = cleanContent.replace(match[0], '');
		}
		
		// Clean up extra whitespace
		cleanContent = cleanContent.replace(/\n{3,}/g, '\n\n').trim();
		
		return { cleanContent, codeWrites };
	}

	// Animate code appearing line by line
	function startCodeAnimation(messageIndex: number, codeIndex: number, fullContent: string) {
		const key = `${messageIndex}-${codeIndex}`;
		const lines = fullContent.split('\n');
		
		if (activeCodeAnimations.has(key)) {
			return; // Animation already running
		}
		
		activeCodeAnimations.set(key, {
			fullContent,
			displayedLines: 0,
			totalLines: lines.length,
			intervalId: null
		});
		
		let currentLine = 0;
		const animSpeed = Math.max(20, Math.min(80, 2000 / lines.length)); // Adaptive speed
		
		const intervalId = setInterval(() => {
			currentLine += 1;
			const anim = activeCodeAnimations.get(key);
			if (anim) {
				anim.displayedLines = currentLine;
				activeCodeAnimations = new Map(activeCodeAnimations);
				
				// Update the message's animated content
				if (messages[messageIndex]?.codeWrites?.[codeIndex]) {
					messages[messageIndex].codeWrites[codeIndex].animatedContent = 
						lines.slice(0, currentLine).join('\n');
					messages[messageIndex].codeWrites[codeIndex].isComplete = currentLine >= lines.length;
					messages = [...messages];
				}
				
				if (currentLine >= lines.length) {
					clearInterval(intervalId);
					activeCodeAnimations.delete(key);
				}
			}
		}, animSpeed);
		
		const anim = activeCodeAnimations.get(key);
		if (anim) {
			anim.intervalId = intervalId;
		}
	}
	
	// File browser - API driven
	interface FileItem {
		name: string;
		type: 'file' | 'directory';
		path: string;
		size?: number;
		expanded?: boolean;
		children?: FileItem[];
		level?: number;
	}
	
	let files: FileItem[] = [];
	let isLoadingFiles = false;
	
	// Build hierarchical tree from flat list
	function buildFileTree(items: FileItem[]): FileItem[] {
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
	
	async function toggleDirectory(dir: FileItem) {
		if (dir.type !== 'directory') return;
		
		dir.expanded = !dir.expanded;
		
		if (dir.expanded && (!dir.children || dir.children.length === 0)) {
			// Load children
			const children = await fetchFileTree(dir.path);
			dir.children = children.map(child => ({
				...child,
				level: (dir.level || 0) + 1
			})).sort((a, b) => {
				if (a.type !== b.type) {
					return a.type === 'directory' ? -1 : 1;
				}
				return a.name.localeCompare(b.name);
			});
		}
		
		files = [...files]; // Trigger reactivity
	}
	
	function flattenTree(items: FileItem[]): FileItem[] {
		const result: FileItem[] = [];
		for (const item of items) {
			result.push(item);
			if (item.type === 'directory' && item.expanded && item.children) {
				result.push(...flattenTree(item.children));
			}
		}
		return result;
	}
	
	// API service functions
	async function fetchFileTree(path: string = ''): Promise<FileItem[]> {
		try {
			const response = await fetch(`http://localhost:8000/api/v1/files/list?path=${encodeURIComponent(path)}`);
			if (!response.ok) {
				console.error('Failed to fetch file tree:', response.statusText);
				return [];
			}
			const data = await response.json();
			return data.items || [];
		} catch (error) {
			console.error('Error fetching file tree:', error);
			return [];
		}
	}

	async function loadFileContent(path: string): Promise<string> {
		try {
			const response = await fetch(`http://localhost:8000/api/v1/files/content?path=${encodeURIComponent(path)}`);
			if (!response.ok) {
				throw new Error(`Failed to load file: ${response.statusText}`);
			}
			const data = await response.json();
			return data.content || '';
		} catch (error) {
			console.error('Error loading file:', error);
			throw error;
		}
	}

	async function saveFileContent(path: string, content: string): Promise<boolean> {
		try {
			const response = await fetch('http://localhost:8000/api/v1/files/content', {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ path, content })
			});
			if (!response.ok) {
				throw new Error(`Failed to save file: ${response.statusText}`);
			}
			return true;
		} catch (error) {
			console.error('Error saving file:', error);
			return false;
		}
	}

	async function refreshFileTree() {
		isLoadingFiles = true;
		const items = await fetchFileTree('');
		files = buildFileTree(items);
		isLoadingFiles = false;
	}

	async function openFileInEditor(file: FileItem) {
		if (file.type === 'directory') return;
		
		try {
			const content = await loadFileContent(file.path);
			if (monacoEditor) {
				monacoEditor.setValue(content);
				currentOpenFile = file.path;
				editorHasUnsavedChanges = false;
				activeView = 'forge';
				
				// Detect language from file extension
				const extension = file.name.split('.').pop()?.toLowerCase();
				const languageMap: Record<string, string> = {
					'py': 'python', 'js': 'javascript', 'ts': 'typescript',
					'json': 'json', 'md': 'markdown', 'html': 'html',
					'css': 'css', 'yaml': 'yaml', 'yml': 'yaml',
					'sh': 'shell', 'bash': 'shell', 'rs': 'rust',
					'go': 'go', 'java': 'java', 'cpp': 'cpp', 'c': 'c'
				};
				const language = languageMap[extension || ''] || 'plaintext';
				const monaco = await import('monaco-editor');
				const model = monacoEditor.getModel();
				if (model) {
					monaco.editor.setModelLanguage(model, language);
				}
			}
		} catch (error) {
			addLog(`Failed to open file: ${error}`);
		}
	}

	async function saveCurrentFile() {
		if (!currentOpenFile || !monacoEditor) return;
		
		const content = monacoEditor.getValue();
		const success = await saveFileContent(currentOpenFile, content);
		if (success) {
			editorHasUnsavedChanges = false;
			addLog(`File saved: ${currentOpenFile}`);
			await refreshFileTree();
		} else {
			addLog(`Failed to save file: ${currentOpenFile}`);
		}
	}

	// VS Code style file operations
	async function createNewFile(parentPath: string = '') {
		isCreatingFile = true;
		newItemParentPath = parentPath;
		newItemName = '';
	}

	async function createNewFolder(parentPath: string = '') {
		isCreatingFolder = true;
		newItemParentPath = parentPath;
		newItemName = '';
	}

	async function confirmCreateItem() {
		if (!newItemName.trim()) {
			isCreatingFile = false;
			isCreatingFolder = false;
			return;
		}

		const itemPath = newItemParentPath ? `${newItemParentPath}/${newItemName}` : newItemName;
		
		if (isCreatingFile) {
			// Create empty file
			await saveFileContent(itemPath, '');
		} else if (isCreatingFolder) {
			// Create folder by creating a .gitkeep inside
			await saveFileContent(`${itemPath}/.gitkeep`, '');
		}
		
		isCreatingFile = false;
		isCreatingFolder = false;
		newItemName = '';
		await refreshFileTree();
	}

	async function deleteFile(file: FileItem) {
		if (!confirm(`Are you sure you want to delete "${file.name}"?`)) return;
		
		try {
			const response = await fetch(`http://localhost:8000/api/v1/files/?path=${encodeURIComponent(file.path)}`, {
				method: 'DELETE'
			});
			if (response.ok) {
				await refreshFileTree();
				if (currentOpenFile === file.path) {
					currentOpenFile = null;
				}
			}
		} catch (error) {
			console.error('Error deleting file:', error);
		}
		contextMenuFile = null;
	}

	async function startRename(file: FileItem) {
		renamingFile = file;
		renameValue = file.name;
		contextMenuFile = null;
	}

	async function confirmRename() {
		if (!renamingFile || !renameValue.trim()) {
			renamingFile = null;
			return;
		}
		
		const oldPath = renamingFile.path;
		const parentPath = oldPath.includes('/') ? oldPath.substring(0, oldPath.lastIndexOf('/')) : '';
		const newPath = parentPath ? `${parentPath}/${renameValue}` : renameValue;
		
		// Read old content, create new file, delete old
		try {
			if (renamingFile.type === 'file') {
				const content = await loadFileContent(oldPath);
				await saveFileContent(newPath, content);
				await fetch(`http://localhost:8000/api/v1/files/?path=${encodeURIComponent(oldPath)}`, {
					method: 'DELETE'
				});
			}
			await refreshFileTree();
		} catch (error) {
			console.error('Error renaming:', error);
		}
		
		renamingFile = null;
	}

	function showContextMenu(event: MouseEvent, file: FileItem) {
		event.preventDefault();
		contextMenuFile = file;
		contextMenuPos = { x: event.clientX, y: event.clientY };
	}

	function closeContextMenu() {
		contextMenuFile = null;
	}

	// Conversation management
	async function loadConversations() {
		try {
			const response = await fetch('http://localhost:8000/api/v1/conversations');
			if (response.ok) {
				const data = await response.json();
				conversations = data.conversations || [];
			}
		} catch (error) {
			console.error('Error loading conversations:', error);
		}
	}

	async function createNewConversation() {
		try {
			const title = `Chat ${new Date().toLocaleString()}`;
			const response = await fetch('http://localhost:8000/api/v1/conversations', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					title,
					workspace_path: workspacePath,
					model: selectedModel
				})
			});
			if (response.ok) {
				const data = await response.json();
				currentConversationId = data.conversation.id;
				messages = [{ role: 'system', content: 'Prometheus AI Agent initialized. How can I assist you today?', timestamp: new Date() }];
				await loadConversations();
			}
		} catch (error) {
			console.error('Error creating conversation:', error);
		}
	}

	async function loadConversation(convId: string) {
		try {
			const response = await fetch(`http://localhost:8000/api/v1/conversations/${convId}`);
			if (response.ok) {
				const data = await response.json();
				currentConversationId = convId;
				messages = data.messages.map((m: any) => ({
					role: m.role,
					content: m.content,
					timestamp: new Date(m.timestamp)
				}));
				if (messages.length === 0) {
					messages = [{ role: 'system', content: 'Prometheus AI Agent initialized. How can I assist you today?', timestamp: new Date() }];
				}
			}
		} catch (error) {
			console.error('Error loading conversation:', error);
		}
	}

	async function deleteConversation(convId: string) {
		if (!confirm('Delete this conversation?')) return;
		try {
			await fetch(`http://localhost:8000/api/v1/conversations/${convId}`, { method: 'DELETE' });
			if (currentConversationId === convId) {
				currentConversationId = null;
				messages = [{ role: 'system', content: 'Prometheus AI Agent initialized. How can I assist you today?', timestamp: new Date() }];
			}
			await loadConversations();
		} catch (error) {
			console.error('Error deleting conversation:', error);
		}
	}

	async function saveMessageToConversation(role: string, content: string) {
		if (!currentConversationId) return;
		try {
			await fetch(`http://localhost:8000/api/v1/conversations/${currentConversationId}/messages`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ role, content })
			});
		} catch (error) {
			console.error('Error saving message:', error);
		}
	}

	// Rules management
	async function loadRules() {
		try {
			const globalRes = await fetch('http://localhost:8000/api/v1/rules/global');
			if (globalRes.ok) {
				const data = await globalRes.json();
				globalRules = data.rules || [];
			}

			const projectRes = await fetch(`http://localhost:8000/api/v1/rules/project?workspace_path=${encodeURIComponent(workspacePath)}`);
			if (projectRes.ok) {
				const data = await projectRes.json();
				projectRules = data.rules || [];
			}
		} catch (error) {
			console.error('Error loading rules:', error);
		}
	}

	async function createRule() {
		if (!newRuleName.trim() || !newRuleContent.trim()) return;
		
		try {
			const endpoint = isGlobalRule ? 'http://localhost:8000/api/v1/rules/global' : 'http://localhost:8000/api/v1/rules/project';
			await fetch(endpoint, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					name: newRuleName,
					content: newRuleContent,
					workspace_path: isGlobalRule ? null : workspacePath
				})
			});
			newRuleName = '';
			newRuleContent = '';
			await loadRules();
		} catch (error) {
			console.error('Error creating rule:', error);
		}
	}

	async function deleteRule(ruleId: number, isGlobal: boolean) {
		if (!confirm('Delete this rule?')) return;
		try {
			const endpoint = isGlobal 
				? `http://localhost:8000/api/v1/rules/global/${ruleId}`
				: `http://localhost:8000/api/v1/rules/project/${ruleId}`;
			await fetch(endpoint, { method: 'DELETE' });
			await loadRules();
		} catch (error) {
			console.error('Error deleting rule:', error);
		}
	}

	// Settings persistence
	async function loadSettings() {
		try {
			const response = await fetch('http://localhost:8000/api/v1/settings');
			if (response.ok) {
				const data = await response.json();
				const settings = data.settings || {};
				
				// Load saved values
				if (settings.apiKey) customApiKey = settings.apiKey;
				if (settings.customEndpoint) customEndpoint = settings.customEndpoint;
				if (settings.workspacePath) workspacePath = settings.workspacePath;
				if (settings.selectedModel) selectedModel = settings.selectedModel;
				if (settings.autoApproveEdits !== undefined) autoApproveEdits = settings.autoApproveEdits === 'true';
				if (settings.verboseMode !== undefined) verboseMode = settings.verboseMode === 'true';
			}
		} catch (error) {
			console.error('Error loading settings:', error);
		}
		settingsLoaded = true;
	}

	async function saveSetting(key: string, value: string) {
		if (!settingsLoaded) return; // Don't save during initial load
		try {
			await fetch('http://localhost:8000/api/v1/settings', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ key, value })
			});
		} catch (error) {
			console.error('Error saving setting:', error);
		}
	}

	// Watch for settings changes and auto-save (debounced via settingsLoaded check)
	$: if (settingsLoaded && customApiKey) saveSetting('apiKey', customApiKey);
	$: if (settingsLoaded && customEndpoint) saveSetting('customEndpoint', customEndpoint);
	$: if (settingsLoaded) saveSetting('workspacePath', workspacePath);
	$: if (settingsLoaded) saveSetting('selectedModel', selectedModel);
	$: if (settingsLoaded) saveSetting('autoApproveEdits', String(autoApproveEdits));
	$: if (settingsLoaded) saveSetting('verboseMode', String(verboseMode));

	
	function addLog(text: string, type = 'info') {
		messages = [...messages, { role: 'assistant', content: text, timestamp: new Date() }];
	}

					async function sendMessage() {
		if (!chatInput.trim() || !workspacePath) return;
		
		const userMessage = chatInput;
		messages = [...messages, { role: 'user', content: userMessage, timestamp: new Date() }];
		chatInput = '';
		isLoading = true;
		
		// Save user message to conversation
		if (currentConversationId) {
			saveMessageToConversation('user', userMessage);
		}
		abortController = new AbortController();

		if (selectedModel === 'custom' && !customEndpoint) {
			addLog('Error: Custom endpoint URL is required');
			isLoading = false;
			return;
		}

		try {
			const response = await fetch('http://localhost:8000/api/v1/chat/stream', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				signal: abortController.signal,
				body: JSON.stringify({
					model: selectedModel,
					messages: messages.map(m => ({ role: m.role, content: m.content })),
					api_base: customEndpoint || null,
					api_key: customApiKey || null,
					workspace_path: workspacePath
				})
			});

			const reader = response.body?.getReader();
			if (!reader) return;

			const decoder = new TextDecoder();
			let currentResponse = '';
			
			// Add assistant message placeholder
			messages = [...messages, { role: 'assistant', content: '', timestamp: new Date() }];

			while (true) {
				const { done, value } = await reader.read();
				if (done) break;

				const chunk = decoder.decode(value);
				const lines = chunk.split('\n');

				for (const line of lines) {
					if (line.startsWith('data: ')) {
						const dataStr = line.slice(6);
						if (dataStr === '[DONE]') {
							isLoading = false;
							isConnected = true;
							abortController = null;
							// Save assistant message to conversation
							if (currentConversationId && currentResponse) {
								saveMessageToConversation('assistant', currentResponse);
							}
							break;
						}

						try {
							const data = JSON.parse(dataStr);
							if (data.token) {
								currentResponse += data.token;
								
								// Parse code writes from the response
								const { cleanContent, codeWrites } = parseCodeWrites(currentResponse);
								
								const msgIndex = messages.length - 1;
								messages[msgIndex].content = cleanContent;
								
								// Track new code writes and start animations
								if (codeWrites.length > 0) {
									const existingWrites = messages[msgIndex].codeWrites || [];
									
									for (let i = 0; i < codeWrites.length; i++) {
										if (i >= existingWrites.length) {
											// New code write detected - add it with animation
											if (!messages[msgIndex].codeWrites) {
												messages[msgIndex].codeWrites = [];
											}
											messages[msgIndex].codeWrites.push({
												...codeWrites[i],
												animatedContent: '',
												isComplete: false
											});
											// Start the animation
											setTimeout(() => startCodeAnimation(msgIndex, i, codeWrites[i].content), 100);
										}
									}
								}
								
								messages = [...messages];
							}
							if (data.tool_execution) {
								// Log tool execution with output
								const exec = {
									type: data.tool_execution.tool || data.tool_execution.action || 'execute',
									path: data.tool_execution.path,
									file: data.tool_execution.file,
									command: data.tool_execution.command,
									stdout: data.tool_execution.stdout,
									stderr: data.tool_execution.stderr,
									status: data.tool_execution.success ? 'success' : 'error',
									timestamp: new Date(),
									return_code: data.tool_execution.return_code,
									hint: data.tool_execution.hint
								};
								toolExecutions = [...toolExecutions, exec];
								
								// Refresh file tree after file operations
								if (exec.type === 'filesystem_write' || exec.type === 'filesystem_list') {
									refreshFileTree();
								}
								
								// Auto-show terminal panel for shell commands or python runs
								if ((exec.type === 'shell_execute' && exec.command) || 
									exec.type === 'run_python' || 
									exec.type === 'run_tests') {
									showTerminalPanel = true;
								}
								
								// Write to terminal if available
								if (terminalInstance) {
									if (exec.type === 'run_python' || exec.type === 'run_tests') {
										const cmdDisplay = exec.type === 'run_python' 
											? `python3 ${exec.file}` 
											: `pytest ${exec.file || ''}`;
										terminalInstance.writeln(`\r\n\x1b[1;33m$ ${cmdDisplay}\x1b[0m`);
										if (exec.stdout) {
											terminalInstance.writeln(exec.stdout);
										}
										if (exec.stderr) {
											terminalInstance.writeln(`\x1b[1;31m${exec.stderr}\x1b[0m`);
										}
										if (exec.hint) {
											terminalInstance.writeln(`\x1b[1;33m⚠ ${exec.hint}\x1b[0m`);
										}
										terminalInstance.write('prometheus@agent:~$ ');
									} else if (exec.command) {
										terminalInstance.writeln(`\r\n\x1b[1;33m$ ${exec.command}\x1b[0m`);
										if (exec.stdout) {
											terminalInstance.writeln(exec.stdout);
										}
										if (exec.stderr) {
											terminalInstance.writeln(`\x1b[1;31m${exec.stderr}\x1b[0m`);
										}
										terminalInstance.write('prometheus@agent:~$ ');
									}
								}
							}
							if (data.error) {
								messages[messages.length - 1].content = `Error: ${data.error}`;
								isConnected = false;
							}
						} catch (e) {
							// Handle partial JSON
						}
					}
				}
			}
		} catch (err: any) {
			if (err.name === 'AbortError') {
				addLog('Generation cancelled by user');
			} else {
				addLog(`Connection failed: ${err}`);
			}
			isConnected = false;
		} finally {
			isLoading = false;
			abortController = null;
		}
	}

	function stopGeneration() {
		if (abortController) {
			abortController.abort();
			isLoading = false;
		}
	}

	async function handleDeploy() {
		chatInput = 'Say hello and tell me you are ready.';
		await sendMessage();
	}

	onMount(async () => {
		// Dynamic imports to prevent SSR issues
		const { Terminal } = await import('@xterm/xterm');
		const monaco = await import('monaco-editor');

		// Initialize Terminal
		const term = new Terminal({
			theme: {
				background: '#0a0e1a',
				foreground: '#10b981',
				cursor: '#10b981'
			},
			fontSize: 13,
			fontFamily: 'JetBrains Mono, Menlo, monospace',
			cursorBlink: true
		});
		term.open(terminalElement);
		terminalInstance = term;
		
		term.writeln('\x1b[1;36m╔═══════════════════════════════════════════════════╗\x1b[0m');
		term.writeln('\x1b[1;36m║       PROMETHEUS HEARTH TERMINAL v0.1.0          ║\x1b[0m');
		term.writeln('\x1b[1;36m╚═══════════════════════════════════════════════════╝\x1b[0m');
		term.write('\r\n\x1b[1;33mprometheus@agent\x1b[0m:\x1b[1;34m~\x1b[0m$ ');

		// Initialize Monaco
		monacoEditor = monaco.editor.create(editorElement, {
			value: `# Prometheus AI Agent Workspace
# This is your code forge - edit and create files here
# Click on files in the sidebar to open them

def hello_prometheus():
    """Welcome to the forge!"""
    print("🔥 Igniting the flames of creation...")
    
if __name__ == "__main__":
    hello_prometheus()`,
			language: 'python',
			theme: 'vs-dark',
			automaticLayout: true,
			minimap: { enabled: false },
			fontSize: 14,
			padding: { top: 16, bottom: 16 },
			lineNumbers: 'on',
			roundedSelection: true,
			scrollBeyondLastLine: false,
			renderLineHighlight: 'all'
		});

		// Track editor changes
		monacoEditor.onDidChangeModelContent(() => {
			if (currentOpenFile) {
				editorHasUnsavedChanges = true;
			}
		});

		// Add save keyboard shortcut (Ctrl+S / Cmd+S)
		monacoEditor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
			saveCurrentFile();
		});

		// Load saved settings first (API keys, etc.)
		await loadSettings();
		
		// Load file tree
		await refreshFileTree();
		
		// Load conversations and rules
		await loadConversations();
		await loadRules();
	});
</script>

<!-- Main Container -->
<div class="flex h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 text-slate-100 font-sans overflow-hidden">
	
	<!-- Sidebar -->
	<!-- VS Code Style Activity Bar -->
	<aside class="w-12 bg-slate-950 border-r border-slate-800/50 flex flex-col items-center py-2 gap-1">
		<!-- Logo -->
		<div class="w-9 h-9 rounded-lg bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center mb-4 shadow-lg shadow-amber-500/20">
			<Zap class="w-5 h-5 text-white fill-white" />
		</div>

		<!-- VS Code Style Nav -->
		<button 
			on:click={() => { showExplorer = !showExplorer; activeExplorerTab = 'files'; }}
			class="activity-btn {showExplorer && activeExplorerTab === 'files' ? 'active' : ''}"
			title="Explorer">
			<File class="w-5 h-5" />
		</button>
		
		<button 
			on:click={() => { showExplorer = true; activeExplorerTab = 'search'; }}
			class="activity-btn {showExplorer && activeExplorerTab === 'search' ? 'active' : ''}"
			title="Search">
			<Search class="w-5 h-5" />
		</button>
		
		<button 
			on:click={() => { showExplorer = true; activeExplorerTab = 'git'; }}
			class="activity-btn {showExplorer && activeExplorerTab === 'git' ? 'active' : ''}"
			title="Source Control">
			<GitBranch class="w-5 h-5" />
		</button>

		<div class="w-8 h-px bg-slate-700 my-2"></div>

		<button 
			on:click={() => activeView = 'chat'}
			class="activity-btn {activeView === 'chat' ? 'active' : ''}"
			title="AI Chat">
			<MessageSquare class="w-5 h-5" />
		</button>
		
		<button 
			on:click={() => showTerminalPanel = !showTerminalPanel}
			class="activity-btn {showTerminalPanel ? 'active' : ''}"
			title="Terminal">
			<TerminalIcon class="w-5 h-5" />
		</button>

		<div class="flex-1"></div>

		<button 
			on:click={() => { showRulesPanel = !showRulesPanel; loadRules(); }}
			class="activity-btn {showRulesPanel ? 'active' : ''}"
			title="Rules">
			<BookOpen class="w-5 h-5" />
		</button>

		<button 
			on:click={() => showSettings = !showSettings}
			class="activity-btn {showSettings ? 'active' : ''}"
			title="Settings">
			<SettingsIcon class="w-5 h-5" />
		</button>
	</aside>

	<!-- VS Code Style Side Panel (Explorer/Search/Git) -->
	{#if showExplorer}
	<aside class="w-72 bg-slate-900/80 border-r border-slate-800/50 flex flex-col overflow-hidden" style="min-width: 200px; max-width: 400px;">
		<!-- Panel Header -->
		<div class="h-9 flex items-center justify-between px-4 bg-slate-900/50 border-b border-slate-800/50">
			<span class="text-xs font-semibold text-slate-400 uppercase tracking-wider">
				{activeExplorerTab === 'files' ? 'Explorer' : activeExplorerTab === 'search' ? 'Search' : 'Source Control'}
			</span>
			<button on:click={() => showExplorer = false} class="p-1 hover:bg-slate-700/50 rounded">
				<X class="w-4 h-4 text-slate-500" />
			</button>
		</div>

		{#if activeExplorerTab === 'files'}
			<!-- File Explorer -->
			<div class="flex-1 flex flex-col overflow-hidden">
				<!-- Workspace Header -->
				<div class="px-2 py-2 flex items-center justify-between border-b border-slate-800/30">
					<div class="flex items-center gap-2 flex-1 min-w-0">
						<ChevronDown class="w-4 h-4 text-slate-500 flex-shrink-0" />
						<span class="text-xs font-semibold text-slate-300 truncate">{workspacePath.split('/').pop() || 'WORKSPACE'}</span>
					</div>
					<div class="flex items-center gap-1">
						<button on:click={() => createNewFile('')} class="p-1 hover:bg-slate-700/50 rounded" title="New File">
							<FilePlus class="w-4 h-4 text-slate-400" />
						</button>
						<button on:click={() => createNewFolder('')} class="p-1 hover:bg-slate-700/50 rounded" title="New Folder">
							<FolderPlus class="w-4 h-4 text-slate-400" />
						</button>
						<button on:click={refreshFileTree} class="p-1 hover:bg-slate-700/50 rounded" title="Refresh">
							<RefreshCw class="w-4 h-4 text-slate-400 {isLoadingFiles ? 'animate-spin' : ''}" />
						</button>
					</div>
				</div>

				<!-- File Tree -->
				<div class="flex-1 overflow-y-auto py-1" on:click={closeContextMenu}>
					{#if isLoadingFiles}
						<div class="flex items-center justify-center py-8">
							<Loader2 class="w-5 h-5 text-slate-500 animate-spin" />
						</div>
					{:else if files.length === 0}
						<div class="px-4 py-8 text-center">
							<div class="text-slate-500 text-xs mb-2">No files in workspace</div>
							<button 
								on:click={() => createNewFile('')}
								class="text-xs text-amber-500 hover:text-amber-400"
							>
								Create a file to get started
							</button>
						</div>
					{:else}
						<!-- Create New Item Input -->
						{#if isCreatingFile || isCreatingFolder}
							<div class="flex items-center gap-1 px-2 py-1" style="padding-left: 12px">
								{#if isCreatingFolder}
									<Folder class="w-4 h-4 text-amber-500 flex-shrink-0" />
								{:else}
									<File class="w-4 h-4 text-slate-400 flex-shrink-0" />
								{/if}
								<input
									type="text"
									bind:value={newItemName}
									on:keydown={(e) => { if (e.key === 'Enter') confirmCreateItem(); if (e.key === 'Escape') { isCreatingFile = false; isCreatingFolder = false; } }}
									on:blur={confirmCreateItem}
									class="flex-1 bg-slate-800 border border-amber-500 rounded px-2 py-0.5 text-xs text-slate-200 outline-none"
									placeholder={isCreatingFolder ? 'folder name' : 'filename.ext'}
									autofocus
								/>
							</div>
						{/if}

						{#each flattenTree(files) as file}
							{#if renamingFile?.path === file.path}
								<div class="flex items-center gap-1 px-2 py-1" style="padding-left: {(file.level || 0) * 12 + 12}px">
									{#if file.type === 'directory'}
										<Folder class="w-4 h-4 text-amber-500 flex-shrink-0" />
									{:else}
										<File class="w-4 h-4 text-slate-400 flex-shrink-0" />
									{/if}
									<input
										type="text"
										bind:value={renameValue}
										on:keydown={(e) => { if (e.key === 'Enter') confirmRename(); if (e.key === 'Escape') renamingFile = null; }}
										on:blur={confirmRename}
										class="flex-1 bg-slate-800 border border-amber-500 rounded px-2 py-0.5 text-xs text-slate-200 outline-none"
										autofocus
									/>
								</div>
							{:else}
								<button 
									on:click={() => file.type === 'directory' ? toggleDirectory(file) : openFileInEditor(file)}
									on:contextmenu={(e) => showContextMenu(e, file)}
									class="w-full px-2 py-1 text-left flex items-center gap-1 group transition-colors hover:bg-slate-800/60"
									class:bg-slate-700={currentOpenFile === file.path}
									style="padding-left: {(file.level || 0) * 12 + 12}px"
								>
									{#if file.type === 'directory'}
										<ChevronRight class="w-3 h-3 text-slate-500 transition-transform flex-shrink-0 {file.expanded ? 'rotate-90' : ''}" />
										<Folder class="w-4 h-4 text-amber-500 flex-shrink-0" />
									{:else}
										<span class="w-3"></span>
										<File class="w-4 h-4 text-slate-400 flex-shrink-0" />
									{/if}
									<span class="text-xs text-slate-300 group-hover:text-white truncate flex-1">{file.name}</span>
								</button>
							{/if}
						{/each}
					{/if}
				</div>
			</div>
		{:else if activeExplorerTab === 'search'}
			<!-- Search Panel -->
			<div class="flex-1 flex flex-col p-3">
				<input 
					type="text" 
					placeholder="Search files..."
					class="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 outline-none focus:border-amber-500"
				/>
				<div class="text-xs text-slate-500 mt-4 text-center">
					Search functionality coming soon
				</div>
			</div>
		{:else if activeExplorerTab === 'git'}
			<!-- Chat History Panel -->
			<div class="flex-1 flex flex-col overflow-hidden">
				<div class="px-2 py-2 flex items-center justify-between border-b border-slate-800/30">
					<span class="text-xs font-semibold text-slate-300">Chat History</span>
					<button on:click={createNewConversation} class="p-1 hover:bg-slate-700/50 rounded" title="New Chat">
						<Plus class="w-4 h-4 text-slate-400" />
					</button>
				</div>
				<div class="flex-1 overflow-y-auto py-1">
					{#if conversations.length === 0}
						<div class="px-4 py-8 text-center text-xs text-slate-500">
							No saved chats yet
						</div>
					{:else}
						{#each conversations as conv}
							<div 
								class="px-3 py-2 flex items-center gap-2 hover:bg-slate-800/50 cursor-pointer group"
								class:bg-slate-700={currentConversationId === conv.id}
								on:click={() => loadConversation(conv.id)}
							>
								<MessageSquare class="w-3 h-3 text-slate-500 flex-shrink-0" />
								<span class="text-xs text-slate-300 truncate flex-1">{conv.title}</span>
								<button 
									on:click|stopPropagation={() => deleteConversation(conv.id)}
									class="p-1 opacity-0 group-hover:opacity-100 hover:bg-red-500/20 rounded"
								>
									<Trash2 class="w-3 h-3 text-red-400" />
								</button>
							</div>
						{/each}
					{/if}
				</div>
			</div>
		{/if}
	</aside>
	{/if}

	<!-- Context Menu -->
	{#if contextMenuFile}
		<div 
			class="fixed bg-slate-800 border border-slate-700 rounded-lg shadow-xl py-1 z-50"
			style="left: {contextMenuPos.x}px; top: {contextMenuPos.y}px"
		>
			<button 
				on:click={() => { openFileInEditor(contextMenuFile); contextMenuFile = null; }}
				class="w-full px-4 py-1.5 text-left text-xs text-slate-300 hover:bg-slate-700 flex items-center gap-2"
			>
				<FileCode class="w-3 h-3" /> Open
			</button>
			<button 
				on:click={() => startRename(contextMenuFile)}
				class="w-full px-4 py-1.5 text-left text-xs text-slate-300 hover:bg-slate-700 flex items-center gap-2"
			>
				<Edit3 class="w-3 h-3" /> Rename
			</button>
			<div class="h-px bg-slate-700 my-1"></div>
			<button 
				on:click={() => deleteFile(contextMenuFile)}
				class="w-full px-4 py-1.5 text-left text-xs text-red-400 hover:bg-slate-700 flex items-center gap-2"
			>
				<Trash2 class="w-3 h-3" /> Delete
			</button>
		</div>
	{/if}

	<!-- Main Content -->
	<main class="flex-1 flex flex-col overflow-hidden">
		
		<!-- Top Bar -->
		<header class="h-16 border-b border-slate-800/50 bg-slate-900/30 backdrop-blur-xl flex items-center justify-between px-6">
			<div class="flex items-center gap-4">
				<h1 class="text-lg font-black tracking-tight bg-gradient-to-r from-amber-400 to-orange-500 bg-clip-text text-transparent">
					PROMETHEUS
				</h1>
				<div class="h-4 w-px bg-slate-700"></div>
				<div class="flex items-center gap-2 text-xs text-slate-400">
					{#if isConnected}
						<div class="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
						<span>Connected</span>
					{:else if isLoading}
						<Loader2 class="w-3 h-3 animate-spin" />
						<span>Connecting...</span>
					{:else}
						<div class="w-2 h-2 rounded-full bg-slate-600"></div>
						<span>Disconnected</span>
					{/if}
				</div>
			</div>

			<div class="flex items-center gap-3">
				<!-- Model Selector -->
				<div class="flex items-center gap-2 bg-slate-800 px-3 py-2 rounded-lg border border-slate-700 hover:border-amber-500/50 transition-all">
					<Cpu class="w-4 h-4 text-amber-500" />
					<select
						bind:value={selectedModel}
						class="model-select bg-slate-800 border-none text-xs text-slate-100 cursor-pointer outline-none font-medium min-w-[140px]"
					>
						<optgroup label="Local Models">
							<option value="ollama/llama3.2">Llama 3.2</option>
							<option value="ollama/codellama">CodeLlama</option>
							<option value="ollama/deepseek-r1">DeepSeek R1 (Local)</option>
						</optgroup>
						<optgroup label="DeepSeek API">
							<option value="deepseek/deepseek-chat">DeepSeek Chat</option>
							<option value="deepseek/deepseek-reasoner">DeepSeek Reasoner</option>
						</optgroup>
						<optgroup label="Commercial">
							<option value="anthropic/claude-3-5-sonnet-20240620">Claude 3.5 Sonnet</option>
							<option value="openai/gpt-4o">GPT-4o</option>
						</optgroup>
						<optgroup label="Custom">
							<option value="custom">Custom Endpoint</option>
						</optgroup>
					</select>
				</div>

				<!-- Deploy Button -->
				<button 
					on:click={handleDeploy}
					disabled={isLoading}
					class="px-4 py-2 rounded-lg font-bold text-sm bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-600 hover:to-orange-700 active:scale-95 transition-all shadow-lg shadow-amber-500/30 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
				>
					{#if isLoading}
						<Loader2 class="w-4 h-4 animate-spin" />
					{:else}
						<Play class="w-4 h-4 fill-current" />
					{/if}
					<span>Deploy</span>
				</button>
			</div>
		</header>

		<!-- Settings Panel -->
		{#if showSettings}
			<div class="absolute right-6 top-20 w-96 bg-slate-900 border border-slate-700/50 rounded-xl shadow-2xl z-50 p-6 animate-in slide-in-from-right backdrop-blur-xl">
				<div class="flex items-center justify-between mb-6">
					<div class="flex items-center gap-3">
						<div class="w-10 h-10 rounded-lg bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center">
							<Globe class="w-5 h-5 text-white" />
						</div>
						<h3 class="text-base font-bold text-white">Connection Settings</h3>
					</div>
					<button on:click={() => showSettings = false} class="text-slate-400 hover:text-white">
						<X class="w-5 h-5" />
					</button>
				</div>
				
				<div class="space-y-5">
					<div>
						<label class="block text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">Workspace Path (Required)</label>
						<input 
							type="text" 
							bind:value={workspacePath}
							placeholder="/home/john/my_project"
							class="w-full bg-slate-950 border border-slate-700 rounded-lg px-4 py-2.5 text-sm focus:border-amber-500 focus:ring-1 focus:ring-amber-500 outline-none transition-all font-mono"
						/>
						<p class="text-[10px] text-slate-500 mt-1.5 italic">Directory where the agent will create/modify files</p>
					</div>

					<div class="flex items-center justify-between p-3 bg-slate-950 rounded-lg border border-slate-700">
						<div>
							<label class="block text-[10px] font-bold text-slate-400 uppercase">Auto-Approve Edits</label>
							<p class="text-[9px] text-slate-500 mt-0.5">Allow agent to create/modify files without asking</p>
						</div>
						<button 
							on:click={() => autoApproveEdits = !autoApproveEdits}
							class="relative w-12 h-6 rounded-full transition-colors {autoApproveEdits ? 'bg-green-500' : 'bg-slate-700'}"
						>
							<div class="absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform {autoApproveEdits ? 'translate-x-6' : ''}"></div>
						</button>
					</div>

					<div class="flex items-center justify-between p-3 bg-slate-950 rounded-lg border border-slate-700">
						<div>
							<label class="block text-[10px] font-bold text-slate-400 uppercase">Verbose Mode</label>
							<p class="text-[9px] text-slate-500 mt-0.5">Show internal tool calls and debug info</p>
						</div>
						<button 
							on:click={() => verboseMode = !verboseMode}
							class="relative w-12 h-6 rounded-full transition-colors {verboseMode ? 'bg-amber-500' : 'bg-slate-700'}"
						>
							<div class="absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform {verboseMode ? 'translate-x-6' : ''}"></div>
						</button>
					</div>

					<div>
						<label class="block text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">Custom Endpoint URL</label>
						<input 
							type="text" 
							bind:value={customEndpoint}
							placeholder="http://192.168.1.50:11434"
							class="w-full bg-slate-950 border border-slate-700 rounded-lg px-4 py-2.5 text-sm focus:border-amber-500 focus:ring-1 focus:ring-amber-500 outline-none transition-all"
						/>
						<p class="text-[10px] text-slate-500 mt-1.5 italic">For remote Ollama or LM Studio instances</p>
					</div>

					<div>
						<label class="block text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">API Key (Optional)</label>
						<div class="relative">
							<Shield class="absolute left-3 top-3 w-4 h-4 text-slate-600" />
							<input 
								type="password" 
								bind:value={customApiKey}
								placeholder="sk-..."
								class="w-full bg-slate-950 border border-slate-700 rounded-lg pl-10 pr-4 py-2.5 text-sm focus:border-amber-500 focus:ring-1 focus:ring-amber-500 outline-none transition-all"
							/>
						</div>
					</div>

					<button 
						on:click={() => showSettings = false}
						class="w-full bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-600 hover:to-orange-700 text-white text-sm font-bold py-2.5 rounded-lg transition-all shadow-lg shadow-amber-500/20"
					>
						<Check class="w-4 h-4 inline mr-2" />
						Save & Close
					</button>
				</div>
			</div>
		{/if}

		<!-- Rules Panel -->
		{#if showRulesPanel}
			<div class="absolute right-6 top-20 w-[450px] bg-slate-900 border border-slate-700/50 rounded-xl shadow-2xl z-50 p-6 animate-in slide-in-from-right backdrop-blur-xl max-h-[80vh] overflow-y-auto">
				<div class="flex items-center justify-between mb-6">
					<div class="flex items-center gap-3">
						<div class="w-10 h-10 rounded-lg bg-gradient-to-br from-purple-500 to-indigo-600 flex items-center justify-center">
							<BookOpen class="w-5 h-5 text-white" />
						</div>
						<h3 class="text-base font-bold text-white">Rules & Memory</h3>
					</div>
					<button on:click={() => showRulesPanel = false} class="text-slate-400 hover:text-white">
						<X class="w-5 h-5" />
					</button>
				</div>
				
				<p class="text-xs text-slate-400 mb-4">
					Rules are injected into every conversation to guide the agent's behavior.
				</p>

				<!-- Create New Rule -->
				<div class="bg-slate-950 rounded-lg p-4 border border-slate-700 mb-4">
					<div class="flex items-center gap-4 mb-3">
						<label class="flex items-center gap-2 text-xs text-slate-300">
							<input type="radio" bind:group={isGlobalRule} value={true} class="accent-amber-500" />
							Global Rule
						</label>
						<label class="flex items-center gap-2 text-xs text-slate-300">
							<input type="radio" bind:group={isGlobalRule} value={false} class="accent-amber-500" />
							Project Rule
						</label>
					</div>
					<input 
						type="text" 
						bind:value={newRuleName}
						placeholder="Rule name (e.g., 'Code Style')"
						class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 mb-2 outline-none focus:border-amber-500"
					/>
					<textarea 
						bind:value={newRuleContent}
						placeholder="Rule content (e.g., 'Always use TypeScript. Follow PEP-8 for Python.')"
						rows="3"
						class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 mb-2 outline-none focus:border-amber-500 resize-none"
					></textarea>
					<button 
						on:click={createRule}
						class="w-full bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-600 hover:to-orange-700 text-white text-sm font-bold py-2 rounded transition-all"
					>
						Add Rule
					</button>
				</div>

				<!-- Global Rules -->
				<div class="mb-4">
					<h4 class="text-xs font-bold text-slate-400 uppercase mb-2">Global Rules (Apply to all projects)</h4>
					{#if globalRules.length === 0}
						<div class="text-xs text-slate-500 italic">No global rules defined</div>
					{:else}
						<div class="space-y-2">
							{#each globalRules as rule}
								<div class="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
									<div class="flex items-center justify-between mb-1">
										<span class="text-xs font-bold text-slate-300">{rule.name}</span>
										<button on:click={() => deleteRule(rule.id, true)} class="p-1 hover:bg-red-500/20 rounded">
											<Trash2 class="w-3 h-3 text-red-400" />
										</button>
									</div>
									<p class="text-[10px] text-slate-400 line-clamp-2">{rule.content}</p>
								</div>
							{/each}
						</div>
					{/if}
				</div>

				<!-- Project Rules -->
				<div>
					<h4 class="text-xs font-bold text-slate-400 uppercase mb-2">Project Rules (This workspace only)</h4>
					{#if projectRules.length === 0}
						<div class="text-xs text-slate-500 italic">No project rules for this workspace</div>
					{:else}
						<div class="space-y-2">
							{#each projectRules as rule}
								<div class="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
									<div class="flex items-center justify-between mb-1">
										<span class="text-xs font-bold text-slate-300">{rule.name}</span>
										<button on:click={() => deleteRule(rule.id, false)} class="p-1 hover:bg-red-500/20 rounded">
											<Trash2 class="w-3 h-3 text-red-400" />
										</button>
									</div>
									<p class="text-[10px] text-slate-400 line-clamp-2">{rule.content}</p>
								</div>
							{/each}
						</div>
					{/if}
				</div>
			</div>
		{/if}

		<!-- Content Area -->
		<div class="flex-1 flex overflow-hidden">
			
			<!-- Chat View -->
			<div class="flex-1 flex" class:hidden={activeView !== 'chat'}>
				<div class="flex-1 flex flex-col">
					<!-- Messages -->
					<div class="flex-1 overflow-y-auto p-6 space-y-4">
						{#each messages as msg, i}
							<div class="flex gap-3 {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
								{#if msg.role !== 'user'}
									<div class="w-8 h-8 rounded-lg bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center flex-shrink-0">
										<Sparkles class="w-4 h-4 text-white" />
									</div>
								{/if}
								<div class="max-w-2xl {msg.role === 'user' ? 'bg-amber-500/10 border-amber-500/30' : 'bg-slate-800/50 border-slate-700/50'} border rounded-xl p-4">
									{#if msg.content}
										<div class="text-sm text-slate-200 leading-relaxed whitespace-pre-wrap">{msg.content}</div>
									{/if}
									
									<!-- Animated Code Writes -->
									{#if msg.codeWrites && msg.codeWrites.length > 0}
										{#each msg.codeWrites as codeWrite, codeIdx}
											<div class="mt-3 rounded-lg overflow-hidden border border-slate-600/50 bg-slate-900/80">
												<!-- File Header -->
												<div class="flex items-center justify-between px-3 py-2 bg-slate-800/80 border-b border-slate-700/50">
													<div class="flex items-center gap-2">
														<FileCode class="w-4 h-4 text-amber-500" />
														<span class="text-xs font-mono text-slate-300">{codeWrite.path}</span>
														<span class="text-[10px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-400 uppercase">{codeWrite.language}</span>
													</div>
													<div class="flex items-center gap-2">
														{#if !codeWrite.isComplete}
															<div class="flex items-center gap-1">
																<div class="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse"></div>
																<span class="text-[10px] text-amber-400">Writing...</span>
															</div>
														{:else}
															<div class="flex items-center gap-1">
																<Check class="w-3 h-3 text-green-500" />
																<span class="text-[10px] text-green-400">Saved</span>
															</div>
														{/if}
													</div>
												</div>
												
												<!-- Code Content with Line Numbers -->
												<div class="relative overflow-x-auto">
													<pre class="p-0 m-0 text-xs leading-5"><code class="block">{#each (codeWrite.animatedContent || '').split('\n') as line, lineNum}<div class="flex hover:bg-slate-800/50 transition-colors"><span class="w-10 inline-block text-right pr-3 text-slate-600 select-none border-r border-slate-700/50 bg-slate-900/50">{lineNum + 1}</span><span class="pl-3 text-slate-200">{line}</span></div>{/each}</code></pre>
													
													<!-- Typing cursor -->
													{#if !codeWrite.isComplete}
														<div class="absolute bottom-1 right-3">
															<span class="inline-block w-2 h-4 bg-amber-500 animate-pulse"></span>
														</div>
													{/if}
												</div>
											</div>
										{/each}
									{/if}
									
									<div class="text-[10px] text-slate-500 mt-2">{msg.timestamp.toLocaleTimeString()}</div>
								</div>
								{#if msg.role === 'user'}
									<div class="w-8 h-8 rounded-lg bg-slate-700 flex items-center justify-center flex-shrink-0">
										<span class="text-xs font-bold">You</span>
									</div>
								{/if}
							</div>
						{/each}
						
						{#if isLoading}
							<div class="flex gap-3">
								<div class="w-8 h-8 rounded-lg bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center">
									<Loader2 class="w-4 h-4 text-white animate-spin" />
								</div>
								<div class="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4">
									<div class="flex gap-1">
										<div class="w-2 h-2 bg-slate-500 rounded-full animate-bounce"></div>
										<div class="w-2 h-2 bg-slate-500 rounded-full animate-bounce [animation-delay:0.1s]"></div>
										<div class="w-2 h-2 bg-slate-500 rounded-full animate-bounce [animation-delay:0.2s]"></div>
									</div>
								</div>
							</div>
						{/if}
					</div>

					<!-- Input -->
					<div class="border-t border-slate-800/50 p-4 bg-slate-900/30 backdrop-blur-xl">
						<div class="flex gap-3">
							<input 
								type="text"
								bind:value={chatInput}
								on:keydown={(e) => e.key === 'Enter' && !isLoading && sendMessage()}
								placeholder="Ask Prometheus anything..."
								class="flex-1 bg-slate-800/50 border border-slate-700/50 rounded-xl px-4 py-3 text-sm focus:border-amber-500 focus:ring-1 focus:ring-amber-500 outline-none transition-all placeholder-slate-500"
								disabled={isLoading}
							/>
							{#if isLoading}
								<button 
									on:click={stopGeneration}
									class="px-6 py-3 rounded-xl font-bold text-sm bg-red-500 hover:bg-red-600 active:scale-95 transition-all shadow-lg shadow-red-500/30"
								>
									<X class="w-4 h-4 inline mr-2" />
									Stop
								</button>
							{:else}
								<button 
									on:click={sendMessage}
									disabled={!chatInput.trim() || !workspacePath}
									class="px-6 py-3 rounded-xl font-bold text-sm bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-600 hover:to-orange-700 active:scale-95 transition-all shadow-lg shadow-amber-500/30 disabled:opacity-50 disabled:cursor-not-allowed"
								>
									Send
								</button>
							{/if}
						</div>
						{#if !workspacePath}
							<div class="mt-2 flex items-center gap-2 text-xs text-amber-400">
								<AlertCircle class="w-3 h-3" />
								<span>Please set your workspace path in Settings first</span>
							</div>
						{/if}
					</div>
				</div>

				<!-- Tool Activity Panel (Collapsible Right Side) -->
				<aside class="w-64 border-l border-slate-800/50 bg-slate-900/20 backdrop-blur-xl flex flex-col">
					<div class="p-3 border-b border-slate-800/50">
						<div class="flex items-center gap-2 mb-2">
							<Zap class="w-4 h-4 text-amber-500" />
							<span class="text-xs font-bold text-slate-300">Tool Activity</span>
						</div>
						{#if toolExecutions.length > 0}
							<div class="space-y-2 max-h-96 overflow-y-auto">
								{#each toolExecutions.slice(-10) as exec}
									<div class="bg-slate-800/30 rounded px-2 py-1.5 border border-slate-700/50">
										<div class="flex items-center gap-2">
											{#if exec.status === 'success'}
												<Check class="w-3 h-3 text-green-500 flex-shrink-0" />
											{:else}
												<AlertCircle class="w-3 h-3 text-red-500 flex-shrink-0" />
											{/if}
											<div class="text-[10px] font-bold text-slate-400 uppercase truncate">{exec.type}</div>
										</div>
										<div class="text-[10px] text-slate-300 font-mono truncate mt-1">
											{#if exec.type === 'run_python' || exec.type === 'run_tests'}
												{exec.file || 'Running tests...'}
											{:else if exec.path}
												{exec.path}
											{:else if exec.command}
												{exec.command}
											{:else if exec.type === 'filesystem_list'}
												Listed workspace files
											{:else if exec.type === 'filesystem_write'}
												File created/modified
											{:else if exec.type === 'filesystem_read'}
												File read
											{:else}
												Executed
											{/if}
										</div>
										{#if exec.stdout}
											<div class="text-[9px] text-green-400 font-mono mt-1 opacity-70 whitespace-pre-wrap max-h-20 overflow-y-auto">{exec.stdout.substring(0, 200)}{exec.stdout.length > 200 ? '...' : ''}</div>
										{/if}
										{#if exec.stderr}
											<div class="text-[9px] text-red-400 font-mono mt-1 opacity-70 whitespace-pre-wrap max-h-20 overflow-y-auto">{exec.stderr.substring(0, 200)}{exec.stderr.length > 200 ? '...' : ''}</div>
										{/if}
										{#if exec.hint}
											<div class="text-[9px] text-amber-400 italic mt-1">{exec.hint}</div>
										{/if}
										{#if exec.return_code !== undefined && exec.return_code !== 0}
											<div class="text-[9px] text-red-400 mt-1">Exit code: {exec.return_code}</div>
										{/if}
									</div>
								{/each}
							</div>
						{:else}
							<div class="text-xs text-slate-500 italic">No tool executions yet</div>
						{/if}
					</div>
				</aside>
			</div>

			<!-- Forge View (always in DOM, hidden when not active) -->
			<div class="flex-1 flex flex-col" class:hidden={activeView !== 'forge'}>
				<div class="h-10 border-b border-slate-800/50 bg-slate-900/20 flex items-center px-4 gap-2 justify-between">
					<div class="flex items-center gap-2">
						<FileCode class="w-4 h-4 text-amber-500" />
						<span class="text-xs font-medium text-slate-400">
							{currentOpenFile || 'The Forge - Code Editor'}
						</span>
						{#if editorHasUnsavedChanges}
							<span class="text-xs text-amber-400">● Unsaved</span>
						{/if}
					</div>
					{#if currentOpenFile}
						<button
							on:click={saveCurrentFile}
							class="px-3 py-1 rounded text-xs font-bold bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-600 hover:to-orange-700 transition-all flex items-center gap-1"
							title="Save file (Ctrl+S / Cmd+S)"
						>
							<Check class="w-3 h-3" />
							Save
						</button>
					{/if}
				</div>
				<div bind:this={editorElement} class="flex-1"></div>
			</div>

		</div>
		
		<!-- Bottom Terminal Panel (always in DOM, slides up when active) -->
		<div 
			class="border-t border-slate-700/50 bg-[#0a0e1a] transition-all duration-300 ease-in-out overflow-hidden"
			style="height: {showTerminalPanel ? '280px' : '0px'}"
		>
			<div class="h-10 border-b border-slate-800/50 bg-slate-900/40 flex items-center px-4 gap-2">
				<TerminalIcon class="w-4 h-4 text-green-500" />
				<span class="text-xs font-medium text-slate-400">The Hearth - Command Center</span>
				<div class="flex-1"></div>
				<button 
					on:click={() => showTerminalPanel = false}
					class="p-1 hover:bg-slate-700/50 rounded transition-colors"
				>
					<X class="w-4 h-4 text-slate-400" />
				</button>
			</div>
			<div bind:this={terminalElement} class="h-[230px] p-2"></div>
		</div>
	</main>
</div>

<style>
	:global(body) {
		margin: 0;
		padding: 0;
		overflow: hidden;
		background: #020617;
		font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
	}

	/* Activity Bar Buttons (VS Code style) */
	.activity-btn {
		@apply w-10 h-10 rounded flex items-center justify-center text-slate-500 hover:text-slate-300 transition-all relative;
	}

	.activity-btn.active {
		@apply text-white;
	}

	.activity-btn.active::before {
		content: '';
		@apply absolute left-0 w-0.5 h-6 bg-amber-500 rounded-r;
	}

	/* Legacy nav buttons */
	.nav-btn {
		@apply w-12 h-12 rounded-xl flex items-center justify-center text-slate-400 hover:text-white hover:bg-slate-800/50 transition-all relative;
	}

	.nav-btn.active {
		@apply text-white bg-gradient-to-br from-amber-500/20 to-orange-600/20 border border-amber-500/30;
	}

	.nav-btn.active::before {
		content: '';
		@apply absolute left-0 w-1 h-8 bg-gradient-to-b from-amber-500 to-orange-600 rounded-r;
	}

	/* Scrollbar Styling */
	:global(::-webkit-scrollbar) {
		width: 8px;
		height: 8px;
	}

	:global(::-webkit-scrollbar-track) {
		background: transparent;
	}

	:global(::-webkit-scrollbar-thumb) {
		background: #334155;
		border-radius: 4px;
	}

	:global(::-webkit-scrollbar-thumb:hover) {
		background: #475569;
	}

	/* Code Animation Styles */
	.code-line-enter {
		animation: code-line-fade-in 0.15s ease-out forwards;
	}

	@keyframes code-line-fade-in {
		from {
			opacity: 0;
			transform: translateY(-2px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}

	/* Syntax Highlighting Colors (minimal) */
	pre code {
		font-family: 'JetBrains Mono', 'Fira Code', 'Monaco', monospace;
		tab-size: 4;
	}

	/* Typing Cursor Animation */
	@keyframes blink-cursor {
		0%, 50% { opacity: 1; }
		51%, 100% { opacity: 0; }
	}

	.typing-cursor {
		animation: blink-cursor 0.8s infinite;
	}

	/* Code block styling */
	.code-write-block {
		box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
	}

	/* Smooth scroll for code */
	.code-content {
		scroll-behavior: smooth;
	}

	/* Animations */
	@keyframes slide-in-from-right {
		from {
			transform: translateX(100%);
			opacity: 0;
		}
		to {
			transform: translateX(0);
			opacity: 1;
		}
	}

	.animate-in.slide-in-from-right {
		animation: slide-in-from-right 0.3s ease-out;
	}

	/* Monaco Editor Adjustments */
	:global(.monaco-editor) {
		@apply rounded-lg;
	}

	:global(.monaco-editor .margin) {
		background: #0f172a !important;
	}

	/* Model Selector Dropdown Fix */
	.model-select {
		appearance: none;
		-webkit-appearance: none;
		-moz-appearance: none;
		padding-right: 20px;
		background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23f59e0b' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E");
		background-repeat: no-repeat;
		background-position: right 0 center;
	}

	.model-select option {
		background-color: #1e293b;
		color: #e2e8f0;
		padding: 8px 12px;
	}

	.model-select optgroup {
		background-color: #0f172a;
		color: #94a3b8;
		font-weight: bold;
		padding: 4px 0;
	}

	.model-select:focus {
		outline: none;
	}
</style>
