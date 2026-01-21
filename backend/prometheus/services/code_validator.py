"""Enhanced code validation service with multi-stage validation.

This service provides comprehensive code quality checks:
1. Syntax validation (AST parsing)
2. Import verification (detect missing imports)
3. Type checking (optional, via mypy)
4. Code formatting (via Black)
"""

import ast
import asyncio
import subprocess
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
import structlog

logger = structlog.get_logger()


class ValidationStage(str, Enum):
    """Validation stages."""
    SYNTAX = "syntax"
    FORMATTING = "formatting"
    IMPORTS = "imports"
    TYPES = "types"


class ValidationResult(BaseModel):
    """Result from a validation stage."""
    stage: ValidationStage
    passed: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    fixed_content: Optional[str] = None
    auto_fixable: bool = False
    details: Dict[str, Any] = Field(default_factory=dict)


class CodeValidatorService:
    """Multi-stage code validation with auto-fixing."""

    def __init__(self, workspace_path: str, strict_mode: bool = False):
        """Initialize the code validator.

        Args:
            workspace_path: Path to workspace root
            strict_mode: Enable strict validation (types, etc.)
        """
        self.workspace_path = Path(workspace_path)
        self.strict_mode = strict_mode

        # Common standard library modules (for import suggestions)
        self.stdlib_modules = {
            'os', 'sys', 'json', 're', 'time', 'datetime', 'collections',
            'itertools', 'functools', 'pathlib', 'typing', 'asyncio',
            'logging', 'unittest', 'pytest', 'math', 'random', 'hashlib'
        }

        # Common module -> function mappings (for import suggestions)
        self.common_imports = {
            'Path': 'pathlib',
            'Dict': 'typing',
            'List': 'typing',
            'Optional': 'typing',
            'Any': 'typing',
            'sleep': 'time',
            'datetime': 'datetime',
            'timedelta': 'datetime',
        }

    async def validate_python(
        self,
        content: str,
        file_path: str,
        stages: Optional[List[ValidationStage]] = None
    ) -> List[ValidationResult]:
        """Run multi-stage validation on Python code.

        Args:
            content: File content to validate
            file_path: Path to file (relative to workspace)
            stages: Stages to run (default: all except types)

        Returns:
            List of validation results
        """
        if stages is None:
            stages = [
                ValidationStage.SYNTAX,
                ValidationStage.FORMATTING,
                ValidationStage.IMPORTS
            ]
            if self.strict_mode:
                stages.append(ValidationStage.TYPES)

        results = []
        current_content = content

        for stage in stages:
            logger.debug(
                "Running validation stage",
                stage=stage.value,
                file_path=file_path
            )

            result = await self._run_validation_stage(
                stage, current_content, file_path
            )
            results.append(result)

            # Use fixed content for next stages
            if result.fixed_content:
                current_content = result.fixed_content

            # Stop on critical error (unless auto-fixable)
            if not result.passed and not result.auto_fixable:
                logger.warning(
                    "Validation failed",
                    stage=stage.value,
                    errors=result.errors
                )
                break

        return results

    async def _run_validation_stage(
        self,
        stage: ValidationStage,
        content: str,
        file_path: str
    ) -> ValidationResult:
        """Run a single validation stage."""
        try:
            if stage == ValidationStage.SYNTAX:
                return await self._validate_syntax(content, file_path)
            elif stage == ValidationStage.FORMATTING:
                return await self._validate_formatting(content, file_path)
            elif stage == ValidationStage.IMPORTS:
                return await self._validate_imports(content, file_path)
            elif stage == ValidationStage.TYPES:
                return await self._validate_types(content, file_path)
            else:
                return ValidationResult(
                    stage=stage,
                    passed=True,
                    warnings=[f"Unknown stage: {stage}"]
                )
        except Exception as e:
            logger.error(
                "Validation stage failed",
                stage=stage.value,
                error=str(e)
            )
            return ValidationResult(
                stage=stage,
                passed=False,
                errors=[f"Validation error: {str(e)}"]
            )

    async def _validate_syntax(
        self,
        content: str,
        file_path: str
    ) -> ValidationResult:
        """Validate Python syntax using AST parsing."""
        errors = []
        warnings = []

        try:
            # Try to parse as Python
            ast.parse(content)

            return ValidationResult(
                stage=ValidationStage.SYNTAX,
                passed=True
            )

        except SyntaxError as e:
            # Get detailed error information
            error_line = e.lineno or 0
            error_msg = str(e.msg)
            error_text = e.text or ""

            errors.append(
                f"SyntaxError on line {error_line}: {error_msg}"
            )
            errors.append(f"  {error_text.strip()}")

            # Try to suggest fix
            suggestion = self._suggest_syntax_fix(error_msg, error_text)
            if suggestion:
                warnings.append(f"Suggestion: {suggestion}")

            return ValidationResult(
                stage=ValidationStage.SYNTAX,
                passed=False,
                errors=errors,
                warnings=warnings,
                auto_fixable=False,
                details={
                    "line": error_line,
                    "message": error_msg,
                    "text": error_text
                }
            )

    def _suggest_syntax_fix(self, error_msg: str, error_text: str) -> Optional[str]:
        """Suggest a fix for common syntax errors."""
        error_lower = error_msg.lower()

        if "invalid syntax" in error_lower:
            if ":" in error_text and error_text.strip().endswith(":"):
                return "Missing code block after colon - add indented code"
            if "(" in error_text and ")" not in error_text:
                return "Unclosed parenthesis - add closing ')'"
            if "[" in error_text and "]" not in error_text:
                return "Unclosed bracket - add closing ']'"
            if "{" in error_text and "}" not in error_text:
                return "Unclosed brace - add closing '}'"

        if "unexpected eof" in error_lower:
            return "File ends unexpectedly - check for unclosed brackets, quotes, or incomplete blocks"

        if "unterminated" in error_lower:
            if "string" in error_lower:
                return "Unterminated string - add closing quote"

        if "indentation" in error_lower:
            return "Indentation error - use consistent 4-space indentation"

        return None

    async def _validate_formatting(
        self,
        content: str,
        file_path: str
    ) -> ValidationResult:
        """Validate/fix code formatting with Black."""
        try:
            # Run Black to format code
            process = await asyncio.create_subprocess_exec(
                "black",
                "--check",
                "--quiet",
                "-",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate(content.encode())

            if process.returncode == 0:
                # Already formatted
                return ValidationResult(
                    stage=ValidationStage.FORMATTING,
                    passed=True
                )
            else:
                # Needs formatting - get formatted version
                format_process = await asyncio.create_subprocess_exec(
                    "black",
                    "--quiet",
                    "-",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

                formatted_stdout, _ = await format_process.communicate(content.encode())
                formatted_content = formatted_stdout.decode()

                return ValidationResult(
                    stage=ValidationStage.FORMATTING,
                    passed=False,
                    warnings=["Code formatting could be improved"],
                    fixed_content=formatted_content,
                    auto_fixable=True
                )

        except FileNotFoundError:
            # Black not installed - skip formatting
            return ValidationResult(
                stage=ValidationStage.FORMATTING,
                passed=True,
                warnings=["Black not installed - skipping formatting check"]
            )
        except Exception as e:
            logger.warning("Formatting check failed", error=str(e))
            return ValidationResult(
                stage=ValidationStage.FORMATTING,
                passed=True,
                warnings=[f"Formatting check failed: {str(e)}"]
            )

    async def _validate_imports(
        self,
        content: str,
        file_path: str
    ) -> ValidationResult:
        """Check for missing or unused imports."""
        errors = []
        warnings = []

        try:
            tree = ast.parse(content)

            # Extract all names used in the code
            used_names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    used_names.add(node.id)
                elif isinstance(node, ast.Attribute):
                    # For module.function calls
                    if isinstance(node.value, ast.Name):
                        used_names.add(node.value.id)

            # Extract imported names
            imported_names = set()
            import_statements = []

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        name = alias.asname or alias.name
                        imported_names.add(name)
                        import_statements.append((node.lineno, alias.name))

                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    for alias in node.names:
                        name = alias.asname or alias.name
                        imported_names.add(name)
                        import_statements.append((node.lineno, f"{module}.{alias.name}"))

            # Check for unused imports
            unused = []
            for name in imported_names:
                if name not in used_names and name != "_":
                    unused.append(name)

            if unused:
                warnings.append(f"Potentially unused imports: {', '.join(unused[:5])}")

            # Check for missing imports (heuristic)
            missing = []
            for name in used_names:
                # Skip builtins
                if name in dir(__builtins__):
                    continue

                # Skip if imported
                if name in imported_names:
                    continue

                # Check if it's a known module/function
                if name in self.common_imports:
                    module = self.common_imports[name]
                    missing.append(f"'{name}' might need: from {module} import {name}")

            if missing:
                errors.extend(missing[:5])  # Limit to 5 suggestions

            passed = len(errors) == 0

            return ValidationResult(
                stage=ValidationStage.IMPORTS,
                passed=passed,
                errors=errors,
                warnings=warnings,
                auto_fixable=False,
                details={
                    "imported": list(imported_names),
                    "used": list(used_names),
                    "unused": unused,
                    "potentially_missing": missing
                }
            )

        except Exception as e:
            # Don't fail on import check errors
            return ValidationResult(
                stage=ValidationStage.IMPORTS,
                passed=True,
                warnings=[f"Import check failed: {str(e)}"]
            )

    async def _validate_types(
        self,
        content: str,
        file_path: str
    ) -> ValidationResult:
        """Run mypy type checking."""
        try:
            # Write content to temp file
            full_path = self.workspace_path / file_path
            temp_file = full_path.with_suffix('.tmp.py')

            try:
                temp_file.write_text(content)

                # Run mypy
                process = await asyncio.create_subprocess_exec(
                    "mypy",
                    "--show-column-numbers",
                    "--no-error-summary",
                    "--no-color-output",
                    str(temp_file),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(self.workspace_path)
                )

                stdout, _ = await process.communicate()
                output = stdout.decode()

                # Parse mypy output
                errors = []
                warnings = []

                for line in output.splitlines():
                    if ": error:" in line:
                        errors.append(line)
                    elif ": warning:" in line:
                        warnings.append(line)

                passed = len(errors) == 0

                return ValidationResult(
                    stage=ValidationStage.TYPES,
                    passed=passed,
                    errors=errors[:10],  # Limit to 10
                    warnings=warnings[:10],
                    auto_fixable=False
                )

            finally:
                # Clean up temp file
                if temp_file.exists():
                    temp_file.unlink()

        except FileNotFoundError:
            # mypy not installed
            return ValidationResult(
                stage=ValidationStage.TYPES,
                passed=True,
                warnings=["mypy not installed - skipping type checking"]
            )
        except Exception as e:
            logger.warning("Type checking failed", error=str(e))
            return ValidationResult(
                stage=ValidationStage.TYPES,
                passed=True,
                warnings=[f"Type checking failed: {str(e)}"]
            )

    def get_validation_summary(self, results: List[ValidationResult]) -> Dict[str, Any]:
        """Get summary of validation results.

        Args:
            results: List of validation results

        Returns:
            Summary dictionary
        """
        total_stages = len(results)
        passed_stages = sum(1 for r in results if r.passed)
        total_errors = sum(len(r.errors) for r in results)
        total_warnings = sum(len(r.warnings) for r in results)
        auto_fixable = any(r.auto_fixable and r.fixed_content for r in results)

        return {
            "total_stages": total_stages,
            "passed_stages": passed_stages,
            "failed_stages": total_stages - passed_stages,
            "total_errors": total_errors,
            "total_warnings": total_warnings,
            "auto_fixable": auto_fixable,
            "all_passed": passed_stages == total_stages
        }
