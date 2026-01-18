/**
 * Settings API service
 * Handles loading and saving application settings
 */

const BASE_URL = 'http://localhost:8000/api/v1';

export interface Settings {
	[key: string]: string;
}

/**
 * Load all settings
 */
export async function loadSettings(): Promise<Settings> {
	const response = await fetch(`${BASE_URL}/settings`);
	if (!response.ok) throw new Error('Failed to load settings');
	const data = await response.json();
	return data.settings || {};
}

/**
 * Save a single setting
 */
export async function saveSetting(key: string, value: string): Promise<void> {
	const response = await fetch(`${BASE_URL}/settings`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ key, value })
	});
	if (!response.ok) throw new Error('Failed to save setting');
}

/**
 * Save multiple settings at once
 */
export async function saveSettings(settings: Record<string, string>): Promise<void> {
	await Promise.all(
		Object.entries(settings).map(([key, value]) => saveSetting(key, value))
	);
}
