from typing import Any, AsyncGenerator

import litellm
from prometheus.config import Settings


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
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Perform a streaming completion.

        Args:
            model (str): The name of the model to use.
            messages (list[dict[str, str]]): A list of message objects.
            api_base (str | None): Optional custom API base URL.
            api_key (str | None): Optional API key.

        Yields:
            dict[str, Any]: A dictionary containing the chunk of the response.
        """
        extra = self.model_configs.get(model, {}).copy()
        if api_base:
            extra["api_base"] = api_base
        if api_key:
            extra["api_key"] = api_key

        response = await litellm.acompletion(model=model, messages=messages, stream=True, **extra)
        async for chunk in response:
            yield chunk
