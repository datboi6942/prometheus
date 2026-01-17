<script lang="ts">
	import { onMount } from 'svelte';
	import { 
		Cpu, Terminal as TerminalIcon, Code2, Zap, Settings as SettingsIcon, 
		Globe, Shield, MessageSquare, FileCode, History, Play, Sparkles,
		FolderOpen, Plus, ChevronRight, X, Check, AlertCircle, Loader2
	} from 'lucide-svelte';

	let selectedModel = 'ollama/llama3.2';
	let customEndpoint = '';
	let customApiKey = '';
	let workspacePath = '/home/john/prometheus_workspace';
	let verboseMode = false;
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
	
	// Tool executions log
	let toolExecutions: Array<{
		type: string, 
		path?: string, 
		command?: string, 
		stdout?: string,
		stderr?: string,
		status: string, 
		timestamp: Date
	}> = [];
	
	// Chat messages
	let messages = [
		{ role: 'system', content: 'Prometheus AI Agent initialized. How can I assist you today?', timestamp: new Date() }
	];
	
	// File browser
	let files = [
		{ name: 'src', type: 'folder', expanded: true, children: [
			{ name: 'main.py', type: 'file' },
			{ name: 'utils.py', type: 'file' }
		]},
		{ name: 'README.md', type: 'file' }
	];
	
	function addLog(text: string, type = 'info') {
		messages = [...messages, { role: 'assistant', content: text, timestamp: new Date() }];
	}

					async function sendMessage() {
		if (!chatInput.trim() || !workspacePath) return;
		
		const userMessage = chatInput;
		messages = [...messages, { role: 'user', content: userMessage, timestamp: new Date() }];
		chatInput = '';
		isLoading = true;
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
							break;
						}

						try {
							const data = JSON.parse(dataStr);
							if (data.token) {
								currentResponse += data.token;
								messages[messages.length - 1].content = currentResponse;
								messages = [...messages];
							}
							if (data.tool_execution) {
								// Log tool execution with output
								const exec = {
									type: data.tool_execution.tool || data.tool_execution.action || 'execute',
									path: data.tool_execution.path,
									command: data.tool_execution.command,
									stdout: data.tool_execution.stdout,
									stderr: data.tool_execution.stderr,
									status: data.tool_execution.success ? 'success' : 'error',
									timestamp: new Date()
								};
								toolExecutions = [...toolExecutions, exec];
								
								// Auto-show terminal panel for shell commands
								if (exec.type === 'shell_execute' && exec.command) {
									showTerminalPanel = true;
								}
								
								// Write to terminal if available
								if (terminalInstance && exec.command) {
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
		monaco.editor.create(editorElement, {
			value: `# Prometheus AI Agent Workspace
# This is your code forge - edit and create files here

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
	});
</script>

<!-- Main Container -->
<div class="flex h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 text-slate-100 font-sans overflow-hidden">
	
	<!-- Sidebar -->
	<aside class="w-16 bg-slate-950/50 backdrop-blur-xl border-r border-slate-800/50 flex flex-col items-center py-4 gap-2">
		<!-- Logo -->
		<div class="w-12 h-12 rounded-xl bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center mb-4 shadow-lg shadow-amber-500/20">
			<Zap class="w-6 h-6 text-white fill-white" />
		</div>

		<!-- Nav Icons -->
		<button 
			on:click={() => activeView = 'chat'}
			class="nav-btn {activeView === 'chat' ? 'active' : ''}"
			title="Chat">
			<MessageSquare class="w-5 h-5" />
		</button>
		
		<button 
			on:click={() => activeView = 'forge'}
			class="nav-btn {activeView === 'forge' ? 'active' : ''}"
			title="Code Forge">
			<FileCode class="w-5 h-5" />
		</button>
		
		<button 
			on:click={() => showTerminalPanel = !showTerminalPanel}
			class="nav-btn {showTerminalPanel ? 'active' : ''}"
			title="Toggle Terminal">
			<TerminalIcon class="w-5 h-5" />
		</button>

		<div class="flex-1"></div>

		<button 
			on:click={() => showSettings = !showSettings}
			class="nav-btn {showSettings ? 'active' : ''}"
			title="Settings">
			<SettingsIcon class="w-5 h-5" />
		</button>
	</aside>

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
				<div class="flex items-center gap-2 bg-slate-800/50 px-3 py-2 rounded-lg border border-slate-700/50 hover:border-amber-500/50 transition-all">
					<Cpu class="w-4 h-4 text-slate-400" />
					<select
						bind:value={selectedModel}
						class="bg-transparent border-none text-xs text-slate-200 cursor-pointer outline-none font-medium"
					>
						<optgroup label="Local Models">
							<option value="ollama/llama3.2">Llama 3.2</option>
							<option value="ollama/codellama">CodeLlama</option>
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
									<div class="text-sm text-slate-200 leading-relaxed">{msg.content}</div>
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

				<!-- Side Panel: Tool Executions & Files -->
				<aside class="w-80 border-l border-slate-800/50 bg-slate-900/20 backdrop-blur-xl flex flex-col">
					<div class="p-4 border-b border-slate-800/50">
						<div class="flex items-center gap-2 mb-3">
							<Zap class="w-4 h-4 text-amber-500" />
							<span class="text-sm font-bold text-slate-300">Tool Activity</span>
						</div>
						{#if toolExecutions.length > 0}
							<div class="space-y-2 max-h-64 overflow-y-auto">
								{#each toolExecutions.slice(-10) as exec}
									<div class="bg-slate-800/30 rounded-lg px-3 py-2 border border-slate-700/50">
										<div class="flex items-center gap-2 mb-1">
											{#if exec.status === 'success'}
												<Check class="w-3 h-3 text-green-500 flex-shrink-0" />
											{:else}
												<AlertCircle class="w-3 h-3 text-red-500 flex-shrink-0" />
											{/if}
											<div class="text-[10px] font-bold text-slate-400 uppercase">{exec.type}</div>
											<div class="text-[9px] text-slate-600 ml-auto">{exec.timestamp.toLocaleTimeString()}</div>
										</div>
										<div class="text-xs text-slate-300 font-mono truncate mb-1">{exec.path || exec.command}</div>
										{#if exec.stdout && verboseMode}
											<div class="mt-2 p-2 bg-slate-900/50 rounded text-[10px] text-green-400 font-mono max-h-20 overflow-y-auto">
												{exec.stdout}
											</div>
										{/if}
										{#if exec.stderr && verboseMode}
											<div class="mt-2 p-2 bg-slate-900/50 rounded text-[10px] text-red-400 font-mono max-h-20 overflow-y-auto">
												{exec.stderr}
											</div>
										{/if}
									</div>
								{/each}
							</div>
						{:else}
							<div class="text-xs text-slate-500 italic">No tool executions yet</div>
						{/if}
					</div>
					
					<div class="p-4 border-b border-slate-800/50 flex items-center justify-between">
						<div class="flex items-center gap-2">
							<FolderOpen class="w-4 h-4 text-slate-400" />
							<span class="text-sm font-bold text-slate-300">Project Files</span>
						</div>
						<button class="p-1 hover:bg-slate-700/50 rounded">
							<Plus class="w-4 h-4 text-slate-400" />
						</button>
					</div>
					<div class="flex-1 overflow-y-auto p-2 space-y-1">
						{#each files as file}
							<button class="w-full px-3 py-2 rounded-lg hover:bg-slate-800/50 text-left flex items-center gap-2 group">
								{#if file.type === 'folder'}
									<ChevronRight class="w-3 h-3 text-slate-500" />
									<FolderOpen class="w-4 h-4 text-amber-500" />
								{:else}
									<FileCode class="w-4 h-4 text-slate-400 ml-5" />
								{/if}
								<span class="text-xs text-slate-300 group-hover:text-white">{file.name}</span>
							</button>
						{/each}
					</div>
				</aside>
			</div>

			<!-- Forge View (always in DOM, hidden when not active) -->
			<div class="flex-1 flex flex-col" class:hidden={activeView !== 'forge'}>
				<div class="h-10 border-b border-slate-800/50 bg-slate-900/20 flex items-center px-4 gap-2">
					<FileCode class="w-4 h-4 text-amber-500" />
					<span class="text-xs font-medium text-slate-400">The Forge - Code Editor</span>
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

	/* Navigation Buttons */
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
</style>
