<script lang="ts">
	import { slide, fade } from 'svelte/transition';
	import { X, Brain, Wrench, ChevronDown, ChevronRight, Sparkles, Loader2, Activity, Zap, CheckCircle, XCircle, Clock } from 'lucide-svelte';
	import { showAgentPanel, activeThinking, activeToolCalls, toolExecutions, isLoading, iterationProgress, messages, agentStatus, reasoningWarning } from '$lib/stores';
	import { onMount, afterUpdate } from 'svelte';

	// Auto-scroll thinking content
	let thinkingContainer: HTMLDivElement;
	let activityContainer: HTMLDivElement;
	
	afterUpdate(() => {
		if ($activeThinking?.isActive && thinkingContainer) {
			thinkingContainer.scrollTop = thinkingContainer.scrollHeight;
		}
		if (activityContainer) {
			activityContainer.scrollTop = activityContainer.scrollHeight;
		}
	});

	// Format elapsed time
	function formatElapsed(timestamp: Date): string {
		const elapsed = Math.floor((Date.now() - timestamp.getTime()) / 1000);
		if (elapsed < 60) return `${elapsed}s ago`;
		if (elapsed < 3600) return `${Math.floor(elapsed / 60)}m ago`;
		return `${Math.floor(elapsed / 3600)}h ago`;
	}

	// Tool icon mapping
	function getToolIcon(toolName: string): string {
		const icons: Record<string, string> = {
			'filesystem_read': '📄',
			'filesystem_write': '✍️',
			'filesystem_replace_lines': '🔧',
			'filesystem_search_replace': '🔍',
			'filesystem_insert': '➕',
			'filesystem_delete': '🗑️',
			'filesystem_list': '📁',
			'grep': '🔎',
			'shell_execute': '💻',
			'run_python': '🐍',
			'git_status': '📊',
			'git_commit': '💾',
		};
		return icons[toolName] || '⚙️';
	}

	// Recent thinking snippets for display
	$: recentThinking = $activeThinking?.content.slice(-500) || '';
	$: thinkingLines = recentThinking.split('\n').slice(-10);

	// Get last assistant message for activity summary when no thinking is available
	$: lastAssistantMessage = (() => {
		const assistantMessages = $messages.filter(m => m.role === 'assistant');
		if (assistantMessages.length === 0) return null;
		const last = assistantMessages[assistantMessages.length - 1];
		// Get last 200 chars of content for preview
		const content = last.content || '';
		return content.length > 200 ? '...' + content.slice(-200) : content;
	})();
</script>

