/**
 * Rules API service
 * Handles rule management
 */

const BASE_URL = 'http://localhost:8000/api/v1';

export interface Rule {
	id: number;
	name: string;
	content: string;
	enabled: number;
}

/**
 * Load global rules
 */
export async function loadGlobalRules(): Promise<Rule[]> {
	const response = await fetch(`${BASE_URL}/rules/global`);
	if (!response.ok) throw new Error('Failed to load global rules');
	const data = await response.json();
	return data.rules || [];
}

/**
 * Load project-specific rules
 */
export async function loadProjectRules(workspacePath: string): Promise<Rule[]> {
	const response = await fetch(
		`${BASE_URL}/rules/project?workspace_path=${encodeURIComponent(workspacePath)}`
	);
	if (!response.ok) throw new Error('Failed to load project rules');
	const data = await response.json();
	return data.rules || [];
}

/**
 * Create a new rule
 */
export async function createRule(
	name: string,
	content: string,
	isGlobal: boolean,
	workspacePath?: string
): Promise<void> {
	const endpoint = isGlobal ? `${BASE_URL}/rules/global` : `${BASE_URL}/rules/project`;
	const response = await fetch(endpoint, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			name,
			content,
			workspace_path: isGlobal ? null : workspacePath
		})
	});
	if (!response.ok) throw new Error('Failed to create rule');
}

/**
 * Delete a rule
 */
export async function deleteRule(ruleId: number, isGlobal: boolean): Promise<void> {
	const endpoint = isGlobal
		? `${BASE_URL}/rules/global/${ruleId}`
		: `${BASE_URL}/rules/project/${ruleId}`;
	const response = await fetch(endpoint, { method: 'DELETE' });
	if (!response.ok) throw new Error('Failed to delete rule');
}
