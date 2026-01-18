"""SQLite database setup and models for chat persistence and rules."""
import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from prometheus.config import settings

# Database path - configurable via environment variable
DB_PATH = Path(settings.database_path) / "prometheus.db"

# Sensitive setting keys that should be encrypted
SENSITIVE_KEYS = {
    "api_key",
    "apiKey",
    "ollama_api_key",
    "openai_api_key",
    "anthropic_api_key",
    "google_api_key",
    "litellm_api_key",
    "customApiKey",
    "github_token",
}


def _get_encryption_key() -> bytes:
    """Get or generate encryption key for sensitive settings.

    Uses environment variable ENCRYPTION_KEY if set, otherwise generates
    a key derived from a default salt.
    
    **IMPORTANT**: In production, you MUST set ENCRYPTION_KEY or ENCRYPTION_SALT
    environment variables. The default salt is publicly visible and makes
    rainbow table attacks easier. Never use default values in production.

    Returns:
        bytes: Fernet encryption key.
    """
    import structlog

    logger = structlog.get_logger()
    env_key = os.getenv("ENCRYPTION_KEY")
    if env_key:
        # If provided as base64, decode it
        try:
            return base64.urlsafe_b64decode(env_key.encode())
        except Exception:
            # If not base64, derive key from it
            pass

    # Derive key from environment or default salt
    # WARNING: Default salt is for development only
    salt = os.getenv("ENCRYPTION_SALT", "prometheus_default_salt_2024").encode()
    if not os.getenv("ENCRYPTION_SALT"):
        logger.warning(
            "ENCRYPTION_SALT not set - using default salt. "
            "This is insecure for production! Set ENCRYPTION_KEY or ENCRYPTION_SALT."
        )
    password = (env_key or "prometheus_default_password").encode()

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password))
    return key


_fernet = Fernet(_get_encryption_key())


def _encrypt_value(value: str) -> str:
    """Encrypt a sensitive value.

    Args:
        value: Plaintext value to encrypt.

    Returns:
        str: Encrypted value (base64 encoded).
    """
    return _fernet.encrypt(value.encode()).decode()


def _decrypt_value(encrypted_value: str) -> str:
    """Decrypt a sensitive value.

    Args:
        encrypted_value: Encrypted value (base64 encoded).

    Returns:
        str: Decrypted plaintext value.

    Raises:
        ValueError: If decryption fails (value may not be encrypted).
    """
    import structlog

    logger = structlog.get_logger()
    try:
        return _fernet.decrypt(encrypted_value.encode()).decode()
    except Exception as e:
        # If decryption fails, log warning but return value for backward compatibility
        # This handles cases where values were stored before encryption was added
        logger.warning(
            "Decryption failed - value may not be encrypted or key changed",
            error=str(e),
            value_preview=encrypted_value[:20] + "..." if len(encrypted_value) > 20 else encrypted_value,
        )
        return encrypted_value


def _is_sensitive_key(key: str) -> bool:
    """Check if a setting key should be encrypted.

    Args:
        key: Setting key to check.

    Returns:
        bool: True if key should be encrypted.
    """
    return any(sensitive in key.lower() for sensitive in SENSITIVE_KEYS)


async def init_db() -> None:
    """Initialize the database and create tables.

    Creates the database file and all required tables if they don't exist.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        # Conversations table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                workspace_path TEXT,
                model TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Messages table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            )
        """)

        # Global rules table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS global_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                content TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)

        # Project rules table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS project_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_path TEXT NOT NULL,
                name TEXT NOT NULL,
                content TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)

        # Settings table (for API keys, preferences, etc.)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Memories table (memory bank for persistent knowledge)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                tags TEXT,
                workspace_path TEXT,
                source TEXT NOT NULL,
                conversation_id TEXT,
                created_at TEXT NOT NULL,
                last_accessed_at TEXT,
                access_count INTEGER DEFAULT 0,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            )
        """)

        # MCP Servers table (for dynamic tool registration)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS mcp_servers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                config TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Command permissions table (for dynamic command approval)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS command_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                command TEXT NOT NULL UNIQUE,
                approved INTEGER DEFAULT 0,
                workspace_path TEXT,
                approved_at TEXT,
                notes TEXT,
                created_at TEXT NOT NULL
            )
        """)

        # Create index for faster memory searches
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_workspace ON memories(workspace_path)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_tags ON memories(tags)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_command_permissions_command ON command_permissions(command)
        """)

        await db.commit()

        # Run migrations
        await _migrate_add_thinking_columns(db)


async def _migrate_add_thinking_columns(db: aiosqlite.Connection) -> None:
    """Add thinking_summary and thinking_content columns to messages table if they don't exist."""
    # Check if columns already exist
    cursor = await db.execute("PRAGMA table_info(messages)")
    columns = await cursor.fetchall()
    column_names = [col[1] for col in columns]

    # Add thinking_summary column if it doesn't exist
    if "thinking_summary" not in column_names:
        await db.execute("ALTER TABLE messages ADD COLUMN thinking_summary TEXT")

    # Add thinking_content column if it doesn't exist
    if "thinking_content" not in column_names:
        await db.execute("ALTER TABLE messages ADD COLUMN thinking_content TEXT")

    await db.commit()


