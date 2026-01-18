<script lang="ts">
	import { onMount } from 'svelte';
	import { 
		Cpu, MessageSquare, FileCode, Play, Sparkles,
		FolderOpen, Plus, ChevronRight, X, Check, AlertCircle, Loader2,
		Search, GitBranch, RefreshCw, Trash2, FilePlus, FolderPlus, Edit3,
		ChevronDown, File, Folder
	} from 'lucide-svelte';
	
	// Import our refactored components
	import ActivityBar from '$lib/components/sidebar/ActivityBar.svelte';
	import SettingsPanel from '$lib/components/panels/SettingsPanel.svelte';
	import RulesPanel from '$lib/components/panels/RulesPanel.svelte';
	import MemoriesPanel from '$lib/components/panels/MemoriesPanel.svelte';
	import MCPServersPanel from '$lib/components/panels/MCPServersPanel.svelte';
	import TerminalPanel from '$lib/components/panels/TerminalPanel.svelte';
	
	// Import stores
	import { 
		selectedModel, customEndpoint, customApiKey, apiKeys, workspacePath, 
		verboseMode, autoApproveEdits, settingsLoaded, showSettings,
		conversations, currentConversationId, globalRules, projectRules,
		memories, mcpServers, availableTools, files, isLoadingFiles,
		showExplorer, activeExplorerTab, activeView, showTerminalPanel,
		messages, chatInput, isLoading, isConnected, abortController,
		currentOpenFile, editorHasUnsavedChanges, toolExecutions,
		gitStatus, gitBranches, gitCommits, isGitRepo, githubAuthenticated, githubUser
	} from '$lib/stores';
	
	// Import API functions
	import { loadConversations as loadConversationsAPI, createConversation, loadConversation, deleteConversation as deleteConversationAPI, saveMessageToConversation, streamChat } from '$lib/api/chat';
	import { loadSettings as loadSettingsAPI, saveSetting } from '$lib/api/settings';
	import { listFiles, readFile, writeFile, deleteFile as deleteFileAPI, searchFiles as searchFilesAPI } from '$lib/api/files';
	import { getGitStatus, initGitRepo as initGitRepoAPI, stageFiles as stageFilesAPI, unstageFiles as unstageFilesAPI, createCommit as createCommitAPI, getBranches, getCommitLog, pushToRemote as pushToRemoteAPI, pullFromRemote as pullFromRemoteAPI, checkGitHubAuth as checkGitHubAuthAPI, addRemote, createGitHubRepo as createGitHubRepoAPI } from '$lib/api/git';
	import { loadGlobalRules, loadProjectRules, createRule as createRuleAPI, deleteRule as deleteRuleAPI } from '$lib/api/rules';
	import { loadMemories as loadMemoriesAPI, deleteMemory as deleteMemoryAPI } from '$lib/api/memories';
	import { loadMCPServers as loadMCPServersAPI, loadAvailableTools as loadAvailableToolsAPI, createMCPServer, deleteMCPServer as deleteMCPServerAPI, reloadMCPServer as reloadMCPServerAPI } from '$lib/api/mcp';
	
	// Import utilities
	import { buildFileTree, flattenTree, findFileInTree } from '$lib/utils/fileTree';
	import { getLanguageFromPath } from '$lib/utils/language';
	
	// File explorer state
	let isCreatingFile = false;
	let isCreatingFolder = false;
	let newItemName = '';
	let newItemParentPath = '';
	let contextMenuFile: any | null = null;
	let contextMenuPos = { x: 0, y: 0 };
	let renamingFile: any | null = null;
	let renameValue = '';
	
	// File search
	let fileSearchQuery = '';
	let fileSearchResults: Array<any> = [];
	let isSearchingFiles = false;
	let searchInContent = false;
	
	// Git state
	let selectedFiles: Set<string> = new Set();
	let commitMessage = '';
	let showGitHubAuth = false;
	let showCreateRepo = false;
	let githubToken = '';
	let newRepoName = '';
	let newRepoDescription = '';
	let newRepoPrivate = false;
	
	// Editor
	let terminalElement: HTMLElement;
	let editorElement: HTMLElement;
	let monacoEditor: any = null;
	let monacoInitialized = false;
	
	// Initialize Monaco editor lazily (when editor element is available)
	async function initializeMonaco() {
		if (monacoInitialized || !editorElement) return;
		
		try {
			console.log('Initializing Monaco Editor...');
			const monaco = await import('monaco-editor');
			monacoEditor = monaco.editor.create(editorElement, {
				value: '// Select a file from the explorer to edit',
				language: 'javascript',
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
			
			monacoEditor.onDidChangeModelContent(() => {
				if ($currentOpenFile) $editorHasUnsavedChanges = true;
			});
			
			monacoEditor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
				saveCurrentFile();
			});
			
			monacoInitialized = true;
			console.log('Monaco Editor initialized');
		} catch (error) {
			console.error('Error initializing Monaco Editor:', error);
		}
	}
	
	// Code writing animations
	interface CodeAnimation {
		path: string;
		fullContent: string;
		displayedContent: string;
		currentIndex: number;
		language: string;
		completed: boolean;
	}
	let activeCodeAnimations: Map<string, CodeAnimation> = new Map();

	function startCodeAnimation(path: string, content: string) {
		const language = getLanguageFromPath(path);
		const animation: CodeAnimation = {
			path,
			fullContent: content,
			displayedContent: '',
			currentIndex: 0,
			language,
			completed: false
		};

		activeCodeAnimations.set(path, animation);
		activeCodeAnimations = activeCodeAnimations;

		// Animate character by character at ~50 chars/sec for smooth effect
		const charsPerFrame = 5;
		const interval = setInterval(() => {
			const anim = activeCodeAnimations.get(path);
			if (!anim) {
				clearInterval(interval);
				return;
			}

			if (anim.currentIndex >= anim.fullContent.length) {
				anim.completed = true;
				clearInterval(interval);

				// When animation completes, append formatted code block to assistant's message
				if ($messages.length > 0 && $messages[$messages.length - 1].role === 'assistant') {
					const fileExtension = path.split('.').pop()?.toLowerCase() || '';
					const codeBlock = `\n\n**File: \`${path}\`**\n\`\`\`${language}\n${content}\n\`\`\``;

					$messages[$messages.length - 1].content += codeBlock;
					$messages = [...$messages];

					// Save to conversation if active
					if ($currentConversationId) {
						saveMessageToConversation($currentConversationId, 'assistant', $messages[$messages.length - 1].content);
					}
				}

				// Remove animation from active list after 1 second (gives time to see completion)
				setTimeout(() => {
					activeCodeAnimations.delete(path);
					activeCodeAnimations = activeCodeAnimations;
				}, 1000);
			} else {
				anim.displayedContent += anim.fullContent.slice(anim.currentIndex, anim.currentIndex + charsPerFrame);
				anim.currentIndex += charsPerFrame;
			}

			activeCodeAnimations = activeCodeAnimations;
		}, 100);
	}
	
	// Debounced save for settings
	let saveTimeout: any;
	function debouncedSave(key: string, value: string) {
		clearTimeout(saveTimeout);
		saveTimeout = setTimeout(() => {
			saveSetting(key, value);
		}, 500);
	}
	
	// Settings reactivity - save when changed
	$: if ($settingsLoaded && $customApiKey) debouncedSave('apiKey', $customApiKey);
	$: if ($settingsLoaded && $customEndpoint) debouncedSave('customEndpoint', $customEndpoint);
	$: if ($settingsLoaded && $workspacePath) debouncedSave('workspacePath', $workspacePath);
	$: if ($settingsLoaded && $selectedModel) debouncedSave('selectedModel', $selectedModel);
	$: if ($settingsLoaded) debouncedSave('autoApproveEdits', String($autoApproveEdits));
	$: if ($settingsLoaded) debouncedSave('verboseMode', String($verboseMode));
	$: if ($settingsLoaded && $apiKeys.openai) debouncedSave('openai_api_key', $apiKeys.openai);
	$: if ($settingsLoaded && $apiKeys.anthropic) debouncedSave('anthropic_api_key', $apiKeys.anthropic);
	$: if ($settingsLoaded && $apiKeys.deepseek) debouncedSave('deepseek_api_key', $apiKeys.deepseek);
	$: if ($settingsLoaded && $apiKeys.grok) debouncedSave('grok_api_key', $apiKeys.grok);
	$: if ($settingsLoaded && $apiKeys.google) debouncedSave('google_api_key', $apiKeys.google);
	$: if ($settingsLoaded && $apiKeys.litellm) debouncedSave('litellm_api_key', $apiKeys.litellm);
	
	function addLog(text: string) {
		$messages = [...$messages, { role: 'assistant', content: text, timestamp: new Date() }];
	}
	
	// File operations
	async function refreshFileTree() {
		try {
			$isLoadingFiles = true;
			console.log('Fetching file tree from workspace:', $workspacePath);
			const items = await listFiles('', $workspacePath);
			console.log('Got items:', items);
			$files = buildFileTree(items);
			console.log('Built tree, files count:', $files.length);
		} catch (error) {
			console.error('Error loading file tree:', error);
			addLog(`Failed to load file tree: ${error}`);
		} finally {
			$isLoadingFiles = false;
		}
	}
	
	async function toggleDirectory(dir: any) {
		if (dir.type !== 'directory') return;
		dir.expanded = !dir.expanded;
		if (dir.expanded && (!dir.children || dir.children.length === 0)) {
			const children = await listFiles(dir.path, $workspacePath);
			dir.children = children.map(child => ({
				...child,
				level: (dir.level || 0) + 1
			})).sort((a, b) => {
				if (a.type !== b.type) return a.type === 'directory' ? -1 : 1;
				return a.name.localeCompare(b.name);
			});
		}
		$files = [...$files];
	}
	
	async function openFileInEditor(file: any) {
		if (file.type === 'directory') return;
		try {
			const content = await readFile(file.path, $workspacePath);

			// Switch to editor view first (so the editor element is rendered)
			$activeView = 'forge';
			$currentOpenFile = file.path;

			// Wait a tick for the DOM to update
			await new Promise(resolve => setTimeout(resolve, 50));

			// Initialize Monaco if needed
			if (!monacoInitialized && editorElement) {
				await initializeMonaco();
			}

			if (monacoEditor) {
				monacoEditor.setValue(content);
				$editorHasUnsavedChanges = false;

				const monaco = await import('monaco-editor');
				const model = monacoEditor.getModel();
				if (model) {
					monaco.editor.setModelLanguage(model, getLanguageFromPath(file.name));
				}
			}
		} catch (error) {
			addLog(`Failed to open file: ${error}`);
		}
	}
	
	async function saveCurrentFile() {
		if (!$currentOpenFile || !monacoEditor) return;
		const content = monacoEditor.getValue();
		await writeFile($currentOpenFile, content, $workspacePath);
		$editorHasUnsavedChanges = false;
		addLog(`File saved: ${$currentOpenFile}`);
		await refreshFileTree();
	}
	
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
			await writeFile(itemPath, '', $workspacePath);
		} else if (isCreatingFolder) {
			await writeFile(`${itemPath}/.gitkeep`, '', $workspacePath);
		}
		isCreatingFile = false;
		isCreatingFolder = false;
		newItemName = '';
		await refreshFileTree();
	}
	
	async function deleteFile(file: any) {
		if (!confirm(`Delete "${file.name}"?`)) return;
		await deleteFileAPI(file.path, $workspacePath);
		await refreshFileTree();
		if ($currentOpenFile === file.path) $currentOpenFile = null;
		contextMenuFile = null;
	}
	
	async function startRename(file: any) {
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

		if (renamingFile.type === 'file') {
			const content = await readFile(oldPath, $workspacePath);
			await writeFile(newPath, content, $workspacePath);
			await deleteFileAPI(oldPath, $workspacePath);
		}
		await refreshFileTree();
		renamingFile = null;
	}
	
	function showContextMenu(event: MouseEvent, file: any) {
		event.preventDefault();
		contextMenuFile = file;
		contextMenuPos = { x: event.clientX, y: event.clientY };
	}
	
	function closeContextMenu() {
		contextMenuFile = null;
	}
	
	// Conversation management
	async function loadConversations(autoSelect: boolean = false) {
		try {
			console.log('Loading conversations...');
			const convs = await loadConversationsAPI();
			console.log('Got conversations:', convs.length);
			$conversations = convs;
			if (autoSelect && convs.length > 0 && !$currentConversationId) {
				await loadConversationById(convs[0].id);
			}
		} catch (error) {
			console.error('Error loading conversations:', error);
			addLog(`Failed to load conversations: ${error}`);
		}
	}
	
	async function createNewConversation() {
		const title = `Chat ${new Date().toLocaleString()}`;
		const conv = await createConversation(title, $workspacePath, $selectedModel);
		$currentConversationId = conv.id;
		$messages = [{ role: 'system', content: 'Prometheus AI Agent initialized. How can I assist you today?', timestamp: new Date() }];
		await loadConversations();
	}
	
	async function loadConversationById(convId: string) {
		const msgs = await loadConversation(convId);
		$currentConversationId = convId;
		$messages = msgs.length > 0 ? msgs : [{ role: 'system', content: 'Prometheus AI Agent initialized. How can I assist you today?', timestamp: new Date() }];
	}
	
	async function deleteConversationById(convId: string) {
		if (!confirm('Delete this conversation?')) return;
		await deleteConversationAPI(convId);
		if ($currentConversationId === convId) {
			$currentConversationId = null;
			$messages = [{ role: 'system', content: 'Prometheus AI Agent initialized. How can I assist you today?', timestamp: new Date() }];
		}
		await loadConversations();
	}
	
	// Search files
	async function searchFiles() {
		if (!fileSearchQuery.trim()) return;
		isSearchingFiles = true;
		fileSearchResults = [];
		fileSearchResults = await searchFilesAPI(fileSearchQuery, searchInContent, $workspacePath);
		isSearchingFiles = false;
	}
	
	async function openFileFromPath(path: string) {
		const fileItem = findFileInTree($files, path);
		if (fileItem) {
			await openFileInEditor(fileItem);
		} else {
			const pathParts = path.split('/');
			const fileName = pathParts[pathParts.length - 1];
			await openFileInEditor({ name: fileName, path, type: 'file', level: pathParts.length - 1 });
		}
	}
	
	// Git operations
	async function loadGitStatus() {
		try {
			const status = await getGitStatus($workspacePath);
			$gitStatus = status;
			$isGitRepo = !status.error;
		} catch {
			$isGitRepo = false;
		}
	}
	
	async function initGitRepo() {
		await initGitRepoAPI($workspacePath);
		await loadGitStatus();
	}
	
	async function stageFiles(files: string[]) {
		await stageFilesAPI($workspacePath, files);
		await loadGitStatus();
		selectedFiles.clear();
	}
	
	async function unstageFiles(files: string[]) {
		await unstageFilesAPI($workspacePath, files);
		await loadGitStatus();
		selectedFiles.clear();
	}
	
	async function createCommit() {
		if (!commitMessage.trim()) return;
		await createCommitAPI($workspacePath, commitMessage);
		commitMessage = '';
		await loadGitStatus();
		await loadGitBranches();
		await loadGitLog();
	}
	
	async function loadGitBranches() {
		$gitBranches = await getBranches($workspacePath);
	}
	
	async function loadGitLog() {
		$gitCommits = await getCommitLog($workspacePath, 20);
	}
	
	async function pushToRemote() {
		try {
			await pushToRemoteAPI($workspacePath);
			await loadGitStatus();
		} catch (error: any) {
			alert(`Push failed: ${error.message}`);
		}
	}
	
	async function pullFromRemote() {
		try {
			await pullFromRemoteAPI($workspacePath);
			await loadGitStatus();
			await refreshFileTree();
		} catch (error: any) {
			alert(`Pull failed: ${error.message}`);
		}
	}
	
	async function checkGitHubAuth() {
		const auth = await checkGitHubAuthAPI();
		$githubAuthenticated = auth.authenticated;
		$githubUser = auth.user;
	}
	
	async function saveGitHubToken() {
		if (!githubToken.trim()) return;
		await saveSetting('github_token', githubToken);
		githubToken = '';
		showGitHubAuth = false;
		await checkGitHubAuth();
	}
	
	async function createGitHubRepo() {
		if (!newRepoName.trim()) return;
		const repo = await createGitHubRepoAPI(newRepoName, newRepoDescription, newRepoPrivate);
		await addRemote($workspacePath, 'origin', repo.clone_url);
		newRepoName = '';
		newRepoDescription = '';
		showCreateRepo = false;
		await loadGitStatus();
	}
	
	// Settings
	async function loadSettings() {
		try {
			console.log('Loading settings from API...');
			const settings = await loadSettingsAPI();
			console.log('Got settings:', Object.keys(settings));
			if (settings.apiKey) $customApiKey = settings.apiKey;
			if (settings.customEndpoint) $customEndpoint = settings.customEndpoint;
			if (settings.workspacePath) $workspacePath = settings.workspacePath;
			if (settings.selectedModel) $selectedModel = settings.selectedModel;
			if (settings.autoApproveEdits !== undefined) $autoApproveEdits = settings.autoApproveEdits === 'true';
			if (settings.verboseMode !== undefined) $verboseMode = settings.verboseMode === 'true';
			if (settings.openai_api_key) $apiKeys.openai = settings.openai_api_key;
			if (settings.anthropic_api_key) $apiKeys.anthropic = settings.anthropic_api_key;
			if (settings.deepseek_api_key) $apiKeys.deepseek = settings.deepseek_api_key;
			if (settings.grok_api_key) $apiKeys.grok = settings.grok_api_key;
			if (settings.google_api_key) $apiKeys.google = settings.google_api_key;
			if (settings.litellm_api_key) $apiKeys.litellm = settings.litellm_api_key;
			$settingsLoaded = true;
			console.log('Settings loaded, workspace:', $workspacePath);
		} catch (error) {
			console.error('Error loading settings:', error);
			$settingsLoaded = true; // Still mark as loaded to allow saves
		}
	}
	
	// Rules
	async function loadRules() {
		try {
			$globalRules = await loadGlobalRules();
			$projectRules = await loadProjectRules($workspacePath);
			console.log('Loaded rules - global:', $globalRules.length, 'project:', $projectRules.length);
		} catch (error) {
			console.error('Error loading rules:', error);
		}
	}
	
	// Memories
	async function loadMemories() {
		try {
			$memories = await loadMemoriesAPI($workspacePath);
			console.log('Loaded memories:', $memories.length);
		} catch (error) {
			console.error('Error loading memories:', error);
		}
	}
	
	// MCP Servers
	async function loadMCPServers() {
		try {
			$mcpServers = await loadMCPServersAPI();
			console.log('Loaded MCP servers:', $mcpServers.length);
		} catch (error) {
			console.error('Error loading MCP servers:', error);
		}
	}
	
	async function loadAvailableTools() {
		try {
			$availableTools = await loadAvailableToolsAPI();
			console.log('Loaded tools:', $availableTools.length);
		} catch (error) {
			console.error('Error loading tools:', error);
		}
	}
	
	// Chat (simplified - full implementation kept for now)
	async function sendMessage() {
		console.log('sendMessage called, chatInput:', $chatInput, 'workspacePath:', $workspacePath);
		
		if (!$chatInput.trim()) {
			console.log('No chat input provided');
			addLog('Please type a message first');
			return;
		}
		if (!$workspacePath) {
			addLog('Error: Workspace path is required');
			return;
		}
		
		const userMessage = $chatInput;
		$messages = [...$messages, { role: 'user', content: userMessage, timestamp: new Date() }];
		$chatInput = '';
		$isLoading = true;
		
		if (!$currentConversationId) {
			await createNewConversation();
		}
		
		if ($currentConversationId) {
			saveMessageToConversation($currentConversationId, 'user', userMessage);
		}
		
		$abortController = new AbortController();
		
		try {
			const response = await streamChat({
				model: $selectedModel,
				messages: $messages.map(m => ({ role: m.role, content: m.content, timestamp: m.timestamp })),
				workspace_path: $workspacePath,
				api_base: $customEndpoint || undefined
			}, $abortController.signal);
			
			const reader = response.body?.getReader();
			if (!reader) return;
			
			const decoder = new TextDecoder();
			let currentResponse = '';
			$messages = [...$messages, { role: 'assistant', content: '', timestamp: new Date() }];
			
			while (true) {
				const { done, value } = await reader.read();
				if (done) break;
				
				const chunk = decoder.decode(value);
				const lines = chunk.split('\n');
				
				for (const line of lines) {
					if (line.startsWith('data: ') && line !== 'data: [DONE]') {
						try {
							const data = JSON.parse(line.slice(6));
							
							// Handle our custom token format
							if (data.token) {
								currentResponse += data.token;
								$messages[$messages.length - 1].content = currentResponse;
								$messages = [...$messages];
							}
							
							// Handle tool execution notifications
							if (data.tool_execution) {
								const te = data.tool_execution;
								$toolExecutions = [...$toolExecutions, {
									type: te.tool || 'unknown',
									path: te.path || te.file,
									command: te.command,
									stdout: te.stdout,
									stderr: te.stderr,
									status: te.success ? 'success' : 'error',
									timestamp: new Date(),
									return_code: te.return_code,
									hint: te.hint
								}];
								console.log('Tool executed:', te.tool, te.success ? '✓' : '✗');

								// Trigger code animation for file writes
								if (te.tool === 'filesystem_write' && te.success && te.content && te.path) {
									console.log('Starting code animation for:', te.path);
									startCodeAnimation(te.path, te.content);
								}
							}
							
							// Handle permission requests
							if (data.permission_request) {
								console.log('Permission required:', data.permission_request);
								// TODO: Show permission dialog
							}
							
							// Handle errors
							if (data.error) {
								console.error('Stream error:', data.error);
								addLog(`Error: ${data.error}`);
							}
							
							// Handle OpenAI format (fallback)
							if (data.choices?.[0]?.delta?.content) {
								currentResponse += data.choices[0].delta.content;
								$messages[$messages.length - 1].content = currentResponse;
								$messages = [...$messages];
							}
						} catch (e) {
							// Ignore parse errors for incomplete chunks
						}
					}
				}
			}
			
			if ($currentConversationId) {
				saveMessageToConversation($currentConversationId, 'assistant', currentResponse);
			}
		} catch (error: any) {
			if (error.name !== 'AbortError') {
				addLog(`Error: ${error.message}`);
			}
		} finally {
			$isLoading = false;
			$isConnected = false;
		}
	}
	
	function handleDeploy() {
		console.log('Deploy button clicked!');
		sendMessage();
	}
	
	function stopGeneration() {
		$abortController?.abort();
		$isLoading = false;
		$isConnected = false;
	}

	// Format message content with markdown-style code blocks
	function formatMessageContent(content: string): string {
		if (!content) return '';

		// Step 1: Extract code blocks to preserve them
		const codeBlocks: Array<{ lang: string; code: string }> = [];
		let processedContent = content.replace(/```(\w+)?\n([\s\S]+?)```/g, (match, lang, code) => {
			const index = codeBlocks.length;
			codeBlocks.push({ lang: lang || 'text', code: code.trim() });
			return `__CODE_BLOCK_${index}__`;
		});

		// Step 2: Escape HTML to prevent XSS
		processedContent = processedContent
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;');

		// Step 3: Convert **bold** to <strong>
		processedContent = processedContent.replace(/\*\*(.+?)\*\*/g, '<strong class="text-amber-400">$1</strong>');

		// Step 4: Convert `inline code` to <code> (but not code block markers)
		processedContent = processedContent.replace(/`([^`]+)`/g, '<code class="bg-slate-900 px-1 py-0.5 rounded text-amber-300 font-mono text-xs">$1</code>');

		// Step 5: Convert newlines to <br>
		processedContent = processedContent.replace(/\n/g, '<br>');

		// Step 6: Restore code blocks with proper formatting
		processedContent = processedContent.replace(/__CODE_BLOCK_(\d+)__/g, (match, index) => {
			const block = codeBlocks[parseInt(index)];
			if (!block) return match;

			return `<div class="code-block my-3 rounded-lg overflow-hidden border border-slate-700">
				<div class="bg-slate-900/80 px-3 py-1.5 border-b border-slate-700 flex items-center justify-between">
					<span class="text-xs text-slate-400 font-mono">${block.lang}</span>
				</div>
				<pre class="bg-slate-950 p-4 overflow-x-auto"><code class="language-${block.lang} text-xs">${block.code}</code></pre>
			</div>`;
		});

		return processedContent;
	}
	
	// Initialize
	onMount(async () => {
		console.log('onMount started');
		
		// Load data first (don't wait for Monaco)
		try {
			console.log('Loading settings...');
			await loadSettings();
			console.log('Loading file tree...');
			await refreshFileTree();
			console.log('Loading conversations...');
			await loadConversations(true);
			console.log('Loading rules...');
			await loadRules();
			console.log('Loading memories...');
			await loadMemories();
			// Git operations may fail - don't let them break the app
			try {
				console.log('Loading git status...');
				await loadGitStatus();
			} catch (gitError) {
				console.warn('Git status check failed (non-critical):', gitError);
			}
			console.log('Loading MCP servers...');
			await loadMCPServers();
			console.log('Loading available tools...');
			await loadAvailableTools();
			console.log('All core data loaded!');
			
			// GitHub auth is optional and may fail with CORS - don't let it break the app
			try {
				console.log('Checking GitHub auth...');
				await checkGitHubAuth();
				console.log('GitHub auth checked');
			} catch (githubError) {
				console.warn('GitHub auth check failed (non-critical):', githubError);
			}
			
			console.log('All data loaded!');
		} catch (error) {
			console.error('Error loading data:', error);
		}
		
		// Monaco Editor is now initialized lazily when opening a file
		// This is because the editor element is inside a conditional block
		// that only renders when activeView === 'forge'
		console.log('Monaco Editor will initialize when opening a file');
	});
</script>

<!-- Main Container -->
<div class="flex h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 text-slate-100 font-sans overflow-hidden">
	
	<!-- Activity Bar (extracted component) -->
	<ActivityBar />
	
	<!-- VS Code Style Side Panel (File Explorer/Search/Git/History) -->
	{#if $showExplorer}
	<aside class="w-72 bg-slate-900/80 border-r border-slate-800/50 flex flex-col overflow-hidden">
		<div class="h-9 flex items-center justify-between px-4 bg-slate-900/50 border-b border-slate-800/50">
			<span class="text-xs font-semibold text-slate-400 uppercase tracking-wider">
				{$activeExplorerTab === 'files' ? 'Explorer' : $activeExplorerTab === 'search' ? 'Search' : $activeExplorerTab === 'history' ? 'Chat History' : 'Source Control'}
			</span>
			<button on:click={() => $showExplorer = false} class="p-1 hover:bg-slate-700/50 rounded">
				<X class="w-4 h-4 text-slate-500" />
			</button>
		</div>
		
		{#if $activeExplorerTab === 'files'}
			<!-- File Explorer -->
			<div class="flex-1 flex flex-col overflow-hidden">
				<div class="px-2 py-2 flex items-center justify-between border-b border-slate-800/30">
					<div class="flex items-center gap-2 flex-1 min-w-0">
						<ChevronDown class="w-4 h-4 text-slate-500 flex-shrink-0" />
						<span class="text-xs font-semibold text-slate-300 truncate">{$workspacePath.split('/').pop() || 'WORKSPACE'}</span>
					</div>
					<div class="flex items-center gap-1">
						<button on:click={() => createNewFile('')} class="p-1 hover:bg-slate-700/50 rounded" title="New File">
							<FilePlus class="w-4 h-4 text-slate-400" />
						</button>
						<button on:click={() => createNewFolder('')} class="p-1 hover:bg-slate-700/50 rounded" title="New Folder">
							<FolderPlus class="w-4 h-4 text-slate-400" />
						</button>
						<button on:click={refreshFileTree} class="p-1 hover:bg-slate-700/50 rounded" title="Refresh">
							<RefreshCw class="w-4 h-4 text-slate-400 {$isLoadingFiles ? 'animate-spin' : ''}" />
						</button>
					</div>
				</div>
				
				<div class="flex-1 overflow-y-auto py-1" on:click={closeContextMenu}>
					{#if $isLoadingFiles}
						<div class="flex items-center justify-center py-8">
							<Loader2 class="w-5 h-5 text-slate-500 animate-spin" />
						</div>
					{:else if $files.length === 0}
						<div class="px-4 py-8 text-center">
							<div class="text-slate-500 text-xs mb-2">No files in workspace</div>
							<button on:click={() => createNewFile('')} class="text-xs text-amber-500 hover:text-amber-400">
								Create a file to get started
							</button>
						</div>
					{:else}
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
						
						{#each flattenTree($files) as file}
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
									class:bg-slate-700={$currentOpenFile === file.path}
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
			
		{:else if $activeExplorerTab === 'search'}
			<!-- Search Panel -->
			<div class="flex-1 flex flex-col overflow-hidden">
				<div class="p-3 border-b border-slate-800/30">
					<div class="flex gap-2 mb-2">
						<input 
							type="text" 
							bind:value={fileSearchQuery}
							on:keydown={(e) => e.key === 'Enter' && searchFiles()}
							placeholder="Search files..."
							class="flex-1 bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 outline-none focus:border-amber-500"
						/>
						<button 
							on:click={searchFiles}
							disabled={!fileSearchQuery.trim() || isSearchingFiles}
							class="px-3 py-2 bg-amber-500 hover:bg-amber-600 disabled:bg-slate-700 disabled:cursor-not-allowed text-white text-xs font-bold rounded transition-all flex items-center justify-center"
						>
							{#if isSearchingFiles}
								<Loader2 class="w-4 h-4 animate-spin" />
							{:else}
								<Search class="w-4 h-4" />
							{/if}
						</button>
					</div>
					<label class="flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
						<input type="checkbox" bind:checked={searchInContent} class="accent-amber-500" />
						<span>Search in file contents</span>
					</label>
				</div>
				<div class="flex-1 overflow-y-auto p-3">
					{#if isSearchingFiles}
						<div class="flex items-center justify-center py-8">
							<Loader2 class="w-5 h-5 text-slate-500 animate-spin" />
						</div>
					{:else if fileSearchQuery && fileSearchResults.length === 0}
						<div class="text-xs text-slate-500 text-center py-8">
							No results found for "{fileSearchQuery}"
						</div>
					{:else if fileSearchResults.length > 0}
						<div class="text-xs text-slate-400 mb-2">
							Found {fileSearchResults.length} result{fileSearchResults.length !== 1 ? 's' : ''}
						</div>
						<div class="space-y-1">
							{#each fileSearchResults as result}
								<button 
									on:click={() => openFileFromPath(result.path)}
									class="w-full text-left bg-slate-800/50 hover:bg-slate-800 rounded p-2 border border-slate-700/50 group"
								>
									<div class="flex items-center gap-2 mb-1">
										<File class="w-3 h-3 text-slate-400 flex-shrink-0" />
										<span class="text-xs text-slate-300 font-mono truncate flex-1">{result.path}</span>
										<span class="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400">
											{result.match_type}
										</span>
									</div>
								</button>
							{/each}
						</div>
					{:else}
						<div class="text-xs text-slate-500 text-center py-8">
							Enter a search query to find files
						</div>
					{/if}
				</div>
			</div>
			
		{:else if $activeExplorerTab === 'history'}
			<!-- Chat History Panel -->
			<div class="flex-1 flex flex-col overflow-hidden">
				<div class="px-2 py-2 flex items-center justify-between border-b border-slate-800/30">
					<span class="text-xs font-semibold text-slate-300">Chat History</span>
					<button on:click={createNewConversation} class="p-1 hover:bg-slate-700/50 rounded" title="New Chat">
						<Plus class="w-4 h-4 text-slate-400" />
					</button>
				</div>
				<div class="flex-1 overflow-y-auto py-1">
					{#if $conversations.length === 0}
						<div class="px-4 py-8 text-center text-xs text-slate-500">
							No saved chats yet
						</div>
					{:else}
						{#each $conversations as conv}
							<div 
								class="px-3 py-2 flex items-center gap-2 hover:bg-slate-800/50 cursor-pointer group"
								class:bg-slate-700={$currentConversationId === conv.id}
								on:click={() => loadConversationById(conv.id)}
							>
								<MessageSquare class="w-3 h-3 text-slate-500 flex-shrink-0" />
								<span class="text-xs text-slate-300 truncate flex-1">{conv.title}</span>
								<button 
									on:click|stopPropagation={() => deleteConversationById(conv.id)}
									class="p-1 opacity-0 group-hover:opacity-100 hover:bg-red-500/20 rounded"
								>
									<Trash2 class="w-3 h-3 text-red-400" />
								</button>
							</div>
						{/each}
					{/if}
				</div>
			</div>
			
		{:else if $activeExplorerTab === 'git'}
			<!-- Git Panel - Placeholder (extract later) -->
			<div class="flex-1 p-4">
				<div class="text-xs text-slate-400">Git integration panel</div>
				<div class="text-xs text-slate-500 mt-2">Full git panel to be extracted as component</div>
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
	
	<!-- Main Content Area -->
	<main class="flex-1 flex flex-col overflow-hidden">
		<!-- Top Bar -->
		<header class="h-16 border-b border-slate-800/50 bg-slate-900/30 backdrop-blur-xl flex items-center justify-between px-6">
			<div class="flex items-center gap-4">
				<h1 class="text-lg font-black tracking-tight bg-gradient-to-r from-amber-400 to-orange-500 bg-clip-text text-transparent">
					PROMETHEUS
				</h1>
				<div class="h-4 w-px bg-slate-700"></div>
				<div class="flex items-center gap-2 text-xs text-slate-400">
					{#if $isConnected}
						<div class="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
						<span>Connected</span>
					{:else if $isLoading}
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
					<select bind:value={$selectedModel} class="bg-slate-800 border-none text-xs text-slate-100 cursor-pointer outline-none font-medium min-w-[140px]">
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
					</select>
				</div>
				
				<!-- Deploy Button -->
				<button 
					on:click={handleDeploy}
					disabled={$isLoading}
					class="px-4 py-2 rounded-lg font-bold text-sm bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-600 hover:to-orange-700 active:scale-95 transition-all shadow-lg shadow-amber-500/30 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
				>
					{#if $isLoading}
						<Loader2 class="w-4 h-4 animate-spin" />
					{:else}
						<Play class="w-4 h-4 fill-current" />
					{/if}
					<span>Deploy</span>
				</button>
			</div>
		</header>
		
		<!-- Chat/Editor Content -->
		<div class="flex-1 flex overflow-hidden">
			{#if $activeView === 'chat'}
				<!-- Chat View -->
				<div class="flex-1 flex flex-col">
					<div class="flex-1 overflow-y-auto p-6 space-y-4">
						{#each $messages as msg}
							<div class="flex gap-3 {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
								{#if msg.role !== 'user'}
									<div class="w-8 h-8 rounded-lg bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center flex-shrink-0">
										<Sparkles class="w-4 h-4 text-white" />
									</div>
								{/if}
								<div class="max-w-2xl {msg.role === 'user' ? 'bg-amber-500/10 border-amber-500/30' : 'bg-slate-800/50 border-slate-700/50'} border rounded-xl p-4">
									{#if msg.content}
										<div class="text-sm text-slate-200 leading-relaxed markdown-content">
											{@html formatMessageContent(msg.content)}
										</div>
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
						
						{#if $isLoading}
							<div class="flex gap-3">
								<div class="w-8 h-8 rounded-lg bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center">
									<Loader2 class="w-4 h-4 text-white animate-spin" />
								</div>
								<div class="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4">
									<div class="text-sm text-slate-400">Thinking...</div>
								</div>
							</div>
						{/if}

						<!-- Code Animations -->
						{#each Array.from(activeCodeAnimations.values()) as animation}
							<div class="flex gap-3">
								<div class="w-8 h-8 rounded-lg bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center flex-shrink-0">
									{#if animation.completed}
										<Check class="w-4 h-4 text-white" />
									{:else}
										<FileCode class="w-4 h-4 text-white animate-pulse" />
									{/if}
								</div>
								<div class="max-w-4xl flex-1 bg-slate-800/50 border border-amber-500/30 rounded-xl overflow-hidden">
									<div class="bg-slate-900/80 px-4 py-2 border-b border-slate-700/50 flex items-center justify-between">
										<div class="flex items-center gap-2">
											<File class="w-3 h-3 text-amber-500" />
											<span class="text-xs font-mono text-slate-300">{animation.path}</span>
										</div>
										<span class="text-[10px] px-2 py-0.5 rounded bg-amber-500/20 text-amber-400">
											{animation.completed ? 'Complete' : 'Writing...'}
										</span>
									</div>
									<div class="p-4 bg-slate-950 font-mono text-xs overflow-auto max-h-96">
										<pre class="text-slate-300 leading-relaxed">{animation.displayedContent}<span class="animate-pulse">|</span></pre>
									</div>
								</div>
							</div>
						{/each}
					</div>
					
					<!-- Chat Input -->
					<div class="border-t border-slate-800/50 bg-slate-900/50 p-4">
						<div class="flex gap-3">
							<textarea 
								bind:value={$chatInput}
								on:keydown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
								placeholder="Ask Prometheus anything... (Shift+Enter for new line)"
								rows="3"
								class="flex-1 bg-slate-800 border border-slate-700 rounded-lg px-4 py-3 text-sm text-slate-200 outline-none focus:border-amber-500 resize-none"
								disabled={$isLoading}
							></textarea>
							{#if $isLoading}
								<button 
									on:click={stopGeneration}
									class="px-4 bg-red-500 hover:bg-red-600 text-white font-bold rounded-lg transition-all"
								>
									Stop
								</button>
							{:else}
								<button 
									on:click={sendMessage}
									disabled={!$chatInput.trim()}
									class="px-6 bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-600 hover:to-orange-700 disabled:from-slate-700 disabled:to-slate-700 disabled:cursor-not-allowed text-white font-bold rounded-lg transition-all shadow-lg shadow-amber-500/20"
								>
									Send
								</button>
							{/if}
						</div>
					</div>
				</div>
			{:else}
				<!-- Code Editor View -->
				<div class="flex-1 flex flex-col bg-slate-950">
					{#if $currentOpenFile}
						<div class="h-10 flex items-center justify-between px-4 bg-slate-900/80 border-b border-slate-800/50">
							<div class="flex items-center gap-2">
								<File class="w-4 h-4 text-amber-500" />
								<span class="text-xs font-mono text-slate-300">{$currentOpenFile}</span>
								{#if $editorHasUnsavedChanges}
									<span class="text-xs text-amber-500">● unsaved</span>
								{/if}
							</div>
							<div class="flex items-center gap-2">
								<button 
									on:click={saveCurrentFile}
									disabled={!$editorHasUnsavedChanges}
									class="px-3 py-1 text-xs font-bold rounded bg-amber-500 hover:bg-amber-600 disabled:bg-slate-700 disabled:cursor-not-allowed text-white transition-all"
								>
									Save
								</button>
								<button 
									on:click={() => $currentOpenFile = null}
									class="p-1 hover:bg-slate-700 rounded"
								>
									<X class="w-4 h-4 text-slate-400" />
								</button>
							</div>
						</div>
					{/if}
					<div bind:this={editorElement} class="flex-1"></div>
				</div>
			{/if}
		</div>
	</main>
	
	<!-- Extracted Panel Components -->
	<SettingsPanel />
	<RulesPanel />
	<MemoriesPanel />
	<MCPServersPanel />
	<TerminalPanel />
</div>

<style>
	:global(body) {
		margin: 0;
		padding: 0;
		overflow: hidden;
	}

	:global(.activity-btn) {
		@apply w-12 h-10 flex items-center justify-center rounded-lg transition-all text-slate-400 hover:text-white hover:bg-slate-800/50 mb-1;
	}

	:global(.activity-btn.active) {
		@apply text-white bg-slate-800/80 border-l-2 border-amber-500;
	}

	/* Markdown content styling */
	:global(.markdown-content) {
		word-wrap: break-word;
	}

	:global(.markdown-content .code-block) {
		margin-top: 1rem;
		margin-bottom: 1rem;
	}

	:global(.markdown-content pre) {
		font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
		line-height: 1.6;
		tab-size: 2;
	}

	:global(.markdown-content code) {
		font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
	}

	/* Basic syntax highlighting for common languages */
	:global(.markdown-content .language-python .keyword),
	:global(.markdown-content .language-javascript .keyword),
	:global(.markdown-content .language-typescript .keyword) {
		color: #c586c0;
	}

	:global(.markdown-content .language-python .string),
	:global(.markdown-content .language-javascript .string),
	:global(.markdown-content .language-typescript .string) {
		color: #ce9178;
	}

	:global(.markdown-content .language-python .comment),
	:global(.markdown-content .language-javascript .comment),
	:global(.markdown-content .language-typescript .comment) {
		color: #6a9955;
		font-style: italic;
	}

	:global(.markdown-content .language-python .function),
	:global(.markdown-content .language-javascript .function),
	:global(.markdown-content .language-typescript .function) {
		color: #dcdcaa;
	}

	/* Default code color */
	:global(.markdown-content pre code) {
		color: #d4d4d4;
	}
</style>
