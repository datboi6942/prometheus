<script lang="ts">
	import { X, Check, Shield } from 'lucide-svelte';
	import { 
		showSettings, 
		workspacePath, 
		autoApproveEdits, 
		verboseMode,
		customEndpoint,
		customApiKey,
		apiKeys
	} from '$lib/stores';

	function closeSettings() {
		$showSettings = false;
	}
</script>

<!-- Settings Panel -->
{#if $showSettings}
	<div class="absolute right-6 top-20 w-[480px] bg-slate-900 border border-slate-700/50 rounded-xl shadow-2xl z-50 p-6 animate-in slide-in-from-right backdrop-blur-xl max-h-[calc(100vh-120px)] overflow-hidden flex flex-col">
		<div class="flex items-center justify-between mb-6">
			<div class="flex items-center gap-3">
				<div class="w-10 h-10 rounded-lg bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center">
					<Shield class="w-5 h-5 text-white" />
				</div>
				<h3 class="text-base font-bold text-white">Settings & API Keys</h3>
			</div>
			<button on:click={closeSettings} class="text-slate-400 hover:text-white">
				<X class="w-5 h-5" />
			</button>
		</div>
		
		<div class="space-y-5 max-h-[calc(100vh-200px)] overflow-y-auto pr-2">
			<div>
				<label class="block text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">Workspace Path (Required)</label>
				<input 
					type="text" 
					bind:value={$workspacePath}
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
					on:click={() => $autoApproveEdits = !$autoApproveEdits}
					class="relative w-12 h-6 rounded-full transition-colors {$autoApproveEdits ? 'bg-green-500' : 'bg-slate-700'}"
				>
					<div class="absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform {$autoApproveEdits ? 'translate-x-6' : ''}"></div>
				</button>
			</div>

			<div class="flex items-center justify-between p-3 bg-slate-950 rounded-lg border border-slate-700">
				<div>
					<label class="block text-[10px] font-bold text-slate-400 uppercase">Verbose Mode</label>
					<p class="text-[9px] text-slate-500 mt-0.5">Show internal tool calls and debug info</p>
				</div>
				<button 
					on:click={() => $verboseMode = !$verboseMode}
					class="relative w-12 h-6 rounded-full transition-colors {$verboseMode ? 'bg-amber-500' : 'bg-slate-700'}"
				>
					<div class="absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform {$verboseMode ? 'translate-x-6' : ''}"></div>
				</button>
			</div>

			<div>
				<label class="block text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">Custom Endpoint URL</label>
				<input 
					type="text" 
					bind:value={$customEndpoint}
					placeholder="http://192.168.1.50:11434"
					class="w-full bg-slate-950 border border-slate-700 rounded-lg px-4 py-2.5 text-sm focus:border-amber-500 focus:ring-1 focus:ring-amber-500 outline-none transition-all"
				/>
				<p class="text-[10px] text-slate-500 mt-1.5 italic">For remote Ollama or LM Studio instances</p>
			</div>

			<!-- API Keys Section -->
			<div class="border-t border-slate-700 pt-4">
				<h4 class="text-xs font-bold text-slate-300 mb-3 flex items-center gap-2">
					<Shield class="w-4 h-4 text-amber-500" />
					API Keys (Encrypted & Stored Securely)
				</h4>
				
				<!-- OpenAI -->
				<div class="mb-3">
					<label class="block text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">OpenAI API Key</label>
					<input 
						type="password" 
						bind:value={$apiKeys.openai}
						placeholder="sk-..."
						class="w-full bg-slate-950 border border-slate-700 rounded-lg px-4 py-2 text-sm focus:border-amber-500 focus:ring-1 focus:ring-amber-500 outline-none transition-all font-mono"
					/>
				</div>

				<!-- Anthropic -->
				<div class="mb-3">
					<label class="block text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">Anthropic API Key (Claude)</label>
					<input 
						type="password" 
						bind:value={$apiKeys.anthropic}
						placeholder="sk-ant-..."
						class="w-full bg-slate-950 border border-slate-700 rounded-lg px-4 py-2 text-sm focus:border-amber-500 focus:ring-1 focus:ring-amber-500 outline-none transition-all font-mono"
					/>
				</div>

				<!-- DeepSeek -->
				<div class="mb-3">
					<label class="block text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">DeepSeek API Key</label>
					<input 
						type="password" 
						bind:value={$apiKeys.deepseek}
						placeholder="sk-..."
						class="w-full bg-slate-950 border border-slate-700 rounded-lg px-4 py-2 text-sm focus:border-amber-500 focus:ring-1 focus:ring-amber-500 outline-none transition-all font-mono"
					/>
				</div>

				<!-- Grok -->
				<div class="mb-3">
					<label class="block text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">Grok API Key (xAI)</label>
					<input 
						type="password" 
						bind:value={$apiKeys.grok}
						placeholder="xai-..."
						class="w-full bg-slate-950 border border-slate-700 rounded-lg px-4 py-2 text-sm focus:border-amber-500 focus:ring-1 focus:ring-amber-500 outline-none transition-all font-mono"
					/>
				</div>

				<!-- Google -->
				<div class="mb-3">
					<label class="block text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">Google AI API Key (Gemini)</label>
					<input 
						type="password" 
						bind:value={$apiKeys.google}
						placeholder="AI..."
						class="w-full bg-slate-950 border border-slate-700 rounded-lg px-4 py-2 text-sm focus:border-amber-500 focus:ring-1 focus:ring-amber-500 outline-none transition-all font-mono"
					/>
				</div>

				<!-- LiteLLM -->
				<div class="mb-3">
					<label class="block text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">LiteLLM API Key</label>
					<input 
						type="password" 
						bind:value={$apiKeys.litellm}
						placeholder="sk-..."
						class="w-full bg-slate-950 border border-slate-700 rounded-lg px-4 py-2 text-sm focus:border-amber-500 focus:ring-1 focus:ring-amber-500 outline-none transition-all font-mono"
					/>
				</div>

				<!-- Legacy API Key (for backward compatibility) -->
				<div class="mt-4 pt-4 border-t border-slate-700/50">
					<label class="block text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">Legacy API Key (Deprecated)</label>
					<input 
						type="password" 
						bind:value={$customApiKey}
						placeholder="sk-..."
						class="w-full bg-slate-950 border border-slate-700/50 rounded-lg px-4 py-2 text-sm focus:border-amber-500 focus:ring-1 focus:ring-amber-500 outline-none transition-all font-mono opacity-60"
					/>
					<p class="text-[9px] text-slate-500 mt-1 italic">Use provider-specific keys above instead</p>
				</div>
			</div>

			<button 
				on:click={closeSettings}
				class="w-full bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-600 hover:to-orange-700 text-white text-sm font-bold py-2.5 rounded-lg transition-all shadow-lg shadow-amber-500/20 sticky bottom-0"
			>
				<Check class="w-4 h-4 inline mr-2" />
				Save & Close
			</button>
		</div>
	</div>
{/if}
