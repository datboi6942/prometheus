import os
import re
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized application settings using Pydantic Settings.

    Attributes:
        ollama_base_url (str): The base URL for the local Ollama instance.
        default_model (str): The default LLM model to use for inference.
        workspace_path (str): Default workspace path (can be overridden per request).
        database_path (str): Path to the database directory for persistence.
        log_level (str): Logging level (e.g., INFO, DEBUG).
        debug (bool): Whether to enable debug mode.
    """

    ollama_base_url: str = "http://localhost:11434"
    default_model: str = "ollama/llama3.2"
    # Default workspace - user can override via API on each request
    workspace_path: str = "/default_workspace"
    # Database stored in ~/.prometheus by default
    database_path: str = "/root/.prometheus"
    log_level: str = "INFO"
    debug: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()


def translate_host_path_to_container(path: str) -> str:
    """Translate a host filesystem path to a container path.

    Inside Docker, the user's home directory is mounted at /host_home.
    This function converts paths like /home/username/... to /host_home/...

    Args:
        path: The path to translate (may be host or container path).

    Returns:
        str: The translated container path.
    """
    if not path:
        return settings.workspace_path

    # Check if it's already a container path
    if path.startswith("/host_home") or path.startswith("/default_workspace"):
        return path

    # Check if /host_home mount exists (indicates we're in Docker)
    if not Path("/host_home").exists():
        # Not in Docker, return path as-is
        return path

    # Match /home/username/... pattern
    home_pattern = re.match(r"^/home/([^/]+)(/.*)?$", path)
    if home_pattern:
        # Convert to /host_home path
        subpath = home_pattern.group(2) or ""
        return f"/host_home{subpath}"

    # Match ~ or $HOME patterns (shouldn't normally come from frontend but handle anyway)
    if path.startswith("~"):
        return path.replace("~", "/host_home", 1)

    # Return as-is for other paths
    return path
