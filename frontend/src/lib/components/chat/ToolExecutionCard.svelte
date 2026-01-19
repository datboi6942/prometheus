<script lang="ts">
	import { 
		FileText, FileCode, FolderOpen, Terminal, Search, Play, 
		Check, X, AlertCircle, Loader2, Eye, Edit3, Plus, Trash2,
		ChevronDown, ChevronRight
	} from 'lucide-svelte';
	import { slide } from 'svelte/transition';

	export let execution: {
		type: string;
		path?: string;
		command?: string;
		stdout?: string;
		stderr?: string;
		status: string;
		timestamp: Date;
		return_code?: number;
		hint?: string;
		diff?: any;
		args?: Record<string, any>;
	};
	export let isActive: boolean = false;

	// Normalize status for display
	$: normalizedStatus = execution.status === 'success' ? 'success' : execution.status === 'error' ? 'error' : 'pending';

	let isExpanded = false;

	// Get icon and color based on tool type
	function getToolInfo(type: string): { icon: any; color: string; label: string; bgColor: string } {
		switch (type) {
			case 'filesystem_read':
				return { icon: Eye, color: 'text-blue-400', label: 'Reading File', bgColor: 'from-blue-500 to-cyan-600' };
			case 'filesystem_write':
				return { icon: FileCode, color: 'text-green-400', label: 'Writing File', bgColor: 'from-green-500 to-emerald-600' };
			case 'filesystem_replace_lines':
				return { icon: Edit3, color: 'text-purple-400', label: 'Editing Lines', bgColor: 'from-purple-500 to-fuchsia-600' };
			case 'filesystem_search_replace':
				return { icon: Search, color: 'text-amber-400', label: 'Search & Replace', bgColor: 'from-amber-500 to-orange-600' };
			case 'filesystem_insert':
				return { icon: Plus, color: 'text-teal-400', label: 'Inserting Code', bgColor: 'from-teal-500 to-cyan-600' };
			case 'filesystem_list':
				return { icon: FolderOpen, color: 'text-yellow-400', label: 'Listing Directory', bgColor: 'from-yellow-500 to-amber-600' };
			case 'filesystem_delete':
				return { icon: Trash2, color: 'text-red-400', label: 'Deleting File', bgColor: 'from-red-500 to-rose-600' };
			case 'grep':
				return { icon: Search, color: 'text-indigo-400', label: 'Searching Code', bgColor: 'from-indigo-500 to-purple-600' };
			case 'shell_execute':
				return { icon: Terminal, color: 'text-slate-400', label: 'Running Command', bgColor: 'from-slate-500 to-zinc-600' };
			case 'run_python':
				return { icon: Play, color: 'text-yellow-400', label: 'Running Python', bgColor: 'from-yellow-500 to-amber-600' };
			case 'run_tests':
				return { icon: Play, color: 'text-green-400', label: 'Running Tests', bgColor: 'from-green-500 to-emerald-600' };
			default:
				return { icon: Terminal, color: 'text-slate-400', label: type.replace(/_/g, ' '), bgColor: 'from-slate-500 to-zinc-600' };
		}
	}

	$: toolInfo = getToolInfo(execution.type);
	$: Icon = toolInfo.icon;

	// Format path for display
	function formatPath(path: string | undefined): string {
		if (!path) return '';
		// Show last 2 parts of path
		const parts = path.split('/');
		if (parts.length <= 2) return path;
		return '.../' + parts.slice(-2).join('/');
	}

	// Get action description
	function getActionDescription(): string {
		const path = execution.path ? formatPath(execution.path) : '';
		
		switch (execution.type) {
			case 'filesystem_read':
				return path ? `Reading ${path}` : 'Reading file';
			case 'filesystem_write':
				return path ? `Writing to ${path}` : 'Writing file';
			case 'filesystem_replace_lines':
				const startLine = execution.args?.start_line;
				const endLine = execution.args?.end_line;
				if (startLine && endLine && path) {
					return `Editing ${path} (lines ${startLine}-${endLine})`;
				}
				return path ? `Editing ${path}` : 'Editing file';
			case 'filesystem_search_replace':
				return path ? `Replacing in ${path}` : 'Search and replace';
			case 'filesystem_insert':
				const line = execution.args?.line_number;
				if (line && path) {
					return `Inserting at ${path}:${line}`;
				}
				return path ? `Inserting in ${path}` : 'Inserting code';
			case 'filesystem_list':
				return path ? `Listing ${path}` : 'Listing directory';
			case 'filesystem_delete':
				return path ? `Deleting ${path}` : 'Deleting file';
			case 'grep':
				const pattern = execution.args?.pattern;
				return pattern ? `Searching for "${pattern}"` : 'Searching code';
			case 'shell_execute':
				return execution.command ? `$ ${execution.command.substring(0, 50)}${execution.command.length > 50 ? '...' : ''}` : 'Running command';
			case 'run_python':
				return path ? `Running ${path}` : 'Running Python';
			case 'run_tests':
				return 'Running tests';
			default:
				return execution.type.replace(/_/g, ' ');
		}
	}

	$: actionDescription = getActionDescription();
