"""Post-edit verification service with linting and test execution.

This service runs various checks after code edits:
1. Syntax validation (always, blocking)
2. Linter checks (non-blocking warnings)
3. Type checking (non-blocking if enabled)
4. Related tests (blocking for related tests, warnings for unrelated)
"""

import asyncio
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
import structlog

from prometheus.services.code_validator import CodeValidatorService, ValidationStage

logger = structlog.get_logger()


class VerificationType(str, Enum):
    """Types of verification checks."""
    SYNTAX = "syntax"
    LINT = "lint"
    TYPE_CHECK = "type_check"
    UNIT_TESTS = "unit_tests"
    INTEGRATION_TESTS = "integration_tests"


class VerificationResult(BaseModel):
    """Result from a verification check."""
    type: VerificationType
    passed: bool
    blocking: bool  # Should this stop execution?
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    details: Dict[str, Any] = Field(default_factory=dict)


class VerificationLoopService:
    """Post-edit verification with escalating warnings."""

    def __init__(
        self,
        code_validator: CodeValidatorService,
        workspace_path: str,
        verification_level: str = "standard"
    ):
        """Initialize verification service.

        Args:
            code_validator: CodeValidator instance
            workspace_path: Workspace root path
            verification_level: "minimal", "standard", or "thorough"
        """
        self.code_validator = code_validator
        self.workspace_path = Path(workspace_path)
        self.verification_level = verification_level

        # Test path patterns
        self.test_patterns = [
            "test_*.py",
            "*_test.py",
            "tests/*.py",
            "test/*.py"
        ]

    async def verify_changes(
        self,
        changed_files: List[str]
    ) -> List[VerificationResult]:
        """Run verification checks on changed files.

        Args:
            changed_files: List of file paths that were modified

        Returns:
            List of verification results
        """
        results = []

        # Always run syntax check (blocking)
        for file_path in changed_files:
            if file_path.endswith('.py'):
                syntax_result = await self._verify_syntax(file_path)
                results.append(syntax_result)

                # Stop on syntax errors
                if not syntax_result.passed:
                    logger.error(
                        "Syntax error detected",
                        file_path=file_path,
                        errors=syntax_result.errors
                    )
                    return results

        # Lint check (non-blocking warnings)
        if self.verification_level in ["standard", "thorough"]:
            for file_path in changed_files:
                if file_path.endswith('.py'):
                    lint_result = await self._verify_lint(file_path)
                    if lint_result:
                        results.append(lint_result)

        # Type check (non-blocking if enabled)
        if self.verification_level == "thorough":
            for file_path in changed_files:
                if file_path.endswith('.py'):
                    type_result = await self._verify_types(file_path)
                    if type_result:
                        results.append(type_result)

        # Tests (requires user decision on failure)
        if self.verification_level in ["standard", "thorough"]:
            test_result = await self._verify_tests(changed_files)
            if test_result:
                results.append(test_result)

        logger.info(
            "Verification complete",
            total_checks=len(results),
            passed=sum(1 for r in results if r.passed),
            failed=sum(1 for r in results if not r.passed)
        )

        return results

    async def _verify_syntax(self, file_path: str) -> VerificationResult:
        """Verify syntax (always blocking)."""
        full_path = self.workspace_path / file_path

        try:
            if not full_path.exists():
                return VerificationResult(
                    type=VerificationType.SYNTAX,
                    passed=False,
                    blocking=True,
                    errors=[f"File not found: {file_path}"]
                )

            content = full_path.read_text()

            # Use CodeValidator for syntax check
            validation_results = await self.code_validator.validate_python(
                content=content,
                file_path=file_path,
                stages=[ValidationStage.SYNTAX]
            )

            syntax_result = validation_results[0]

            return VerificationResult(
                type=VerificationType.SYNTAX,
                passed=syntax_result.passed,
                blocking=True,  # Syntax errors always block
                errors=syntax_result.errors,
                warnings=syntax_result.warnings,
                details=syntax_result.details
            )

        except Exception as e:
            logger.error("Syntax verification failed", file_path=file_path, error=str(e))
            return VerificationResult(
                type=VerificationType.SYNTAX,
                passed=False,
                blocking=True,
                errors=[f"Syntax check failed: {str(e)}"]
            )

    async def _verify_lint(self, file_path: str) -> Optional[VerificationResult]:
        """Run linter (non-blocking warnings)."""
        full_path = self.workspace_path / file_path

        try:
            # Try ruff first (faster)
            process = await asyncio.create_subprocess_exec(
                "ruff",
                "check",
                "--output-format=text",
                str(full_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace_path)
            )

            stdout, stderr = await process.communicate()
            output = stdout.decode()

            if process.returncode == 0:
                # No issues
                return VerificationResult(
                    type=VerificationType.LINT,
                    passed=True,
                    blocking=False
                )
            else:
                # Parse ruff output
                warnings = []
                for line in output.splitlines():
                    if line.strip() and not line.startswith("Found"):
                        warnings.append(line)

                return VerificationResult(
                    type=VerificationType.LINT,
                    passed=False,
                    blocking=False,  # Lint warnings don't block
                    warnings=warnings[:10],  # Limit to 10
                    details={"linter": "ruff"}
                )

        except FileNotFoundError:
            # ruff not installed - try flake8
            try:
                process = await asyncio.create_subprocess_exec(
                    "flake8",
                    str(full_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(self.workspace_path)
                )

                stdout, _ = await process.communicate()
                output = stdout.decode()

                if process.returncode == 0:
                    return VerificationResult(
                        type=VerificationType.LINT,
                        passed=True,
                        blocking=False
                    )
                else:
                    warnings = output.splitlines()[:10]
                    return VerificationResult(
                        type=VerificationType.LINT,
                        passed=False,
                        blocking=False,
                        warnings=warnings,
                        details={"linter": "flake8"}
                    )

            except FileNotFoundError:
                # No linter installed
                logger.debug("No linter available (ruff or flake8)")
                return None

        except Exception as e:
            logger.warning("Lint check failed", file_path=file_path, error=str(e))
            return None

    async def _verify_types(self, file_path: str) -> Optional[VerificationResult]:
        """Run type checking (non-blocking)."""
        full_path = self.workspace_path / file_path

        try:
            # Use CodeValidator for type checking
            content = full_path.read_text()

            validation_results = await self.code_validator.validate_python(
                content=content,
                file_path=file_path,
                stages=[ValidationStage.TYPES]
            )

            type_result = validation_results[0]

            if "mypy not installed" in " ".join(type_result.warnings):
                return None  # Skip if mypy not available

            return VerificationResult(
                type=VerificationType.TYPE_CHECK,
                passed=type_result.passed,
                blocking=False,  # Type errors don't block
                errors=type_result.errors,
                warnings=type_result.warnings
            )

        except Exception as e:
            logger.warning("Type check failed", file_path=file_path, error=str(e))
            return None

    async def _verify_tests(self, changed_files: List[str]) -> Optional[VerificationResult]:
        """Run related tests."""
        # Find test files related to changed files
        test_files = []

        for file_path in changed_files:
            test_path = self._get_test_path(file_path)
            if test_path and test_path.exists():
                test_files.append(str(test_path))

        if not test_files:
            return VerificationResult(
                type=VerificationType.UNIT_TESTS,
                passed=True,
                blocking=False,
                warnings=["No tests found for changed files"]
            )

        try:
            # Run pytest with timeout
            process = await asyncio.create_subprocess_exec(
                "pytest",
                "-v",
                "--tb=short",
                "--no-header",
                *test_files,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace_path)
            )

            # Wait for tests with timeout (5 minutes)
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=300.0  # 5 minute timeout
                )
                output = stdout.decode()
            except asyncio.TimeoutError:
                # Kill the process if it times out
                process.kill()
                await process.wait()
                logger.error("Test execution timed out", test_files=test_files)
                return VerificationResult(
                    type=VerificationType.UNIT_TESTS,
                    passed=False,
                    blocking=False,
                    errors=["Test execution timed out after 5 minutes"]
                )

            passed = process.returncode == 0

            # Parse output for failures
            errors = []
            if not passed:
                for line in output.splitlines():
                    if "FAILED" in line or "ERROR" in line:
                        errors.append(line)

            return VerificationResult(
                type=VerificationType.UNIT_TESTS,
                passed=passed,
                blocking=False,  # User decides whether to continue
                errors=errors[:10],
                details={
                    "test_files": test_files,
                    "output": output[:2000]  # Limit output
                }
            )

        except FileNotFoundError:
            logger.debug("pytest not installed - skipping tests")
            return None
        except Exception as e:
            logger.warning("Test execution failed", error=str(e))
            return None

    def _get_test_path(self, file_path: str) -> Optional[Path]:
        """Get test file path for a source file.

        Converts:
        - src/module.py -> tests/test_module.py
        - lib/utils.py -> tests/test_utils.py
        - app/service.py -> tests/test_service.py
        """
        path = Path(file_path)

        # Skip if already a test file
        if path.name.startswith("test_") or path.name.endswith("_test.py"):
            return None

        # Common test directory structures
        test_dirs = [
            self.workspace_path / "tests",
            self.workspace_path / "test",
            path.parent / "tests",
            path.parent / "test"
        ]

        test_filename = f"test_{path.stem}.py"

        for test_dir in test_dirs:
            test_path = test_dir / test_filename
            if test_path.exists():
                return test_path

        return None

    def get_verification_summary(
        self,
        results: List[VerificationResult]
    ) -> Dict[str, Any]:
        """Get summary of verification results."""
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        blocking_failures = [r for r in results if not r.passed and r.blocking]
        non_blocking_failures = [r for r in results if not r.passed and not r.blocking]

        return {
            "total_checks": total,
            "passed": passed,
            "failed": total - passed,
            "blocking_failures": len(blocking_failures),
            "non_blocking_failures": len(non_blocking_failures),
            "all_passed": passed == total,
            "can_continue": len(blocking_failures) == 0
        }
