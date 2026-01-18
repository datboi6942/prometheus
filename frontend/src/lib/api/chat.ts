/**
 * Chat API service
 * Handles all chat and conversation-related API calls
 */

const BASE_URL = 'http://localhost:8000/api/v1';

export interface Message {
	role: string;
	content: string;
	timestamp: Date;
}

export interface Conversation {
	id: string;
	title: string;
	updated_at: string;
}

export interface ChatRequest {
	messages: Message[];
	workspace_path: string;
	model: string;
	api_base?: string;
}

/**
 * Load all conversations
 */
export async function loadConversations(): Promise<Conversation[]> {
	const response = await fetch(`${BASE_URL}/conversations`);
	if (!response.ok) throw new Error('Failed to load conversations');
	const data = await response.json();
	return data.conversations || [];
}

/**
 * Create a new conversation
 */
export async function createConversation(
	title: string,
	workspacePath: string,
	model: string
): Promise<Conversation> {
	const response = await fetch(`${BASE_URL}/conversations`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			title,
			workspace_path: workspacePath,
			model
		})
	});
	if (!response.ok) throw new Error('Failed to create conversation');
	const data = await response.json();
	return data.conversation;
}

/**
 * Load a specific conversation
 */
export async function loadConversation(conversationId: string): Promise<Message[]> {
	const response = await fetch(`${BASE_URL}/conversations/${conversationId}`);
	if (!response.ok) throw new Error('Failed to load conversation');
	const data = await response.json();
	return data.messages.map((m: any) => ({
		role: m.role,
		content: m.content,
		timestamp: new Date(m.timestamp)
	}));
}

/**
 * Delete a conversation
 */
export async function deleteConversation(conversationId: string): Promise<void> {
	const response = await fetch(`${BASE_URL}/conversations/${conversationId}`, {
		method: 'DELETE'
	});
	if (!response.ok) throw new Error('Failed to delete conversation');
}

/**
 * Save a message to a conversation
 */
export async function saveMessageToConversation(
	conversationId: string,
	role: string,
	content: string
): Promise<void> {
	const response = await fetch(`${BASE_URL}/conversations/${conversationId}/messages`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ role, content })
	});
	if (!response.ok) throw new Error('Failed to save message');
}

/**
 * Stream chat responses (returns ReadableStream)
 */
export async function streamChat(
	request: ChatRequest,
	signal?: AbortSignal
): Promise<Response> {
	const response = await fetch(`${BASE_URL}/chat/stream`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(request),
		signal
	});
	if (!response.ok) throw new Error('Failed to stream chat');
	return response;
}
