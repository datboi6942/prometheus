"""Tests for context window management."""

import pytest
from prometheus.services.context_manager import (
    count_tokens,
    count_messages_tokens,
    get_model_context_limit,
    compress_messages,
    check_and_compress_if_needed,
)


@pytest.mark.asyncio
async def test_count_tokens():
    """Test basic token counting."""
    text = "Hello, world! This is a test message."
    model = "gpt-4"

    token_count = await count_tokens(text, model)

    # Token count should be positive and reasonable
    assert token_count > 0
    assert token_count < 100  # Should be much less for this short text


@pytest.mark.asyncio
async def test_get_model_context_limit():
    """Test getting model context limits."""
    # Known models
    assert get_model_context_limit("gpt-4") == 8192
    assert get_model_context_limit("gpt-4o") == 128000
    assert get_model_context_limit("claude-3-opus") == 200000
    assert get_model_context_limit("ollama/llama3.2") == 8192

    # Unknown model should return default
    assert get_model_context_limit("unknown-model") == 4096


@pytest.mark.asyncio
async def test_count_messages_tokens():
    """Test counting tokens in message list."""
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"},
        {"role": "assistant", "content": "Hi there! How can I help?"},
    ]
    model = "gpt-4"

    total_tokens = await count_messages_tokens(messages, model)

    # Should count all messages with overhead
    assert total_tokens > 0
    assert total_tokens > 10  # At least some tokens from content


@pytest.mark.asyncio
async def test_compress_messages_when_not_needed():
    """Test that compression is skipped when not needed."""
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"},
    ]
    model = "gpt-4"

    compressed, stats = await compress_messages(messages, model, target_tokens=10000)

    # Should not compress since we're under target
    assert not stats["compressed"]
    assert len(compressed) == len(messages)


@pytest.mark.asyncio
async def test_compress_messages_when_needed():
    """Test compression when messages exceed target."""
    # Create a large message history
    messages = [
        {"role": "system", "content": "You are a helpful assistant."}
    ]

    # Add many user/assistant exchanges
    for i in range(20):
        messages.append({
            "role": "user",
            "content": f"This is user message number {i}. " * 50  # Make it long
        })
        messages.append({
            "role": "assistant",
            "content": f"This is assistant response number {i}. " * 50  # Make it long
        })

    model = "gpt-4"

    # Compress to a low target
    compressed, stats = await compress_messages(messages, model, target_tokens=500, keep_recent=2)

    # Should have compressed
    assert stats["compressed"]
    assert stats["messages_compressed"] > 0
    assert len(compressed) < len(messages)

    # Should keep system message
    assert compressed[0]["role"] == "system"

    # Should keep recent messages
    assert len(compressed) >= 3  # system + at least some recent


@pytest.mark.asyncio
async def test_check_and_compress_if_needed():
    """Test automatic compression checking."""
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"},
    ]
    model = "gpt-4"

    result_messages, context_info = await check_and_compress_if_needed(messages, model)

    # Should return context info
    assert "current_tokens" in context_info
    assert "max_tokens" in context_info
    assert "usage_ratio" in context_info
    assert "compression_needed" in context_info

    # For small messages, should not compress
    assert not context_info["compression_needed"]
    assert len(result_messages) == len(messages)


@pytest.mark.asyncio
async def test_check_and_compress_with_high_usage():
    """Test automatic compression with high context usage."""
    # Create messages that will exceed threshold
    messages = [{"role": "system", "content": "System prompt."}]

    # Add enough messages to trigger compression
    long_content = "This is a very long message. " * 1000
    for i in range(50):
        messages.append({"role": "user", "content": long_content})
        messages.append({"role": "assistant", "content": long_content})

    model = "gpt-4"  # 8192 token limit

    result_messages, context_info = await check_and_compress_if_needed(
        messages, model, auto_compress=True
    )

    # Should have triggered compression
    assert context_info["compressed"]
    assert len(result_messages) < len(messages)
    assert context_info["tokens_saved"] > 0
