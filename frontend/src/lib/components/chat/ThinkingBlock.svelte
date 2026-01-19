<script lang="ts">
	import { Brain, ChevronDown, ChevronRight, Sparkles, Loader2 } from 'lucide-svelte';
	import { slide } from 'svelte/transition';
	import { onMount, afterUpdate } from 'svelte';

	export let summary: string;
	export let fullContent: string;
	export let isStreaming: boolean = false;
	export let isExpanded: boolean = false;

	// Auto-expand when streaming starts
	$: if (isStreaming && fullContent.length > 0) {
		isExpanded = true;
	}

	// Auto-scroll the content container when new content arrives
	let contentContainer: HTMLDivElement;
	afterUpdate(() => {
		if (isStreaming && contentContainer) {
			contentContainer.scrollTop = contentContainer.scrollHeight;
		}
	});

	function toggleExpanded() {
		isExpanded = !isExpanded;
	}
</script>

<div
	class="bg-gradient-to-br from-purple-500/10 to-blue-500/10 rounded-lg p-4 border border-purple-500/30 shadow-lg mb-3 transition-all duration-500 {isStreaming ? 'ring-2 ring-purple-500/50' : ''} {isStreaming && fullContent.length === 0 ? 'animate-pulse' : ''}"
>
	<!-- Header with Summary -->
	<button
		on:click={toggleExpanded}
		class="w-full flex items-center justify-between hover:bg-purple-500/5 rounded-md p-2 -m-2 transition-colors"
	>
		<div class="flex items-center gap-3">
			<div class="relative">
				{#if isStreaming}
					<div class="w-6 h-6 rounded-full bg-purple-500/20 flex items-center justify-center">
						<Loader2 class="w-4 h-4 text-purple-400 animate-spin" />
					</div>
					<Sparkles class="w-3 h-3 text-yellow-400 absolute -top-1 -right-1 animate-pulse" />
				{:else}
					<Brain class="w-5 h-5 text-purple-300" />
				{/if}
			</div>

			<div class="flex-1 text-left">
				<div class="text-xs font-medium {isStreaming ? 'text-purple-400' : 'text-purple-300'} mb-1 flex items-center gap-2">
					{#if isStreaming}
						<span class="animate-pulse">🧠 Reasoning in progress...</span>
						<span class="text-[10px] px-2 py-0.5 rounded-full bg-purple-500/20 text-purple-300">
							Live
						</span>
					{:else}
						Reasoning Process
					{/if}
				</div>
				{#if summary && !isStreaming}
					<div class="text-sm text-slate-300 line-clamp-2">
						{summary}
					</div>
				{:else if isStreaming && fullContent.length > 0}
					<div class="text-sm text-slate-400 italic line-clamp-1">
						{fullContent.slice(-100)}
					</div>
				{:else if isStreaming}
					<div class="text-sm text-slate-400 italic flex items-center gap-2">
						<span class="w-1.5 h-1.5 rounded-full bg-purple-400 animate-ping"></span>
						Analyzing the problem...
					</div>
				{/if}
			</div>
		</div>

		<div class="flex items-center gap-2">
			<span class="text-xs text-slate-500 font-mono">
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
			<div 
				bind:this={contentContainer}
				class="bg-slate-900/50 rounded-md p-4 max-h-96 overflow-y-auto scroll-smooth"
			>
				{#if fullContent}
					<pre class="text-xs text-slate-300 leading-relaxed whitespace-pre-wrap font-mono">{fullContent}{#if isStreaming}<span class="animate-pulse text-purple-400">▊</span>{/if}</pre>
				{:else if isStreaming}
					<div class="flex items-center justify-center py-4 gap-2 text-purple-400">
						<Loader2 class="w-4 h-4 animate-spin" />
						<span class="text-sm">Initializing reasoning...</span>
					</div>
				{/if}
			</div>
		</div>
	{/if}
</div>

<style>
	.line-clamp-1 {
		display: -webkit-box;
		-webkit-line-clamp: 1;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}

	.line-clamp-2 {
		display: -webkit-box;
		-webkit-line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
</style>
