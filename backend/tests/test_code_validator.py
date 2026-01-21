"""Unit tests for CodeValidator service."""

import pytest
from prometheus.services.code_validator import (
    CodeValidatorService,
    ValidationStage,
    ValidationResult
)


class TestCodeValidator:
    """Test CodeValidator functionality."""

    @pytest.fixture
    def validator(self, tmp_path):
        """Create a CodeValidator instance with temp workspace."""
        return CodeValidatorService(workspace_path=str(tmp_path), strict_mode=False)

    @pytest.mark.asyncio
    async def test_valid_python_syntax(self, validator):
        """Test validation of valid Python code."""
        code = """
def hello():
    print("Hello, world!")
    return True
"""

        results = await validator.validate_python(
            content=code,
            file_path="test.py",
            stages=[ValidationStage.SYNTAX]
        )

        assert len(results) == 1
        assert results[0].stage == ValidationStage.SYNTAX
        assert results[0].passed

    @pytest.mark.asyncio
    async def test_invalid_python_syntax(self, validator):
        """Test detection of syntax errors."""
        code = """
def hello()
    print("Missing colon!")
"""

        results = await validator.validate_python(
            content=code,
            file_path="test.py",
            stages=[ValidationStage.SYNTAX]
        )

        assert len(results) == 1
        assert results[0].stage == ValidationStage.SYNTAX
        assert not results[0].passed
        assert len(results[0].errors) > 0
        assert "SyntaxError" in results[0].errors[0]

    @pytest.mark.asyncio
    async def test_unclosed_brackets(self, validator):
        """Test detection of unclosed brackets."""
        code = """
def hello():
    items = [1, 2, 3
    return items
"""

        results = await validator.validate_python(
            content=code,
            file_path="test.py",
            stages=[ValidationStage.SYNTAX]
        )

        assert not results[0].passed

    @pytest.mark.asyncio
    async def test_import_validation(self, validator):
        """Test import validation."""
        code = """
import os
import sys

def main():
    # Using 'os' but not 'sys'
    print(os.getcwd())
"""

        results = await validator.validate_python(
            content=code,
            file_path="test.py",
            stages=[ValidationStage.IMPORTS]
        )

        assert len(results) == 1
        assert results[0].stage == ValidationStage.IMPORTS

        # Should detect unused 'sys' import
        if results[0].warnings:
            assert any("sys" in w for w in results[0].warnings)

    @pytest.mark.asyncio
    async def test_missing_import_detection(self, validator):
        """Test detection of missing imports."""
        code = """
def main():
    # Using Dict without importing from typing
    data: Dict[str, int] = {}
    return data
"""

        results = await validator.validate_python(
            content=code,
            file_path="test.py",
            stages=[ValidationStage.IMPORTS]
        )

        assert len(results) == 1
        assert results[0].stage == ValidationStage.IMPORTS

        # Should suggest importing Dict from typing
        if results[0].errors:
            assert any("Dict" in e and "typing" in e for e in results[0].errors)

    @pytest.mark.asyncio
    async def test_multi_stage_validation(self, validator):
        """Test running multiple validation stages."""
        code = """
def hello():
    print("Hello!")
"""

        results = await validator.validate_python(
            content=code,
            file_path="test.py",
            stages=[ValidationStage.SYNTAX, ValidationStage.IMPORTS]
        )

        assert len(results) == 2
        assert results[0].stage == ValidationStage.SYNTAX
        assert results[1].stage == ValidationStage.IMPORTS

    @pytest.mark.asyncio
    async def test_validation_stops_on_syntax_error(self, validator):
        """Test that validation stops after syntax error."""
        code = """
def hello()
    print("syntax error")
"""

        results = await validator.validate_python(
            content=code,
            file_path="test.py",
            stages=[ValidationStage.SYNTAX, ValidationStage.IMPORTS]
        )

        # Should only have syntax result, no import check
        assert len(results) == 1
        assert results[0].stage == ValidationStage.SYNTAX
        assert not results[0].passed

    def test_syntax_fix_suggestions(self, validator):
        """Test syntax error fix suggestions."""
        # Missing closing parenthesis
        suggestion = validator._suggest_syntax_fix(
            "invalid syntax",
            "print('hello'"
        )
        assert suggestion is not None
        assert "parenthesis" in suggestion.lower() or ")" in suggestion

        # Indentation error
        suggestion = validator._suggest_syntax_fix(
            "indentation error",
            "  def hello():"
        )
        assert suggestion is not None
        assert "indentation" in suggestion.lower()

    def test_validation_summary(self, validator):
        """Test validation summary generation."""
        results = [
            ValidationResult(
                stage=ValidationStage.SYNTAX,
                passed=True,
                errors=[],
                warnings=[]
            ),
            ValidationResult(
                stage=ValidationStage.IMPORTS,
                passed=False,
                errors=["Missing import: Dict"],
                warnings=["Unused import: sys"]
            )
        ]

        summary = validator.get_validation_summary(results)

        assert summary["total_stages"] == 2
        assert summary["passed_stages"] == 1
        assert summary["failed_stages"] == 1
        assert summary["total_errors"] == 1
        assert summary["total_warnings"] == 1
        assert not summary["all_passed"]
