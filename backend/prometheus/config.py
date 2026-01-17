from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized application settings using Pydantic Settings.

    Attributes:
        ollama_base_url (str): The base URL for the local Ollama instance.
        default_model (str): The default LLM model to use for inference.
        workspace_path (str): Path to the user's workspace directory.
        log_level (str): Logging level (e.g., INFO, DEBUG).
        debug (bool): Whether to enable debug mode.
    """

    ollama_base_url: str = "http://localhost:11434"
    default_model: str = "ollama/llama3.2"
    workspace_path: str = "/tmp/prometheus_workspace"
    log_level: str = "INFO"
    debug: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