# Conversation functions
async def create_conversation(
    conv_id: str,
    title: str,
    workspace_path: str,
    model: str,
) -> dict[str, Any]:
    """Create a new conversation.

    Args:
        conv_id: Unique conversation ID.
        title: Conversation title.
        workspace_path: Associated workspace path.
        model: Model used for conversation.

    Returns:
        dict: The created conversation.
    """
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO conversations (id, title, workspace_path, model, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (conv_id, title, workspace_path, model, now, now),
        )
        await db.commit()

    return {
        "id": conv_id,
        "title": title,
        "workspace_path": workspace_path,
        "model": model,
        "created_at": now,
        "updated_at": now,
    }


async def get_conversations(limit: int = 50) -> list[dict[str, Any]]:
    """Get recent conversations.

    Args:
        limit: Maximum number of conversations to return.

    Returns:
        list: List of conversation dictionaries.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def get_conversation(conv_id: str) -> dict[str, Any] | None:
    """Get a conversation by ID.

    Args:
        conv_id: Conversation ID.

    Returns:
        dict or None: The conversation if found.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM conversations WHERE id = ?",
            (conv_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def delete_conversation(conv_id: str) -> bool:
    """Delete a conversation and its messages.

    Args:
        conv_id: Conversation ID.

    Returns:
        bool: True if deleted.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
        await db.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        await db.commit()
    return True


# Message functions
async def add_message(
    conversation_id: str,
    role: str,
    content: str,
    thinking_summary: str | None = None,
    thinking_content: str | None = None,
) -> dict[str, Any]:
    """Add a message to a conversation.

    Args:
        conversation_id: Conversation ID.
        role: Message role (user, assistant, system).
        content: Message content.
        thinking_summary: Optional thinking summary for reasoning models.
        thinking_content: Optional full thinking content for reasoning models.

    Returns:
        dict: The created message.
    """
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO messages (conversation_id, role, content, thinking_summary, thinking_content, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (conversation_id, role, content, thinking_summary, thinking_content, now),
        )
        msg_id = cursor.lastrowid
        # Update conversation timestamp
        await db.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (now, conversation_id),
        )
        await db.commit()

    return {
        "id": msg_id,
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
        "thinking_summary": thinking_summary,
        "thinking_content": thinking_content,
        "timestamp": now,
    }


async def get_messages(conversation_id: str) -> list[dict[str, Any]]:
    """Get all messages for a conversation.

    Args:
        conversation_id: Conversation ID.

    Returns:
        list: List of message dictionaries.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY timestamp",
            (conversation_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


# Rules functions
async def get_global_rules() -> list[dict[str, Any]]:
    """Get all global rules.

    Returns:
        list: List of global rule dictionaries.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM global_rules ORDER BY created_at",
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def add_global_rule(name: str, content: str) -> dict[str, Any]:
    """Add a global rule.

    Args:
        name: Rule name.
        content: Rule content.

    Returns:
        dict: The created rule.
    """
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO global_rules (name, content, enabled, created_at)
            VALUES (?, ?, 1, ?)
            """,
            (name, content, now),
        )
        rule_id = cursor.lastrowid
        await db.commit()

    return {"id": rule_id, "name": name, "content": content, "enabled": 1, "created_at": now}


async def update_global_rule(rule_id: int, name: str, content: str, enabled: bool) -> bool:
    """Update a global rule.

    Args:
        rule_id: Rule ID.
        name: Rule name.
        content: Rule content.
        enabled: Whether rule is enabled.

    Returns:
        bool: True if updated.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE global_rules SET name = ?, content = ?, enabled = ? WHERE id = ?",
            (name, content, 1 if enabled else 0, rule_id),
        )
        await db.commit()
    return True


async def delete_global_rule(rule_id: int) -> bool:
    """Delete a global rule.

    Args:
        rule_id: Rule ID.

    Returns:
        bool: True if deleted.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM global_rules WHERE id = ?", (rule_id,))
        await db.commit()
    return True


async def get_project_rules(workspace_path: str) -> list[dict[str, Any]]:
    """Get project rules for a workspace.

    Args:
        workspace_path: Workspace path.

    Returns:
        list: List of project rule dictionaries.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM project_rules WHERE workspace_path = ? ORDER BY created_at",
            (workspace_path,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def add_project_rule(workspace_path: str, name: str, content: str) -> dict[str, Any]:
    """Add a project rule.

    Args:
        workspace_path: Workspace path.
        name: Rule name.
        content: Rule content.

    Returns:
        dict: The created rule.
    """
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO project_rules (workspace_path, name, content, enabled, created_at)
            VALUES (?, ?, ?, 1, ?)
            """,
            (workspace_path, name, content, now),
        )
        rule_id = cursor.lastrowid
        await db.commit()

    return {
        "id": rule_id,
        "workspace_path": workspace_path,
        "name": name,
        "content": content,
        "enabled": 1,
        "created_at": now,
    }


