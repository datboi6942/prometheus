<script lang="ts">
	import { File } from 'lucide-svelte';
	
	export let path: string;
	export let displayContent: string;
	export let language: string;
	export let bytesWritten: number;
	export let isComplete: boolean;
	
	$: displayLines = displayContent.split('\n');
	$: totalLines = displayLines.length;
	$: visibleLines = displayLines.slice(-25);
	$: startLineNum = Math.max(1, totalLines - 24);
</script>

<div class="flex gap-3 animate-fadeIn">
	<div class="w-9 h-9 rounded-xl bg-gradient-to-br from-violet-500 via-purple-500 to-fuchsia-500 flex items-center justify-center flex-shrink-0 shadow-lg shadow-purple-500/40 animate-pulse">
		<File class="w-5 h-5 text-white" />
	</div>
	<div class="max-w-4xl flex-1 bg-[#0d1117] border border-purple-500/30 rounded-xl overflow-hidden shadow-2xl shadow-purple-500/10">
		<!-- macOS-style title bar -->
		<div class="bg-[#161b22] px-4 py-2.5 border-b border-purple-500/20 flex items-center justify-between">
			<div class="flex items-center gap-3">
				<div class="flex gap-2">
					<span class="w-3 h-3 rounded-full bg-[#ff5f56] shadow-inner"></span>
					<span class="w-3 h-3 rounded-full bg-[#ffbd2e] shadow-inner"></span>
					<span class="w-3 h-3 rounded-full bg-[#27ca40] shadow-inner"></span>
				</div>
				<div class="flex items-center gap-2 ml-3 pl-3 border-l border-slate-700">
					<File class="w-3.5 h-3.5 text-purple-400" />
					<span class="text-xs font-mono text-slate-200 font-medium tracking-tight">{path}</span>
				</div>
			</div>
			<div class="flex items-center gap-3">
				<span class="text-[10px] font-mono px-2 py-1 rounded-md bg-purple-500/10 text-purple-300 border border-purple-500/20">
					{language}
				</span>
				<div class="flex items-center gap-1.5 px-2 py-1 rounded-md bg-emerald-500/10 border border-emerald-500/20">
					<span class="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
					<span class="text-[10px] text-emerald-300 font-medium">Writing</span>
				</div>
			</div>
		</div>
		<!-- Code content with line numbers -->
		<div class="relative overflow-hidden">
			<div class="overflow-auto max-h-80 scrollbar-thin scrollbar-thumb-purple-500/30 scrollbar-track-transparent">
				<table class="w-full border-collapse">
					<tbody class="font-mono text-[13px] leading-6">
						{#each visibleLines as line, i}
							<tr class="hover:bg-purple-500/5 transition-colors">
								<td class="text-right pr-4 pl-4 text-slate-600 select-none w-12 border-r border-slate-800 bg-[#0d1117]">
									{startLineNum + i}
								</td>
								<td class="pl-4 pr-4 text-slate-200 whitespace-pre">
									{line}{#if i === visibleLines.length - 1}<span class="inline-block w-[2px] h-[18px] bg-purple-400 animate-cursor-blink ml-[1px] align-middle"></span>{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			<!-- Top gradient fade -->
			<div class="absolute top-0 left-0 right-0 h-6 bg-gradient-to-b from-[#0d1117] to-transparent pointer-events-none"></div>
		</div>
		<!-- Status bar -->
		<div class="bg-[#161b22] px-4 py-2 border-t border-slate-800 flex items-center justify-between">
			<div class="flex items-center gap-4">
				<span class="text-[11px] text-slate-500">
					<span class="text-purple-400 font-medium">{totalLines}</span> lines
				</span>
				<span class="text-[11px] text-slate-500">
					<span class="text-purple-400 font-medium">{displayContent.length}</span> chars
				</span>
			</div>
			<div class="flex items-center gap-2">
				<div class="h-1 w-24 bg-slate-800 rounded-full overflow-hidden">
					<div 
						class="h-full bg-gradient-to-r from-purple-500 to-fuchsia-500 transition-all duration-300 ease-out"
						style="width: {Math.min(100, (displayContent.length / Math.max(1, bytesWritten)) * 100)}%"
					></div>
				</div>
				<span class="text-[10px] text-slate-500">{Math.round(bytesWritten / 1024 * 10) / 10} KB</span>
			</div>
		</div>
	</div>
</div>
