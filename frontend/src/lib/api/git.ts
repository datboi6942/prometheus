/**
 * Git API service
 * Handles all git-related operations
 */

const BASE_URL = 'http://localhost:8000/api/v1';

export interface GitStatus {
	staged: string[];
	unstaged: string[];
	untracked: string[];
	current_branch: string;
	error?: string;
}

export interface GitBranch {
	name: string;
	is_current: boolean;
	is_remote: boolean;
}

export interface GitCommit {
	hash: string;
	message: string;
	author: string;
	date: string;
}

export interface GitHubUser {
	login: string;
	name: string;
	avatar_url: string;
}

/**
 * Get git status
 */
export async function getGitStatus(workspacePath: string): Promise<GitStatus> {
	const response = await fetch(
		`${BASE_URL}/git/status?workspace_path=${encodeURIComponent(workspacePath)}`
	);
	if (!response.ok) throw new Error('Failed to get git status');
	return await response.json();
}

/**
 * Initialize git repository
 */
export async function initGitRepo(workspacePath: string): Promise<void> {
	const response = await fetch(
		`${BASE_URL}/git/init?workspace_path=${encodeURIComponent(workspacePath)}`,
		{ method: 'POST' }
	);
	if (!response.ok) throw new Error('Failed to initialize repository');
}

/**
 * Stage files
 */
export async function stageFiles(workspacePath: string, files: string[]): Promise<void> {
	const response = await fetch(
		`${BASE_URL}/git/stage?workspace_path=${encodeURIComponent(workspacePath)}`,
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ files })
		}
	);
	if (!response.ok) throw new Error('Failed to stage files');
}

/**
 * Unstage files
 */
export async function unstageFiles(workspacePath: string, files: string[]): Promise<void> {
	const response = await fetch(
		`${BASE_URL}/git/unstage?workspace_path=${encodeURIComponent(workspacePath)}`,
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ files })
		}
	);
	if (!response.ok) throw new Error('Failed to unstage files');
}

/**
 * Create commit
 */
export async function createCommit(workspacePath: string, message: string): Promise<void> {
	const response = await fetch(
		`${BASE_URL}/git/commit?workspace_path=${encodeURIComponent(workspacePath)}`,
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ message })
		}
	);
	if (!response.ok) throw new Error('Failed to create commit');
}

/**
 * Get branches
 */
export async function getBranches(workspacePath: string): Promise<GitBranch[]> {
	const response = await fetch(
		`${BASE_URL}/git/branches?workspace_path=${encodeURIComponent(workspacePath)}`
	);
	if (!response.ok) throw new Error('Failed to get branches');
	const data = await response.json();
	return data.branches || [];
}

/**
 * Get commit log
 */
export async function getCommitLog(
	workspacePath: string,
	limit: number = 20
): Promise<GitCommit[]> {
	const response = await fetch(
		`${BASE_URL}/git/log?workspace_path=${encodeURIComponent(workspacePath)}&limit=${limit}`
	);
	if (!response.ok) throw new Error('Failed to get commit log');
	const data = await response.json();
	return data.commits || [];
}

/**
 * Push to remote
 */
export async function pushToRemote(workspacePath: string): Promise<void> {
	const response = await fetch(
		`${BASE_URL}/git/push?workspace_path=${encodeURIComponent(workspacePath)}`,
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ remote: 'origin', set_upstream: true })
		}
	);
	if (!response.ok) {
		const data = await response.json();
		throw new Error(data.detail || 'Push failed');
	}
}

/**
 * Pull from remote
 */
export async function pullFromRemote(workspacePath: string): Promise<void> {
	const response = await fetch(
		`${BASE_URL}/git/pull?workspace_path=${encodeURIComponent(workspacePath)}`,
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ remote: 'origin' })
		}
	);
	if (!response.ok) {
		const data = await response.json();
		throw new Error(data.detail || 'Pull failed');
	}
}

/**
 * Check GitHub authentication
 */
export async function checkGitHubAuth(): Promise<{
	authenticated: boolean;
	user?: GitHubUser;
}> {
	const response = await fetch(`${BASE_URL}/git/github/auth`);
	if (!response.ok) throw new Error('Failed to check GitHub auth');
	return await response.json();
}

/**
 * Add remote
 */
export async function addRemote(
	workspacePath: string,
	name: string,
	url: string
): Promise<void> {
	const response = await fetch(
		`${BASE_URL}/git/remote?workspace_path=${encodeURIComponent(workspacePath)}`,
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ name, url })
		}
	);
	if (!response.ok) throw new Error('Failed to add remote');
}

/**
 * Get GitHub repositories
 */
export async function getGitHubRepos(): Promise<any> {
	const response = await fetch(`${BASE_URL}/git/github/repos`);
	if (!response.ok) throw new Error('Failed to get GitHub repositories');
	return await response.json();
}

/**
 * Create GitHub repository
 */