async def delete_project_rule(rule_id: int) -> bool:
    """Delete a project rule.

    Args:
        rule_id: Rule ID.

    Returns:
        bool: True if deleted.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM project_rules WHERE id = ?", (rule_id,))
        await db.commit()
    return True


# Settings functions
async def get_setting(key: str) -> str | None:
    """Get a setting value by key.

    Automatically decrypts sensitive values.

    Args:
        key: Setting key.

    Returns:
        str or None: Setting value if found (decrypted if sensitive).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            value = row[0]
            if _is_sensitive_key(key):
                return _decrypt_value(value)
            return value


async def set_setting(key: str, value: str) -> None:
    """Set a setting value.

    Automatically encrypts sensitive values before storage.

    Args:
        key: Setting key.
        value: Setting value (will be encrypted if key is sensitive).
    """
    now = datetime.now(timezone.utc).isoformat()
    # Encrypt sensitive values before storage
    stored_value = _encrypt_value(value) if _is_sensitive_key(key) else value
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?
            """,
            (key, stored_value, now, stored_value, now),
        )
        await db.commit()


async def get_all_settings() -> dict[str, str]:
    """Get all settings.

    Automatically decrypts sensitive values.

    Returns:
        dict: All settings as key-value pairs (decrypted if sensitive).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT key, value FROM settings") as cursor:
            rows = await cursor.fetchall()
            result = {}
            for key, value in rows:
                if _is_sensitive_key(key):
                    result[key] = _decrypt_value(value)
                else:
                    result[key] = value
            return result


