<script lang="ts">
	import { X, MessageSquare, Trash2 } from 'lucide-svelte';
	import { showMemoriesPanel, memories, workspacePath } from '$lib/stores';
	import { loadMemories as loadMemoriesAPI, deleteMemory as deleteMemoryAPI } from '$lib/api/memories';
	import { onMount } from 'svelte';

	let memorySearchQuery = '';

	onMount(async () => {
		await loadMemories();
	});

	async function loadMemories() {
		try {
			const results = await loadMemoriesAPI($workspacePath, memorySearchQuery);
			$memories = results;
		} catch (error) {
			console.error('Error loading memories:', error);
		}
	}

	async function handleDeleteMemory(memoryId: number) {
		if (!confirm('Delete this memory?')) return;
		try {
			await deleteMemoryAPI(memoryId);
			await loadMemories();
		} catch (error) {
			console.error('Error deleting memory:', error);
		}
	}

	function close() {
		$showMemoriesPanel = false;
	}
</script>

<!-- Memory Bank Panel -->
{#if $showMemoriesPanel}
	<div class="absolute right-6 top-20 w-[450px] bg-slate-900 border border-slate-700/50 rounded-xl shadow-2xl z-50 p-6 animate-in slide-in-from-right backdrop-blur-xl max-h-[80vh] overflow-y-auto">
		<div class="flex items-center justify-between mb-6">
			<div class="flex items-center gap-3">
				<div class="w-10 h-10 rounded-lg bg-gradient-to-br from-blue-500 to-cyan-600 flex items-center justify-center">
					<MessageSquare class="w-5 h-5 text-white" />
				</div>
				<h3 class="text-base font-bold text-white">Memory Bank</h3>
			</div>
			<button on:click={close} class="text-slate-400 hover:text-white">
				<X class="w-5 h-5" />
			</button>
		</div>
		
		<p class="text-xs text-slate-400 mb-4">
			Memories are automatically extracted when you say "remember that..." or when the model decides to remember important information. These are injected into future conversations.
		</p>

		<!-- Search -->
		<div class="mb-4">
			<input 
				type="text" 
				bind:value={memorySearchQuery}
				on:input={loadMemories}
				placeholder="Search memories..."
				class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 outline-none focus:border-amber-500"
			/>
		</div>

		<!-- Memories List -->
		<div class="space-y-2">
			{#if $memories.length === 0}
				<div class="text-xs text-slate-500 italic text-center py-8">
					No memories yet. Say "remember that..." in a conversation to create one!
				</div>
			{:else}
				{#each $memories as memory}
					<div class="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
						<div class="flex items-start justify-between mb-2">
							<div class="flex items-center gap-2">
								<span class="text-[10px] px-2 py-0.5 rounded {memory.source === 'user' ? 'bg-blue-500/20 text-blue-400' : 'bg-purple-500/20 text-purple-400'} uppercase font-bold">
									{memory.source}
								</span>
								{#if memory.tags}
									<span class="text-[10px] text-slate-500">{memory.tags}</span>
								{/if}
							</div>
							<button on:click={() => handleDeleteMemory(memory.id)} class="p-1 hover:bg-red-500/20 rounded">
								<Trash2 class="w-3 h-3 text-red-400" />
							</button>
						</div>
						<p class="text-xs text-slate-300 leading-relaxed">{memory.content}</p>
						<div class="flex items-center gap-3 mt-2 text-[10px] text-slate-500">
							<span>Accessed {memory.access_count} times</span>
							<span>•</span>
							<span>{new Date(memory.created_at).toLocaleDateString()}</span>
						</div>
					</div>
				{/each}
			{/if}
		</div>
	</div>
{/if}
