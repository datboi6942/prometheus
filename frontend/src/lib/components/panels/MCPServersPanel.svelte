<script lang="ts">
	import { X, Code2, RefreshCw, Trash2 } from 'lucide-svelte';
	import { showMCPServersPanel, mcpServers, availableTools } from '$lib/stores';
	import { 
		loadMCPServers as loadMCPServersAPI, 
		loadAvailableTools as loadAvailableToolsAPI,
		createMCPServer as createMCPServerAPI,
		deleteMCPServer as deleteMCPServerAPI,
		reloadMCPServer as reloadMCPServerAPI
	} from '$lib/api/mcp';
	import { onMount } from 'svelte';

	let newMCPServerName = '';
	let newMCPServerCommand = '';
	let newMCPServerArgs: string[] = [];
	let newMCPServerArgInput = '';
	let newMCPServerEnvVars: Array<{key: string, value: string}> = [];
	let newMCPServerEnvKey = '';
	let newMCPServerEnvValue = '';
	let newMCPServerCwd = '';
	let newMCPServerTransport = 'stdio';
	let newMCPServerHttpUrl = '';
	let newMCPServerTools: Array<{name: string, description: string, parameters: any}> = [];
	let newMCPServerToolName = '';
	let newMCPServerToolDesc = '';
	let newMCPServerToolParams = '';

	onMount(async () => {
		await loadData();
	});

	async function loadData() {
		try {
			const [servers, tools] = await Promise.all([
				loadMCPServersAPI(),
				loadAvailableToolsAPI()
			]);
			$mcpServers = servers;
			$availableTools = tools;
		} catch (error) {
			console.error('Error loading MCP data:', error);
		}
	}

	function addMCPServerArg() {
		if (newMCPServerArgInput.trim()) {
			newMCPServerArgs = [...newMCPServerArgs, newMCPServerArgInput.trim()];
			newMCPServerArgInput = '';
		}
	}

	function removeMCPServerArg(index: number) {
		newMCPServerArgs = newMCPServerArgs.filter((_, i) => i !== index);
	}

	function addMCPServerEnvVar() {
		if (newMCPServerEnvKey.trim() && newMCPServerEnvValue.trim()) {
			newMCPServerEnvVars = [...newMCPServerEnvVars, { 
				key: newMCPServerEnvKey.trim(), 
				value: newMCPServerEnvValue.trim() 
			}];
			newMCPServerEnvKey = '';
			newMCPServerEnvValue = '';
		}
	}

	function removeMCPServerEnvVar(index: number) {
		newMCPServerEnvVars = newMCPServerEnvVars.filter((_, i) => i !== index);
	}

	function addMCPServerTool() {
		if (newMCPServerToolName.trim()) {
			let params = {};
			if (newMCPServerToolParams.trim()) {
				try {
					params = JSON.parse(newMCPServerToolParams);
				} catch {
					alert('Invalid JSON for tool parameters');
					return;
				}
			}
			newMCPServerTools = [...newMCPServerTools, {
				name: newMCPServerToolName.trim(),
				description: newMCPServerToolDesc.trim(),
				parameters: params
			}];
			newMCPServerToolName = '';
			newMCPServerToolDesc = '';
			newMCPServerToolParams = '';
		}
	}

	function removeMCPServerTool(index: number) {
		newMCPServerTools = newMCPServerTools.filter((_, i) => i !== index);
	}

	function resetMCPServerForm() {
		newMCPServerName = '';
		newMCPServerCommand = '';
		newMCPServerArgs = [];
		newMCPServerArgInput = '';
		newMCPServerEnvVars = [];
		newMCPServerEnvKey = '';
		newMCPServerEnvValue = '';
		newMCPServerCwd = '';
		newMCPServerTransport = 'stdio';
		newMCPServerHttpUrl = '';
		newMCPServerTools = [];
		newMCPServerToolName = '';
		newMCPServerToolDesc = '';
		newMCPServerToolParams = '';
	}

	async function handleCreateMCPServer() {
		if (!newMCPServerName.trim()) {
			alert('Server name is required');
			return;
		}
		
		if (newMCPServerTransport === 'stdio' && !newMCPServerCommand.trim()) {
			alert('Command is required for stdio transport');
			return;
		}
		
		if (newMCPServerTransport === 'http' && !newMCPServerHttpUrl.trim()) {
			alert('HTTP URL is required for HTTP transport');
			return;
		}

		try {
			const config: any = {};
			
			if (newMCPServerTransport === 'stdio') {
				const command = newMCPServerCommand.trim();
				if (newMCPServerArgs.length > 0) {
					config.command = [command, ...newMCPServerArgs];
				} else {
					config.command = command;
				}
			} else if (newMCPServerTransport === 'http') {
				config.url = newMCPServerHttpUrl.trim();
			}
			
			if (newMCPServerEnvVars.length > 0) {
				config.env = {};
				newMCPServerEnvVars.forEach(env => {
					config.env[env.key] = env.value;
				});
			}
			
			if (newMCPServerCwd.trim()) {
				config.cwd = newMCPServerCwd.trim();
			}
			
			config.transport = newMCPServerTransport;
			
			if (newMCPServerTools.length > 0) {
				config.tools = newMCPServerTools;
			}
			
			await createMCPServerAPI(newMCPServerName, config, true);
			resetMCPServerForm();
			await loadData();
		} catch (error: any) {
			alert(`Error: ${error.message || 'Failed to create MCP server'}`);
		}
	}

	async function handleDeleteMCPServer(name: string) {
		if (!confirm(`Delete MCP server "${name}"?`)) return;
		try {
			await deleteMCPServerAPI(name);
			await loadData();
		} catch (error) {
			console.error('Error deleting MCP server:', error);
		}
	}

	async function handleReloadMCPServer(name: string) {
		try {
			await reloadMCPServerAPI(name);
			await loadData();
		} catch (error) {
			console.error('Error reloading MCP server:', error);
		}
	}

	function close() {
		$showMCPServersPanel = false;
	}
