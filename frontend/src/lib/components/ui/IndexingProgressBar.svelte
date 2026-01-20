<script lang="ts">
	import { indexingStatus, workspacePath } from '$lib/stores';
	import { Search, CheckCircle2, AlertCircle, Loader2 } from 'lucide-svelte';
	import { onMount, onDestroy } from 'svelte';
	import { browser } from '$app/environment';

	let eventSource: EventSource | null = null;

	let lastWorkspacePath = '';
	let isIndexingStarted = false;
	
	async function startIndexing() {
		if (!browser || !$workspacePath || isIndexingStarted) {
			console.log('Skipping startIndexing: ', { browser, workspacePath: !!$workspacePath, isIndexingStarted });
			return;
		}
		
		// If status is not idle/error and path hasn't changed, we're already doing something
		if ($indexingStatus.status !== 'idle' && $indexingStatus.status !== 'error' && $workspacePath === lastWorkspacePath) {
			console.log('Skipping startIndexing (already active): ', { status: $indexingStatus.status, path: $workspacePath });
			return;
		}
		
		isIndexingStarted = true;
		lastWorkspacePath = $workspacePath;
		// Set status immediately to prevent multiple triggers
		$indexingStatus = { ...$indexingStatus, status: 'starting', error: undefined };

		// Close any existing EventSource
		if (eventSource) {
			eventSource.close();
			eventSource = null;
		}

		// Use the same host as the frontend but port 8000 for the backend
		const backendUrl = `${window.location.protocol}//${window.location.hostname}:8000/api/v1`;
		const url = new URL(`${backendUrl}/index/stream`);
		url.searchParams.append('workspace_path', $workspacePath);
		
		console.log('Connecting to indexing stream:', url.toString());
		const currentEventSource = new EventSource(url.toString());
		eventSource = currentEventSource;
		
		currentEventSource.onmessage = (event) => {
			// Ensure we only process messages from the latest EventSource
			if (eventSource !== currentEventSource) {
				currentEventSource.close();
				return;
			}

			try {
				const data = JSON.parse(event.data);
				$indexingStatus = { ...$indexingStatus, ...data };
				
		if (data.status === 'completed' || data.status === 'error') {
			isIndexingStarted = false;
			currentEventSource.close();
			if (eventSource === currentEventSource) eventSource = null;
			
			// DO NOT reset to idle automatically, as it triggers a loop with the reactive statement
			// The user can manually retry if there's an error, or it will re-index on workspace change
		}
			} catch (e) {
				console.error('Error parsing indexing status:', e);
			}
		};

		currentEventSource.onerror = () => {
			if (eventSource !== currentEventSource) return;
			
			console.error('Indexing EventSource error');
			isIndexingStarted = false;
			currentEventSource.close();
			if (eventSource === currentEventSource) eventSource = null;
			$indexingStatus = { ...$indexingStatus, status: 'error', error: 'Connection lost' };
		};
	}

	onDestroy(() => {
		if (eventSource) eventSource.close();
	});

	// Automatically start indexing when workspace changes or we're explicitly idle
	$: if (browser && $workspacePath) {
		// Only trigger if the path changed or if we're in idle status
		if ($workspacePath !== lastWorkspacePath || $indexingStatus.status === 'idle') {
			startIndexing();
		}
	}
</script>

{#if $indexingStatus.status !== 'idle'}
	<div class="fixed bottom-4 left-20 z-50 bg-slate-900 border border-slate-800 rounded-lg shadow-2xl p-3 w-72 animate-fadeIn">
		<div class="flex items-center justify-between mb-2">
			<div class="flex items-center gap-2">
				{#if $indexingStatus.status === 'indexing' || $indexingStatus.status === 'starting'}
					<Loader2 class="w-4 h-4 text-amber-500 animate-spin" />
					<span class="text-xs font-bold text-slate-200 uppercase tracking-wider">Indexing Codebase</span>
				{:else if $indexingStatus.status === 'completed'}
					<CheckCircle2 class="w-4 h-4 text-emerald-500" />
					<span class="text-xs font-bold text-emerald-500 uppercase tracking-wider">Indexed</span>
				{:else}
					<AlertCircle class="w-4 h-4 text-red-500" />
					<span class="text-xs font-bold text-red-500 uppercase tracking-wider">Indexing Error</span>
				{/if}
			</div>
			<span class="text-[10px] font-mono text-slate-500">
				{$indexingStatus.current} / {$indexingStatus.total}
			</span>
		</div>

		<div class="h-1.5 bg-slate-800 rounded-full overflow-hidden mb-2">
			<div 
				class="h-full transition-all duration-300 {$indexingStatus.status === 'error' ? 'bg-red-500' : 'bg-amber-500'}"
				style="width: {$indexingStatus.percent}%"
			></div>
		</div>

		{#if $indexingStatus.file}
			<p class="text-[10px] text-slate-500 truncate font-mono italic">
				{$indexingStatus.file}
			</p>
		{:else if $indexingStatus.status === 'completed'}
			<p class="text-[10px] text-slate-400">
				Semantic search is now ready.
			</p>
		{:else}
			<div class="flex items-center justify-between">
				<p class="text-[10px] text-red-400 truncate">
					{$indexingStatus.error || 'Unknown error'}
				</p>
				<button 
					on:click={() => {
						$indexingStatus = { status: 'idle', total: 0, current: 0, percent: 0 };
						startIndexing();
					}}
					class="text-[10px] bg-slate-800 hover:bg-slate-700 text-slate-300 px-2 py-0.5 rounded ml-2"
				>
					Retry
				</button>
			</div>
		{/if}
	</div>
{/if}
