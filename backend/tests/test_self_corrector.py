"""Unit tests for SelfCorrector service."""

import pytest
from prometheus.services.self_corrector import (
    SelfCorrectorService,
    LoopType,
    LoopDetection
)


class TestSelfCorrector:
    """Test SelfCorrector functionality."""

    @pytest.fixture
    def corrector(self):
        """Create a SelfCorrector instance."""
        return SelfCorrectorService()

    def test_initialization(self, corrector):
        """Test that corrector initializes correctly."""
        assert len(corrector.action_history) == 0
        assert len(corrector.error_patterns) == 0
        assert len(corrector.file_read_counts) == 0
        assert len(corrector.file_edit_counts) == 0

    def test_record_read_action(self, corrector):
        """Test recording file read actions."""
        corrector.record_action(
            iteration=1,
            tool="filesystem_read",
            args={"path": "test.py"},
            success=True
        )

        assert len(corrector.action_history) == 1
        assert corrector.file_read_counts["test.py"] == 1

    def test_record_edit_action(self, corrector):
        """Test recording file edit actions."""
        corrector.record_action(
            iteration=1,
            tool="filesystem_replace_lines",
            args={"path": "test.py"},
            success=True
        )

        assert len(corrector.action_history) == 1
        assert corrector.file_edit_counts["test.py"] == 1

    def test_detect_read_loop(self, corrector):
        """Test detection of read loops."""
        # Simulate reading the same file multiple times
        for i in range(6):
            corrector.record_action(
                iteration=i + 1,
                tool="filesystem_read",
                args={"path": "test.py"},
                success=True
            )

        loop = corrector.detect_loops(recent_window=10)

        assert loop is not None
        assert loop.loop_type == LoopType.READ_LOOP
        assert loop.severity >= 7
        assert "test.py" in loop.suggestion

    def test_no_read_loop_with_edits(self, corrector):
        """Test that reads mixed with edits don't trigger loop detection."""
        # Alternate between reads and edits
        for i in range(6):
            if i % 2 == 0:
                corrector.record_action(
                    iteration=i + 1,
                    tool="filesystem_read",
                    args={"path": "test.py"},
                    success=True
                )
            else:
                corrector.record_action(
                    iteration=i + 1,
                    tool="filesystem_replace_lines",
                    args={"path": "test.py"},
                    success=True
                )

        loop = corrector.detect_loops(recent_window=10)

        # Should not detect a read loop because we're also making edits
        assert loop is None

    def test_detect_syntax_loop(self, corrector):
        """Test detection of syntax error loops."""
        # Simulate repeated syntax errors on same file
        for i in range(4):
            corrector.record_action(
                iteration=i + 1,
                tool="filesystem_replace_lines",
                args={"path": "buggy.py"},
                success=False,
                error="SyntaxError: invalid syntax"
            )

        loop = corrector.detect_loops()

        assert loop is not None
        assert loop.loop_type == LoopType.SYNTAX_LOOP
        assert loop.severity >= 8
        assert "buggy.py" in loop.suggestion
        assert loop.should_stop

    def test_detect_tool_repetition(self, corrector):
        """Test detection of tool repetition without progress."""
        # Simulate repeated failed tool calls
        for i in range(5):
            corrector.record_action(
                iteration=i + 1,
                tool="execute_command",
                args={"command": "npm install"},
                success=False,
                error="Command failed"
            )

        loop = corrector.detect_loops(recent_window=10)

        assert loop is not None
        assert loop.loop_type == LoopType.TOOL_REPETITION
        assert "execute_command" in loop.evidence[0]

    def test_no_loop_with_progress(self, corrector):
        """Test that successful operations don't trigger loop detection."""
        # Simulate successful operations
        for i in range(10):
            corrector.record_action(
                iteration=i + 1,
                tool="filesystem_read",
                args={"path": f"file{i}.py"},  # Different files
                success=True
            )

        loop = corrector.detect_loops(recent_window=10)

        # Should not detect a loop - different files each time
        assert loop is None

    def test_suggest_alternative_no_history(self, corrector):
        """Test alternative suggestion with no history."""
        suggestion = corrector.suggest_alternative("current approach")

        assert "not enough history" in suggestion.lower()

    def test_suggest_alternative_with_failures(self, corrector):
        """Test alternative suggestions based on failure patterns."""
        # Record some failed read operations
        for i in range(3):
            corrector.record_action(
                iteration=i + 1,
                tool="filesystem_read",
                args={"path": "missing.py"},
                success=False,
                error="File not found"
            )

        suggestion = corrector.suggest_alternative("trying to read files")

        assert "codebase_search" in suggestion or "different" in suggestion.lower()

    def test_learn_from_error(self, corrector):
        """Test error pattern learning."""
        corrector.learn_from_error(
            error_type="syntax",
            file_path="test.py",
            error_message="SyntaxError: invalid syntax on line 10"
        )

        assert len(corrector.error_patterns) == 1

        # Learn same error again
        corrector.learn_from_error(
            error_type="syntax",
            file_path="test.py",
            error_message="SyntaxError: invalid syntax on line 10"
        )

        # Should update count, not create new pattern
        assert len(corrector.error_patterns) == 1
        pattern = list(corrector.error_patterns.values())[0]
        assert pattern.count == 2

    def test_get_error_history(self, corrector):
        """Test retrieving error history."""
        # Add some errors
        corrector.learn_from_error("syntax", "file1.py", "Error 1")
        corrector.learn_from_error("import", "file1.py", "Error 2")
        corrector.learn_from_error("syntax", "file2.py", "Error 3")

        # Get all errors
        all_errors = corrector.get_error_history()
        assert len(all_errors) == 3

        # Get errors for specific file
        file1_errors = corrector.get_error_history(file_path="file1.py")
        assert len(file1_errors) == 2

    def test_reset(self, corrector):
        """Test resetting corrector state."""
        # Add some data
        corrector.record_action(1, "filesystem_read", {"path": "test.py"}, True)
        corrector.learn_from_error("syntax", "test.py", "Error")

        assert len(corrector.action_history) > 0
        assert len(corrector.error_patterns) > 0

        # Reset
        corrector.reset()

        assert len(corrector.action_history) == 0
        assert len(corrector.error_patterns) == 0
        assert len(corrector.file_read_counts) == 0

    def test_get_summary(self, corrector):
        """Test getting execution summary."""
        # Add some actions
        corrector.record_action(1, "filesystem_read", {"path": "test.py"}, True)
        corrector.record_action(2, "filesystem_write", {"path": "test.py"}, True)
        corrector.record_action(3, "filesystem_read", {"path": "test.py"}, False, "Error")

        summary = corrector.get_summary()

        assert summary["total_actions"] == 3
        assert summary["successful_actions"] == 2
        assert summary["failed_actions"] == 1
        assert summary["files_read"] == 1
        assert summary["files_edited"] == 1
        assert summary["most_read_file"] == "test.py"

    def test_multiple_file_tracking(self, corrector):
        """Test tracking multiple files."""
        # Read multiple files
        corrector.record_action(1, "filesystem_read", {"path": "file1.py"}, True)
        corrector.record_action(2, "filesystem_read", {"path": "file2.py"}, True)
        corrector.record_action(3, "filesystem_read", {"path": "file1.py"}, True)
        corrector.record_action(4, "filesystem_read", {"path": "file1.py"}, True)

        assert corrector.file_read_counts["file1.py"] == 3
        assert corrector.file_read_counts["file2.py"] == 1

        summary = corrector.get_summary()
        assert summary["most_read_file"] == "file1.py"
