<script lang="ts">
	import { Terminal as TerminalIcon, X, Trash2 } from 'lucide-svelte';
	import { showTerminalPanel, toolExecutions } from '$lib/stores';

	function clearTerminal() {
		$toolExecutions = [];
	}

	function formatTimestamp(date: Date): string {
		return date.toLocaleTimeString();
	}
</script>

{#if $showTerminalPanel}
	<aside class="fixed right-0 bottom-0 w-2/5 h-96 bg-slate-900/95 border-t border-l border-slate-800/50 backdrop-blur-xl z-40 flex flex-col shadow-2xl">
		<!-- Header -->
		<div class="h-10 flex items-center justify-between px-4 bg-slate-900/50 border-b border-slate-800/50">
			<div class="flex items-center gap-2">
				<TerminalIcon class="w-4 h-4 text-amber-500" />
				<span class="text-xs font-semibold text-slate-400 uppercase tracking-wider">Terminal</span>
			</div>
			<div class="flex items-center gap-2">
				<button
					on:click={clearTerminal}
					class="p-1 hover:bg-slate-700/50 rounded"
					title="Clear terminal"
				>
					<Trash2 class="w-4 h-4 text-slate-500 hover:text-slate-300" />
				</button>
				<button
					on:click={() => $showTerminalPanel = false}
					class="p-1 hover:bg-slate-700/50 rounded"
				>
					<X class="w-4 h-4 text-slate-500 hover:text-slate-300" />
				</button>
			</div>
		</div>

		<!-- Terminal Output -->
		<div class="flex-1 overflow-y-auto p-4 font-mono text-xs bg-slate-950 text-slate-300">
			{#if $toolExecutions.length === 0}
				<div class="text-slate-600 italic">No command output yet...</div>
			{:else}
				{#each $toolExecutions as execution}
					<div class="mb-4 pb-4 border-b border-slate-800/30">
						<!-- Header -->
						<div class="flex items-center justify-between mb-2">
							<div class="flex items-center gap-2">
								<span class="text-amber-500">$</span>
								<span class="text-slate-400">{execution.type}</span>
								{#if execution.path}
									<span class="text-slate-500">•</span>
									<span class="text-slate-400">{execution.path}</span>
								{/if}
							</div>
							<div class="flex items-center gap-2">
								<span class="text-[10px] px-2 py-0.5 rounded {execution.status === 'success' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}">
									{execution.status}
								</span>
								<span class="text-[10px] text-slate-600">{formatTimestamp(execution.timestamp)}</span>
							</div>
						</div>

						<!-- Command -->
						{#if execution.command}
							<div class="mb-1 text-slate-400">
								<span class="text-amber-600">cmd:</span> {execution.command}
							</div>
						{/if}

						<!-- STDOUT -->
						{#if execution.stdout}
							<div class="bg-slate-900/50 p-2 rounded mb-1">
								<div class="text-green-400 mb-1 text-[10px] uppercase tracking-wider">stdout:</div>
								<pre class="text-slate-300 whitespace-pre-wrap">{execution.stdout}</pre>
							</div>
						{/if}

						<!-- STDERR -->
						{#if execution.stderr}
							<div class="bg-red-950/30 p-2 rounded mb-1">
								<div class="text-red-400 mb-1 text-[10px] uppercase tracking-wider">stderr:</div>
								<pre class="text-red-300 whitespace-pre-wrap">{execution.stderr}</pre>
							</div>
						{/if}

						<!-- Return Code -->
						{#if execution.return_code !== undefined}
							<div class="text-slate-500 text-[10px]">
								exit code: <span class="{execution.return_code === 0 ? 'text-green-400' : 'text-red-400'}">{execution.return_code}</span>
							</div>
						{/if}

						<!-- Hint -->
						{#if execution.hint}
							<div class="mt-2 bg-amber-950/30 border-l-2 border-amber-500 p-2 rounded">
								<div class="text-amber-400 mb-1 text-[10px] uppercase tracking-wider">hint:</div>
								<div class="text-amber-200/80">{execution.hint}</div>
							</div>
						{/if}
					</div>
				{/each}
			{/if}
		</div>
	</aside>
{/if}

<style>
	/* Auto-scroll terminal to bottom */
	.overflow-y-auto {
		scroll-behavior: smooth;
	}
</style>
