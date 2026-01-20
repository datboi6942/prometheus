import json
import subprocess
import asyncio
from pathlib import Path
from typing import Any, List, Dict
from pydantic import BaseModel
import structlog

logger = structlog.get_logger()

class Diagnostic(BaseModel):
    line: int
    column: int
    severity: str  # "error", "warning", "info", "hint"
    message: str
    source: str | None = None
    code: str | int | None = None

class DiagnosticsService:
    """LSP-based and CLI-based diagnostics for multiple languages."""

    def __init__(self, workspace_path: str):
        self.workspace_path = Path(workspace_path)

    async def get_diagnostics(self, file_path: str) -> List[Diagnostic]:
        """Get diagnostics for a specific file.

        Args:
            file_path: Relative path to the file within the workspace.

        Returns:
            List[Diagnostic]: List of diagnostic issues found.
        """
        full_path = (self.workspace_path / file_path).resolve()
        if not full_path.exists():
            return []

        ext = full_path.suffix.lower()
        if ext == ".py":
            return await self._get_python_diagnostics(full_path)
        elif ext in [".js", ".ts", ".jsx", ".tsx"]:
            return await self._get_typescript_diagnostics(full_path)
        
        return []

    async def _get_python_diagnostics(self, full_path: Path) -> List[Diagnostic]:
        """Get diagnostics for Python files using ruff (as a reliable LSP alternative)."""
        try:
            # Using ruff as it's much faster and easier to use via CLI than full pylsp JSON-RPC
            cmd = ["ruff", "check", "--format", "json", str(full_path)]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace_path)
            )
            stdout, stderr = await process.communicate()
            
            if not stdout:
                return []

            data = json.loads(stdout.decode())
            diagnostics = []
            for item in data:
                diagnostics.append(Diagnostic(
                    line=item["location"]["row"],
                    column=item["location"]["column"],
                    severity="error" if item["code"].startswith("E") or item["code"].startswith("F") else "warning",
                    message=item["message"],
                    source="ruff",
                    code=item["code"]
                ))
            return diagnostics
        except Exception as e:
            logger.error("Failed to get Python diagnostics", error=str(e))
            return []

    async def _get_typescript_diagnostics(self, full_path: Path) -> List[Diagnostic]:
        """Get diagnostics for JS/TS files using tsc or eslint."""
        try:
            # Basic implementation using tsc --noEmit for type checking
            # This requires node_modules to be present in the workspace
            cmd = ["npx", "tsc", "--noEmit", "--skipLibCheck", str(full_path)]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace_path)
            )
            stdout, stderr = await process.communicate()
            
            output = stdout.decode()
            diagnostics = []
            
            # Simple tsc output parsing: path/to/file.ts(line,col): error TS1234: message
            import re
            pattern = r".*\((\d+),(\d+)\): error (TS\d+): (.*)"
            for line in output.splitlines():
                match = re.match(pattern, line)
                if match:
                    diagnostics.append(Diagnostic(
                        line=int(match.group(1)),
                        column=int(match.group(2)),
                        severity="error",
                        message=match.group(4),
                        source="tsc",
                        code=match.group(3)
                    ))
            
            return diagnostics
        except Exception as e:
            logger.error("Failed to get TypeScript diagnostics", error=str(e))
            return []

    async def get_all_diagnostics(self, paths: List[str]) -> Dict[str, List[Diagnostic]]:
        """Get diagnostics for multiple files."""
        results = {}
        for path in paths:
            results[path] = await self.get_diagnostics(path)
        return results
