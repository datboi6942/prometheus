<script lang="ts">
	import { 
		File, Search, History, GitBranch, MessageSquare, 
		Terminal as TerminalIcon, BookOpen, Code2, Settings, Brain, ListTodo, Undo2
	} from 'lucide-svelte';
	import { 
		showExplorer, 
		activeExplorerTab,
		activeView,
		showTerminalPanel,
		showRulesPanel,
		showMemoriesPanel,
		showMCPServersPanel,
		showTodoPanel,
		showCheckpointsPanel,
		showSettings,
		showAgentPanel,
		isLoading,
		activeThinking
	} from '$lib/stores';
</script>

<!-- Activity Bar (left-most vertical icon bar) -->
<aside class="w-14 bg-slate-950 border-r border-slate-800/50 flex flex-col items-center py-4">
	<div class="w-10 h-10 rounded-lg bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center mb-6">
		<svg class="w-6 h-6 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
			<path d="M13 2L3 14h8l-2 8 10-12h-8l2-8z" />
		</svg>
	</div>

	<!-- File Explorer -->
	<button 
		on:click={() => { $showExplorer = !$showExplorer; $activeExplorerTab = 'files'; }}
		class="activity-btn {$showExplorer && $activeExplorerTab === 'files' ? 'active' : ''}"
		title="Explorer">
		<File class="w-5 h-5" />
	</button>
	
	<!-- Search -->
	<button 
		on:click={() => { $showExplorer = true; $activeExplorerTab = 'search'; }}
		class="activity-btn {$showExplorer && $activeExplorerTab === 'search' ? 'active' : ''}"
		title="Search">
		<Search class="w-5 h-5" />
	</button>
	
	<!-- History -->
	<button 
		on:click={() => { $showExplorer = true; $activeExplorerTab = 'history'; }}
		class="activity-btn {$showExplorer && $activeExplorerTab === 'history' ? 'active' : ''}"
		title="Chat History">
		<History class="w-5 h-5" />
	</button>
	
	<!-- Git -->
	<button 
		on:click={() => { $showExplorer = true; $activeExplorerTab = 'git'; }}
		class="activity-btn {$showExplorer && $activeExplorerTab === 'git' ? 'active' : ''}"
		title="Source Control">
		<GitBranch class="w-5 h-5" />
	</button>

	<div class="w-8 h-px bg-slate-700 my-2"></div>

	<!-- Chat View -->
	<button 
		on:click={() => $activeView = 'chat'}
		class="activity-btn {$activeView === 'chat' ? 'active' : ''}"
		title="AI Chat">
		<MessageSquare class="w-5 h-5" />
	</button>
	
	<!-- Terminal -->
	<button 
		on:click={() => $showTerminalPanel = !$showTerminalPanel}
		class="activity-btn {$showTerminalPanel ? 'active' : ''}"
		title="Terminal">
		<TerminalIcon class="w-5 h-5" />
	</button>

	<!-- Agent Activity Panel -->
	<button 
		on:click={() => $showAgentPanel = !$showAgentPanel}
		class="activity-btn {$showAgentPanel ? 'active' : ''} relative"
		title="Agent Activity">
		<Brain class="w-5 h-5" />
		{#if $isLoading || $activeThinking?.isActive}
			<span class="absolute top-1 right-1 w-2 h-2 bg-purple-500 rounded-full animate-ping"></span>
			<span class="absolute top-1 right-1 w-2 h-2 bg-purple-500 rounded-full"></span>
		{/if}
	</button>

	<div class="flex-1"></div>

	<!-- Rules -->
	<button 
		on:click={() => $showRulesPanel = !$showRulesPanel}
		class="activity-btn {$showRulesPanel ? 'active' : ''}"
		title="Rules">
		<BookOpen class="w-5 h-5" />
	</button>
	
	<!-- Memories -->
	<button 
		on:click={() => $showMemoriesPanel = !$showMemoriesPanel}
		class="activity-btn {$showMemoriesPanel ? 'active' : ''}"
		title="Memory Bank">
		<MessageSquare class="w-5 h-5" />
	</button>
	
	<!-- MCP Servers -->
	<button 
		on:click={() => $showMCPServersPanel = !$showMCPServersPanel}
		class="activity-btn {$showMCPServersPanel ? 'active' : ''}"
		title="MCP Servers">
		<Code2 class="w-5 h-5" />
	</button>

	<!-- Task List -->
	<button 
		on:click={() => $showTodoPanel = !$showTodoPanel}
		class="activity-btn {$showTodoPanel ? 'active' : ''}"
		title="Agent Task List">
		<ListTodo class="w-5 h-5" />
	</button>

	<!-- Checkpoints -->
	<button 
		on:click={() => $showCheckpointsPanel = !$showCheckpointsPanel}
		class="activity-btn {$showCheckpointsPanel ? 'active' : ''}"
		title="File Checkpoints">
		<Undo2 class="w-5 h-5" />
	</button>
	
	<!-- Settings -->
	<button 
		on:click={() => $showSettings = !$showSettings}
		class="activity-btn {$showSettings ? 'active' : ''}"
		title="Settings">
		<Settings class="w-5 h-5" />
	</button>
</aside>

<style>
	.activity-btn {
		@apply w-12 h-10 flex items-center justify-center rounded-lg transition-all text-slate-400 hover:text-white hover:bg-slate-800/50 mb-1;
	}
	
	.activity-btn.active {
		@apply text-white bg-slate-800/80 border-l-2 border-amber-500;
	}
</style>
