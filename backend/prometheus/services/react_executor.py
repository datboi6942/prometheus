"""ReAct (Reasoning + Acting) execution loop service.

This service implements the core agent loop using the ReAct pattern:
1. THOUGHT: Analyze current state and decide next action
2. ACTION: Execute selected tool(s)
3. OBSERVATION: Process and understand results
4. REFLECTION: Assess progress and adapt strategy

This replaces the simple while loop with intelligent, self-correcting execution.
"""

from typing import Any, AsyncGenerator, Dict, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timezone
import asyncio
import json
import structlog

from prometheus.services.self_corrector import SelfCorrectorService, LoopDetection
from prometheus.services.task_planner import ExecutionPlan, TaskComplexity

logger = structlog.get_logger()


class ThoughtRecord(BaseModel):
    """Record of agent's reasoning before taking action."""
    iteration: int
    thought: str
    reasoning: str
    next_actions: List[str]
    confidence: float = Field(ge=0.0, le=1.0)  # 0-1 confidence in approach


class ActionRecord(BaseModel):
    """Record of a single action execution."""
    iteration: int
    tool: str
    args: Dict[str, Any]
    rationale: str


class ObservationRecord(BaseModel):
    """Record of action result and interpretation."""
    iteration: int
    action: ActionRecord
    result: Dict[str, Any]
    success: bool
    error: Optional[str] = None
    interpretation: str  # What this result means


class ReflectionRecord(BaseModel):
    """Record of progress assessment after observation."""
    iteration: int
    progress_assessment: str  # "on_track", "stuck", "error", "complete"
    learned: Optional[str] = None  # What we learned this iteration
    should_continue: bool
    should_change_approach: bool
    corrective_action: Optional[str] = None


class ReActExecutor:
    """ReAct (Reasoning + Acting) execution loop."""

    def __init__(
        self,
        tool_registry,
        self_corrector: SelfCorrectorService,
        workspace_path: str,
        max_iterations: int = 50
    ):
        """Initialize the ReAct executor.

        Args:
            tool_registry: Tool registry for executing tools
            self_corrector: Self-correction service
            workspace_path: Workspace path for file operations
            max_iterations: Maximum iterations before stopping
        """
        self.tool_registry = tool_registry
        self.self_corrector = self_corrector
        self.workspace_path = workspace_path
        self.max_iterations = max_iterations

        # Execution history
        self.thoughts: List[ThoughtRecord] = []
        self.actions: List[ActionRecord] = []
        self.observations: List[ObservationRecord] = []
        self.reflections: List[ReflectionRecord] = []

        # State tracking
        self.task_complete = False
        self.current_iteration = 0

    def start_iteration(self, iteration: int, plan: Optional[ExecutionPlan] = None):
        """Start a new ReAct iteration.

        This method is called at the start of each iteration by chat.py.

        Args:
            iteration: Current iteration number
            plan: Optional execution plan
        """
        self.current_iteration = iteration

        # Check for loops before starting
        loop_detection = self.self_corrector.detect_loops()
        if loop_detection:
            logger.warning(
                "Loop detected at iteration start",
                loop_type=loop_detection.loop_type,
                severity=loop_detection.severity
            )
            return loop_detection

        return None

    def record_tool_execution(
        self,
        iteration: int,
        tool: str,
        args: Dict[str, Any],
        success: bool,
        error: Optional[str] = None,
        execution_time: Optional[float] = None
    ):
        """Record a tool execution for self-correction.

        This is called by chat.py after each tool execution.

        Args:
            iteration: Current iteration number
            tool: Tool name
            args: Tool arguments
            success: Whether execution succeeded
            error: Error message if failed
            execution_time: Time taken to execute tool in seconds (optional)
        """
        self.self_corrector.record_action(
            iteration=iteration,
            tool=tool,
            args=args,
            success=success,
            error=error,
            execution_time=execution_time
        )

    def get_reflection(self, iteration: int) -> ReflectionRecord:
        """Get reflection for current iteration.

        Args:
            iteration: Current iteration number

        Returns:
            ReflectionRecord with progress assessment
        """
        # Assess progress based on recent actions
        recent_observations = self.observations[-5:] if self.observations else []

        if not recent_observations:
            assessment = "no_actions"
            should_continue = True
            should_change = False
        else:
            success_rate = sum(1 for obs in recent_observations if obs.success) / len(recent_observations)

            if success_rate == 1.0:
                assessment = "on_track"
                should_continue = True
                should_change = False
            elif success_rate >= 0.5:
                assessment = "making_progress"
                should_continue = True
                should_change = False
            elif success_rate >= 0.25:
                assessment = "struggling"
                should_continue = True
                should_change = True
            else:
                assessment = "stuck"
                should_continue = True
                should_change = True

        # Generate corrective action if needed
        corrective_action = None
        if should_change:
            corrective_action = self.self_corrector.suggest_alternative(
                current_approach="current execution"
            )

        reflection = ReflectionRecord(
            iteration=iteration,
            progress_assessment=assessment,
            learned=None,
            should_continue=should_continue,
            should_change_approach=should_change,
            corrective_action=corrective_action
        )

        self.reflections.append(reflection)
        return reflection


    def get_execution_summary(self) -> Dict[str, Any]:
        """Get summary of execution for logging/debugging.

        Returns:
            Dictionary with execution statistics
        """
        return {
            "total_iterations": self.current_iteration,
            "task_complete": self.task_complete,
            "thoughts": len(self.thoughts),
            "actions": len(self.actions),
            "observations": len(self.observations),
            "reflections": len(self.reflections),
            "success_rate": (
                sum(1 for obs in self.observations if obs.success) / len(self.observations)
                if self.observations else 0
            ),
            "self_corrector": self.self_corrector.get_summary()
        }
