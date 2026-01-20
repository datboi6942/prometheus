<script lang="ts">
	import { Sparkles, Brain } from 'lucide-svelte';
	import ThinkingBlock from './ThinkingBlock.svelte';
	
	export let message: {
		role: string;
		content: string;
		timestamp: Date;
		thinking?: {
			summary: string;
			fullContent: string;
		};
	};
	
	function formatMessageContent(content: string): string {
		if (!content) return '';

		// Step 1: Extract code blocks to preserve them
		const codeBlocks: Array<{ lang: string; code: string }> = [];
		let processedContent = content.replace(/```(\w+)?\n([\s\S]+?)```/g, (match, lang, code) => {
			const index = codeBlocks.length;
			codeBlocks.push({ lang: lang || 'text', code: code.trim() });
			return `__CODE_BLOCK_${index}__`;
		});

		// Step 2: Escape HTML to prevent XSS
		processedContent = processedContent
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;');

		// Step 3: Convert **bold** to <strong>
		processedContent = processedContent.replace(/\*\*(.+?)\*\*/g, '<strong class="text-amber-400">$1</strong>');

		// Step 4: Convert `inline code` to <code>
		processedContent = processedContent.replace(/`([^`]+)`/g, '<code class="bg-slate-900 px-1 py-0.5 rounded text-amber-300 font-mono text-xs">$1</code>');

		// Step 5: Convert newlines to <br>
		processedContent = processedContent.replace(/\n/g, '<br>');

		// Step 6: Restore code blocks with proper formatting
		processedContent = processedContent.replace(/__CODE_BLOCK_(\d+)__/g, (match, index) => {
			const block = codeBlocks[parseInt(index)];
			if (!block) return match;

			return `<div class="code-block my-3 rounded-lg overflow-hidden border border-slate-700">
				<div class="bg-slate-900/80 px-3 py-1.5 border-b border-slate-700 flex items-center justify-between">
					<span class="text-xs text-slate-400 font-mono">${block.lang}</span>
				</div>
				<pre class="bg-slate-950 p-4 overflow-x-auto"><code class="language-${block.lang} text-xs">${block.code}</code></pre>
			</div>`;
		});

		return processedContent;
	}
</script>

<div class="flex gap-3 {message.role === 'user' ? 'justify-end' : 'justify-start'}">
	{#if message.role !== 'user'}
		<div class="w-8 h-8 rounded-lg bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center flex-shrink-0">
			<Sparkles class="w-4 h-4 text-white" />
		</div>
	{/if}
	<div class="max-w-2xl space-y-2">
		<!-- Thinking Block (for assistant messages with reasoning) -->
		{#if message.thinking && message.role === 'assistant'}
			<ThinkingBlock
				summary={message.thinking.summary}
				fullContent={message.thinking.fullContent}
				isStreaming={false}
				isExpanded={false}
			/>
		{/if}

		<!-- Message Content -->
		<div class="{message.role === 'user' ? 'bg-amber-500/10 border-amber-500/30' : 'bg-slate-800/50 border-slate-700/50'} border rounded-xl p-4 transition-all hover:shadow-lg">
			{#if message.content}
				<div class="text-sm text-slate-200 leading-relaxed markdown-content">
					{@html formatMessageContent(message.content)}
				</div>
			{/if}
			<div class="text-[10px] text-slate-500 mt-2">{message.timestamp.toLocaleTimeString()}</div>
		</div>
	</div>
	{#if message.role === 'user'}
		<div class="w-8 h-8 rounded-lg bg-slate-700 flex items-center justify-center flex-shrink-0">
			<span class="text-xs font-bold">You</span>
		</div>
	{/if}
</div>
