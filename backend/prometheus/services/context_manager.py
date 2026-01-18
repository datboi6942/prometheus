"""Context window management with automatic compression.

This module provides token counting and automatic context compression
to prevent hitting model context limits during conversations.
"""

import asyncio
from typing import Any

import litellm
import structlog

logger = structlog.get_logger()

# Model context window limits (in tokens)
# These are conservative estimates; actual limits may vary by provider
MODEL_CONTEXT_LIMITS = {
    # OpenAI models
    "gpt-4": 8192,
    "gpt-4-32k": 32768,
    "gpt-4-turbo": 128000,
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-3.5-turbo": 16385,
    "gpt-3.5-turbo-16k": 16385,
    # Anthropic models
    "claude-3-opus": 200000,
    "claude-3-sonnet": 200000,
    "claude-3-haiku": 200000,
    "claude-3-5-sonnet": 200000,
    "claude-3-5-haiku": 200000,
    # DeepSeek models
    "deepseek-chat": 64000,
    "deepseek-reasoner": 64000,
    # Google models
    "gemini-pro": 32768,
    "gemini-1.5-pro": 1000000,
    "gemini-1.5-flash": 1000000,
    # Ollama local models (conservative estimates)
    "llama3.2": 8192,
    "llama3.1": 128000,
    "codellama": 16384,
    "mistral": 32768,
    "deepseek-r1": 64000,
    # Fallback default
    "default": 4096,
}

# Compression threshold (percentage of context window)
COMPRESSION_THRESHOLD = 0.80  # Start compressing at 80% usage
CRITICAL_THRESHOLD = 0.95  # Aggressive compression at 95%


def get_model_context_limit(model: str) -> int:
    """Get the context window limit for a model.

    Args:
        model: Model identifier (e.g., "gpt-4", "ollama/llama3.2")

    Returns:
        int: Maximum context window size in tokens
    """
    # Try using LiteLLM's built-in limit detection
    try:
        max_tokens = litellm.get_max_tokens(model)
        if max_tokens and max_tokens > 0:
            logger.info("Got context limit from LiteLLM", model=model, max_tokens=max_tokens)
            return max_tokens
    except Exception as e:
        logger.debug("Could not get max tokens from LiteLLM", model=model, error=str(e))

    # Fall back to our configuration
    # Extract base model name (handle "provider/model" format)
    base_model = model.split("/")[-1].lower()

    # Check exact match first
    for key, limit in MODEL_CONTEXT_LIMITS.items():
        if key.lower() in base_model or base_model in key.lower():
            logger.info("Using configured context limit", model=model, limit=limit)
            return limit

    # Default fallback
    logger.warning("Unknown model, using default limit", model=model, default=MODEL_CONTEXT_LIMITS["default"])
    return MODEL_CONTEXT_LIMITS["default"]


async def count_tokens(text: str, model: str) -> int:
    """Count tokens in text for a specific model.

    Uses LiteLLM's token_counter which supports multiple tokenizers.

    Args:
        text: Text to count tokens for
        model: Model identifier for tokenizer selection

    Returns:
        int: Number of tokens
    """
    try:
        # LiteLLM's token_counter handles different model tokenizers
        token_count = litellm.token_counter(model=model, text=text)
        return token_count
    except Exception as e:
        logger.error("Token counting failed", model=model, error=str(e))
        # Fallback: rough estimate (1 token ≈ 4 characters)
        return len(text) // 4


async def count_messages_tokens(messages: list[dict[str, str]], model: str) -> int:
    """Count total tokens in a list of messages.

    Args:
        messages: List of message dictionaries with 'role' and 'content'
        model: Model identifier for tokenizer selection

    Returns:
        int: Total number of tokens across all messages
    """
    total_tokens = 0

    for msg in messages:
        # Count role tokens (typically "user", "assistant", "system")
        role_tokens = await count_tokens(msg.get("role", ""), model)
        # Count content tokens
        content_tokens = await count_tokens(msg.get("content", ""), model)

        # Add overhead for message formatting (conservative estimate)
        # OpenAI uses ~4 tokens per message, Anthropic varies
        message_overhead = 4

        total_tokens += role_tokens + content_tokens + message_overhead

    return total_tokens


async def summarize_message(content: str, model: str, max_summary_tokens: int = 100) -> str:
    """Summarize a message using the model itself.

    Args:
        content: Original message content
        model: Model to use for summarization
        max_summary_tokens: Maximum tokens for the summary

    Returns:
        str: Summarized content
    """
    # Don't summarize very short messages
    token_count = await count_tokens(content, model)
    if token_count < 50:
        return content

    try:
        # Use the model to create a concise summary
        summary_prompt = [
            {
                "role": "system",
                "content": "You are a summarization assistant. Create a concise summary of the following text, preserving key information and technical details. Keep it under 100 tokens."
            },
            {
                "role": "user",
                "content": f"Summarize this:\n\n{content}"
            }
        ]

        # Use LiteLLM to generate summary
        response = await litellm.acompletion(
            model=model,
            messages=summary_prompt,
            max_tokens=max_summary_tokens,
            temperature=0.3,  # Lower temperature for more focused summaries
        )

        summary = response.choices[0].message.content.strip()
        logger.info("Message summarized", original_tokens=token_count, summary_tokens=await count_tokens(summary, model))

        return f"[Summarized]: {summary}"

    except Exception as e:
        logger.error("Summarization failed", error=str(e))
        # Fallback: simple truncation
        return content[:200] + "..." if len(content) > 200 else content


