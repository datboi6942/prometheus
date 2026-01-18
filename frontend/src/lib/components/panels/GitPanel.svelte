<script lang="ts">
	import { onMount } from 'svelte';
	import {
		GitBranch,
		GitCommit,
		GitPullRequest,
		GitMerge,
		Upload,
		Download,
		RefreshCw,
		Plus,
		Check,
		X,
		ExternalLink,
		AlertCircle,
		Code,
		GitFork,
		ChevronRight,
		ChevronDown
	} from 'lucide-svelte';
	import {
		workspacePath,
		gitStatus,
		gitBranches,
		gitCommits,
		isGitRepo,
		githubAuthenticated,
		githubUser
	} from '$lib/stores';
	import {
		getGitStatus,
		stageFiles,
		unstageFiles,
		createCommit,
		getBranches,
		getCommitLog,
		pushToRemote,
		pullFromRemote,
		initGitRepo,
		checkGitHubAuth,
		getGitHubRepos,
		getPullRequests,
		getIssues,
		getWorkflowRuns
	} from '$lib/api/git';

	// Local state
	let activeTab: 'status' | 'commits' | 'github' = 'status';
	let commitMessage = '';
	let selectedFiles = new Set<string>();
	let loading = false;
	let error: string | null = null;
	let expandedSections = {
		staged: true,
		unstaged: true,
		untracked: true
	};

	// GitHub state
	let githubRepos: any[] = [];
	let selectedRepo: string = '';
	let pullRequests: any[] = [];
	let issues: any[] = [];
	let workflowRuns: any[] = [];
	let githubTab: 'repos' | 'prs' | 'issues' | 'workflows' = 'repos';

	onMount(async () => {
		await loadGitStatus();
		if ($isGitRepo) {
			await loadGitBranches();
			await loadGitLog();
		}
		await checkGitHubAuthentication();
	});

	async function loadGitStatus() {
		try {
			loading = true;
			error = null;
			const status = await getGitStatus($workspacePath);
			$gitStatus = status;
			$isGitRepo = !status.error;
		} catch (e: any) {
			error = e.message;
			$isGitRepo = false;
		} finally {
			loading = false;
		}
	}

	async function loadGitBranches() {
		try {
			$gitBranches = await getBranches($workspacePath);
		} catch (e: any) {
			console.error('Failed to load branches:', e);
		}
	}

	async function loadGitLog() {
		try {
			$gitCommits = await getCommitLog($workspacePath, 20);
		} catch (e: any) {
			console.error('Failed to load commits:', e);
		}
	}

	async function checkGitHubAuthentication() {
		try {
			const auth = await checkGitHubAuth();
			$githubAuthenticated = auth.authenticated;
			$githubUser = auth.user;
			if (auth.authenticated) {
				await loadGitHubRepos();
			}
		} catch (e: any) {
			console.error('Failed to check GitHub auth:', e);
		}
	}

	async function loadGitHubRepos() {
		try {
			const result = await getGitHubRepos();
			if (result.success) {
				githubRepos = result.repositories || [];
				if (githubRepos.length > 0 && !selectedRepo) {
					// Try to match current directory to a repo
					const repoName = $workspacePath.split('/').pop();
					const matchingRepo = githubRepos.find((r) => r.name === repoName);
					if (matchingRepo) {
						selectedRepo = matchingRepo.full_name;
						await loadGitHubData();
					}
				}
			}
		} catch (e: any) {
			console.error('Failed to load GitHub repos:', e);
		}
	}

	async function loadGitHubData() {
		if (!selectedRepo) return;
		try {
			// Load PRs, issues, and workflows in parallel
			const [prsResult, issuesResult, workflowsResult] = await Promise.all([
				getPullRequests(selectedRepo),
				getIssues(selectedRepo),
				getWorkflowRuns(selectedRepo)
			]);

			if (prsResult.success) pullRequests = prsResult.pull_requests || [];
			if (issuesResult.success) issues = issuesResult.issues || [];
			if (workflowsResult.success) workflowRuns = workflowsResult.runs || [];
		} catch (e: any) {
			console.error('Failed to load GitHub data:', e);
		}
	}

	async function handleInitRepo() {
		try {
			loading = true;
			error = null;
			await initGitRepo($workspacePath);
			await loadGitStatus();
			await loadGitBranches();
		} catch (e: any) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	async function handleStageFiles(files: string[]) {
		try {
			loading = true;
			error = null;
			await stageFiles($workspacePath, files);
			await loadGitStatus();
			selectedFiles.clear();
		} catch (e: any) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	async function handleUnstageFiles(files: string[]) {
		try {
			loading = true;
			error = null;
			await unstageFiles($workspacePath, files);
			await loadGitStatus();
			selectedFiles.clear();
		} catch (e: any) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	async function handleCommit() {
		if (!commitMessage.trim()) return;
		try {
			loading = true;
			error = null;
			await createCommit($workspacePath, commitMessage);
			commitMessage = '';
			await loadGitStatus();
			await loadGitBranches();
			await loadGitLog();
		} catch (e: any) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	async function handlePush() {
		try {
			loading = true;
			error = null;
			await pushToRemote($workspacePath);
			await loadGitStatus();
		} catch (e: any) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	async function handlePull() {
		try {
			loading = true;
			error = null;
			await pullFromRemote($workspacePath);
			await loadGitStatus();
			await loadGitLog();
		} catch (e: any) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	function toggleSection(section: 'staged' | 'unstaged' | 'untracked') {
		expandedSections[section] = !expandedSections[section];
	}

	function toggleFileSelection(file: string) {
		if (selectedFiles.has(file)) {
			selectedFiles.delete(file);
		} else {
			selectedFiles.add(file);
		}
		selectedFiles = selectedFiles;
	}

	function getStatusColor(status: string): string {
		switch (status) {
			case 'completed':
			case 'success':
			case 'open':
				return 'text-green-400';
			case 'in_progress':
			case 'queued':
				return 'text-yellow-400';
			case 'failure':
			case 'closed':
				return 'text-red-400';
			default:
				return 'text-slate-400';
		}
	}
</script>

<div class="flex flex-col h-full bg-slate-900 text-slate-300">
	<!-- Header -->
	<div class="flex items-center justify-between p-3 border-b border-slate-700">
		<div class="flex items-center gap-2">
			<GitBranch class="w-4 h-4" />
			<span class="text-sm font-semibold">
				{#if $isGitRepo && $gitStatus?.current_branch}
					{$gitStatus.current_branch}
				{:else}
					Git
				{/if}
			</span>
		</div>
		<div class="flex gap-1">
			<button
				on:click={loadGitStatus}
				disabled={loading}
				class="p-1.5 hover:bg-slate-700 rounded transition-colors disabled:opacity-50"
				title="Refresh"
			>
				<RefreshCw class="w-3.5 h-3.5 {loading ? 'animate-spin' : ''}" />
			</button>
		</div>
	</div>

	{#if error}
		<div class="m-3 p-2 bg-red-900/20 border border-red-500/50 rounded text-xs text-red-400 flex items-center gap-2">
			<AlertCircle class="w-4 h-4" />
			<span>{error}</span>
		</div>
	{/if}

	{#if !$isGitRepo}
		<!-- Not a Git repository -->
		<div class="flex-1 flex flex-col items-center justify-center p-6 text-center">
			<GitBranch class="w-12 h-12 text-slate-600 mb-4" />
			<p class="text-sm text-slate-400 mb-4">This folder is not a Git repository</p>
			<button
				on:click={handleInitRepo}
				disabled={loading}
				class="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm font-medium transition-colors disabled:opacity-50"
			>
				Initialize Repository
			</button>
		</div>
	{:else}
		<!-- Tabs -->
		<div class="flex border-b border-slate-700">
			<button
				on:click={() => (activeTab = 'status')}
				class="px-4 py-2 text-xs font-medium transition-colors {activeTab === 'status'
					? 'text-blue-400 border-b-2 border-blue-400'
					: 'text-slate-400 hover:text-slate-300'}"
			>
				Changes
			</button>
			<button
				on:click={() => (activeTab = 'commits')}
				class="px-4 py-2 text-xs font-medium transition-colors {activeTab === 'commits'
					? 'text-blue-400 border-b-2 border-blue-400'
					: 'text-slate-400 hover:text-slate-300'}"
			>
				History
			</button>
			<button
				on:click={() => (activeTab = 'github')}
				class="px-4 py-2 text-xs font-medium transition-colors {activeTab === 'github'
					? 'text-blue-400 border-b-2 border-blue-400'
					: 'text-slate-400 hover:text-slate-300'}"
			>
				GitHub
			</button>
		</div>

		<!-- Content -->
		<div class="flex-1 overflow-y-auto">
			{#if activeTab === 'status'}
				<div class="p-3">
					<!-- Commit section -->
					<div class="mb-4">
						<textarea
							bind:value={commitMessage}
							placeholder="Commit message..."
							class="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded text-xs resize-none focus:outline-none focus:border-blue-500"
							rows="3"
						/>
						<div class="flex gap-2 mt-2">
							<button
								on:click={handleCommit}
								disabled={loading || !commitMessage.trim() || !$gitStatus?.staged?.length}
								class="flex-1 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 rounded text-xs font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-1.5"
							>
								<GitCommit class="w-3.5 h-3.5" />
								Commit
							</button>
							<button
								on:click={handlePush}
								disabled={loading}
								class="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 rounded text-xs font-medium transition-colors disabled:opacity-50 flex items-center gap-1.5"
								title="Push"
							>
								<Upload class="w-3.5 h-3.5" />
							</button>
							<button
								on:click={handlePull}
								disabled={loading}
								class="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 rounded text-xs font-medium transition-colors disabled:opacity-50 flex items-center gap-1.5"
								title="Pull"
							>
								<Download class="w-3.5 h-3.5" />
							</button>
						</div>
					</div>

					<!-- Staged files -->
					{#if $gitStatus?.staged?.length}
						<div class="mb-3">
							<button
								on:click={() => toggleSection('staged')}
								class="w-full flex items-center gap-2 px-2 py-1.5 hover:bg-slate-800 rounded text-xs font-medium"
							>
								{#if expandedSections.staged}
									<ChevronDown class="w-3.5 h-3.5" />
								{:else}
									<ChevronRight class="w-3.5 h-3.5" />
								{/if}
								<span>Staged Changes ({$gitStatus.staged.length})</span>
							</button>
							{#if expandedSections.staged}
								<div class="mt-1 space-y-0.5">
									{#each $gitStatus.staged as file}
										<div class="flex items-center gap-2 px-2 py-1 hover:bg-slate-800 rounded text-xs">
											<Check class="w-3.5 h-3.5 text-green-400" />
											<span class="flex-1 truncate">{file}</span>
											<button
												on:click={() => handleUnstageFiles([file])}
												class="p-0.5 hover:bg-slate-700 rounded"
												title="Unstage"
											>
												<X class="w-3 h-3" />
											</button>
										</div>
									{/each}
								</div>
							{/if}
						</div>
					{/if}

					<!-- Unstaged files -->
					{#if $gitStatus?.unstaged?.length}
						<div class="mb-3">
							<button
								on:click={() => toggleSection('unstaged')}
								class="w-full flex items-center gap-2 px-2 py-1.5 hover:bg-slate-800 rounded text-xs font-medium"
							>
								{#if expandedSections.unstaged}
									<ChevronDown class="w-3.5 h-3.5" />
								{:else}
									<ChevronRight class="w-3.5 h-3.5" />
								{/if}
								<span>Modified ({$gitStatus.unstaged.length})</span>
							</button>
							{#if expandedSections.unstaged}
								<div class="mt-1 space-y-0.5">
									{#each $gitStatus.unstaged as file}
										<div class="flex items-center gap-2 px-2 py-1 hover:bg-slate-800 rounded text-xs">
											<Code class="w-3.5 h-3.5 text-yellow-400" />
											<span class="flex-1 truncate">{file}</span>
											<button
												on:click={() => handleStageFiles([file])}
												class="p-0.5 hover:bg-slate-700 rounded"
												title="Stage"
											>
												<Plus class="w-3 h-3" />
											</button>
										</div>
									{/each}
								</div>
							{/if}
						</div>
					{/if}

					<!-- Untracked files -->
					{#if $gitStatus?.untracked?.length}
						<div class="mb-3">
							<button
								on:click={() => toggleSection('untracked')}
								class="w-full flex items-center gap-2 px-2 py-1.5 hover:bg-slate-800 rounded text-xs font-medium"
							>
								{#if expandedSections.untracked}
									<ChevronDown class="w-3.5 h-3.5" />
								{:else}
									<ChevronRight class="w-3.5 h-3.5" />
								{/if}
								<span>Untracked ({$gitStatus.untracked.length})</span>
							</button>
							{#if expandedSections.untracked}
								<div class="mt-1 space-y-0.5">
									{#each $gitStatus.untracked as file}
										<div class="flex items-center gap-2 px-2 py-1 hover:bg-slate-800 rounded text-xs">
											<Plus class="w-3.5 h-3.5 text-blue-400" />
											<span class="flex-1 truncate">{file}</span>
											<button
												on:click={() => handleStageFiles([file])}
												class="p-0.5 hover:bg-slate-700 rounded"
												title="Stage"
											>
												<Plus class="w-3 h-3" />
											</button>
										</div>
									{/each}
								</div>
							{/if}
						</div>
					{/if}

					{#if !$gitStatus?.staged?.length && !$gitStatus?.unstaged?.length && !$gitStatus?.untracked?.length}
						<div class="text-center py-8 text-xs text-slate-500">
							<GitCommit class="w-8 h-8 mx-auto mb-2 opacity-50" />
							<p>Working tree clean</p>
						</div>
					{/if}
				</div>
			{:else if activeTab === 'commits'}
				<div class="p-3 space-y-2">
					{#each $gitCommits as commit}
						<div class="p-2 bg-slate-800 rounded hover:bg-slate-750 transition-colors">
							<div class="flex items-start gap-2">
								<GitCommit class="w-3.5 h-3.5 mt-0.5 text-slate-400" />
								<div class="flex-1 min-w-0">
									<p class="text-xs font-medium truncate">{commit.message}</p>
									<div class="flex items-center gap-2 mt-1 text-[10px] text-slate-500">
										<span>{commit.author}</span>
										<span>•</span>
										<span>{new Date(commit.date).toLocaleDateString()}</span>
									</div>
									<code class="text-[10px] text-slate-600">{commit.hash.substring(0, 7)}</code>
								</div>
							</div>
						</div>
					{/each}
					{#if !$gitCommits?.length}
						<div class="text-center py-8 text-xs text-slate-500">
							<GitCommit class="w-8 h-8 mx-auto mb-2 opacity-50" />
							<p>No commits yet</p>
						</div>
					{/if}
				</div>
			{:else if activeTab === 'github'}
				<div class="p-3">
					{#if !$githubAuthenticated}
						<div class="text-center py-8">
							<GitFork class="w-12 h-12 mx-auto mb-4 text-slate-600" />
							<p class="text-sm text-slate-400 mb-4">GitHub authentication required</p>
							<p class="text-xs text-slate-500">Configure your GitHub token in Settings</p>
						</div>
					{:else}
						<!-- GitHub tabs -->
						<div class="flex gap-2 mb-4">
							<button
								on:click={() => (githubTab = 'repos')}
								class="px-3 py-1.5 text-xs rounded {githubTab === 'repos'
									? 'bg-blue-600 text-white'
									: 'bg-slate-800 hover:bg-slate-700'}"
							>
								Repos
							</button>
							<button
								on:click={() => (githubTab = 'prs')}
								class="px-3 py-1.5 text-xs rounded {githubTab === 'prs'
									? 'bg-blue-600 text-white'
									: 'bg-slate-800 hover:bg-slate-700'}"
							>
								PRs
							</button>
							<button
								on:click={() => (githubTab = 'issues')}
								class="px-3 py-1.5 text-xs rounded {githubTab === 'issues'
									? 'bg-blue-600 text-white'
									: 'bg-slate-800 hover:bg-slate-700'}"
							>
								Issues
							</button>
							<button
								on:click={() => (githubTab = 'workflows')}
								class="px-3 py-1.5 text-xs rounded {githubTab === 'workflows'
									? 'bg-blue-600 text-white'
									: 'bg-slate-800 hover:bg-slate-700'}"
							>
								Workflows
							</button>
						</div>

						<!-- Repository selector -->
						{#if githubTab !== 'repos'}
							<div class="mb-4">
								<select
									bind:value={selectedRepo}
									on:change={loadGitHubData}
									class="w-full px-3 py-1.5 bg-slate-800 border border-slate-700 rounded text-xs focus:outline-none focus:border-blue-500"
								>
									<option value="">Select repository...</option>
									{#each githubRepos as repo}
										<option value={repo.full_name}>{repo.full_name}</option>
									{/each}
								</select>
							</div>
						{/if}

						<!-- GitHub content -->
						{#if githubTab === 'repos'}
							<div class="space-y-2">
								{#each githubRepos as repo}
									<div class="p-2 bg-slate-800 rounded hover:bg-slate-750 transition-colors">
										<div class="flex items-start justify-between">
											<div class="flex-1 min-w-0">
												<p class="text-xs font-medium truncate">{repo.name}</p>
												{#if repo.description}
													<p class="text-[10px] text-slate-500 mt-0.5 line-clamp-2">{repo.description}</p>
												{/if}
											</div>
											<a
												href={repo.url}
												target="_blank"
												rel="noopener noreferrer"
												class="p-1 hover:bg-slate-700 rounded"
											>
												<ExternalLink class="w-3 h-3" />
											</a>
										</div>
									</div>
								{/each}
							</div>
						{:else if githubTab === 'prs'}
							<div class="space-y-2">
								{#each pullRequests as pr}
									<div class="p-2 bg-slate-800 rounded hover:bg-slate-750 transition-colors">
										<div class="flex items-start gap-2">
											<GitPullRequest class="w-3.5 h-3.5 mt-0.5 {getStatusColor(pr.state)}" />
											<div class="flex-1 min-w-0">
												<p class="text-xs font-medium truncate">#{pr.number} {pr.title}</p>
												<div class="flex items-center gap-2 mt-1 text-[10px] text-slate-500">
													<span>{pr.user}</span>
													<span>•</span>
													<span>{pr.head} → {pr.base}</span>
												</div>
											</div>
											<a
												href={pr.url}
												target="_blank"
												rel="noopener noreferrer"
												class="p-1 hover:bg-slate-700 rounded"
											>
												<ExternalLink class="w-3 h-3" />
											</a>
										</div>
									</div>
								{/each}
								{#if !pullRequests.length && selectedRepo}
									<div class="text-center py-8 text-xs text-slate-500">
										<GitPullRequest class="w-8 h-8 mx-auto mb-2 opacity-50" />
										<p>No pull requests</p>
									</div>
								{/if}
							</div>
						{:else if githubTab === 'issues'}
							<div class="space-y-2">
								{#each issues as issue}
									<div class="p-2 bg-slate-800 rounded hover:bg-slate-750 transition-colors">
										<div class="flex items-start gap-2">
											<AlertCircle class="w-3.5 h-3.5 mt-0.5 {getStatusColor(issue.state)}" />
											<div class="flex-1 min-w-0">
												<p class="text-xs font-medium truncate">#{issue.number} {issue.title}</p>
												<div class="flex items-center gap-2 mt-1 text-[10px] text-slate-500">
													<span>{issue.user}</span>
													{#if issue.labels.length}
														<span>•</span>
														<div class="flex gap-1">
															{#each issue.labels.slice(0, 2) as label}
																<span class="px-1.5 py-0.5 bg-slate-700 rounded">{label}</span>
															{/each}
														</div>
													{/if}
												</div>
											</div>
											<a
												href={issue.url}
												target="_blank"
												rel="noopener noreferrer"
												class="p-1 hover:bg-slate-700 rounded"
											>
												<ExternalLink class="w-3 h-3" />
											</a>
										</div>
									</div>
								{/each}
								{#if !issues.length && selectedRepo}
									<div class="text-center py-8 text-xs text-slate-500">
										<AlertCircle class="w-8 h-8 mx-auto mb-2 opacity-50" />
										<p>No issues</p>
									</div>
								{/if}
							</div>
						{:else if githubTab === 'workflows'}
							<div class="space-y-2">
								{#each workflowRuns as run}
									<div class="p-2 bg-slate-800 rounded hover:bg-slate-750 transition-colors">
										<div class="flex items-start gap-2">
											<GitMerge class="w-3.5 h-3.5 mt-0.5 {getStatusColor(run.conclusion || run.status)}" />
											<div class="flex-1 min-w-0">
												<p class="text-xs font-medium truncate">{run.name}</p>
												<div class="flex items-center gap-2 mt-1 text-[10px] text-slate-500">
													<span>{run.head_branch}</span>
													<span>•</span>
													<span class={getStatusColor(run.conclusion || run.status)}>
														{run.conclusion || run.status}
													</span>
												</div>
											</div>
											<a
												href={run.url}
												target="_blank"
												rel="noopener noreferrer"
												class="p-1 hover:bg-slate-700 rounded"
											>
												<ExternalLink class="w-3 h-3" />
											</a>
										</div>
									</div>
								{/each}
								{#if !workflowRuns.length && selectedRepo}
									<div class="text-center py-8 text-xs text-slate-500">
										<GitMerge class="w-8 h-8 mx-auto mb-2 opacity-50" />
										<p>No workflow runs</p>
									</div>
								{/if}
							</div>
						{/if}
					{/if}
				</div>
			{/if}
		</div>
	{/if}
</div>