</script>

<!-- MCP Servers Panel -->
{#if $showMCPServersPanel}
	<div class="absolute right-6 top-20 w-[500px] bg-slate-900 border border-slate-700/50 rounded-xl shadow-2xl z-50 p-6 animate-in slide-in-from-right backdrop-blur-xl max-h-[80vh] overflow-y-auto">
		<div class="flex items-center justify-between mb-6">
			<div class="flex items-center gap-3">
				<div class="w-10 h-10 rounded-lg bg-gradient-to-br from-green-500 to-emerald-600 flex items-center justify-center">
					<Code2 class="w-5 h-5 text-white" />
				</div>
				<h3 class="text-base font-bold text-white">MCP Servers & Tools</h3>
			</div>
			<button on:click={close} class="text-slate-400 hover:text-white">
				<X class="w-5 h-5" />
			</button>
		</div>
		
		<p class="text-xs text-slate-400 mb-4">
			Manage MCP (Model Context Protocol) servers to add custom tools. Tools are dynamically discovered and registered.
		</p>

		<!-- Available Tools -->
		<div class="mb-6">
			<h4 class="text-xs font-bold text-slate-400 uppercase mb-2">Available Tools ({$availableTools.length})</h4>
			<div class="bg-slate-950 rounded-lg p-3 max-h-40 overflow-y-auto">
				{#if $availableTools.length === 0}
					<div class="text-xs text-slate-500 italic">No tools available</div>
				{:else}
					<div class="space-y-1">
						{#each $availableTools as tool}
							<div class="flex items-center gap-2 text-xs">
								<span class="text-slate-300 font-mono">{tool.name}</span>
								<span class="text-[10px] px-1.5 py-0.5 rounded {tool.source === 'fallback' ? 'bg-amber-500/20 text-amber-400' : tool.source === 'mcp' ? 'bg-green-500/20 text-green-400' : 'bg-blue-500/20 text-blue-400'}">
									{tool.source}
								</span>
								{#if tool.description}
									<span class="text-slate-500 text-[10px]">- {tool.description}</span>
								{/if}
							</div>
						{/each}
					</div>
				{/if}
			</div>
		</div>

		<!-- Add New MCP Server -->
		<div class="bg-slate-950 rounded-lg p-4 border border-slate-700 mb-4 max-h-[70vh] overflow-y-auto">
			<h4 class="text-xs font-bold text-slate-400 uppercase mb-3">Add MCP Server</h4>
			
			<!-- Server Name -->
			<div class="mb-3">
				<label class="block text-xs text-slate-300 mb-1">Server Name *</label>
				<input 
					type="text" 
					bind:value={newMCPServerName}
					placeholder="e.g., github-mcp, filesystem-mcp"
					class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 outline-none focus:border-amber-500"
				/>
			</div>

			<!-- Transport Type -->
			<div class="mb-3">
				<label class="block text-xs text-slate-300 mb-1">Transport Type *</label>
				<select 
					bind:value={newMCPServerTransport}
					class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 outline-none focus:border-amber-500"
				>
					<option value="stdio">stdio (Standard I/O)</option>
					<option value="http">HTTP</option>
					<option value="sse">SSE (Server-Sent Events)</option>
				</select>
			</div>

			<!-- Command (for stdio) -->
			{#if newMCPServerTransport === 'stdio'}
				<div class="mb-3">
					<label class="block text-xs text-slate-300 mb-1">Command *</label>
					<input 
						type="text" 
						bind:value={newMCPServerCommand}
						placeholder="e.g., npx, python, node"
						class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 outline-none focus:border-amber-500"
					/>
				</div>

				<!-- Command Arguments -->
				<div class="mb-3">
					<label class="block text-xs text-slate-300 mb-1">Command Arguments</label>
					<div class="flex gap-2 mb-2">
						<input 
							type="text" 
							bind:value={newMCPServerArgInput}
							on:keydown={(e) => e.key === 'Enter' && addMCPServerArg()}
							placeholder="e.g., -y, @modelcontextprotocol/server-github"
							class="flex-1 bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 outline-none focus:border-amber-500"
						/>
						<button 
							on:click={addMCPServerArg}
							class="px-3 py-2 bg-slate-800 border border-slate-700 rounded text-xs text-slate-300 hover:bg-slate-700"
						>
							Add
						</button>
					</div>
					{#if newMCPServerArgs.length > 0}
						<div class="flex flex-wrap gap-1">
							{#each newMCPServerArgs as arg, i}
								<div class="flex items-center gap-1 bg-slate-800 px-2 py-1 rounded text-xs text-slate-300">
									<span>{arg}</span>
									<button 
										on:click={() => removeMCPServerArg(i)}
										class="text-red-400 hover:text-red-300"
									>
										<X class="w-3 h-3" />
									</button>
								</div>
							{/each}
						</div>
					{/if}
				</div>
			{/if}

			<!-- HTTP URL (for http transport) -->
			{#if newMCPServerTransport === 'http'}
				<div class="mb-3">
					<label class="block text-xs text-slate-300 mb-1">HTTP URL *</label>
					<input 
						type="text" 
						bind:value={newMCPServerHttpUrl}
						placeholder="e.g., http://localhost:3000/mcp"
						class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 outline-none focus:border-amber-500"
					/>
				</div>
			{/if}

			<!-- Working Directory -->
			<div class="mb-3">
				<label class="block text-xs text-slate-300 mb-1">Working Directory (optional)</label>
				<input 
					type="text" 
					bind:value={newMCPServerCwd}
					placeholder="e.g., /path/to/workspace"
					class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 outline-none focus:border-amber-500"
				/>
			</div>

			<!-- Environment Variables -->
			<div class="mb-3">
				<label class="block text-xs text-slate-300 mb-1">Environment Variables</label>
				<div class="flex gap-2 mb-2">
					<input 
						type="text" 
						bind:value={newMCPServerEnvKey}
						placeholder="Key"
						class="flex-1 bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 outline-none focus:border-amber-500"
					/>
					<input 
						type="text" 
						bind:value={newMCPServerEnvValue}
						on:keydown={(e) => e.key === 'Enter' && addMCPServerEnvVar()}
						placeholder="Value"
						class="flex-1 bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 outline-none focus:border-amber-500"
					/>
					<button 
						on:click={addMCPServerEnvVar}
						class="px-3 py-2 bg-slate-800 border border-slate-700 rounded text-xs text-slate-300 hover:bg-slate-700"
					>
						Add
					</button>
				</div>
				{#if newMCPServerEnvVars.length > 0}
					<div class="space-y-1">
						{#each newMCPServerEnvVars as env, i}
							<div class="flex items-center gap-2 bg-slate-800 px-2 py-1 rounded text-xs">
								<span class="text-slate-300 font-mono">{env.key}</span>
								<span class="text-slate-500">=</span>
								<span class="text-slate-400 flex-1 truncate">{env.value}</span>
								<button 
									on:click={() => removeMCPServerEnvVar(i)}
									class="text-red-400 hover:text-red-300"
								>
									<X class="w-3 h-3" />
								</button>
							</div>
						{/each}
					</div>
				{/if}
			</div>

			<!-- Submit Button -->
			<button 
				on:click={handleCreateMCPServer}
				disabled={!newMCPServerName.trim() || (newMCPServerTransport === 'stdio' && !newMCPServerCommand.trim()) || (newMCPServerTransport === 'http' && !newMCPServerHttpUrl.trim())}
				class="w-full bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-600 hover:to-orange-700 disabled:from-slate-700 disabled:to-slate-700 disabled:cursor-not-allowed text-white text-xs font-bold py-2 rounded transition-all"
			>
				Add MCP Server
			</button>
		</div>

		<!-- MCP Servers List -->
		<div>
			<h4 class="text-xs font-bold text-slate-400 uppercase mb-2">Configured Servers</h4>
			{#if $mcpServers.length === 0}
				<div class="text-xs text-slate-500 italic text-center py-4">
					No MCP servers configured
				</div>
			{:else}
				<div class="space-y-2">
					{#each $mcpServers as server}
						<div class="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
							<div class="flex items-center justify-between mb-2">
								<div class="flex items-center gap-2">
									<span class="text-xs font-bold text-slate-300">{server.name}</span>
									<span class="text-[10px] px-1.5 py-0.5 rounded {server.enabled ? 'bg-green-500/20 text-green-400' : 'bg-slate-500/20 text-slate-400'}">
										{server.enabled ? 'enabled' : 'disabled'}
									</span>
								</div>
								<div class="flex items-center gap-1">
									<button 
										on:click={() => handleReloadMCPServer(server.name)}
										class="p-1 hover:bg-blue-500/20 rounded"
										title="Reload tools"
									>
										<RefreshCw class="w-3 h-3 text-blue-400" />
									</button>
									<button 
										on:click={() => handleDeleteMCPServer(server.name)}
										class="p-1 hover:bg-red-500/20 rounded"
									>
										<Trash2 class="w-3 h-3 text-red-400" />
									</button>
								</div>
							</div>
							<pre class="text-[10px] text-slate-500 overflow-x-auto">{JSON.stringify(server.config, null, 2)}</pre>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	</div>
{/if}
