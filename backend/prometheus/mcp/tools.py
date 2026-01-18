import os
import re
import shlex
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
            file_existed = full_path.exists()
            full_path.parent.mkdir(parents=True, exist_ok=True)

            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)

            return {
                "success": True,
                "path": path,
                "size": len(content),
                "action": "modified" if file_existed else "created",
            }
        except Exception as e:
            return {"error": str(e)}

    def filesystem_list(self, path: str = "") -> dict[str, Any]:
        """List contents of a directory in the workspace.

        Args:
            path (str): Relative path within workspace (empty for root).

        Returns:
            dict[str, Any]: Directory listing with files and subdirectories.
        """
        try:
            if path:
                full_path = self._validate_path(path)
            else:
                full_path = self.workspace_path

            if not full_path.exists():
                return {"error": f"Directory not found: {path}"}

            if not full_path.is_dir():
                return {"error": f"Path is not a directory: {path}"}

            items = []
            for item in sorted(full_path.iterdir()):
                # Skip hidden files
                if item.name.startswith("."):
                    continue

                item_info = {
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "path": str(item.relative_to(self.workspace_path)),
                }

                if item.is_file():
                    item_info["size"] = item.stat().st_size

                items.append(item_info)

            return {
                "success": True,
                "path": path,
                "items": items,
            }
        except Exception as e:
            return {"error": str(e)}

    def run_python(
        self, file_path: str, stdin_input: str = "", args: str = ""
    ) -> dict[str, Any]:
        """Run a Python file with optional stdin input for testing.

        Args:
            file_path (str): Path to Python file within workspace.
            stdin_input (str): Input to provide via stdin (for testing interactive programs).
            args (str): Command line arguments to pass.

        Returns:
            dict[str, Any]: Execution result with stdout, stderr, return code.
        """
        try:
            full_path = self._validate_path(file_path)
            if not full_path.exists():
                return {"error": f"File not found: {file_path}"}

            cmd = ["python3", str(full_path)]
            if args:
                cmd.extend(shlex.split(args))

            result = subprocess.run(
                cmd,
                shell=False,
                cwd=str(self.workspace_path),
                capture_output=True,
                text=True,
                timeout=10,
                input=stdin_input if stdin_input else None,
            )

            return {
                "success": result.returncode == 0,
                "file": file_path,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {
                "error": "Script timed out after 10 seconds (may need stdin input)",
                "file": file_path,
                "hint": "Use stdin_input parameter to provide test input for interactive scripts",
            }
        except Exception as e:
            return {"error": str(e), "file": file_path}

    def run_tests(self, test_path: str = "") -> dict[str, Any]:
        """Run pytest on test files in the workspace.

        Args:
            test_path (str): Specific test file or directory (empty for all tests).

        Returns:
            dict[str, Any]: Test results.
        """
        try:
            cmd = ["python3", "-m", "pytest", "-v", "--tb=short"]
            if test_path:
                full_path = self._validate_path(test_path)
                cmd.append(str(full_path))
            else:
                cmd.append(str(self.workspace_path))

            result = subprocess.run(
                cmd,
                shell=False,
                cwd=str(self.workspace_path),
                capture_output=True,
                text=True,
                timeout=60,
            )

            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"error": "Tests timed out after 60 seconds"}
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
        # Security: Block dangerous command patterns using regex
        dangerous_patterns = [
            r'rm\s+-rf\s+/',  # rm -rf /
            r'rm\s+-fr\s+/',  # rm -fr / (alternate flag order)
            r'rm\s+-rf\s+/\*',  # rm -rf /*
            r':\(\)\{.*\}',  # Fork bomb
            r'dd\s+if=',  # Disk destruction
            r'mkfs\s+',  # Format filesystem
            r'format\s+',  # Format command
            r'>\s*/dev/sd',  # Write to block device
            r'wget.*\|.*sh',  # Download and pipe to shell
            r'curl.*\|.*sh',  # Download and pipe to shell
        ]
        if any(re.search(pattern, command, re.IGNORECASE) for pattern in dangerous_patterns):
            return {"error": "Command blocked for security reasons", "command": command}

        # Security: Block shell metacharacters to prevent command injection
        dangerous_chars = [';', '|', '&&', '||', '`', '$', '(', ')', '<', '>']
        if any(char in command for char in dangerous_chars):
            return {"error": "Command contains unsafe characters", "command": command}

        if dry_run:
            return {"dry_run": True, "command": command, "status": "would_execute"}

        try:
            work_dir = self.workspace_path
            if cwd:
                work_dir = self._validate_path(cwd)

            # Security: Use shell=False with shlex.split() to prevent injection
            # This only allows single commands, not pipes/redirections
            command_parts = shlex.split(command)
            if not command_parts:
                return {"error": "Empty command", "command": command}

            result = subprocess.run(
                command_parts,
                shell=False,
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
