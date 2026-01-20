<script lang="ts">
	import { agentTodos, showRulesPanel } from '$lib/stores';
	import { CheckCircle2, Circle, Clock, XCircle, ListTodo } from 'lucide-svelte';
	import { fly } from 'svelte/transition';

	// The panel visibility is controlled by a shared store
	// For simplicity, we'll reuse showRulesPanel or create a new one
	// In +page.svelte we'll add a way to toggle it
	export let visible = false;
</script>

{#if visible}
	<aside 
		class="fixed right-0 top-16 bottom-0 w-80 bg-slate-900 border-l border-slate-800 shadow-2xl z-40 flex flex-col"
		transition:fly={{ x: 320, duration: 300 }}
	>
		<div class="p-4 border-b border-slate-800 flex items-center justify-between bg-slate-900/50">
			<div class="flex items-center gap-2">
				<ListTodo class="w-5 h-5 text-amber-500" />
				<h2 class="font-bold text-slate-200">Agent Task List</h2>
			</div>
			<button on:click={() => visible = false} class="text-slate-500 hover:text-slate-300">
				<XCircle class="w-5 h-5" />
			</button>
		</div>

		<div class="flex-1 overflow-y-auto p-4 space-y-3">
			{#if $agentTodos.length === 0}
				<div class="flex flex-col items-center justify-center py-12 text-slate-500 text-center">
					<ListTodo class="w-12 h-12 mb-4 opacity-20" />
					<p class="text-sm">No active tasks</p>
					<p class="text-xs mt-1">The agent will add tasks here when working on complex requests.</p>
				</div>
			{:else}
				{#each $agentTodos as todo (todo.id)}
					<div class="bg-slate-800/50 border border-slate-700/50 rounded-lg p-3 flex gap-3 transition-all hover:bg-slate-800">
						<div class="mt-0.5">
							{#if todo.status === 'completed'}
								<CheckCircle2 class="w-5 h-5 text-emerald-500" />
							{:else if todo.status === 'in_progress'}
								<Clock class="w-5 h-5 text-amber-500 animate-pulse" />
							{:else if todo.status === 'cancelled'}
								<XCircle class="w-5 h-5 text-slate-500" />
							{:else}
								<Circle class="w-5 h-5 text-slate-600" />
							{/if}
						</div>
						<div class="flex-1">
							<p class="text-sm font-medium {todo.status === 'completed' ? 'text-slate-400 line-through' : 'text-slate-200'}">
								{todo.content}
							</p>
							<div class="flex items-center justify-between mt-2">
								<span class="text-[10px] uppercase tracking-wider font-bold {
									todo.status === 'completed' ? 'text-emerald-500/70' : 
									todo.status === 'in_progress' ? 'text-amber-500/70' : 
									'text-slate-500'
								}">
									{todo.status.replace('_', ' ')}
								</span>
								<span class="text-[10px] text-slate-600 font-mono">ID: {todo.id}</span>
							</div>
						</div>
					</div>
				{/each}
			{/if}
		</div>

		<div class="p-4 bg-slate-950/50 border-t border-slate-800">
			<div class="flex items-center justify-between text-xs text-slate-500">
				<span>Total: {$agentTodos.length}</span>
				<span>Done: {$agentTodos.filter(t => t.status === 'completed').length}</span>
			</div>
		</div>
	</aside>
{/if}