async def delete_setting(key: str) -> None:
    """Delete a setting.

    Args:
        key: Setting key.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM settings WHERE key = ?", (key,))
        await db.commit()


async def get_enabled_rules_text(workspace_path: str) -> str:
    """Get combined text of all enabled rules for a workspace.

    Args:
        workspace_path: Workspace path.

    Returns:
        str: Combined rules text for injection into system prompt.
    """
    rules_text = []

    # Get global rules
    global_rules = await get_global_rules()
    for rule in global_rules:
        if rule.get("enabled"):
            rules_text.append(f"[Global Rule: {rule['name']}]\n{rule['content']}")

    # Get project rules
    project_rules = await get_project_rules(workspace_path)
    for rule in project_rules:
        if rule.get("enabled"):
            rules_text.append(f"[Project Rule: {rule['name']}]\n{rule['content']}")

    if rules_text:
        return "\n\nUSER-DEFINED RULES (Follow these strictly):\n" + "\n\n".join(rules_text)
    return ""


# Memory functions
async def add_memory(
    content: str,
    source: str,
    workspace_path: str | None = None,
    conversation_id: str | None = None,
    tags: str | None = None,
) -> dict[str, Any]:
    """Add a memory to the memory bank.

    Args:
        content: Memory content.
        source: Source of memory ('user' or 'model').
        workspace_path: Optional workspace path for workspace-specific memories.
        conversation_id: Optional conversation ID where memory was created.
        tags: Optional comma-separated tags for searching.

    Returns:
        dict: The created memory.
    """
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO memories (content, tags, workspace_path, source, conversation_id, created_at, last_accessed_at, access_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (content, tags, workspace_path, source, conversation_id, now, now),
        )
        memory_id = cursor.lastrowid
        await db.commit()

    return {
        "id": memory_id,
        "content": content,
        "tags": tags,
        "workspace_path": workspace_path,
        "source": source,
        "conversation_id": conversation_id,
        "created_at": now,
        "last_accessed_at": now,
        "access_count": 0,
    }


async def get_memories(
    workspace_path: str | None = None,
    limit: int = 50,
    search_query: str | None = None,
) -> list[dict[str, Any]]:
    """Get memories, optionally filtered by workspace and search query.

    Args:
        workspace_path: Optional workspace path to filter by.
        limit: Maximum number of memories to return.
        search_query: Optional search query to filter memories.

    Returns:
        list: List of memory dictionaries, sorted by relevance (access_count, last_accessed_at).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT * FROM memories WHERE 1=1"
        params: list[Any] = []

        if workspace_path:
            query += " AND (workspace_path = ? OR workspace_path IS NULL)"
            params.append(workspace_path)

        if search_query:
            query += " AND (content LIKE ? OR tags LIKE ?)"
            search_term = f"%{search_query}%"
            params.extend([search_term, search_term])

        query += " ORDER BY access_count DESC, last_accessed_at DESC, created_at DESC LIMIT ?"
        params.append(limit)

        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def get_relevant_memories(
    workspace_path: str | None = None,
    context: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Get relevant memories based on context and workspace.

    Args:
        workspace_path: Optional workspace path.
        context: Optional context string to find relevant memories.
        limit: Maximum number of memories to return.

    Returns:
        list: List of relevant memory dictionaries.
    """
    # Simple keyword-based relevance for now
    # Could be enhanced with embeddings/semantic search
    if context:
        return await get_memories(workspace_path=workspace_path, search_query=context, limit=limit)
    return await get_memories(workspace_path=workspace_path, limit=limit)


async def update_memory_access(memory_id: int) -> None:
    """Update memory access statistics.

    Args:
        memory_id: Memory ID to update.
    """
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE memories 
            SET last_accessed_at = ?, access_count = access_count + 1
            WHERE id = ?
            """,
            (now, memory_id),
        )
        await db.commit()


async def delete_memory(memory_id: int) -> bool:
    """Delete a memory.

    Args:
        memory_id: Memory ID to delete.

    Returns:
        bool: True if deleted.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        await db.commit()
    return True


async def get_memories_text(workspace_path: str | None = None, context: str | None = None) -> str:
    """Get formatted memories text for injection into system prompt.

    Args:
        workspace_path: Optional workspace path.
        context: Optional context for finding relevant memories.

    Returns:
        str: Formatted memories text.
    """
    memories = await get_relevant_memories(workspace_path=workspace_path, context=context, limit=10)
    if not memories:
        return ""

    # Update access counts for retrieved memories
    for memory in memories:
        await update_memory_access(memory["id"])

    memory_texts = []
    for memory in memories:
        source_label = "User" if memory["source"] == "user" else "Model"
        memory_texts.append(f"[Memory - {source_label}]: {memory['content']}")

    return "\n\nMEMORY BANK (Important information to remember):\n" + "\n".join(memory_texts)


# MCP Server functions
async def add_mcp_server(name: str, config: dict[str, Any]) -> dict[str, Any]:
    """Add an MCP server configuration.

    Args:
        name: Server name.
        config: Server configuration (JSON-serializable dict).

    Returns:
        dict: The created server configuration.
    """
    now = datetime.now(timezone.utc).isoformat()
    config_json = json.dumps(config)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO mcp_servers (name, config, enabled, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(name) DO UPDATE SET config = ?, enabled = 1, updated_at = ?
            """,
            (name, config_json, now, now, config_json, now),
        )
        server_id = cursor.lastrowid
        await db.commit()

    return {
        "id": server_id,
        "name": name,
        "config": config,
        "enabled": 1,
        "created_at": now,
        "updated_at": now,
    }