{#if $showAgentPanel}
<aside 
	class="w-96 bg-slate-900/95 backdrop-blur-xl border-l border-slate-800/50 flex flex-col overflow-hidden shadow-2xl"
	transition:slide={{ axis: 'x', duration: 200 }}
>
	<!-- Header -->
	<div class="h-12 flex items-center justify-between px-4 bg-gradient-to-r from-purple-900/50 to-blue-900/50 border-b border-slate-700/50">
		<div class="flex items-center gap-2">
			<div class="relative">
				<Brain class="w-5 h-5 text-purple-400" />
				{#if $isLoading}
					<span class="absolute -top-0.5 -right-0.5 w-2 h-2 bg-green-400 rounded-full animate-ping"></span>
				{/if}
			</div>
			<span class="text-sm font-bold text-slate-200">Agent Activity</span>
			{#if $isLoading}
				<span class="text-[10px] px-2 py-0.5 rounded-full bg-green-500/20 text-green-400 animate-pulse">
					LIVE
				</span>
			{/if}
		</div>
		<button 
			on:click={() => $showAgentPanel = false} 
			class="p-1.5 hover:bg-slate-700/50 rounded-lg transition-colors"
		>
			<X class="w-4 h-4 text-slate-400" />
		</button>
	</div>

	<!-- Content -->
	<div class="flex-1 flex flex-col overflow-hidden">
		<!-- Thinking Section -->
		<div class="border-b border-slate-800/50">
			<div class="px-4 py-3 flex items-center justify-between bg-slate-900/50">
				<div class="flex items-center gap-2">
					<Sparkles class="w-4 h-4 text-purple-400" />
					<span class="text-xs font-semibold text-slate-300 uppercase tracking-wider">Reasoning</span>
				</div>
				{#if $activeThinking?.isActive}
					<div class="flex items-center gap-1.5">
						<Loader2 class="w-3 h-3 text-purple-400 animate-spin" />
						<span class="text-[10px] text-purple-400 font-mono">
							{$activeThinking?.content.length.toLocaleString()} chars
						</span>
					</div>
				{/if}
			</div>

			<div 
				bind:this={thinkingContainer}
				class="max-h-48 overflow-y-auto bg-slate-950/50"
			>
				{#if $activeThinking?.isActive}
					<div class="p-4" transition:fade>
						<div class="bg-gradient-to-br {$reasoningWarning ? 'from-amber-500/10 to-red-500/10 border-amber-500/30' : 'from-purple-500/10 to-blue-500/10 border-purple-500/30'} rounded-lg p-3 border">
							<div class="flex items-center gap-2 mb-2">
								{#if $reasoningWarning}
									<Zap class="w-4 h-4 text-amber-400 animate-pulse" />
									<span class="text-xs text-amber-300 font-medium">Overthinking detected!</span>
									<span class="text-[10px] text-amber-500 font-mono ml-auto">
										{Math.round($reasoningWarning.length / 1000)}k chars
									</span>
								{:else}
									<Brain class="w-4 h-4 text-purple-400 animate-pulse" />
									<span class="text-xs text-purple-300 font-medium">Thinking in progress...</span>
								{/if}
							</div>
							{#if $reasoningWarning}
								<p class="text-[10px] text-amber-400 mb-2">
									⚡ Agent is thinking too much. Waiting for action...
								</p>
							{/if}
							<pre class="text-xs text-slate-300 font-mono whitespace-pre-wrap leading-relaxed max-h-32 overflow-y-auto">{#each thinkingLines as line}{line}
{/each}<span class="{$reasoningWarning ? 'text-amber-400' : 'text-purple-400'} animate-pulse">▊</span></pre>
						</div>
					</div>
				{:else if $activeThinking?.isComplete}
					<div class="p-4" transition:fade>
						<div class="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
							<div class="flex items-center gap-2 mb-2">
								<CheckCircle class="w-4 h-4 text-emerald-400" />
								<span class="text-xs text-emerald-300 font-medium">Reasoning complete</span>
								<span class="text-[10px] text-slate-500 font-mono">
									{$activeThinking?.content.length.toLocaleString()} chars
								</span>
							</div>
							<p class="text-xs text-slate-400 line-clamp-3">
								{$activeThinking?.summary || 'Analysis complete.'}
							</p>
						</div>
					</div>
				{:else if $isLoading}
					<div class="p-4" transition:fade>
						<div class="bg-gradient-to-br {$agentStatus?.is_reasoning_model ? 'from-purple-500/10 to-blue-500/10 border-purple-500/30' : 'from-amber-500/5 to-orange-500/5 border-amber-500/20'} rounded-lg p-3 border">
							<div class="flex items-center gap-2 mb-2">
								{#if $agentStatus?.is_reasoning_model}
									<Brain class="w-4 h-4 text-purple-400 animate-pulse" />
									<span class="text-xs text-purple-300 font-medium">Reasoning model active</span>
								{:else}
									<Loader2 class="w-4 h-4 text-amber-400 animate-spin" />
									<span class="text-xs text-amber-300 font-medium">Agent working...</span>
								{/if}
							</div>
							<div class="space-y-1.5">
								{#if $agentStatus?.is_reasoning_model}
									<p class="text-xs text-slate-400">
										🧠 Model: <span class="font-mono text-purple-400">{$agentStatus.model.split('/').pop()}</span>
									</p>
									<p class="text-[10px] text-slate-500">
										Extended thinking enabled. The model is analyzing your request deeply before responding.
									</p>
								{/if}
								
								{#if $activeToolCalls.length > 0}
									<p class="text-xs text-slate-400">
										<span class="text-amber-400">⚡</span> Executing: {$activeToolCalls[0]?.tool}
									</p>
								{:else if $iterationProgress}
									<p class="text-xs text-slate-400">
										<span class="text-blue-400">📊</span> Step {$iterationProgress.current} of {$iterationProgress.max}
									</p>
									{#if $iterationProgress.read_ops}
										<p class="text-xs text-slate-500">
											📖 {$iterationProgress.read_ops} file{$iterationProgress.read_ops > 1 ? 's' : ''} analyzed
										</p>
									{/if}
									{#if $iterationProgress.edit_ops}
										<p class="text-xs text-slate-500">
											✏️ {$iterationProgress.edit_ops} edit{$iterationProgress.edit_ops > 1 ? 's' : ''} made
										</p>
									{/if}
								{:else if !$agentStatus?.is_reasoning_model}
									<p class="text-xs text-slate-500 italic">
										Processing request...
									</p>
								{/if}
								
								<!-- Show last response snippet as context -->
								{#if lastAssistantMessage && !$activeToolCalls.length}
									<div class="mt-2 pt-2 border-t border-slate-700/30">
										<p class="text-[10px] text-slate-500 mb-1">Last response:</p>
										<p class="text-[10px] text-slate-400 font-mono line-clamp-3">
											{lastAssistantMessage}
										</p>
									</div>
								{/if}
								
								{#if !$agentStatus?.is_reasoning_model}
									<p class="text-[10px] text-slate-600 mt-2">
										💡 Tip: Use a reasoning model for visible thinking
									</p>
								{/if}
							</div>
						</div>
					</div>
				{:else}
					<div class="p-4 text-center">
						<div class="text-slate-500 text-xs">
							No active reasoning
						</div>
					</div>
				{/if}
			</div>
		</div>

		<!-- Active Tools Section -->
		{#if $activeToolCalls.length > 0}
			<div class="border-b border-slate-800/50" transition:slide>
				<div class="px-4 py-3 flex items-center justify-between bg-amber-900/20">
					<div class="flex items-center gap-2">
						<Zap class="w-4 h-4 text-amber-400 animate-pulse" />
						<span class="text-xs font-semibold text-amber-300 uppercase tracking-wider">Executing</span>
					</div>
					<span class="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400">
						{$activeToolCalls.length} active
					</span>
				</div>
				<div class="p-2 space-y-2 bg-slate-950/50">
					{#each $activeToolCalls as toolCall}
						<div class="bg-amber-500/10 border border-amber-500/30 rounded-lg p-3 animate-pulse-subtle">
							<div class="flex items-center gap-2 mb-1">
								<span class="text-lg">{getToolIcon(toolCall.tool)}</span>
								<span class="text-xs font-bold text-amber-300">{toolCall.tool}</span>
								<Loader2 class="w-3 h-3 text-amber-400 animate-spin ml-auto" />
							</div>
							{#if toolCall.args?.path}
								<p class="text-[10px] font-mono text-slate-400 truncate">
									📁 {toolCall.args.path}
								</p>
							{/if}
							{#if toolCall.args?.pattern}
								<p class="text-[10px] font-mono text-slate-400 truncate">
									🔍 {toolCall.args.pattern}
								</p>
							{/if}
							<p class="text-[10px] text-slate-500 mt-1">
								{formatElapsed(toolCall.timestamp)}
							</p>
						</div>
					{/each}
				</div>
			</div>
		{/if}

		<!-- Tool History Section -->
		<div class="flex-1 flex flex-col overflow-hidden">
			<div class="px-4 py-3 flex items-center justify-between bg-slate-900/50 border-b border-slate-800/30">
				<div class="flex items-center gap-2">
					<Wrench class="w-4 h-4 text-slate-400" />
					<span class="text-xs font-semibold text-slate-300 uppercase tracking-wider">Tool History</span>
				</div>
				{#if $toolExecutions.length > 0}
					<span class="text-[10px] text-slate-500">
						{$toolExecutions.length} executed
					</span>
				{/if}
			</div>

			<div 
				bind:this={activityContainer}
				class="flex-1 overflow-y-auto p-2 space-y-2"
			>
				{#if $toolExecutions.length === 0}
					<div class="text-center py-8 text-slate-500 text-xs">
						No tools executed yet
					</div>
				{:else}
					{#each [...$toolExecutions].reverse().slice(0, 20) as execution}
						<div 
							class="rounded-lg p-3 border transition-all {
								execution.status === 'success' 
									? 'bg-emerald-500/5 border-emerald-500/20 hover:border-emerald-500/40' 
									: execution.status === 'error'
										? 'bg-red-500/5 border-red-500/20 hover:border-red-500/40'
										: 'bg-slate-800/30 border-slate-700/30 hover:border-slate-600/50'
							}"
						>
							<div class="flex items-center gap-2 mb-1">
								<span class="text-base">{getToolIcon(execution.type)}</span>
								<span class="text-xs font-bold {
									execution.status === 'success' ? 'text-emerald-400' : 
									execution.status === 'error' ? 'text-red-400' : 'text-slate-300'
								}">
									{execution.type}
								</span>
								<div class="ml-auto flex items-center gap-1">
									{#if execution.status === 'success'}
										<CheckCircle class="w-3 h-3 text-emerald-400" />
									{:else if execution.status === 'error'}
										<XCircle class="w-3 h-3 text-red-400" />
									{:else}
										<Clock class="w-3 h-3 text-slate-400" />
									{/if}
								</div>
							</div>

							{#if execution.path}
								<p class="text-[10px] font-mono text-slate-400 truncate mb-1">
									{execution.path}
								</p>
							{/if}

							{#if execution.command}
								<p class="text-[10px] font-mono text-slate-400 truncate mb-1">
									$ {execution.command}
								</p>
							{/if}

							{#if execution.diff}
								<div class="flex items-center gap-2 mt-1">
									<span class="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400">
										+{execution.diff.stats.lines_added}
									</span>
									<span class="text-[10px] px-1.5 py-0.5 rounded bg-red-500/20 text-red-400">
										-{execution.diff.stats.lines_removed}
									</span>
								</div>
							{/if}

							{#if execution.status === 'error' && execution.stderr}
								<p class="text-[10px] text-red-400 mt-1 line-clamp-2">
									{execution.stderr}
								</p>
							{/if}

							<p class="text-[9px] text-slate-600 mt-1">
								{execution.timestamp.toLocaleTimeString()}
							</p>
						</div>
					{/each}
				{/if}
			</div>
		</div>
	</div>

	<!-- Footer with iteration info -->
	{#if $iterationProgress}
		<div class="px-4 py-3 bg-slate-900/80 border-t border-slate-800/50">
			<div class="flex items-center justify-between mb-2">
				<span class="text-xs text-slate-400">Agent Progress</span>
				<span class="text-xs font-mono text-slate-300">
					Step {$iterationProgress.current} / {$iterationProgress.max}
				</span>
			</div>
			<div class="h-1.5 bg-slate-800 rounded-full overflow-hidden">
				<div 
					class="h-full bg-gradient-to-r from-purple-500 to-blue-500 transition-all duration-300"
					style="width: {($iterationProgress.current / $iterationProgress.max) * 100}%"
				></div>
			</div>
			<div class="flex items-center gap-3 mt-2 text-[10px]">
				{#if $iterationProgress.read_ops !== undefined}
					<span class="text-blue-400">📖 {$iterationProgress.read_ops} reads</span>
				{/if}
				{#if $iterationProgress.edit_ops !== undefined}
					<span class="text-emerald-400">✏️ {$iterationProgress.edit_ops} edits</span>
				{/if}
			</div>
			
			<!-- File tracking -->
			{#if $iterationProgress.files_read?.length || Object.keys($iterationProgress.files_edited || {}).length}
				<div class="mt-3 pt-2 border-t border-slate-700/30">
					{#if $iterationProgress.files_read?.length}
						<div class="mb-2">
							<span class="text-[10px] text-slate-500 uppercase tracking-wider">Files Read:</span>
							<div class="flex flex-wrap gap-1 mt-1">
								{#each $iterationProgress.files_read.slice(0, 5) as file}
									<span class="text-[9px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 font-mono truncate max-w-[120px]" title={file}>
										{file.split('/').pop()}
									</span>
								{/each}
								{#if $iterationProgress.files_read.length > 5}
									<span class="text-[9px] text-slate-500">+{$iterationProgress.files_read.length - 5} more</span>
								{/if}
							</div>
						</div>
					{/if}
					{#if Object.keys($iterationProgress.files_edited || {}).length}
						<div>
							<span class="text-[10px] text-slate-500 uppercase tracking-wider">Files Edited:</span>
							<div class="flex flex-wrap gap-1 mt-1">
								{#each Object.entries($iterationProgress.files_edited || {}).slice(0, 5) as [file, count]}
									<span class="text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 font-mono truncate max-w-[120px]" title="{file}: {count} edit(s)">
										{file.split('/').pop()} ({count})
									</span>
								{/each}
							</div>
						</div>
					{/if}
				</div>
			{/if}
		</div>
	{/if}
</aside>
{/if}

<style>
	.line-clamp-2 {
		display: -webkit-box;
		-webkit-line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}

	.line-clamp-3 {
		display: -webkit-box;
		-webkit-line-clamp: 3;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}

	@keyframes pulse-subtle {
		0%, 100% {
			opacity: 1;
		}
		50% {
			opacity: 0.7;
		}
	}

	:global(.animate-pulse-subtle) {
		animation: pulse-subtle 2s ease-in-out infinite;
	}
</style>
