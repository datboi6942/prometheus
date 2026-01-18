<script lang="ts">
	import { Brain, ChevronDown, ChevronRight, Sparkles } from 'lucide-svelte';
	import { slide } from 'svelte/transition';

	export let summary: string;
	export let fullContent: string;
	export let isStreaming: boolean = false;
	export let isExpanded: boolean = false;

	function toggleExpanded() {
		isExpanded = !isExpanded;
	}
</script>

<div
	class="bg-gradient-to-br from-purple-500/10 to-blue-500/10 rounded-lg p-4 border border-purple-500/30 shadow-lg mb-3 transition-all duration-500"
	class:animate-pulse={isStreaming}
	class:opacity-75={!isStreaming && fullContent}
>
	<!-- Header with Summary -->
	<button
		on:click={toggleExpanded}
		class="w-full flex items-center justify-between hover:bg-purple-500/5 rounded-md p-2 -m-2 transition-colors"
	>
		<div class="flex items-center gap-3">
			<div class="relative">
				<Brain
					class="w-5 h-5 transition-colors {isStreaming ? 'text-purple-400' : 'text-purple-300'}"
				/>
				{#if isStreaming}
					<Sparkles class="w-3 h-3 text-yellow-400 absolute -top-1 -right-1 animate-pulse" />
				{/if}
			</div>

			<div class="flex-1 text-left">
				<div class="text-xs font-medium text-purple-300 mb-1">
					{isStreaming ? 'Thinking...' : 'Reasoning Process'}
				</div>
				{#if summary}
					<div class="text-sm text-slate-300">
						{summary}
					</div>
				{:else if isStreaming}
					<div class="text-sm text-slate-400 italic">Working through the problem...</div>
				{/if}
			</div>
		</div>

		<div class="flex items-center gap-2">
			<span class="text-xs text-slate-500">
				{fullContent.length.toLocaleString()} chars
			</span>
			{#if isExpanded}
				<ChevronDown class="w-4 h-4 text-slate-400" />
			{:else}
				<ChevronRight class="w-4 h-4 text-slate-400" />
			{/if}
		</div>
	</button>

	<!-- Expandable Thinking Content -->
	{#if isExpanded}
		<div transition:slide={{ duration: 300 }} class="mt-3 pt-3 border-t border-purple-500/20">
			<div class="bg-slate-900/50 rounded-md p-4 max-h-96 overflow-y-auto">
				<pre
					class="text-xs text-slate-300 leading-relaxed whitespace-pre-wrap font-mono">{fullContent}{#if isStreaming}<span class="animate-pulse">▊</span>{/if}</pre>
			</div>
		</div>
	{/if}
</div>
