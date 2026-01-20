<script lang="ts">
	import { workspacePath, showCheckpointsPanel } from '$lib/stores';
	import { History, Undo2, Clock, Trash2, XCircle, FileCode } from 'lucide-svelte';
	import { fly } from 'svelte/transition';
	import { onMount } from 'svelte';

	export let visible = false;
	
	let checkpoints: any[] = [];
	let isLoading = false;

	async function loadCheckpoints() {
		if (!$workspacePath) return;
		isLoading = true;
		try {
			const response = await fetch(`${window.location.origin}/api/v1/mcp/call`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					name: 'checkpoint_list',
					args: { limit: 20 },
					context: { workspace_path: $workspacePath }
				})
			});
			const data = await response.json();
			if (data.success) {
				checkpoints = data.checkpoints;
			}
		} catch (error) {
			console.error('Failed to load checkpoints:', error);
		} finally {
			isLoading = false;
		}
	}

	async function restoreCheckpoint(id: string) {
		if (!confirm('Are you sure you want to restore this checkpoint? Current changes to these files will be overwritten.')) return;
		
		try {
			const response = await fetch(`${window.location.origin}/api/v1/mcp/call`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					name: 'checkpoint_restore',
					args: { checkpoint_id: id },
					context: { workspace_path: $workspacePath }
				})
			});
			const data = await response.json();
			if (data.success) {
				alert(`Successfully restored ${data.restored_files.join(', ')}`);
				// Trigger file tree refresh
				window.dispatchEvent(new CustomEvent('refresh-file-tree'));
			} else {
				alert(`Error: ${data.error}`);
			}
		} catch (error) {
			console.error('Failed to restore checkpoint:', error);
		}
	}

	$: if (visible) loadCheckpoints();
</script>

{#if visible}
	<aside 
		class="fixed right-0 top-16 bottom-0 w-80 bg-slate-900 border-l border-slate-800 shadow-2xl z-40 flex flex-col"
		transition:fly={{ x: 320, duration: 300 }}
	>
		<div class="p-4 border-b border-slate-800 flex items-center justify-between bg-slate-900/50">
			<div class="flex items-center gap-2">
				<History class="w-5 h-5 text-amber-500" />
				<h2 class="font-bold text-slate-200">File Checkpoints</h2>
			</div>
			<button on:click={() => visible = false} class="text-slate-500 hover:text-slate-300">
				<XCircle class="w-5 h-5" />
			</button>
		</div>

		<div class="flex-1 overflow-y-auto p-4 space-y-4">
			{#if isLoading}
				<div class="flex flex-col items-center justify-center py-12 text-slate-500">
					<div class="w-8 h-8 border-2 border-amber-500 border-t-transparent rounded-full animate-spin mb-4"></div>
					<p class="text-sm">Loading history...</p>
				</div>
			{:else if checkpoints.length === 0}
				<div class="flex flex-col items-center justify-center py-12 text-slate-500 text-center">
					<History class="w-12 h-12 mb-4 opacity-20" />
					<p class="text-sm">No checkpoints yet</p>
					<p class="text-xs mt-1">Checkpoints are created automatically before the agent modifies files.</p>
				</div>
			{:else}
				{#each checkpoints as cp (cp.id)}
					<div class="bg-slate-800/50 border border-slate-700/50 rounded-lg p-3 space-y-3 transition-all hover:bg-slate-800 group">
						<div class="flex items-start justify-between">
							<div class="flex items-center gap-2 text-amber-400">
								<Clock class="w-4 h-4" />
								<span class="text-[10px] font-mono">{new Date(cp.created_at).toLocaleString()}</span>
							</div>
							<button 
								on:click={() => restoreCheckpoint(cp.id)}
								class="opacity-0 group-hover:opacity-100 flex items-center gap-1 px-2 py-1 bg-amber-500/20 hover:bg-amber-500/40 text-amber-400 rounded text-[10px] font-bold transition-all"
								title="Restore this checkpoint"
							>
								<Undo2 class="w-3 h-3" /> RESTORE
							</button>
						</div>
						
						{#if cp.description}
							<p class="text-xs text-slate-300 italic font-medium">{cp.description}</p>
						{/if}

						<div class="space-y-1">
							<p class="text-[10px] uppercase text-slate-500 font-bold tracking-wider mb-1">Affected Files:</p>
							{#each cp.files.split(',') as file}
								<div class="flex items-center gap-2 text-[11px] text-slate-400 bg-slate-900/50 px-2 py-1 rounded">
									<FileCode class="w-3 h-3 text-slate-500" />
									<span class="truncate">{file}</span>
								</div>
							{/each}
						</div>
					</div>
				{/each}
			{/if}
		</div>

		<div class="p-4 bg-slate-950/50 border-t border-slate-800">
			<button 
				on:click={loadCheckpoints}
				class="w-full py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-bold rounded-lg transition-all border border-slate-700"
			>
				Refresh History
			</button>
		</div>
	</aside>
{/if}