async def get_mcp_servers() -> list[dict[str, Any]]:
    """Get all MCP server configurations.

    Returns:
        list: List of server configurations.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM mcp_servers ORDER BY created_at") as cursor:
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                server = dict(row)
                # Parse JSON config
                try:
                    server["config"] = json.loads(server["config"])
                except Exception:
                    server["config"] = {}
                result.append(server)
            return result


async def get_mcp_server(name: str) -> dict[str, Any] | None:
    """Get an MCP server configuration by name.

    Args:
        name: Server name.

    Returns:
        dict or None: Server configuration if found.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM mcp_servers WHERE name = ?", (name,)) as cursor:
            row = await cursor.fetchone()
            if row:
                server = dict(row)
                try:
                    server["config"] = json.loads(server["config"])
                except Exception:
                    server["config"] = {}
                return server
            return None


async def update_mcp_server(name: str, config: dict[str, Any], enabled: bool = True) -> bool:
    """Update an MCP server configuration.

    Args:
        name: Server name.
        config: Updated configuration.
        enabled: Whether server is enabled.

    Returns:
        bool: True if updated.
    """
    now = datetime.now(timezone.utc).isoformat()
    config_json = json.dumps(config)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE mcp_servers 
            SET config = ?, enabled = ?, updated_at = ?
            WHERE name = ?
            """,
            (config_json, 1 if enabled else 0, now, name),
        )
        await db.commit()
    return True


async def delete_mcp_server(name: str) -> bool:
    """Delete an MCP server.

    Args:
        name: Server name.

    Returns:
        bool: True if deleted.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM mcp_servers WHERE name = ?", (name,))
        await db.commit()
    return True


# Command permissions functions
async def check_command_permission(command: str, workspace_path: str | None = None) -> dict[str, Any] | None:
    """Check if a command has been approved.

    Args:
        command: Command to check (base command, e.g., 'node', 'python').
        workspace_path: Optional workspace path for workspace-specific permissions.

    Returns:
        dict or None: Permission record if found, None otherwise.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # Check for workspace-specific permission first, then global
        if workspace_path:
            async with db.execute(
                "SELECT * FROM command_permissions WHERE command = ? AND (workspace_path = ? OR workspace_path IS NULL) ORDER BY workspace_path DESC LIMIT 1",
                (command, workspace_path),
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
        
        # Check global permission
        async with db.execute(
            "SELECT * FROM command_permissions WHERE command = ? AND workspace_path IS NULL",
            (command,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def add_command_permission(
    command: str,
    approved: bool,
    workspace_path: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Add or update a command permission.

    Args:
        command: Command to approve/deny.
        approved: Whether the command is approved.
        workspace_path: Optional workspace path for workspace-specific permissions.
        notes: Optional notes about the permission.

    Returns:
        dict: The created/updated permission.
    """
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO command_permissions (command, approved, workspace_path, approved_at, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(command) DO UPDATE SET
                approved = ?,
                workspace_path = ?,
                approved_at = ?,
                notes = ?
            """,
            (command, 1 if approved else 0, workspace_path, now if approved else None, notes, now,
             1 if approved else 0, workspace_path, now if approved else None, notes),
        )
        perm_id = cursor.lastrowid
        await db.commit()

    return {
        "id": perm_id,
        "command": command,
        "approved": approved,
        "workspace_path": workspace_path,
        "approved_at": now if approved else None,
        "notes": notes,
        "created_at": now,
    }


async def get_all_command_permissions(workspace_path: str | None = None) -> list[dict[str, Any]]:
    """Get all command permissions.

    Args:
        workspace_path: Optional workspace path to filter by.

    Returns:
        list: List of permission dictionaries.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        if workspace_path:
            query = "SELECT * FROM command_permissions WHERE workspace_path = ? OR workspace_path IS NULL ORDER BY created_at DESC"
            params = (workspace_path,)
        else:
            query = "SELECT * FROM command_permissions ORDER BY created_at DESC"
            params = ()
        
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def delete_command_permission(command: str, workspace_path: str | None = None) -> bool:
    """Delete a command permission.

    Args:
        command: Command to delete permission for.
        workspace_path: Optional workspace path.

    Returns:
        bool: True if deleted.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        if workspace_path:
            await db.execute(
                "DELETE FROM command_permissions WHERE command = ? AND workspace_path = ?",
                (command, workspace_path),
            )
        else:
            await db.execute(
                "DELETE FROM command_permissions WHERE command = ? AND workspace_path IS NULL",
                (command,),
            )
        await db.commit()
    return True