async def compress_messages(
    messages: list[dict[str, str]],
    model: str,
    target_tokens: int | None = None,
    keep_recent: int = 3
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Compress message history to fit within token budget.

    Strategy:
    1. Always keep system message (first message)
    2. Always keep most recent N messages
    3. Summarize older messages from oldest to newest
    4. Stop when under target token count

    Args:
        messages: Original message list
        model: Model identifier
        target_tokens: Target token count (defaults to 70% of model limit)
        keep_recent: Number of recent messages to keep unmodified

    Returns:
        tuple: (compressed_messages, compression_stats)
    """
    if not messages:
        return messages, {"compressed": False}

    # Determine target token count
    if target_tokens is None:
        model_limit = get_model_context_limit(model)
        target_tokens = int(model_limit * 0.70)  # Target 70% of limit

    # Count current tokens
    current_tokens = await count_messages_tokens(messages, model)
    original_tokens = current_tokens  # Save original count for stats

    if current_tokens <= target_tokens:
        logger.info("No compression needed", current_tokens=current_tokens, target=target_tokens)
        return messages, {
            "compressed": False,
            "original_tokens": current_tokens,
            "current_tokens": current_tokens,
            "messages_compressed": 0
        }

    logger.info("Starting compression", current_tokens=current_tokens, target=target_tokens)

    compressed_messages = []
    messages_compressed = 0

    # Keep system message if present
    system_msg_count = 1 if messages and messages[0].get("role") == "system" else 0
    if system_msg_count:
        compressed_messages.append(messages[0])

    # Identify messages to keep vs compress
    total_messages = len(messages)
    recent_start_idx = max(system_msg_count, total_messages - keep_recent)

    # Messages to potentially compress (between system and recent)
    compress_candidates = messages[system_msg_count:recent_start_idx]

    # Recent messages to keep
    recent_messages = messages[recent_start_idx:]

    # Compress older messages
    if compress_candidates:
        # Batch summarize older messages
        batch_size = max(1, len(compress_candidates) // 3)  # Summarize in batches

        for i in range(0, len(compress_candidates), batch_size):
            batch = compress_candidates[i:i + batch_size]

            # Combine batch into single summary
            combined_content = "\n\n".join([
                f"{msg.get('role', 'user')}: {msg.get('content', '')}"
                for msg in batch
            ])

            summary = await summarize_message(combined_content, model, max_summary_tokens=150)

            compressed_messages.append({
                "role": "user",
                "content": summary
            })

            messages_compressed += len(batch)

            # Check if we're under target
            current_tokens = await count_messages_tokens(
                compressed_messages + recent_messages, model
            )

            if current_tokens <= target_tokens:
                break

    # Add recent messages
    compressed_messages.extend(recent_messages)

    # Final token count
    final_tokens = await count_messages_tokens(compressed_messages, model)

    stats = {
        "compressed": True,
        "original_tokens": original_tokens,
        "current_tokens": final_tokens,
        "tokens_saved": original_tokens - final_tokens,
        "messages_before": len(messages),
        "messages_after": len(compressed_messages),
        "messages_compressed": messages_compressed,
        "compression_ratio": round(final_tokens / original_tokens, 2) if original_tokens > 0 else 1.0
    }

    logger.info("Compression complete", **stats)

    return compressed_messages, stats


async def check_and_compress_if_needed(
    messages: list[dict[str, str]],
    model: str,
    auto_compress: bool = True
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Check context usage and compress if needed.

    This is the main entry point for context management.

    Args:
        messages: Message history
        model: Model identifier
        auto_compress: Whether to automatically compress when threshold exceeded

    Returns:
        tuple: (potentially_compressed_messages, context_info)
    """
    model_limit = get_model_context_limit(model)
    current_tokens = await count_messages_tokens(messages, model)

    usage_ratio = current_tokens / model_limit if model_limit > 0 else 0

    context_info = {
        "current_tokens": current_tokens,
        "max_tokens": model_limit,
        "usage_ratio": round(usage_ratio, 3),
        "compression_needed": usage_ratio >= COMPRESSION_THRESHOLD,
        "critical": usage_ratio >= CRITICAL_THRESHOLD,
    }

    # Auto-compress if needed
    if auto_compress and usage_ratio >= COMPRESSION_THRESHOLD:
        # Determine target based on severity
        if usage_ratio >= CRITICAL_THRESHOLD:
            # Aggressive compression - target 60%
            target = int(model_limit * 0.60)
            keep_recent = 2
        else:
            # Normal compression - target 70%
            target = int(model_limit * 0.70)
            keep_recent = 3

        compressed_messages, compression_stats = await compress_messages(
            messages, model, target_tokens=target, keep_recent=keep_recent
        )

        context_info.update(compression_stats)

        return compressed_messages, context_info

    return messages, context_info
