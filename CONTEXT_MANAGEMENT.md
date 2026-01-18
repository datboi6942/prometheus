# Context Window Management

## Overview

Prometheus now includes automatic context window management to prevent hitting model token limits during long conversations. The system automatically tracks token usage and compresses older messages when approaching the limit.

## Features

### 1. **Automatic Token Counting**
- Uses LiteLLM's built-in `token_counter()` for accurate token counting across all model providers
- Counts tokens for both user and assistant messages
- Includes message formatting overhead in calculations

### 2. **Model Context Limits**
- Pre-configured limits for popular models (GPT-4, Claude, DeepSeek, Gemini, etc.)
- Falls back to LiteLLM's `get_max_tokens()` for automatic detection
- Conservative estimates to prevent edge cases

### 3. **Intelligent Compression**
- **Compression Threshold**: Triggers at 80% of model's context window
- **Critical Threshold**: Aggressive compression at 95% usage
- **Preservation Strategy**:
  - Always keeps system message intact
  - Always keeps recent messages (configurable, default: 3)
  - Summarizes older messages in batches
  - Uses the model itself to create intelligent summaries

### 4. **Real-time Context Display**
- Visual progress bar showing current context usage
- Color-coded indicators:
  - 🟢 Green: Normal usage (< 80%)
  - 🟡 Amber: Approaching limit (80-95%)
  - 🔴 Red: Critical usage (> 95%)
- Shows compression statistics when applied
- Displays token counts and percentage used

## Implementation

### Backend Components

#### `context_manager.py`
Main service providing:
- `count_tokens(text, model)` - Count tokens in text
- `count_messages_tokens(messages, model)` - Count tokens in message list
- `get_model_context_limit(model)` - Get context window size for model
- `compress_messages(messages, model, target_tokens)` - Compress message history
- `check_and_compress_if_needed(messages, model)` - Main entry point for auto-compression

#### Chat Router Integration
The chat endpoint (`routers/chat.py`):
1. Builds message list with system prompt, rules, and memories
2. Calls `check_and_compress_if_needed()` to analyze and compress if needed
3. Sends context info to frontend via SSE
4. Uses compressed messages for model inference

### Frontend Components

#### Context Store
Added to `lib/stores.ts`:
```typescript
contextInfo: {
  current_tokens: number;
  max_tokens: number;
  usage_ratio: number;
  compression_needed: boolean;
  critical: boolean;
  compressed?: boolean;
  tokens_saved?: number;
  compression_ratio?: number;
}
```

#### UI Display
Visual indicator above chat input showing:
- Current token usage with color-coded styling
- Progress bar for visual representation
- Compression notification when messages are compressed
- Token savings display

## Configuration

### Model Context Limits

Configured in `services/context_manager.py`:

```python
MODEL_CONTEXT_LIMITS = {
    "gpt-4": 8192,
    "gpt-4o": 128000,
    "claude-3-opus": 200000,
    "deepseek-chat": 64000,
    # ... more models
}
```

### Compression Thresholds

```python
COMPRESSION_THRESHOLD = 0.80  # Start compressing at 80% usage
CRITICAL_THRESHOLD = 0.95     # Aggressive compression at 95%
```

### Compression Strategy

```python
keep_recent = 3  # Number of recent messages to keep
target_tokens = model_limit * 0.70  # Target 70% after compression
```

## Usage Examples

### Normal Usage
When context is below 80%, no compression occurs:
```
Context Usage: 4,521 / 128,000 tokens (3%)
```

### Compression Applied
When context exceeds 80%, automatic compression:
```
Context Usage: 85,234 / 128,000 tokens (67%)
Compressed: 26,451 tokens saved
```

### Critical Compression
At 95% or higher, aggressive compression:
```
Context Usage: 72,456 / 128,000 tokens (57%)
Compressed: 54,120 tokens saved (critical compression applied)
```

## How Compression Works

1. **Analysis**: System counts all tokens in conversation
2. **Threshold Check**: Compares to model's limit
3. **Preservation**:
   - System message (with rules/memories): KEPT
   - Recent 3 messages: KEPT
   - Older messages: SUMMARIZED
4. **Summarization**: Uses the model itself to create concise summaries
5. **Batch Processing**: Older messages summarized in batches for efficiency
6. **Result**: Compressed conversation sent to model

## Example Compression

**Before** (172,702 tokens - would fail):
```
[System]: You are Prometheus...
[User]: What is React?
[Assistant]: React is a JavaScript library... (very long response)
[User]: Tell me about hooks
[Assistant]: Hooks are a feature... (very long response)
... (many more messages)
[User]: What are we discussing?
```

**After** (85,234 tokens - fits comfortably):
```
[System]: You are Prometheus...
[Summarized]: Earlier discussion covered React basics, hooks, and component lifecycle...
[User]: What are we discussing?
```

## Testing

Run the context manager tests:
```bash
cd backend
pytest tests/test_context_manager.py -v
```

Tests cover:
- Token counting accuracy
- Model limit detection
- Compression logic
- Threshold triggers
- Message preservation

## Performance Considerations

- **Token Counting**: Fast operation using optimized tokenizers
- **Compression**: Only triggered when needed (80%+ usage)
- **Summarization**: Batched for efficiency
- **Caching**: LiteLLM caches tokenizer instances

## Limitations

1. **Summarization Quality**: Depends on the model's summarization capabilities
2. **Context Loss**: Older details may be lost in summaries (by design)
3. **API Calls**: Summarization requires model API calls (minimal cost)
4. **Token Estimation**: Some models may have slight variance in token counting

## Future Enhancements

Potential improvements:
- [ ] User control over compression settings
- [ ] Semantic compression (preserve important context)
- [ ] Conversation chunking for extremely long sessions
- [ ] Token budget allocation per conversation
- [ ] Compression preview before applying
- [ ] Manual compression trigger

## Troubleshooting

### Context Still Exceeding Limit
If you still hit context limits:
1. Check model configuration is correct
2. Verify compression threshold settings
3. Reduce `keep_recent` value for more aggressive compression
4. Consider switching to a model with larger context window

### Compression Too Aggressive
If too much context is lost:
1. Increase `keep_recent` value
2. Raise `COMPRESSION_THRESHOLD` (e.g., to 0.90)
3. Lower `target_tokens` percentage (e.g., to 0.80)

### Performance Issues
If compression is slow:
1. Check network latency to model provider
2. Verify summarization model is available
3. Consider reducing batch size in compression logic

## API Reference

See `backend/prometheus/services/context_manager.py` for detailed API documentation.

## Contributing

When adding new models:
1. Add context limit to `MODEL_CONTEXT_LIMITS` dict
2. Test token counting accuracy
3. Verify compression works correctly
4. Update this documentation

---

*This feature ensures you never hit context limits during long conversations, allowing for seamless multi-turn interactions without manual message management.*
