<script lang="ts">
	import { onMount, createEventDispatcher } from 'svelte';
	import { FileText, Plus, Minus, ChevronDown, ChevronRight, Check, Loader2, X } from 'lucide-svelte';

	export let path: string;
	export let diff: {
		format: string;
		stats: { lines_added: number; lines_removed: number; lines_changed: number };
		hunks: Array<{ header: string; changes: Array<{ type: string; line: string }> }>;
	} | null;
	export let language: string;
	export let completed: boolean;

	const dispatch = createEventDispatcher();

	function handleDismiss() {
		dispatch('dismiss', { path });
	}

	// Animation state
	let visibleLines = 0;
	let totalLines = 0;
	let isExpanded = true;
	let animationInterval: ReturnType<typeof setInterval> | null = null;

	// Calculate total lines for animation
	$: if (diff) {
		totalLines = diff.hunks.reduce((acc, hunk) => acc + hunk.changes.length, 0);
	}

	// Animation logic - reveal lines progressively
	onMount(() => {
		if (diff && totalLines > 0) {
			// Start animation - reveal 2-3 lines every 50ms for smooth effect
			const linesPerFrame = Math.max(1, Math.ceil(totalLines / 30)); // Complete in ~1.5s
			animationInterval = setInterval(() => {
				if (visibleLines < totalLines) {
					visibleLines = Math.min(visibleLines + linesPerFrame, totalLines);
				} else {
					if (animationInterval) clearInterval(animationInterval);
				}
			}, 50);
		} else {
			// No diff or empty - show immediately
			visibleLines = totalLines;
		}

		return () => {
			if (animationInterval) clearInterval(animationInterval);
		};
	});

	// Skip to end when completed externally
	$: if (completed && visibleLines < totalLines) {
		visibleLines = totalLines;
		if (animationInterval) {
			clearInterval(animationInterval);
			animationInterval = null;
		}
	}

	// Get visible changes per hunk
	function getVisibleChanges(hunk: { changes: Array<{ type: string; line: string }> }, hunkIndex: number): Array<{ type: string; line: string; isNew: boolean }> {
		// Calculate how many lines came before this hunk
		let linesBefore = 0;
		for (let i = 0; i < hunkIndex; i++) {
			linesBefore += diff!.hunks[i].changes.length;
		}

		// Return changes with visibility and "new" indicator
		return hunk.changes.map((change, idx) => {
			const globalIdx = linesBefore + idx;
			const isVisible = globalIdx < visibleLines;
			const isNew = globalIdx === visibleLines - 1 || globalIdx === visibleLines - 2;
			return isVisible ? { ...change, isNew } : null;
		}).filter(Boolean) as Array<{ type: string; line: string; isNew: boolean }>;
	}

	// Helper to get change line classes
	function getChangeClasses(change: { type: string; isNew: boolean }): string {
		let classes = 'flex transition-all duration-150';

		if (change.type === 'added') {
			classes += ' bg-green-500 bg-opacity-15 hover:bg-opacity-25';
		} else if (change.type === 'removed') {
			classes += ' bg-red-500 bg-opacity-15 hover:bg-opacity-25';
		}

		if (change.isNew && !completed) {
			classes += ' animate-pulse ring-1 ring-purple-400 ring-opacity-50';
		}

		return classes;
	}

	// Progress percentage for animation bar
	$: progress = totalLines > 0 ? (visibleLines / totalLines) * 100 : 100;
	$: isAnimating = visibleLines < totalLines && !completed;
</script>

