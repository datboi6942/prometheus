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

    async def execute(
        self,
        messages: List[Dict[str, str]],
        model_router,
        model: str,
        plan: Optional[ExecutionPlan] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Execute task using ReAct loop with streaming support.

        This is the main execution method that replaces the original while loop.

        Args:
            messages: Conversation messages
            model_router: Model router for LLM calls
            model: Model to use for execution
            plan: Optional execution plan

        Yields:
            Event dictionaries for streaming to frontend
        """
        self.current_iteration = 0
        self.task_complete = False

        # Reset self-corrector for new task
        self.self_corrector.reset()

        logger.info(
            "ReAct execution starting",
            max_iterations=self.max_iterations,
            has_plan=plan is not None
        )

        while self.current_iteration < self.max_iterations and not self.task_complete:
            self.current_iteration += 1

            logger.debug(
                "ReAct iteration starting",
                iteration=self.current_iteration,
                max_iterations=self.max_iterations
            )

            try:
                # PHASE 1: THOUGHT - What should I do next?
                thought = await self._generate_thought(messages, plan, model_router, model)
                self.thoughts.append(thought)

                yield {
                    "type": "thought",
                    "iteration": self.current_iteration,
                    "thought": thought.thought,
                    "reasoning": thought.reasoning,
                    "confidence": thought.confidence
                }

                # Check if agent wants to finish
                if self._should_finish(thought):
                    logger.info("Agent signaled task completion")
                    self.task_complete = True
                    yield {
                        "type": "completion",
                        "iteration": self.current_iteration,
                        "message": "Task completed successfully"
                    }
                    break

                # PHASE 2: ACTION - Execute planned actions
                actions = self._extract_actions_from_response(thought, messages)

                for action in actions:
                    self.actions.append(action)

                    yield {
                        "type": "action",
                        "iteration": self.current_iteration,
                        "tool": action.tool,
                        "args": action.args,
                        "rationale": action.rationale
                    }

                    # Execute tool
                    try:
                        result = await self._execute_tool(action)

                        # PHASE 3: OBSERVATION - Process result
                        observation = await self._create_observation(action, result)
                        self.observations.append(observation)

                        # Record action for self-correction
                        self.self_corrector.record_action(
                            iteration=self.current_iteration,
                            tool=action.tool,
                            args=action.args,
                            success=observation.success,
                            error=observation.error
                        )

                        yield {
                            "type": "observation",
                            "iteration": self.current_iteration,
                            "success": observation.success,
                            "result": observation.result,
                            "interpretation": observation.interpretation,
                            "error": observation.error
                        }

                        # Add observation to messages for next iteration
                        messages = self._update_messages_with_observation(
                            messages, action, observation
                        )

                    except Exception as e:
                        logger.error(
                            "Tool execution failed",
                            tool=action.tool,
                            error=str(e),
                            iteration=self.current_iteration
                        )
                        yield {
                            "type": "error",
                            "iteration": self.current_iteration,
                            "tool": action.tool,
                            "error": str(e)
                        }

                # PHASE 4: REFLECTION - Did that work? What next?
                reflection = await self._reflect(thought, actions, self.observations[-len(actions):])
                self.reflections.append(reflection)

                yield {
                    "type": "reflection",
                    "iteration": self.current_iteration,
                    "assessment": reflection.progress_assessment,
                    "should_continue": reflection.should_continue,
                    "learned": reflection.learned
                }

                # Check for completion
                if reflection.progress_assessment == "complete":
                    self.task_complete = True
                    logger.info("Task marked complete by reflection")
                    break

                # Check for stuck state
                if reflection.progress_assessment == "stuck" or not reflection.should_continue:
                    loop_detection = self.self_corrector.detect_loops()

                    if loop_detection:
                        logger.warning(
                            "Loop detected",
                            loop_type=loop_detection.loop_type,
                            severity=loop_detection.severity
                        )

                        yield {
                            "type": "loop_detected",
                            "iteration": self.current_iteration,
                            "loop_type": loop_detection.loop_type,
                            "severity": loop_detection.severity,
                            "evidence": loop_detection.evidence,
                            "suggestion": loop_detection.suggestion
                        }

                        # Inject corrective suggestion into messages
                        messages.append({
                            "role": "system",
                            "content": f"⚠️ LOOP DETECTED: {loop_detection.suggestion}"
                        })

                        if loop_detection.should_stop:
                            logger.error("Critical loop detected - stopping execution")
                            break

                # Adapt strategy if needed
                if reflection.should_change_approach and reflection.corrective_action:
                    messages.append({
                        "role": "system",
                        "content": f"💡 STRATEGY CHANGE: {reflection.corrective_action}"
                    })

            except Exception as e:
                logger.error(
                    "ReAct iteration failed",
                    iteration=self.current_iteration,
                    error=str(e)
                )
                yield {
                    "type": "error",
                    "iteration": self.current_iteration,
                    "error": f"Iteration failed: {str(e)}"
                }

        # Final summary
        logger.info(
            "ReAct execution completed",
            iterations=self.current_iteration,
            task_complete=self.task_complete,
            thoughts=len(self.thoughts),
            actions=len(self.actions),
            observations=len(self.observations)
        )

        yield {
            "type": "execution_summary",
            "iterations": self.current_iteration,
            "task_complete": self.task_complete,
            "total_actions": len(self.actions),
            "successful_actions": sum(1 for obs in self.observations if obs.success),
            "self_corrector_summary": self.self_corrector.get_summary()
        }

    async def _generate_thought(
        self,
        messages: List[Dict[str, str]],
        plan: Optional[ExecutionPlan],
        model_router,
        model: str
    ) -> ThoughtRecord:
        """Generate thought about what to do next.

        This doesn't make an actual LLM call - instead it analyzes the
        conversation to extract the agent's reasoning and intended actions.

        Args:
            messages: Current conversation
            plan: Optional execution plan
            model_router: Model router (not used in this simplified version)
            model: Model name (not used in this simplified version)

        Returns:
            ThoughtRecord with reasoning and planned actions
        """
        # In a full implementation, this would make an LLM call to get explicit reasoning
        # For now, we extract implicit reasoning from the conversation

        last_assistant_msg = None
        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                last_assistant_msg = msg.get("content", "")
                break

        if not last_assistant_msg:
            thought = "Starting task execution"
            reasoning = "This is the first iteration"
            confidence = 0.8
        else:
            thought = "Continue with planned actions"
            reasoning = "Following conversation flow"
            confidence = 0.7

        return ThoughtRecord(
            iteration=self.current_iteration,
            thought=thought,
            reasoning=reasoning,
            next_actions=["execute_tools"],
            confidence=confidence
        )

    def _should_finish(self, thought: ThoughtRecord) -> bool:
        """Determine if agent thinks task is complete.

        Args:
            thought: Current thought record

        Returns:
            True if task should finish
        """
        # Check for completion indicators
        completion_keywords = ["done", "complete", "finished", "success"]
        thought_lower = thought.thought.lower()

        return any(keyword in thought_lower for keyword in completion_keywords)

    def _extract_actions_from_response(
        self,
        thought: ThoughtRecord,
        messages: List[Dict[str, str]]
    ) -> List[ActionRecord]:
        """Extract tool calls from the conversation.

        This is a simplified version - in the actual integration with chat.py,
        this would extract tool calls from the LLM response.

        Args:
            thought: Current thought record
            messages: Conversation messages

        Returns:
            List of action records
        """
        # This is a placeholder - actual implementation will extract
        # tool calls from the streaming response in chat.py
        return []

    async def _execute_tool(self, action: ActionRecord) -> Dict[str, Any]:
        """Execute a single tool.

        Args:
            action: Action to execute

        Returns:
            Tool result dictionary
        """
        try:
            # Execute tool with timeout
            result = await asyncio.wait_for(
                self.tool_registry.execute_tool(
                    name=action.tool,
                    args=action.args,
                    context={"workspace_path": self.workspace_path}
                ),
                timeout=60.0  # 60 second timeout per tool execution
            )
            return result
        except asyncio.TimeoutError:
            logger.error("Tool execution timed out", tool=action.tool, timeout=60)
            return {
                "success": False,
                "error": f"Tool {action.tool} timed out after 60 seconds. The operation may be too complex or stuck. Try a simpler approach.",
                "timeout": True
            }
        except Exception as e:
            logger.error("Tool execution error", tool=action.tool, error=str(e))
            return {
                "success": False,
                "error": str(e)
            }

    async def _create_observation(
        self,
        action: ActionRecord,
        result: Dict[str, Any]
    ) -> ObservationRecord:
        """Create observation from action result.

        Args:
            action: The action that was executed
            result: Result from tool execution

        Returns:
            ObservationRecord with interpretation
        """
        success = result.get("success", False)
        error = result.get("error")

        # Generate interpretation
        if success:
            interpretation = f"Successfully executed {action.tool}"
        else:
            interpretation = f"Failed to execute {action.tool}: {error}"

        return ObservationRecord(
            iteration=self.current_iteration,
            action=action,
            result=result,
            success=success,
            error=error,
            interpretation=interpretation
        )

    async def _reflect(
        self,
        thought: ThoughtRecord,
        actions: List[ActionRecord],
        observations: List[ObservationRecord]
    ) -> ReflectionRecord:
        """Reflect on progress after observations.

        Args:
            thought: The thought that led to actions
            actions: Actions that were executed
            observations: Results of those actions

        Returns:
            ReflectionRecord with progress assessment
        """
        # Assess progress
        if not observations:
            assessment = "no_actions"
            should_continue = True
            should_change = False
        else:
            success_rate = sum(1 for obs in observations if obs.success) / len(observations)

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

        # Check if complete
        if self.task_complete:
            assessment = "complete"
            should_continue = False

        # Generate corrective action if needed
        corrective_action = None
        if should_change:
            corrective_action = self.self_corrector.suggest_alternative(
                current_approach=thought.thought
            )

        return ReflectionRecord(
            iteration=self.current_iteration,
            progress_assessment=assessment,
            learned=None,
            should_continue=should_continue,
            should_change_approach=should_change,
            corrective_action=corrective_action
        )

    def _update_messages_with_observation(
        self,
        messages: List[Dict[str, str]],
        action: ActionRecord,
        observation: ObservationRecord
    ) -> List[Dict[str, str]]:
        """Update message history with observation.

        Args:
            messages: Current messages
            action: Action that was executed
            observation: Result observation

        Returns:
            Updated messages
        """
        # Add tool result as a message
        messages.append({
            "role": "system",
            "content": f"Tool '{action.tool}' result: {observation.interpretation}"
        })

        return messages

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
