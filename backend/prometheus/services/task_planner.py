"""Task planning and complexity analysis service.

This service analyzes user requests to:
1. Classify task complexity (SIMPLE, MODERATE, COMPLEX)
2. Generate execution plans with steps and dependencies
3. Identify risks and estimate resource requirements
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
import structlog
import re

logger = structlog.get_logger()


class TaskComplexity(str, Enum):
    """Task complexity levels."""
    SIMPLE = "simple"        # 1 file, <50 lines, no dependencies
    MODERATE = "moderate"    # 2-3 files, existing patterns, low risk
    COMPLEX = "complex"      # 4+ files, architectural changes, high risk


class PlanStep(BaseModel):
    """A single step in an execution plan."""
    step_num: int
    action: str
    tool: str
    args: Dict[str, Any] = Field(default_factory=dict)
    expected_outcome: str
    dependencies: List[int] = Field(default_factory=list)  # Previous steps that must complete
    validation: Optional[str] = None  # How to verify this step


class ExecutionPlan(BaseModel):
    """Complete execution plan for a task."""
    plan_id: str
    task_description: str
    complexity: TaskComplexity
    estimated_files: int
    estimated_lines: int
    steps: List[PlanStep]
    risks: List[str] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)  # External dependencies
    approval_required: bool
    reasoning: str  # Why this complexity/approach


class TaskPlannerService:
    """Analyzes tasks and creates execution plans."""

    def __init__(self, model_router=None):
        """Initialize the task planner.

        Args:
            model_router: Optional model router for LLM-based planning
        """
        self.model_router = model_router

        # Complexity scoring heuristics
        self.complexity_keywords = {
            TaskComplexity.COMPLEX: [
                "refactor", "migrate", "database", "api contract", "authentication",
                "authorization", "security", "architecture", "redesign", "overhaul"
            ],
            TaskComplexity.MODERATE: [
                "add feature", "implement", "update", "enhance", "modify",
                "extend", "improve", "validation", "error handling"
            ],
            TaskComplexity.SIMPLE: [
                "fix typo", "update comment", "change variable", "add log",
                "format", "rename", "delete unused"
            ]
        }

    async def analyze_complexity(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None
    ) -> TaskComplexity:
        """Analyze task complexity based on heuristics.

        Args:
            task: User's task description
            context: Optional context (workspace info, recent changes, etc.)

        Returns:
            TaskComplexity enum value
        """
        task_lower = task.lower()

        # Check for COMPLEX indicators
        if any(keyword in task_lower for keyword in self.complexity_keywords[TaskComplexity.COMPLEX]):
            logger.info("Task classified as COMPLEX", reason="keyword_match")
            return TaskComplexity.COMPLEX

        # Check for database/migration keywords
        if any(word in task_lower for word in ["database", "migration", "schema", "table"]):
            logger.info("Task classified as COMPLEX", reason="database_changes")
            return TaskComplexity.COMPLEX

        # Check for multi-file indicators
        file_count_match = re.search(r'(\d+)\s+files?', task_lower)
        if file_count_match:
            file_count = int(file_count_match.group(1))
            if file_count >= 4:
                logger.info("Task classified as COMPLEX", reason=f"file_count_{file_count}")
                return TaskComplexity.COMPLEX
            elif file_count >= 2:
                logger.info("Task classified as MODERATE", reason=f"file_count_{file_count}")
                return TaskComplexity.MODERATE

        # Check for SIMPLE indicators
        if any(keyword in task_lower for keyword in self.complexity_keywords[TaskComplexity.SIMPLE]):
            logger.info("Task classified as SIMPLE", reason="keyword_match")
            return TaskComplexity.SIMPLE

        # Check for MODERATE indicators
        if any(keyword in task_lower for keyword in self.complexity_keywords[TaskComplexity.MODERATE]):
            logger.info("Task classified as MODERATE", reason="keyword_match")
            return TaskComplexity.MODERATE

        # Default to MODERATE for ambiguous cases
        logger.info("Task classified as MODERATE", reason="default_heuristic")
        return TaskComplexity.MODERATE

    async def create_plan(
        self,
        task: str,
        complexity: TaskComplexity,
        context: Optional[Dict[str, Any]] = None
    ) -> ExecutionPlan:
        """Create an execution plan for the task.

        Args:
            task: User's task description
            complexity: Pre-determined complexity level
            context: Optional context information

        Returns:
            ExecutionPlan with steps and metadata
        """
        import uuid

        plan_id = str(uuid.uuid4())[:8]

        # Estimate resources based on complexity
        if complexity == TaskComplexity.SIMPLE:
            estimated_files = 1
            estimated_lines = 50
            approval_required = False
        elif complexity == TaskComplexity.MODERATE:
            estimated_files = 3
            estimated_lines = 150
            approval_required = False
        else:  # COMPLEX
            estimated_files = 6
            estimated_lines = 300
            approval_required = True

        # Generate basic plan steps (will be enhanced by LLM if available)
        steps = self._generate_basic_steps(task, complexity)

        # Identify risks
        risks = self._identify_risks(task, complexity)

        plan = ExecutionPlan(
            plan_id=plan_id,
            task_description=task,
            complexity=complexity,
            estimated_files=estimated_files,
            estimated_lines=estimated_lines,
            steps=steps,
            risks=risks,
            dependencies=[],
            approval_required=approval_required,
            reasoning=f"Classified as {complexity.value} based on task analysis"
        )

        logger.info(
            "Execution plan created",
            plan_id=plan_id,
            complexity=complexity.value,
            steps=len(steps),
            approval_required=approval_required
        )

        return plan

    def _generate_basic_steps(self, task: str, complexity: TaskComplexity) -> List[PlanStep]:
        """Generate basic execution steps based on task type.

        This is a fallback for when LLM-based planning is not available.
        """
        task_lower = task.lower()
        steps = []

        # Common pattern: Read → Understand → Modify → Verify
        if complexity == TaskComplexity.SIMPLE:
            steps.append(PlanStep(
                step_num=1,
                action="Read the target file",
                tool="filesystem_read",
                expected_outcome="File content loaded",
                validation="Verify file exists and is readable"
            ))
            steps.append(PlanStep(
                step_num=2,
                action="Make the requested change",
                tool="filesystem_search_replace",
                expected_outcome="Change applied successfully",
                dependencies=[1],
                validation="Verify syntax is valid"
            ))

        elif complexity == TaskComplexity.MODERATE:
            steps.append(PlanStep(
                step_num=1,
                action="Search for relevant files",
                tool="codebase_search",
                expected_outcome="Target files identified",
                validation="At least 2 files found"
            ))
            steps.append(PlanStep(
                step_num=2,
                action="Read and analyze existing code",
                tool="filesystem_read",
                expected_outcome="Understand current implementation",
                dependencies=[1],
                validation="Code structure documented"
            ))
            steps.append(PlanStep(
                step_num=3,
                action="Implement changes incrementally",
                tool="filesystem_replace_lines",
                expected_outcome="All files updated",
                dependencies=[2],
                validation="Syntax valid in all files"
            ))
            steps.append(PlanStep(
                step_num=4,
                action="Verify changes work together",
                tool="read_diagnostics",
                expected_outcome="No errors reported",
                dependencies=[3],
                validation="All integrations working"
            ))

        else:  # COMPLEX
            steps.append(PlanStep(
                step_num=1,
                action="Analyze current architecture",
                tool="codebase_search",
                expected_outcome="Full understanding of system structure",
                validation="Key components identified"
            ))
            steps.append(PlanStep(
                step_num=2,
                action="Design new architecture",
                tool="filesystem_write",
                expected_outcome="Architecture plan documented",
                dependencies=[1],
                validation="Design reviewed and approved"
            ))
            steps.append(PlanStep(
                step_num=3,
                action="Create migration plan",
                tool="filesystem_write",
                expected_outcome="Migration steps documented",
                dependencies=[2],
                validation="Risk assessment complete"
            ))
            steps.append(PlanStep(
                step_num=4,
                action="Implement changes incrementally",
                tool="filesystem_replace_lines",
                expected_outcome="All components updated",
                dependencies=[3],
                validation="Each step validates before next"
            ))
            steps.append(PlanStep(
                step_num=5,
                action="Run comprehensive tests",
                tool="execute_command",
                expected_outcome="All tests pass",
                dependencies=[4],
                validation="Test coverage maintained"
            ))

        return steps

    def _identify_risks(self, task: str, complexity: TaskComplexity) -> List[str]:
        """Identify potential risks in the task."""
        risks = []
        task_lower = task.lower()

        # Common risk patterns
        if "database" in task_lower or "migration" in task_lower:
            risks.append("Data loss risk - requires backup before migration")

        if "authentication" in task_lower or "security" in task_lower:
            risks.append("Security risk - changes could affect access control")

        if "api" in task_lower and any(word in task_lower for word in ["change", "modify", "update"]):
            risks.append("Breaking change risk - could affect API consumers")

        if "delete" in task_lower or "remove" in task_lower:
            risks.append("Data/code deletion risk - ensure proper backups")

        if complexity == TaskComplexity.COMPLEX and not risks:
            risks.append("High complexity - may require multiple iterations")

        return risks

    async def validate_plan(self, plan: ExecutionPlan) -> Dict[str, Any]:
        """Validate that a plan is feasible and safe.

        Args:
            plan: The execution plan to validate

        Returns:
            Validation result with any warnings or blockers
        """
        issues = []
        warnings = []

        # Check for step dependencies
        step_nums = {step.step_num for step in plan.steps}
        for step in plan.steps:
            for dep in step.dependencies:
                if dep not in step_nums:
                    issues.append(f"Step {step.step_num} depends on non-existent step {dep}")

        # Check for circular dependencies (simple check)
        if self._has_circular_dependencies(plan.steps):
            issues.append("Circular dependency detected in plan steps")

        # Warn if COMPLEX task with no approval
        if plan.complexity == TaskComplexity.COMPLEX and not plan.approval_required:
            warnings.append("COMPLEX task should require user approval")

        # Warn if many steps
        if len(plan.steps) > 10:
            warnings.append(f"Plan has {len(plan.steps)} steps - may be too complex")

        is_valid = len(issues) == 0

        return {
            "valid": is_valid,
            "issues": issues,
            "warnings": warnings,
            "plan_id": plan.plan_id
        }

    def _has_circular_dependencies(self, steps: List[PlanStep]) -> bool:
        """Check for circular dependencies in plan steps."""
        # Build dependency graph
        graph = {step.step_num: set(step.dependencies) for step in steps}

        # DFS to detect cycles
        def has_cycle(node: int, visited: set, rec_stack: set) -> bool:
            visited.add(node)
            rec_stack.add(node)

            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    if has_cycle(neighbor, visited, rec_stack):
                        return True
                elif neighbor in rec_stack:
                    return True

            rec_stack.remove(node)
            return False

        visited = set()
        rec_stack = set()

        for node in graph:
            if node not in visited:
                if has_cycle(node, visited, rec_stack):
                    return True

        return False
