"""Self-correction service for detecting stuck states and suggesting alternatives.

This service:
1. Detects when the agent is stuck in loops (read loops, syntax loops, tool repetition)
2. Suggests alternative approaches when stuck
3. Learns from error patterns to prevent recurrence
"""

from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict, Counter
from pydantic import BaseModel, Field
import structlog
from datetime import datetime, timezone

logger = structlog.get_logger()


class LoopType(str):
    """Types of loops that can be detected."""
    READ_LOOP = "read_loop"           # Repeatedly reading same files
    SYNTAX_LOOP = "syntax_loop"       # Repeated syntax errors on same file
    TOOL_REPETITION = "tool_repetition"  # Same tool called repeatedly without progress
    EDIT_REVERT = "edit_revert"       # Editing and reverting same changes


class LoopDetection(BaseModel):
    """Information about a detected loop."""
    loop_type: str
    severity: int = Field(ge=1, le=10)  # 1-10 severity scale
    evidence: List[str]
    suggestion: str
    should_stop: bool = False  # Should we stop the agent immediately?


class ActionRecord(BaseModel):
    """Record of a single action taken by the agent."""
    iteration: int
    tool: str
    args: Dict[str, Any]
    timestamp: str
    success: bool
    error: Optional[str] = None
    execution_time: Optional[float] = None  # Time in seconds


class ErrorPattern(BaseModel):
    """A pattern of repeated errors."""
    error_type: str
    file_path: Optional[str]
    error_message: str
    count: int
    first_seen: str
    last_seen: str


