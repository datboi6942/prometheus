<script lang="ts">
	import { FileText, Plus, Minus } from 'lucide-svelte';

	export let path: string;
	export let diff: {
		format: string;
		stats: { lines_added: number; lines_removed: number; lines_changed: number };
		hunks: Array<{ header: string; changes: Array<{ type: string; line: string }> }>;
	};
	export let language: string;
	export let completed: boolean;
</script>

<div
	class="bg-gradient-to-br from-purple-500/10 to-fuchsia-500/10 rounded-lg p-4 border border-purple-500/30 shadow-lg mb-3 transition-opacity duration-500"
	class:opacity-50={completed}
>
	<!-- Header -->
	<div class="flex items-center justify-between mb-3">
		<div class="flex items-center gap-2">
			<FileText size={16} class="text-purple-400" />
			<span class="font-mono text-sm text-purple-200">{path}</span>
		</div>
		<div class="flex items-center gap-2 text-xs">
			<span class="flex items-center gap-1 text-green-400">
				<Plus size={12} />
				{diff.stats.lines_added}
			</span>
			<span class="flex items-center gap-1 text-red-400">
				<Minus size={12} />
				{diff.stats.lines_removed}
			</span>
		</div>
	</div>

	<!-- Diff Content -->
	<div class="bg-slate-900/50 rounded-md max-h-96 overflow-y-auto font-mono text-xs">
		{#each diff.hunks as hunk}
			<!-- Hunk Header -->
			<div class="px-3 py-1 bg-slate-800/50 text-slate-500 sticky top-0">
				{hunk.header}
			</div>

			<!-- Hunk Changes -->
			{#each hunk.changes as change}
				{#if change.type === 'added'}
					<div class="flex bg-green-500/10 hover:bg-green-500/20 transition-colors">
						<span class="text-green-400 px-3 select-none">+</span>
						<pre class="flex-1 text-green-300 py-0.5">{change.line}</pre>
					</div>
				{:else if change.type === 'removed'}
					<div class="flex bg-red-500/10 hover:bg-red-500/20 transition-colors">
						<span class="text-red-400 px-3 select-none">-</span>
						<pre class="flex-1 text-red-300 py-0.5">{change.line}</pre>
					</div>
				{:else}
					<div class="flex text-slate-400">
						<span class="px-3 select-none"> </span>
						<pre class="flex-1 py-0.5">{change.line}</pre>
					</div>
				{/if}
			{/each}
		{/each}
	</div>
</div>
