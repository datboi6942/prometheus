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

# Database path - will be created in the workspace
DB_PATH = Path("/tmp/prometheus_data/prometheus.db")

# Sensitive setting keys that should be encrypted
SENSITIVE_KEYS = {
    "api_key",
    "ollama_api_key",
    "openai_api_key",
    "anthropic_api_key",
    "google_api_key",
    "litellm_api_key",
}


def _get_encryption_key() -> bytes:
    """Get or generate encryption key for sensitive settings.

    Uses environment variable ENCRYPTION_KEY if set, otherwise generates
    a key derived from a default salt. In production, set ENCRYPTION_KEY
    as a secure environment variable.

    Returns:
        bytes: Fernet encryption key.
    """
    env_key = os.getenv("ENCRYPTION_KEY")
    if env_key:
        # If provided as base64, decode it
        try:
            return base64.urlsafe_b64decode(env_key.encode())
        except Exception:
            # If not base64, derive key from it
            pass

    # Derive key from environment or default salt
    salt = os.getenv("ENCRYPTION_SALT", "prometheus_default_salt_2024").encode()
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
    try:
        return _fernet.decrypt(encrypted_value.encode()).decode()
    except Exception:
        # If decryption fails, assume value is not encrypted (backward compatibility)
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
) -> dict[str, Any]:
    """Add a message to a conversation.

    Args:
        conversation_id: Conversation ID.
        role: Message role (user, assistant, system).
        content: Message content.

    Returns:
        dict: The created message.
    """
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO messages (conversation_id, role, content, timestamp)
            VALUES (?, ?, ?, ?)
            """,
            (conversation_id, role, content, now),
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
