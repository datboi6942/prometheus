/**
 * Shared stores for application state management
 * Writable stores allow components to share and react to state changes
 */
import { writable, type Writable } from 'svelte/store';

// Settings
export const selectedModel = writable('ollama/llama3.2');
export const customEndpoint = writable('');
export const customApiKey = writable('');
export const apiKeys = writable({
	openai: '',
	anthropic: '',
	deepseek: '',
	grok: '',
	google: '',
	litellm: ''
});
export const workspacePath = writable('');
export const verboseMode = writable(false);
export const autoApproveEdits = writable(true);
export const settingsLoaded = writable(false);

// UI State
export const showSettings = writable(false);
export const showRulesPanel = writable(false);
export const showMemoriesPanel = writable(false);
export const showMCPServersPanel = writable(false);
export const showTodoPanel = writable(false);
export const showCheckpointsPanel = writable(false);
export const showExplorer = writable(true);
export const showTerminalPanel = writable(false);
export const showAgentPanel = writable(true);  // Agent activity panel - visible by default
export const activeView = writable<'chat' | 'forge'>('chat');
export const activeExplorerTab = writable<'files' | 'search' | 'history' | 'git'>('files');

// Chat State
export const messages = writable<Array<{
	role: string;
	content: string;
	timestamp: Date;
	thinking?: {
		summary: string;
		fullContent: string;
	};
	codeWrites?: Array<{
		path: string;
		content: string;
		language: string;
		animatedContent: string;
		isComplete: boolean;
	}>;
}>>([
	{ role: 'system', content: 'Prometheus AI Agent initialized. How can I assist you today?', timestamp: new Date() }
]);

export const chatInput = writable('');
export const isLoading = writable(false);
export const currentConversationId = writable<string | null>(null);

// Thinking/Reasoning State (for DeepSeek R1 and similar models)
export const activeThinking = writable<{
	content: string;
	summary: string | null;
	isActive: boolean;
	isComplete: boolean;
} | null>(null);

// Context Window Management
export const contextInfo = writable<{
	current_tokens: number;
	max_tokens: number;
	usage_ratio: number;
	compression_needed: boolean;
	critical: boolean;
	compressed?: boolean;
	tokens_saved?: number;
	compression_ratio?: number;
} | null>(null);

// Conversations
export const conversations = writable<Array<{id: string, title: string, updated_at: string}>>([]);

// Rules
export const globalRules = writable<Array<{id: number, name: string, content: string, enabled: number}>>([]);
export const projectRules = writable<Array<{id: number, name: string, content: string, enabled: number}>>([]);

// Memories
export const memories = writable<Array<{id: number, content: string, source: string, tags: string | null, created_at: string, access_count: number}>>([]);

// MCP Servers
export const mcpServers = writable<Array<{id: number, name: string, config: any, enabled: number}>>([]);
export const availableTools = writable<Array<{name: string, description: string, source: string}>>([]);

// File Explorer
export const files = writable<Array<any>>([]);
export const isLoadingFiles = writable(false);

// Editor
export const currentOpenFile = writable<string | null>(null);
export const editorHasUnsavedChanges = writable(false);

// Tool Executions
export const toolExecutions = writable<Array<{
	type: string;
	path?: string;
	file?: string;
	command?: string;
	stdout?: string;
	stderr?: string;
	status: string;
	timestamp: Date;
	return_code?: number;
	hint?: string;
	args?: Record<string, any>;
	diff?: {
		format: string;
		stats: { lines_added: number; lines_removed: number; lines_changed: number };
		hunks: Array<{ header: string; changes: Array<{ type: string; line: string }> }>;
	};
}>>([]);

// Active Tool Calls (in progress, not yet executed)
export const activeToolCalls = writable<Array<{
	tool: string;
	args: Record<string, any>;
	timestamp: Date;
}>>([]);

// Git State
export const gitStatus = writable<any>(null);
export const gitBranches = writable<Array<{name: string, is_current: boolean, is_remote: boolean}>>([]);
export const gitCommits = writable<Array<{hash: string, message: string, author: string, date: string}>>([]);
export const isGitRepo = writable(false);
export const githubAuthenticated = writable(false);
export const githubToken = writable('');
export const githubUser = writable<any>(null);

// Connection State
export const isConnected = writable(false);
export const abortController = writable<AbortController | null>(null);

// Iteration Progress (for agentic loops)
export const iterationProgress = writable<{
	current: number;
	max: number;
	message_count: number;
	read_ops?: number;
	edit_ops?: number;
	files_read?: string[];
	files_edited?: Record<string, number>;  // path -> edit count
} | null>(null);

// Iteration Warning (when approaching limit)
export const iterationWarning = writable<{
	current: number;
	max: number;
	remaining: number;
	message: string;
} | null>(null);

// Agent Status (for reasoning model activity)
export const agentStatus = writable<{
	status: string;
	model: string;
	is_reasoning_model: boolean;
	message: string;
} | null>(null);

// Agent TODOs
export const agentTodos = writable<Array<{
	id: string;
	content: string;
	status: 'pending' | 'in_progress' | 'completed' | 'cancelled';
}>>([]);

// Indexing Status
export const indexingStatus = writable<{
	status: 'idle' | 'starting' | 'indexing' | 'completed' | 'error';
	total: number;
	current: number;
	percent: number;
	file?: string;
	error?: string;
}>({
	status: 'idle',
	total: 0,
	current: 0,
	percent: 0
});

// Reasoning Warning (when agent is overthinking)
export const reasoningWarning = writable<{
	length: number;
	message: string;
} | null>(null);