class SelfCorrectorService:
    """Detects failure patterns and suggests corrections."""

    def __init__(self):
        """Initialize the self-corrector."""
        # Track action history
        self.action_history: List[ActionRecord] = []

        # Track error patterns
        self.error_patterns: Dict[str, ErrorPattern] = {}

        # Track file interactions
        self.file_read_counts: Dict[str, int] = defaultdict(int)
        self.file_edit_counts: Dict[str, int] = defaultdict(int)
        self.file_syntax_errors: Dict[str, List[str]] = defaultdict(list)

        # Track tool usage
        self.tool_call_sequence: List[Tuple[str, Dict[str, Any]]] = []

        # Configuration
        self.read_loop_threshold = 5  # Max reads of same file before warning
        self.syntax_loop_threshold = 3  # Max syntax errors on same file
        self.tool_repetition_threshold = 4  # Max identical tool calls
        
        # Progressive intervention levels
        self.progressive_intervention = True
        self.intervention_levels = {
            "warning": 2,      # Level 1: Warning nudges after 2 duplicate reads
            "restriction": 3,  # Level 2: Tool restriction after 3 duplicate reads
            "forced_edit": 5,  # Level 3: Forced edit requirement after 5 reads
            "reset": 8         # Level 4: Task reset with preserved context
        }
        
        # Syntax error recovery
        self.syntax_auto_rollback_threshold = 2  # Auto-rollback after 2 syntax errors on same file
        self.max_total_syntax_errors = 8  # Abort if too many syntax errors overall
        
        # Execution time tracking
        self.slow_tool_threshold = 30.0  # 30 seconds threshold for slow tools
        self.timeout_threshold = 120.0   # 2 minute timeout threshold
        
        # Session memory management
        self.max_history_size = 50  # Keep last 50 actions in history
        self.enable_sliding_window = True  # Enable automatic pruning

    def _get_intervention_level(self, read_count: int) -> Optional[str]:
        """Get intervention level based on read count.
        
        Args:
            read_count: Number of times file has been read
            
        Returns:
            Intervention level name or None if no intervention needed
        """
        if not self.progressive_intervention:
            return None
            
        if read_count >= self.intervention_levels["reset"]:
            return "reset"
        elif read_count >= self.intervention_levels["forced_edit"]:
            return "forced_edit"
        elif read_count >= self.intervention_levels["restriction"]:
            return "restriction"
        elif read_count >= self.intervention_levels["warning"]:
            return "warning"
        return None

    def _prune_history(self):
        """Prune action history to keep only recent actions (sliding window)."""
        if not self.enable_sliding_window or len(self.action_history) <= self.max_history_size:
            return
            
        # Keep only the most recent actions
        self.action_history = self.action_history[-self.max_history_size:]
        
        # Rebuild derived data structures from pruned history
        self.file_read_counts.clear()
        self.file_edit_counts.clear()
        self.file_syntax_errors.clear()
        self.tool_call_sequence.clear()
        
        # Re-populate from pruned history
        for action in self.action_history:
            # Track tool sequence
            self.tool_call_sequence.append((action.tool, action.args))
            
            # Track file reads
            if action.tool in ["filesystem_read", "read_file"]:
                file_path = action.args.get("path", "")
                if file_path:
                    self.file_read_counts[file_path] += 1
            
            # Track file edits
            if action.tool in ["filesystem_write", "filesystem_replace_lines", "filesystem_search_replace"]:
                file_path = action.args.get("path", "")
                if file_path:
                    self.file_edit_counts[file_path] += 1
            
            # Track syntax errors
            if not action.success and action.error and "syntax" in action.error.lower():
                file_path = action.args.get("path", "")
                if file_path:
                    self.file_syntax_errors[file_path].append(action.error)
        
        logger.debug(
            "History pruned",
            remaining_actions=len(self.action_history),
            max_history=self.max_history_size
        )

    def record_action(
        self,
        iteration: int,
        tool: str,
        args: Dict[str, Any],
        success: bool,
        error: Optional[str] = None,
        execution_time: Optional[float] = None
    ) -> None:
        """Record an action taken by the agent.

        Args:
            iteration: Current iteration number
            tool: Tool name that was called
            args: Arguments passed to the tool
            success: Whether the tool call succeeded
            error: Error message if tool call failed
            execution_time: Time taken to execute the tool in seconds
        """
        action = ActionRecord(
            iteration=iteration,
            tool=tool,
            args=args,
            timestamp=datetime.now(timezone.utc).isoformat(),
            success=success,
            error=error,
            execution_time=execution_time
        )
        self.action_history.append(action)
        self.tool_call_sequence.append((tool, args))

        # Track file-specific actions
        if tool in ["filesystem_read", "read_file"]:
            file_path = args.get("path", "")
            if file_path:
                self.file_read_counts[file_path] += 1

        elif tool in ["filesystem_write", "filesystem_replace_lines", "filesystem_search_replace"]:
            file_path = args.get("path", "")
            if file_path:
                self.file_edit_counts[file_path] += 1

        # Track syntax errors
        if not success and error and "syntax" in error.lower():
            file_path = args.get("path", "")
            if file_path:
                self.file_syntax_errors[file_path].append(error)
        
        # Prune history if needed (sliding window)
        self._prune_history()

        logger.debug(
            "Action recorded",
            iteration=iteration,
            tool=tool,
            success=success,
            total_actions=len(self.action_history)
        )

    def detect_loops(self, recent_window: int = 10) -> Optional[LoopDetection]:
        """Detect if agent is stuck in a loop.

        Args:
            recent_window: Number of recent actions to analyze

        Returns:
            LoopDetection if a loop is detected, None otherwise
        """
        if len(self.action_history) < 3:
            return None  # Not enough history to detect loops

        # Check for read loops
        read_loop = self._detect_read_loop(recent_window)
        if read_loop:
            return read_loop

        # Check for syntax error loops
        syntax_loop = self._detect_syntax_loop()
        if syntax_loop:
            return syntax_loop

        # Check for tool repetition
        tool_repetition = self._detect_tool_repetition(recent_window)
        if tool_repetition:
            return tool_repetition

        return None

    def _detect_read_loop(self, window: int) -> Optional[LoopDetection]:
        """Detect if agent keeps reading the same files with progressive intervention."""
        recent_actions = self.action_history[-window:]
        read_actions = [
            a for a in recent_actions
            if a.tool in ["filesystem_read", "read_file"]
        ]

        if len(read_actions) < self.read_loop_threshold:
            return None

        # Count unique files being read
        file_paths = [a.args.get("path", "") for a in read_actions]
        file_counts = Counter(file_paths)

        # Find most read file
        if not file_counts:
            return None

        most_read_file, recent_read_count = file_counts.most_common(1)[0]
        total_read_count = self.file_read_counts.get(most_read_file, 0)
        
        # Check if we're making any edits
        recent_edits = [
            a for a in recent_actions
            if a.tool in ["filesystem_write", "filesystem_replace_lines", "filesystem_search_replace"]
        ]
        
        # Determine intervention level
        intervention_level = self._get_intervention_level(total_read_count)
        
        if intervention_level == "reset" or total_read_count >= self.intervention_levels["reset"]:
            # Level 4: Task reset with preserved context
            return LoopDetection(
                loop_type=LoopType.READ_LOOP,
                severity=10,
                evidence=[
                    f"Read '{most_read_file}' {total_read_count} times total ({recent_read_count} recent)",
                    f"Only {len(recent_edits)} edit actions in last {window} actions",
                    "Agent is completely stuck - task reset required"
                ],
                suggestion=(
                    f"🛑 CRITICAL: You've read '{most_read_file}' {total_read_count} TIMES!\n"
                    "This task is being RESET. All tool calls are BLOCKED.\n"
                    "The system will preserve context and restart with a new strategy.\n"
                    "Please wait for system intervention."
                ),
                should_stop=True
            )
        elif intervention_level == "forced_edit" or total_read_count >= self.intervention_levels["forced_edit"]:
            # Level 3: Forced edit requirement
            return LoopDetection(
                loop_type=LoopType.READ_LOOP,
                severity=9,
                evidence=[
                    f"Read '{most_read_file}' {total_read_count} times total ({recent_read_count} recent)",
                    f"Only {len(recent_edits)} edit actions in same period",
                    "Agent must edit now - further reads blocked"
                ],
                suggestion=(
                    f"🚫 FORCED EDIT: You've read '{most_read_file}' {total_read_count} times.\n"
                    "ALL READ OPERATIONS ARE NOW BLOCKED for this file.\n"
                    "You MUST edit the file NOW using filesystem_replace_lines or filesystem_search_replace.\n"
                    "Example:\n"
                    f'{{"tool": "filesystem_replace_lines", "args": {{"path": "{most_read_file}", "start_line": 1, "end_line": 10, "replacement": "your fixed code here"}}}}'
                ),
                should_stop=False  # Agent can still act, but reads blocked
            )
        elif intervention_level == "restriction" or total_read_count >= self.intervention_levels["restriction"]:
            # Level 2: Tool restriction
            return LoopDetection(
                loop_type=LoopType.READ_LOOP,
                severity=8,
                evidence=[
                    f"Read '{most_read_file}' {total_read_count} times total ({recent_read_count} recent)",
                    f"Only {len(recent_edits)} edit actions in same period",
                    "Agent showing strong analysis paralysis"
                ],
                suggestion=(
                    f"⚠️ TOOL RESTRICTION: You've read '{most_read_file}' {total_read_count} times.\n"
                    "filesystem_read is now RESTRICTED for this file.\n"
                    "You must use an edit tool immediately:\n"
                    f'{{"tool": "filesystem_replace_lines", "args": {{"path": "{most_read_file}", "start_line": N, "end_line": M, "replacement": "fixed code"}}}}'
                ),
                should_stop=False
            )
        elif intervention_level == "warning" or total_read_count >= self.intervention_levels["warning"]:
            # Level 1: Warning nudges
            if len(recent_edits) < 2:  # Very few edits compared to reads
                return LoopDetection(
                    loop_type=LoopType.READ_LOOP,
                    severity=7,
                    evidence=[
                        f"Read '{most_read_file}' {total_read_count} times total ({recent_read_count} recent)",
                        f"Only {len(recent_edits)} edit actions in same period",
                        "Agent appears to be stuck analyzing instead of acting"
                    ],
                    suggestion=(
                        f"🔔 WARNING: You've read '{most_read_file}' {total_read_count} times.\n"
                        "You already have the information you need. START EDITING FILES NOW.\n"
                        "Use filesystem_replace_lines or filesystem_search_replace to make changes."
                    ),
                    should_stop=False
                )
        
        return None

    def _detect_syntax_loop(self) -> Optional[LoopDetection]:
        """Detect repeated syntax errors on the same file with auto-rollback."""
        if not self.file_syntax_errors:
            return None

        # Find file with most syntax errors
        worst_file = max(
            self.file_syntax_errors.items(),
            key=lambda x: len(x[1])
        )
        file_path, errors = worst_file
        error_count = len(errors)

        # Check total syntax errors across all files
        total_errors = sum(len(errs) for errs in self.file_syntax_errors.values())
        
        if total_errors >= self.max_total_syntax_errors:
            return LoopDetection(
                loop_type=LoopType.SYNTAX_LOOP,
                severity=10,
                evidence=[
                    f"{total_errors} total syntax errors across all files",
                    f"Worst file: '{file_path}' with {error_count} errors",
                    "Too many syntax errors - aborting task"
                ],
                suggestion=(
                    "🛑 CRITICAL: Too many syntax errors overall.\n"
                    "This task is being ABORTED. Please restart with a simpler approach.\n"
                    "Consider:\n"
                    "1. Starting with a smaller, working code snippet\n"
                    "2. Using the incremental builder service\n"
                    "3. Asking for user clarification on requirements"
                ),
                should_stop=True
            )
        
        if error_count >= self.syntax_loop_threshold:
            return LoopDetection(
                loop_type=LoopType.SYNTAX_LOOP,
                severity=9,
                evidence=[
                    f"{error_count} syntax errors on '{file_path}'",
                    f"Errors: {errors[:3]}",  # Show first 3 errors
                    "Repeated fixes are not working"
                ],
                suggestion=(
                    f"STOP trying to fix '{file_path}' incrementally. "
                    "This approach is not working. Try one of these alternatives:\n"
                    f"1. DELETE '{file_path}' and rebuild it from scratch incrementally\n"
                    "2. Build a skeleton first (just class/function definitions with 'pass')\n"
                    "3. Add functionality ONE FUNCTION AT A TIME and validate after each addition\n"
                    "4. Ask the user for clarification on the requirements"
                ),
                should_stop=True  # Stop and force strategy change
            )
        
        # Auto-rollback suggestion after 2 syntax errors
        if error_count >= self.syntax_auto_rollback_threshold:
            return LoopDetection(
                loop_type=LoopType.SYNTAX_LOOP,
                severity=8,
                evidence=[
                    f"{error_count} syntax errors on '{file_path}'",
                    f"Recent error: {errors[-1][:100]}",
                    "Consider rolling back to last working version"
                ],
                suggestion=(
                    f"⚠️ SYNTAX ERROR PATTERN: {error_count} errors on '{file_path}'\n"
                    "Consider using AUTO-ROLLBACK to last checkpoint:\n"
                    "1. Restore file from last checkpoint before these edits\n"
                    "2. Use incremental builder to add code piece by piece\n"
                    "3. Validate syntax after each small addition\n"
                    "4. Use read_diagnostics after every edit"
                ),
                should_stop=False  # Warning, but agent can continue
            )

        return None

    def _detect_tool_repetition(self, window: int) -> Optional[LoopDetection]:
        """Detect if same tool is being called repeatedly without progress."""
        if len(self.tool_call_sequence) < window:
            return None

        recent_calls = self.tool_call_sequence[-window:]

        # Count consecutive calls to same tool
        tool_runs = []
        current_tool = None
        current_count = 0

        for tool, args in recent_calls:
            if tool == current_tool:
                current_count += 1
            else:
                if current_count > 0:
                    tool_runs.append((current_tool, current_count))
                current_tool = tool
                current_count = 1

        if current_count > 0:
            tool_runs.append((current_tool, current_count))

        # Check for excessive repetition
        for tool, count in tool_runs:
            if count >= self.tool_repetition_threshold:
                # Check if we're making progress
                recent_actions = self.action_history[-count:]
                success_rate = sum(1 for a in recent_actions if a.success) / len(recent_actions)

                if success_rate < 0.5:  # Less than 50% success rate
                    return LoopDetection(
                        loop_type=LoopType.TOOL_REPETITION,
                        severity=7,
                        evidence=[
                            f"Called '{tool}' {count} times consecutively",
                            f"Success rate: {success_rate:.1%}",
                            "Not making progress with current approach"
                        ],
                        suggestion=(
                            f"The '{tool}' tool is not working well for this task. "
                            "Try a different approach:\n"
                            "1. Use a different tool to accomplish the same goal\n"
                            "2. Break the task into smaller steps\n"
                            "3. Ask the user for more information or clarification"
                        ),
                        should_stop=False
                    )

        return None

    def suggest_alternative(
        self,
        current_approach: str,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """Suggest an alternative approach when stuck.

        Args:
            current_approach: Description of what the agent is currently doing
            context: Optional context about the task

        Returns:
            Suggested alternative approach
        """
        # Analyze recent history to understand what's not working
        if len(self.action_history) < 3:
            return "Continue with current approach (not enough history to suggest alternatives)"

        recent_actions = self.action_history[-10:]
        failed_actions = [a for a in recent_actions if not a.success]

        if not failed_actions:
            return "Current approach seems to be working - continue"

        # Group failures by tool
        failures_by_tool = defaultdict(list)
        for action in failed_actions:
            failures_by_tool[action.tool].append(action)

        # Generate suggestions based on failure patterns
        suggestions = []

        # If read failures: suggest codebase_search instead
        if "filesystem_read" in failures_by_tool or "read_file" in failures_by_tool:
            suggestions.append(
                "Reading specific files is failing. Try 'codebase_search' to find the right files first."
            )

        # If write failures: suggest reading first
        if "filesystem_write" in failures_by_tool:
            suggestions.append(
                "Writing files is failing. Read the file first to understand its current state."
            )

        # If edit failures: suggest smaller changes
        if "filesystem_replace_lines" in failures_by_tool or "filesystem_search_replace" in failures_by_tool:
            suggestions.append(
                "Edits are failing. Try smaller, more targeted changes. Validate after each change."
            )

        # If command execution failures: suggest checking dependencies
        if "execute_command" in failures_by_tool:
            suggestions.append(
                "Commands are failing. Check that required dependencies are installed and paths are correct."
            )

        if suggestions:
            return "Alternative approaches:\n" + "\n".join(f"• {s}" for s in suggestions)
        else:
            return (
                "Multiple failures detected. Consider:\n"
                "• Breaking the task into smaller, simpler steps\n"
                "• Verifying your assumptions about the codebase structure\n"
                "• Asking the user for clarification or additional information"
            )

    def learn_from_error(
        self,
        error_type: str,
        file_path: Optional[str],
        error_message: str
    ) -> None:
        """Track error patterns to prevent recurrence.

        Args:
            error_type: Type of error (syntax, import, type, runtime)
            file_path: File where error occurred (if applicable)
            error_message: The error message
        """
        pattern_key = f"{error_type}:{file_path}:{error_message[:100]}"

        if pattern_key in self.error_patterns:
            # Update existing pattern
            pattern = self.error_patterns[pattern_key]
            pattern.count += 1
            pattern.last_seen = datetime.now(timezone.utc).isoformat()
        else:
            # Create new pattern
            self.error_patterns[pattern_key] = ErrorPattern(
                error_type=error_type,
                file_path=file_path,
                error_message=error_message,
                count=1,
                first_seen=datetime.now(timezone.utc).isoformat(),
                last_seen=datetime.now(timezone.utc).isoformat()
            )

        logger.info(
            "Error pattern recorded",
            error_type=error_type,
            file_path=file_path,
            count=self.error_patterns[pattern_key].count
        )

    def get_error_history(self, file_path: Optional[str] = None) -> List[ErrorPattern]:
        """Get error history, optionally filtered by file.

        Args:
            file_path: Optional file path to filter by

        Returns:
            List of error patterns
        """
        patterns = list(self.error_patterns.values())

        if file_path:
            patterns = [p for p in patterns if p.file_path == file_path]

        # Sort by count (most frequent first)
        patterns.sort(key=lambda p: p.count, reverse=True)

        return patterns

    def reset(self) -> None:
        """Reset all tracking state (call at start of new task)."""
        self.action_history.clear()
        self.error_patterns.clear()
        self.file_read_counts.clear()
        self.file_edit_counts.clear()
        self.file_syntax_errors.clear()
        self.tool_call_sequence.clear()

        logger.info("Self-corrector state reset")

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of current state for debugging.

        Returns:
            Dictionary with summary statistics
        """
        return {
            "total_actions": len(self.action_history),
            "successful_actions": sum(1 for a in self.action_history if a.success),
            "failed_actions": sum(1 for a in self.action_history if not a.success),
            "files_read": len(self.file_read_counts),
            "files_edited": len(self.file_edit_counts),
            "files_with_syntax_errors": len(self.file_syntax_errors),
            "unique_error_patterns": len(self.error_patterns),
            "most_read_file": max(self.file_read_counts.items(), key=lambda x: x[1])[0] if self.file_read_counts else None,
            "most_edited_file": max(self.file_edit_counts.items(), key=lambda x: x[1])[0] if self.file_edit_counts else None,
        }
