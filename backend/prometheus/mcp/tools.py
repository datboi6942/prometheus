import os
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class FileReadRequest(BaseModel):
    path: str


class FileWriteRequest(BaseModel):
    path: str
    content: str


class ShellExecuteRequest(BaseModel):
    command: str
    cwd: str | None = None


class MCPTools:
    """Model Context Protocol tools for filesystem and shell operations."""

    def __init__(self, workspace_path: str) -> None:
        self.workspace_path = Path(workspace_path).resolve()
        if not self.workspace_path.exists():
            self.workspace_path.mkdir(parents=True, exist_ok=True)

    def _validate_path(self, path: str) -> Path:
        """Validate that path is within workspace.

        Args:
            path (str): The file path to validate.

        Returns:
            Path: The resolved absolute path.

        Raises:
            ValueError: If path is outside workspace.
        """
        full_path = (self.workspace_path / path).resolve()
        if not str(full_path).startswith(str(self.workspace_path)):
            raise ValueError(f"Path {path} is outside workspace")
        return full_path

    def filesystem_read(self, path: str) -> dict[str, Any]:
        """Read a file from the workspace.

        Args:
            path (str): Relative path within workspace.

        Returns:
            dict[str, Any]: File content and metadata.
        """
        try:
            full_path = self._validate_path(path)
            if not full_path.exists():
                return {"error": f"File not found: {path}"}

            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()

            return {
                "success": True,
                "path": path,
                "content": content,
                "size": len(content),
            }
        except Exception as e:
            return {"error": str(e)}

    def filesystem_write(self, path: str, content: str) -> dict[str, Any]:
        """Write content to a file in the workspace.

        Args:
            path (str): Relative path within workspace.
            content (str): Content to write.

        Returns:
            dict[str, Any]: Operation result.
        """
        try:
            full_path = self._validate_path(path)
            full_path.parent.mkdir(parents=True, exist_ok=True)

            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)

            return {
                "success": True,
                "path": path,
                "size": len(content),
                "action": "created" if not full_path.exists() else "modified",
            }
        except Exception as e:
            return {"error": str(e)}

    def shell_execute(
        self, command: str, cwd: str | None = None, dry_run: bool = False
    ) -> dict[str, Any]:
        """Execute a shell command in the workspace.

        Args:
            command (str): Shell command to execute.
            cwd (str | None): Working directory (relative to workspace).
            dry_run (bool): If True, only validate without executing.

        Returns:
            dict[str, Any]: Execution result.
        """
        # Security: Block dangerous commands
        dangerous_keywords = ["rm -rf /", "dd if=", ":(){ :|:& };:", "mkfs", "format"]
        if any(keyword in command.lower() for keyword in dangerous_keywords):
            return {"error": "Command blocked for security reasons", "command": command}

        if dry_run:
            return {"dry_run": True, "command": command, "status": "would_execute"}

        try:
            work_dir = self.workspace_path
            if cwd:
                work_dir = self._validate_path(cwd)

            result = subprocess.run(
                command,
                shell=True,
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                timeout=30,
            )

            return {
                "success": result.returncode == 0,
                "command": command,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"error": "Command timed out after 30 seconds", "command": command}
        except Exception as e:
            return {"error": str(e), "command": command}
