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
        is_reasoning_model = any(x in model.lower() for x in ["deepseek-reasoner", "deepseek-r1", "r1"])
        if is_reasoning_model:
            # Request reasoning content to be included in the response
            extra["stream_options"] = {"include_usage": True}
            # Limit response length for reasoning models to prevent overthinking
            # Reasoning models tend to generate excessive thinking - cap it
            if max_tokens is None:
                max_tokens = 4096  # Tight limit for faster decisions
        else:
            # For non-reasoning models, set a generous default to prevent truncation
            # Agentic tasks often require outputting tool calls with file content
            if max_tokens is None:
                max_tokens = 16384  # High limit for agentic tasks with file writes
        
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
            
            # Use manual iteration with per-chunk timeout instead of async for
            # This prevents hanging if the stream stalls between chunks
            response_iter = response.__aiter__()
            
            while True:
                try:
                    logger.debug("Waiting for chunk", model=model, chunk_count=chunk_count)
                    
                    # Timeout for EACH chunk - this is the key fix!
                    # The original async for loop could hang indefinitely waiting for chunks
                    chunk = await asyncio.wait_for(
                        response_iter.__anext__(),
                        timeout=chunk_timeout
                    )
                    chunk_count += 1
                    
                    if chunk_count == 1:
                        logger.info("Received first chunk", model=model)
                    
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