</script>

<div 
	class="rounded-lg border overflow-hidden transition-all duration-300 {
		isActive 
			? 'border-blue-500/50 bg-slate-800/70 ring-2 ring-blue-500/30 animate-pulse-subtle' 
			: normalizedStatus === 'success' 
				? 'border-green-500/30 bg-slate-800/50' 
				: normalizedStatus === 'error'
					? 'border-red-500/30 bg-slate-800/50'
					: 'border-slate-700/50 bg-slate-800/50'
	}"
>
	<!-- Main Content -->
	<button
		on:click={() => isExpanded = !isExpanded}
		class="w-full px-4 py-3 flex items-center gap-3 hover:bg-slate-700/30 transition-colors"
	>
		<!-- Icon with gradient background -->
		<div class="w-8 h-8 rounded-lg bg-gradient-to-br {toolInfo.bgColor} flex items-center justify-center flex-shrink-0 shadow-lg {isActive ? 'animate-pulse' : ''}">
			{#if isActive}
				<Loader2 class="w-4 h-4 text-white animate-spin" />
			{:else if normalizedStatus === 'success'}
				<Check class="w-4 h-4 text-white" />
			{:else if normalizedStatus === 'error'}
				<X class="w-4 h-4 text-white" />
			{:else}
				<svelte:component this={Icon} class="w-4 h-4 text-white" />
			{/if}
		</div>

		<!-- Tool Info -->
		<div class="flex-1 text-left min-w-0">
			<div class="flex items-center gap-2">
				<span class="text-xs font-semibold {toolInfo.color} uppercase tracking-wide">
					{toolInfo.label}
				</span>
				{#if isActive}
					<span class="text-[10px] px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-300 flex items-center gap-1">
						<span class="w-1.5 h-1.5 rounded-full bg-blue-400 animate-ping"></span>
						In Progress
					</span>
				{:else if normalizedStatus === 'success'}
					<span class="text-[10px] px-2 py-0.5 rounded-full bg-green-500/20 text-green-300">
						✓ Done
					</span>
				{:else if normalizedStatus === 'error'}
					<span class="text-[10px] px-2 py-0.5 rounded-full bg-red-500/20 text-red-300">
						✗ Failed
					</span>
				{/if}
			</div>
			<div class="text-sm text-slate-300 truncate mt-0.5">
				{actionDescription}
			</div>
		</div>

		<!-- Expand Arrow -->
		<div class="flex items-center gap-2 flex-shrink-0">
			<span class="text-[10px] text-slate-500">
				{execution.timestamp.toLocaleTimeString()}
			</span>
			{#if isExpanded}
				<ChevronDown class="w-4 h-4 text-slate-400" />
			{:else}
				<ChevronRight class="w-4 h-4 text-slate-400" />
			{/if}
		</div>
	</button>

	<!-- Expanded Details -->
	{#if isExpanded}
		<div transition:slide={{ duration: 200 }} class="px-4 pb-3 border-t border-slate-700/50">
			{#if execution.path}
				<div class="mt-2 flex items-center gap-2 text-xs">
					<FileText class="w-3 h-3 text-slate-500" />
					<span class="text-slate-400">Path:</span>
					<code class="text-slate-300 bg-slate-900 px-2 py-0.5 rounded font-mono">{execution.path}</code>
				</div>
			{/if}

			{#if execution.command}
				<div class="mt-2">
					<div class="text-xs text-slate-400 mb-1">Command:</div>
					<code class="block text-xs text-slate-300 bg-slate-900 px-3 py-2 rounded font-mono overflow-x-auto">
						{execution.command}
					</code>
				</div>
			{/if}

			{#if execution.stdout}
				<div class="mt-2">
					<div class="text-xs text-slate-400 mb-1">Output:</div>
					<pre class="text-xs text-green-300 bg-slate-900 px-3 py-2 rounded font-mono overflow-x-auto max-h-32">{execution.stdout}</pre>
				</div>
			{/if}

			{#if execution.stderr}
				<div class="mt-2">
					<div class="text-xs text-slate-400 mb-1">Errors:</div>
					<pre class="text-xs text-red-300 bg-slate-900 px-3 py-2 rounded font-mono overflow-x-auto max-h-32">{execution.stderr}</pre>
				</div>
			{/if}

			{#if execution.hint}
				<div class="mt-2 flex items-start gap-2 text-xs">
					<AlertCircle class="w-3 h-3 text-amber-400 flex-shrink-0 mt-0.5" />
					<span class="text-amber-300">{execution.hint}</span>
				</div>
			{/if}

			{#if execution.args && Object.keys(execution.args).length > 0}
				<div class="mt-2">
					<div class="text-xs text-slate-400 mb-1">Arguments:</div>
					<pre class="text-xs text-slate-400 bg-slate-900 px-3 py-2 rounded font-mono overflow-x-auto max-h-24">{JSON.stringify(execution.args, null, 2)}</pre>
				</div>
			{/if}
		</div>
	{/if}
</div>
