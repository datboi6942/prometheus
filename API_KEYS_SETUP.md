# API Keys Management

## Overview

Prometheus now supports multiple AI providers with secure API key storage. All API keys are:
- ✅ **Encrypted** at rest in the database
- ✅ **Persisted** across container rebuilds  
- ✅ **Provider-specific** - each provider has its own key
- ✅ **Automatically loaded** - no need to re-enter after setting

## Database Location

API keys are stored in: `~/.prometheus/prometheus.db`

This location persists across Docker rebuilds and is mounted from your host system.

## Supported Providers

### 1. **OpenAI** (GPT-4, GPT-4o, etc.)
- Model prefix: `openai/`
- Example: `openai/gpt-4o`
- Get key from: https://platform.openai.com/api-keys

### 2. **Anthropic** (Claude)
- Model prefix: `anthropic/`
- Example: `anthropic/claude-3-5-sonnet-20240620`
- Get key from: https://console.anthropic.com/

### 3. **DeepSeek**
- Model prefix: `deepseek/`
- Example: `deepseek/deepseek-chat`, `deepseek/deepseek-reasoner`
- Get key from: https://platform.deepseek.com/

### 4. **Grok** (xAI)
- Model prefix: `grok/` or `xai/`
- Example: `grok/grok-1`
- Get key from: https://x.ai/

### 5. **Google AI** (Gemini)
- Model prefix: `google/` or `gemini/`
- Example: `google/gemini-pro`
- Get key from: https://makersuite.google.com/app/apikey

### 6. **LiteLLM** (Unified API)
- Model prefix: `litellm/`
- Used for custom LiteLLM proxy setups

### 7. **Ollama** (Local Models)
- Model prefix: `ollama/`
- Example: `ollama/llama3.2`, `ollama/deepseek-r1`
- **No API key needed** - runs locally

## How to Set API Keys

### Via Web Interface (Recommended)

1. Click the **Settings** icon (⚙️) in the sidebar
2. Scroll down to the **API Keys** section
3. Enter your API key for each provider you want to use
4. Keys are **auto-saved** (1-second debounce)
5. Close the settings panel

That's it! Your keys are now encrypted and stored.

### Via API (Programmatic)

```bash
curl -X POST http://localhost:8000/api/v1/settings \
  -H "Content-Type: application/json" \
  -d '{
    "key": "deepseek_api_key",
    "value": "your-key-here"
  }'
```

## How API Keys Are Used

When you send a chat request with a model like `deepseek/deepseek-chat`:

1. The backend checks if an API key is provided in the request
2. If not, it looks up the provider (`deepseek`) in the database
3. It retrieves the stored API key for that provider
4. The key is decrypted and passed to LiteLLM
5. LiteLLM makes the API call with your key

## Model Selection

In the chat interface, you can select from various models:

**Local Models** (No API key needed):
- `ollama/llama3.2`
- `ollama/codellama`
- `ollama/deepseek-r1`

**Cloud Models** (API key required):
- `openai/gpt-4o`
- `anthropic/claude-3-5-sonnet-20240620`
- `deepseek/deepseek-chat`
- `deepseek/deepseek-reasoner`

## Security Features

### Encryption
- All API keys are encrypted using **Fernet** (symmetric encryption)
- Encryption key is derived from `ENCRYPTION_KEY` or `ENCRYPTION_SALT` environment variables
- Keys are encrypted before storage and decrypted on retrieval

### Database Keys Marked as Sensitive
```python
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
    "deepseek_api_key",
    "grok_api_key",
}
```

Any key containing these strings is automatically encrypted.

### Production Security

**IMPORTANT**: For production, set custom encryption keys:

```bash
# In your .env file or environment:
ENCRYPTION_KEY=your-base64-encoded-32-byte-key
# OR
ENCRYPTION_SALT=your-random-salt-string
```

To generate a secure key:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Troubleshooting

### API Key Not Persisting

**Problem**: API keys reset after container rebuild

**Solution**: 
1. Check that `~/.prometheus/` exists and is writable
2. Verify Docker volume mount: `~/.prometheus:/root/.prometheus`
3. Check `docker-compose.yml` has the correct volumes

### Authentication Error

**Problem**: `AuthenticationError: Authentication Fails`

**Solution**:
1. Open Settings (⚙️)
2. Enter your API key for the provider you're using
3. Wait 1 second for auto-save
4. Try your request again

### Wrong API Key Used

**Problem**: Using DeepSeek but OpenAI key is being sent

**Solution**:
1. Check your model selection - it should be `deepseek/deepseek-chat`
2. Make sure you entered the DeepSeek key in the correct field
3. The model prefix (`deepseek/`) determines which key is used

### Keys Not Loading

**Problem**: Set keys but they're empty when opening settings again

**Solution**:
1. Check browser console for errors
2. Verify backend is running: `docker compose logs backend`
3. Test API directly:
   ```bash
   curl http://localhost:8000/api/v1/settings
   ```

## API Endpoints

### Get All Settings
```
GET /api/v1/settings
```

Returns all settings (API keys are encrypted in database but decrypted in response).

### Get Single Setting
```
GET /api/v1/settings/{key}
```

### Save Setting
```
POST /api/v1/settings
Body: {"key": "openai_api_key", "value": "sk-..."}
```

### Delete Setting
```
DELETE /api/v1/settings/{key}
```

## Migration from Legacy Setup

If you were using the old `customApiKey` field:

1. The legacy field still works for backward compatibility
2. It's recommended to migrate to provider-specific keys
3. Enter your keys in the correct provider fields
4. The legacy field will be ignored if a provider-specific key exists

## Example Usage

1. **Install Ollama** (for local models):
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ollama pull llama3.2
   ```

2. **Get a DeepSeek API key**:
   - Go to https://platform.deepseek.com/
   - Create an account
   - Generate an API key

3. **Add to Prometheus**:
   - Open Prometheus web interface
   - Click Settings (⚙️)
   - Paste DeepSeek key in "DeepSeek API Key" field
   - Close settings (auto-saved)

4. **Start chatting**:
   - Select model: `deepseek/deepseek-chat`
   - Send a message
   - ✅ Works! Your key is used automatically

## Support

For issues or questions:
- Check logs: `docker compose logs backend`
- Database location: `ls -la ~/.prometheus/`
- Settings API: `curl http://localhost:8000/api/v1/settings`