<div class="bg-gradient-to-br from-purple-500 from-opacity-10 to-fuchsia-500 to-opacity-10 rounded-lg border border-purple-500 border-opacity-30 shadow-lg mb-3 overflow-hidden transition-all duration-300 {isAnimating ? 'ring-2 ring-purple-500' : ''}">
	<!-- Header -->
	<button
		class="w-full flex items-center justify-between px-4 py-3 hover:bg-purple-500 hover:bg-opacity-5 transition-colors"
		on:click={() => isExpanded = !isExpanded}
	>
		<div class="flex items-center gap-3">
			{#if isExpanded}
				<ChevronDown size={16} class="text-purple-400" />
			{:else}
				<ChevronRight size={16} class="text-purple-400" />
			{/if}
			<FileText size={16} class="text-purple-400" />
			<span class="font-mono text-sm text-purple-200">{path}</span>

			<!-- Status badge -->
			{#if isAnimating}
				<span class="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-purple-500 bg-opacity-20 text-purple-300">
					<Loader2 size={10} class="animate-spin" />
					Applying...
				</span>
			{:else if completed}
				<span class="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-green-500 bg-opacity-20 text-green-300">
					<Check size={10} />
					Applied
				</span>
			{/if}
		</div>

		<div class="flex items-center gap-3 text-xs">
			<span class="flex items-center gap-1 text-green-400">
				<Plus size={12} />
				{diff?.stats.lines_added || 0}
			</span>
			<span class="flex items-center gap-1 text-red-400">
				<Minus size={12} />
				{diff?.stats.lines_removed || 0}
			</span>
			{#if completed}
				<button
					on:click|stopPropagation={handleDismiss}
					class="p-1 hover:bg-slate-700/50 rounded transition-colors ml-2"
					title="Dismiss diff"
				>
					<X size={14} class="text-slate-400 hover:text-slate-200" />
				</button>
			{/if}
		</div>
	</button>

	<!-- Progress bar (only during animation) -->
	{#if isAnimating}
		<div class="h-0.5 bg-slate-800">
			<div
				class="h-full bg-gradient-to-r from-purple-500 to-fuchsia-500 transition-all duration-100"
				style="width: {progress}%"
			></div>
		</div>
	{/if}

	<!-- Diff Content (collapsible) -->
	{#if isExpanded && diff}
		<div class="bg-slate-900 bg-opacity-50 max-h-96 overflow-y-auto font-mono text-xs border-t border-purple-500 border-opacity-20">
			{#each diff.hunks as hunk, hunkIndex}
				<!-- Hunk Header -->
				<div class="px-3 py-1.5 bg-slate-800 bg-opacity-70 text-slate-400 sticky top-0 border-b border-slate-700 border-opacity-50 flex items-center gap-2">
					<span class="text-purple-400">@@</span>
					<span>{hunk.header.replace(/^@@\s*/, '').replace(/\s*@@$/, '')}</span>
				</div>

				<!-- Hunk Changes with animation -->
				{#each getVisibleChanges(hunk, hunkIndex) as change}
					<div class={getChangeClasses(change)}>
						<!-- Line indicator -->
						<span class="w-8 text-center py-0.5 select-none flex-shrink-0 border-r border-slate-700 border-opacity-30 {change.type === 'added' ? 'text-green-400' : change.type === 'removed' ? 'text-red-400' : 'text-slate-500'}">
							{#if change.type === 'added'}+{:else if change.type === 'removed'}-{:else}&nbsp;{/if}
						</span>

						<!-- Code content -->
						<pre class="flex-1 py-0.5 px-3 overflow-x-auto {change.type === 'added' ? 'text-green-300' : change.type === 'removed' ? 'text-red-300' : 'text-slate-400'}">{change.line || ' '}</pre>
					</div>
				{/each}
			{/each}

			<!-- Loading indicator for remaining lines -->
			{#if isAnimating}
				<div class="flex items-center justify-center py-3 text-purple-400 text-xs gap-2">
					<Loader2 size={12} class="animate-spin" />
					<span>Revealing changes... ({visibleLines}/{totalLines})</span>
				</div>
			{/if}
		</div>
	{:else if isExpanded && !diff}
		<div class="px-4 py-6 text-center text-slate-500 text-xs">
			No diff data available
		</div>
	{/if}
</div>
