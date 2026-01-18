<script lang="ts">
	import { X, BookOpen, Trash2 } from 'lucide-svelte';
	import { showRulesPanel, globalRules, projectRules, workspacePath } from '$lib/stores';
	import { createRule, deleteRule as deleteRuleAPI, loadGlobalRules, loadProjectRules } from '$lib/api/rules';
	import { onMount } from 'svelte';

	let newRuleName = '';
	let newRuleContent = '';
	let isGlobalRule = true;

	onMount(async () => {
		await loadRules();
	});

	async function loadRules() {
		try {
			const [globals, projects] = await Promise.all([
				loadGlobalRules(),
				loadProjectRules($workspacePath)
			]);
			$globalRules = globals;
			$projectRules = projects;
		} catch (error) {
			console.error('Error loading rules:', error);
		}
	}

	async function handleCreateRule() {
		if (!newRuleName.trim() || !newRuleContent.trim()) return;
		try {
			await createRule(newRuleName, newRuleContent, isGlobalRule, $workspacePath);
			newRuleName = '';
			newRuleContent = '';
			await loadRules();
		} catch (error) {
			console.error('Error creating rule:', error);
		}
	}

	async function handleDeleteRule(ruleId: number, isGlobal: boolean) {
		if (!confirm('Delete this rule?')) return;
		try {
			await deleteRuleAPI(ruleId, isGlobal);
			await loadRules();
		} catch (error) {
			console.error('Error deleting rule:', error);
		}
	}

	function close() {
		$showRulesPanel = false;
	}
</script>

<!-- Rules Panel -->
{#if $showRulesPanel}
	<div class="absolute right-6 top-20 w-[450px] bg-slate-900 border border-slate-700/50 rounded-xl shadow-2xl z-50 p-6 animate-in slide-in-from-right backdrop-blur-xl max-h-[80vh] overflow-y-auto">
		<div class="flex items-center justify-between mb-6">
			<div class="flex items-center gap-3">
				<div class="w-10 h-10 rounded-lg bg-gradient-to-br from-purple-500 to-pink-600 flex items-center justify-center">
					<BookOpen class="w-5 h-5 text-white" />
				</div>
				<h3 class="text-base font-bold text-white">Agent Rules & Guidelines</h3>
			</div>
			<button on:click={close} class="text-slate-400 hover:text-white">
				<X class="w-5 h-5" />
			</button>
		</div>
		
		<p class="text-xs text-slate-400 mb-4">
			Define custom rules to guide the AI agent's behavior. Global rules apply to all projects, while project rules are specific to this workspace.
		</p>

		<!-- Add New Rule Form -->
		<div class="bg-slate-950 rounded-lg p-4 border border-slate-700 mb-4">
			<h4 class="text-xs font-bold text-slate-400 uppercase mb-3">Add New Rule</h4>
			<input 
				type="text" 
				bind:value={newRuleName}
				placeholder="Rule name (e.g., 'Use TypeScript')"
				class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 mb-2 outline-none focus:border-amber-500"
			/>
			<textarea 
				bind:value={newRuleContent}
				placeholder="Rule description..."
				rows="3"
				class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 mb-2 outline-none focus:border-amber-500 resize-none"
			></textarea>
			<div class="flex items-center gap-3 mb-3">
				<button 
					on:click={() => isGlobalRule = true}
					class="flex-1 py-2 rounded text-xs font-bold transition-all {isGlobalRule ? 'bg-amber-500 text-white' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'}"
				>
					Global Rule
				</button>
				<button 
					on:click={() => isGlobalRule = false}
					class="flex-1 py-2 rounded text-xs font-bold transition-all {!isGlobalRule ? 'bg-amber-500 text-white' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'}"
				>
					Project Rule
				</button>
			</div>
			<button 
				on:click={handleCreateRule}
				class="w-full bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-600 hover:to-orange-700 text-white text-sm font-bold py-2 rounded transition-all"
			>
				Add Rule
			</button>
		</div>

		<!-- Global Rules -->
		<div class="mb-4">
			<h4 class="text-xs font-bold text-slate-400 uppercase mb-2">Global Rules (Apply to all projects)</h4>
			{#if $globalRules.length === 0}
				<div class="text-xs text-slate-500 italic">No global rules defined</div>
			{:else}
				<div class="space-y-2">
					{#each $globalRules as rule}
						<div class="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
							<div class="flex items-center justify-between mb-1">
								<span class="text-xs font-bold text-slate-300">{rule.name}</span>
								<button on:click={() => handleDeleteRule(rule.id, true)} class="p-1 hover:bg-red-500/20 rounded">
									<Trash2 class="w-3 h-3 text-red-400" />
								</button>
							</div>
							<p class="text-[10px] text-slate-400 line-clamp-2">{rule.content}</p>
						</div>
					{/each}
				</div>
			{/if}
		</div>

		<!-- Project Rules -->
		<div>
			<h4 class="text-xs font-bold text-slate-400 uppercase mb-2">Project Rules (This workspace only)</h4>
			{#if $projectRules.length === 0}
				<div class="text-xs text-slate-500 italic">No project rules for this workspace</div>
			{:else}
				<div class="space-y-2">
					{#each $projectRules as rule}
						<div class="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
							<div class="flex items-center justify-between mb-1">
								<span class="text-xs font-bold text-slate-300">{rule.name}</span>
								<button on:click={() => handleDeleteRule(rule.id, false)} class="p-1 hover:bg-red-500/20 rounded">
									<Trash2 class="w-3 h-3 text-red-400" />
								</button>
							</div>
							<p class="text-[10px] text-slate-400 line-clamp-2">{rule.content}</p>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	</div>
{/if}