export async function createGitHubRepo(
	name: string,
	description: string,
	isPrivate: boolean
): Promise<{ clone_url: string }> {
	const response = await fetch(`${BASE_URL}/git/github/repos`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			name,
			description,
			private: isPrivate
		})
	});
	if (!response.ok) throw new Error('Failed to create GitHub repository');
	return await response.json();
}

// Pull Request functions
/**
 * Get pull requests for a repository
 */
export async function getPullRequests(
	repoFullName: string,
	state: string = 'open',
	limit: number = 30
): Promise<any> {
	const response = await fetch(
		`${BASE_URL}/git/github/pulls?repo_full_name=${encodeURIComponent(repoFullName)}&state=${state}&limit=${limit}`
	);
	if (!response.ok) throw new Error('Failed to get pull requests');
	return await response.json();
}

/**
 * Get a specific pull request
 */
export async function getPullRequest(repoFullName: string, prNumber: number): Promise<any> {
	const response = await fetch(
		`${BASE_URL}/git/github/pulls/${prNumber}?repo_full_name=${encodeURIComponent(repoFullName)}`
	);
	if (!response.ok) throw new Error('Failed to get pull request');
	return await response.json();
}

/**
 * Create a pull request
 */
export async function createPullRequest(
	repoFullName: string,
	title: string,
	head: string,
	base: string,
	body: string = '',
	draft: boolean = false
): Promise<any> {
	const response = await fetch(`${BASE_URL}/git/github/pulls`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			repo_full_name: repoFullName,
			title,
			head,
			base,
			body,
			draft
		})
	});
	if (!response.ok) throw new Error('Failed to create pull request');
	return await response.json();
}

/**
 * Merge a pull request
 */
export async function mergePullRequest(
	repoFullName: string,
	prNumber: number,
	commitMessage: string = '',
	mergeMethod: string = 'merge'
): Promise<any> {
	const response = await fetch(`${BASE_URL}/git/github/pulls/merge`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			repo_full_name: repoFullName,
			pr_number: prNumber,
			commit_message: commitMessage,
			merge_method: mergeMethod
		})
	});
	if (!response.ok) throw new Error('Failed to merge pull request');
	return await response.json();
}

/**
 * Get comments on a pull request
 */
export async function getPRComments(repoFullName: string, prNumber: number): Promise<any> {
	const response = await fetch(
		`${BASE_URL}/git/github/pulls/${prNumber}/comments?repo_full_name=${encodeURIComponent(repoFullName)}`
	);
	if (!response.ok) throw new Error('Failed to get PR comments');
	return await response.json();
}

/**
 * Add a comment to a pull request
 */
export async function addPRComment(
	repoFullName: string,
	prNumber: number,
	body: string
): Promise<any> {
	const response = await fetch(`${BASE_URL}/git/github/pulls/comments`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			repo_full_name: repoFullName,
			pr_number: prNumber,
			body
		})
	});
	if (!response.ok) throw new Error('Failed to add PR comment');
	return await response.json();
}

// Issue functions
/**
 * Get issues for a repository
 */
export async function getIssues(
	repoFullName: string,
	state: string = 'open',
	limit: number = 30
): Promise<any> {
	const response = await fetch(
		`${BASE_URL}/git/github/issues?repo_full_name=${encodeURIComponent(repoFullName)}&state=${state}&limit=${limit}`
	);
	if (!response.ok) throw new Error('Failed to get issues');
	return await response.json();
}

/**
 * Create an issue
 */
export async function createIssue(
	repoFullName: string,
	title: string,
	body: string = '',
	labels: string[] = []
): Promise<any> {
	const response = await fetch(`${BASE_URL}/git/github/issues`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			repo_full_name: repoFullName,
			title,
			body,
			labels
		})
	});
	if (!response.ok) throw new Error('Failed to create issue');
	return await response.json();
}

/**
 * Update an issue
 */
export async function updateIssue(
	repoFullName: string,
	issueNumber: number,
	title?: string,
	body?: string,
	state?: string,
	labels?: string[]
): Promise<any> {
	const response = await fetch(`${BASE_URL}/git/github/issues`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			repo_full_name: repoFullName,
			issue_number: issueNumber,
			title,
			body,
			state,
			labels
		})
	});
	if (!response.ok) throw new Error('Failed to update issue');
	return await response.json();
}

// Workflow functions
/**
 * Get workflows for a repository
 */
export async function getWorkflows(repoFullName: string): Promise<any> {
	const response = await fetch(
		`${BASE_URL}/git/github/workflows?repo_full_name=${encodeURIComponent(repoFullName)}`
	);
	if (!response.ok) throw new Error('Failed to get workflows');
	return await response.json();
}

/**
 * Get workflow runs for a repository
 */
export async function getWorkflowRuns(
	repoFullName: string,
	workflowId?: number,
	limit: number = 30
): Promise<any> {
	let url = `${BASE_URL}/git/github/workflows/runs?repo_full_name=${encodeURIComponent(repoFullName)}&limit=${limit}`;
	if (workflowId) {
		url += `&workflow_id=${workflowId}`;
	}
	const response = await fetch(url);
	if (!response.ok) throw new Error('Failed to get workflow runs');
	return await response.json();
}
