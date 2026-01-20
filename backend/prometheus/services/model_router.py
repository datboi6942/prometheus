import asyncio
from typing import Any, AsyncGenerator

import litellm
import structlog
from prometheus.config import Settings

logger = structlog.get_logger()

# Set LiteLLM timeout globally
litellm.request_timeout = 120  # 2 minutes max for API calls


class ModelRouter:
    """Universal inference bridge via LiteLLM.

    This class handles routing requests to various LLM providers (local and remote)
    using LiteLLM.

    Args:
        config (Settings): The application settings.
    """

    def __init__(self, config: Settings) -> None:
        self.config = config
        self.model_configs: dict[str, dict[str, Any]] = {
            # Local models via Ollama
            "ollama/llama3.2": {"api_base": config.ollama_base_url},
            "ollama/codellama": {"api_base": config.ollama_base_url},
            "ollama/deepseek-r1": {"api_base": config.ollama_base_url},
            # DeepSeek API models
            "deepseek/deepseek-chat": {"api_base": "https://api.deepseek.com"},
            "deepseek/deepseek-reasoner": {"api_base": "https://api.deepseek.com"},
            # Commercial providers
            "anthropic/claude-3-5-sonnet-20240620": {},
            "openai/gpt-4o": {},
        }

    async def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        api_base: str | None = None,
        api_key: str | None = None,
    ) -> str:
        """Perform a non-streaming completion.

        Args:
            model (str): The name of the model to use.
            messages (list[dict[str, str]]): A list of message objects.
            api_base (str | None): Optional custom API base URL.
            api_key (str | None): Optional API key.

        Returns:
            str: The content of the completion response.
        """
        extra = self.model_configs.get(model, {}).copy()
        if api_base:
            extra["api_base"] = api_base
        if api_key:
            extra["api_key"] = api_key

        response = await litellm.acompletion(model=model, messages=messages, **extra)
        return str(response.choices[0].message.content)

    async def stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        api_base: str | None = None,
        api_key: str | None = None,
        max_tokens: int | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Perform a streaming completion with timeout protection.

        Args:
            model (str): The name of the model to use.
            messages (list[dict[str, str]]): A list of message objects.
            api_base (str | None): Optional custom API base URL.
            api_key (str | None): Optional API key.
            max_tokens (int | None): Optional maximum tokens for response.

        Yields:
            dict[str, Any]: A dictionary containing the chunk of the response.
        """
        extra = self.model_configs.get(model, {}).copy()
        if api_base:
            extra["api_base"] = api_base
        if api_key:
            extra["api_key"] = api_key

        # For DeepSeek Reasoner, enable streaming of reasoning content
        # Use specific patterns to avoid false positives (e.g., "gpt-r10", "custom-r15")
        model_lower = model.lower()
        # Match patterns: ends with -r1, contains /r1/, or deepseek-r1 variants
        is_reasoning_model = any(x in model_lower for x in ["deepseek-reasoner", "deepseek-r1", "deepseek/r1"]) or \
                           model_lower.endswith("-r1") or "/r1/" in model_lower or "/r1" in model_lower
        is_deepseek = "deepseek" in model_lower
        
        if is_reasoning_model:
            # Request reasoning content to be included in the response
            # include_usage helps track token consumption
            extra["stream_options"] = {"include_usage": True}
            # For reasoning models, we need MORE tokens to allow for:
            # 1. Extended thinking/reasoning
            # 2. Tool call JSON output AFTER thinking
            # Previous 4096 limit was causing tool calls to be cut off!
            if max_tokens is None:
                max_tokens = 16384  # Much higher limit for thinking + tool calls
            logger.info("Configured reasoning model stream", 
                       model=model, max_tokens=max_tokens, is_deepseek=is_deepseek)
        elif max_tokens is None:
            # Set model-appropriate defaults to prevent truncation during agentic tasks
            # Different providers have different max_tokens limits
            if is_deepseek:
                max_tokens = 8192  # DeepSeek limit is [1, 8192]
            else:
                max_tokens = 16384  # High limit for other models (Claude, GPT-4, etc.)
        
        if max_tokens:
            extra["max_tokens"] = max_tokens
        
        logger.info("Starting model stream", model=model, message_count=len(messages))
        
        # Per-chunk timeout (in seconds) - if no chunk arrives within this time, abort
        chunk_timeout = 60.0  # 60s per chunk - generous for slow models
        
        # Also set litellm timeout directly as backup
        extra["timeout"] = 120  # 2 minute global timeout for the entire request
        
        try:
            logger.debug("Calling litellm.acompletion", model=model)
            
            # Timeout for initial connection
            response = await asyncio.wait_for(
                litellm.acompletion(model=model, messages=messages, stream=True, **extra),
                timeout=90.0  # 90s to get initial response
            )
            
            logger.debug("Got response object, starting iteration", model=model)
            
            chunk_count = 0
            first_content_logged = False  # Track if we've logged first content for debugging
            first_reasoning_logged = False  # Track if we've logged first reasoning
            
            # Use manual iteration with per-chunk timeout instead of async for
            # This prevents hanging if the stream stalls between chunks
            response_iter = response.__aiter__()
            
            # Safety limits to prevent runaway streams
            max_chunks = 10000  # Hard limit on chunks
            # Increase limits for reasoning models - they need space for thinking + tool calls
            # 128KB = ~32K tokens, enough for 16K reasoning + 16K response
            max_response_bytes = 128000 if is_reasoning_model else 32000
            accumulated_bytes = 0
            
            while True:
                try:
                    # Only log every 500 chunks to reduce noise
                    if chunk_count % 500 == 0:
                        logger.debug("Stream progress", model=model, chunk_count=chunk_count)
                    
                    # Timeout for EACH chunk - this is the key fix!
                    # The original async for loop could hang indefinitely waiting for chunks
                    chunk = await asyncio.wait_for(
                        response_iter.__anext__(),
                        timeout=chunk_timeout
                    )
                    chunk_count += 1
                    
                    if chunk_count == 1:
                        logger.info("Received first chunk", model=model)
                        # Debug: Log the structure of the first chunk to understand the format
                        if hasattr(chunk, 'choices') and chunk.choices:
                            delta = chunk.choices[0].delta if chunk.choices[0].delta else None
                            if delta:
                                has_content = hasattr(delta, 'content') and delta.content
                                has_reasoning = (
                                    (hasattr(delta, 'provider_specific_fields') and 
                                     delta.provider_specific_fields and 
                                     delta.provider_specific_fields.get('reasoning_content')) or
                                    (hasattr(delta, 'reasoning_content') and delta.reasoning_content)
                                )
                                logger.info("First chunk structure", 
                                           has_content=has_content,
                                           has_reasoning=has_reasoning,
                                           delta_attrs=dir(delta)[:10])
                    
                    # Track accumulated response size
                    if hasattr(chunk, 'choices') and chunk.choices:
                        delta = chunk.choices[0].delta
                        if hasattr(delta, 'content') and delta.content:
                            accumulated_bytes += len(delta.content.encode('utf-8'))
                    
                    # Safety check: abort if stream is too long (chunks)
                    if chunk_count > max_chunks:
                        logger.error(
                            "Stream exceeded max chunks - aborting to prevent runaway",
                            model=model,
                            chunk_count=chunk_count,
                            max_chunks=max_chunks
                        )
                        break
                    
                    # Safety check: abort if response is too large (bytes)
                    if accumulated_bytes > max_response_bytes:
                        logger.warning(
                            "Stream exceeded max response size - aborting",
                            model=model,
                            chunk_count=chunk_count,
                            accumulated_bytes=accumulated_bytes,
                            max_bytes=max_response_bytes
                        )
                        break
                    
                    yield chunk
                    
                except StopAsyncIteration:
                    # Normal end of stream
                    logger.info("Stream completed normally", model=model, chunk_count=chunk_count)
                    break
                    
                except asyncio.TimeoutError:
                    # Chunk timeout - stream stalled
                    logger.error(
                        "Stream chunk timeout - no data received within timeout",
                        model=model,
                        chunk_count=chunk_count,
                        timeout_seconds=chunk_timeout
                    )
                    # Don't raise - just break out and let the caller handle partial response
                    break
            
            logger.info("Stream iteration finished", model=model, chunk_count=chunk_count)
            
        except asyncio.TimeoutError:
            logger.error("Model stream initial connection timed out after 90s", model=model)
            raise
        except Exception as e:
            logger.error("Model stream error", model=model, error=str(e), exc_info=True)
            raise

    async def stream_with_tools(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        api_base: str | None = None,
        api_key: str | None = None,
        max_tokens: int | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Perform a streaming completion with tool support and timeout protection.

        Args:
            model (str): The name of the model to use.
            messages (list[dict[str, Any]]): A list of message objects.
            tools (list[dict[str, Any]]): A list of tool definitions.
            api_base (str | None): Optional custom API base URL.
            api_key (str | None): Optional API key.
            max_tokens (int | None): Optional maximum tokens for response.

        Yields:
            dict[str, Any]: A dictionary containing the chunk of the response.
        """
        extra = self.model_configs.get(model, {}).copy()
        if api_base:
            extra["api_base"] = api_base
        if api_key:
            extra["api_key"] = api_key
        
        if max_tokens:
            extra["max_tokens"] = max_tokens

        # Add tools to extra params
        extra["tools"] = tools
        extra["tool_choice"] = "auto"
        
        # Set litellm timeout directly as backup
        extra["timeout"] = 120

        logger.info("Starting model stream with tools", model=model, message_count=len(messages))
        
        # Per-chunk timeout (in seconds)
        chunk_timeout = 60.0
        
        try:
            response = await asyncio.wait_for(
                litellm.acompletion(model=model, messages=messages, stream=True, **extra),
                timeout=90.0
            )
            
            logger.debug("Got response object with tools, starting iteration", model=model)
            
            chunk_count = 0
            
            # Use manual iteration with per-chunk timeout
            response_iter = response.__aiter__()
            
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        response_iter.__anext__(),
                        timeout=chunk_timeout
                    )
                    chunk_count += 1
                    
                    if chunk_count == 1:
                        logger.info("Received first chunk with tools", model=model)
                    
                    yield chunk
                    
                except StopAsyncIteration:
                    logger.info("Stream with tools completed normally", model=model, chunk_count=chunk_count)
                    break
                    
                except asyncio.TimeoutError:
                    logger.error(
                        "Stream with tools chunk timeout",
                        model=model,
                        chunk_count=chunk_count,
                        timeout_seconds=chunk_timeout
                    )
                    break
            
            logger.info("Stream with tools iteration finished", model=model, chunk_count=chunk_count)
            
        except asyncio.TimeoutError:
            logger.error("Model stream with tools initial connection timed out after 90s", model=model)
            raise
        except Exception as e:
            logger.error("Model stream with tools error", model=model, error=str(e), exc_info=True)
            raise
