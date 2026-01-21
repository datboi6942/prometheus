"""Unit tests for TaskPlanner service."""

import pytest
from prometheus.services.task_planner import (
    TaskPlannerService,
    TaskComplexity,
    ExecutionPlan,
    PlanStep
)


class TestTaskPlanner:
    """Test TaskPlanner functionality."""

    @pytest.fixture
    def planner(self):
        """Create a TaskPlanner instance."""
        return TaskPlannerService()

    @pytest.mark.asyncio
    async def test_simple_task_classification(self, planner):
        """Test that simple tasks are classified correctly."""
        simple_tasks = [
            "Fix the typo on line 42",
            "Update the comment in utils.py",
            "Rename variable x to y",
            "Add a log statement"
        ]

        for task in simple_tasks:
            complexity = await planner.analyze_complexity(task)
            assert complexity == TaskComplexity.SIMPLE, f"Task '{task}' should be SIMPLE"

    @pytest.mark.asyncio
    async def test_moderate_task_classification(self, planner):
        """Test that moderate tasks are classified correctly."""
        moderate_tasks = [
            "Add input validation to the user functions",
            "Implement error handling for API calls",
            "Update the authentication logic",
            "Add a new feature to process payments"
        ]

        for task in moderate_tasks:
            complexity = await planner.analyze_complexity(task)
            assert complexity == TaskComplexity.MODERATE, f"Task '{task}' should be MODERATE"

    @pytest.mark.asyncio
    async def test_complex_task_classification(self, planner):
        """Test that complex tasks are classified correctly."""
        complex_tasks = [
            "Refactor the entire authentication system",
            "Migrate the database schema",
            "Redesign the API architecture",
            "Implement OAuth2 authentication",
            "Add security logging across 10 files"
        ]

        for task in complex_tasks:
            complexity = await planner.analyze_complexity(task)
            assert complexity == TaskComplexity.COMPLEX, f"Task '{task}' should be COMPLEX"

    @pytest.mark.asyncio
    async def test_file_count_classification(self, planner):
        """Test classification based on file count mentions."""
        # 1 file = SIMPLE
        complexity = await planner.analyze_complexity("Update 1 file")
        assert complexity == TaskComplexity.SIMPLE

        # 2-3 files = MODERATE
        complexity = await planner.analyze_complexity("Update 3 files")
        assert complexity == TaskComplexity.MODERATE

        # 4+ files = COMPLEX
        complexity = await planner.analyze_complexity("Update 6 files")
        assert complexity == TaskComplexity.COMPLEX

    @pytest.mark.asyncio
    async def test_create_simple_plan(self, planner):
        """Test plan creation for simple task."""
        complexity = TaskComplexity.SIMPLE
        plan = await planner.create_plan("Fix typo in utils.py", complexity)

        assert plan.complexity == TaskComplexity.SIMPLE
        assert plan.estimated_files == 1
        assert plan.estimated_lines <= 50
        assert not plan.approval_required
        assert len(plan.steps) > 0

    @pytest.mark.asyncio
    async def test_create_complex_plan(self, planner):
        """Test plan creation for complex task."""
        complexity = TaskComplexity.COMPLEX
        plan = await planner.create_plan("Refactor authentication system", complexity)

        assert plan.complexity == TaskComplexity.COMPLEX
        assert plan.estimated_files >= 4
        assert plan.estimated_lines > 200
        assert plan.approval_required
        assert len(plan.steps) > 0

    @pytest.mark.asyncio
    async def test_risk_identification(self, planner):
        """Test that risks are identified in plans."""
        # Database task should have data loss risk
        plan = await planner.create_plan("Migrate database schema", TaskComplexity.COMPLEX)
        assert len(plan.risks) > 0
        assert any("data loss" in risk.lower() for risk in plan.risks)

        # Security task should have security risk
        plan = await planner.create_plan("Update authentication", TaskComplexity.COMPLEX)
        assert len(plan.risks) > 0
        assert any("security" in risk.lower() for risk in plan.risks)

        # Delete task should have deletion risk
        plan = await planner.create_plan("Delete old files", TaskComplexity.MODERATE)
        assert len(plan.risks) > 0
        assert any("deletion" in risk.lower() or "delete" in risk.lower() for risk in plan.risks)

    @pytest.mark.asyncio
    async def test_plan_validation(self, planner):
        """Test plan validation."""
        # Valid plan
        plan = await planner.create_plan("Simple task", TaskComplexity.SIMPLE)
        validation = await planner.validate_plan(plan)
        assert validation["valid"]
        assert len(validation["issues"]) == 0

    @pytest.mark.asyncio
    async def test_step_dependencies(self, planner):
        """Test that plan steps have proper dependencies."""
        plan = await planner.create_plan("Moderate task", TaskComplexity.MODERATE)

        # Check that later steps depend on earlier steps
        for step in plan.steps:
            if step.dependencies:
                for dep in step.dependencies:
                    assert dep < step.step_num, f"Step {step.step_num} depends on future step {dep}"

    def test_circular_dependency_detection(self, planner):
        """Test detection of circular dependencies."""
        # Create steps with circular dependency
        steps = [
            PlanStep(
                step_num=1,
                action="Step 1",
                tool="tool1",
                expected_outcome="outcome1",
                dependencies=[2]  # Depends on step 2
            ),
            PlanStep(
                step_num=2,
                action="Step 2",
                tool="tool2",
                expected_outcome="outcome2",
                dependencies=[1]  # Depends on step 1 - circular!
            )
        ]

        # Check for circular dependencies
        has_cycle = planner._has_circular_dependencies(steps)
        assert has_cycle, "Circular dependency should be detected"

    def test_no_circular_dependency(self, planner):
        """Test that valid dependencies are not flagged as circular."""
        # Create valid dependency chain
        steps = [
            PlanStep(
                step_num=1,
                action="Step 1",
                tool="tool1",
                expected_outcome="outcome1",
                dependencies=[]
            ),
            PlanStep(
                step_num=2,
                action="Step 2",
                tool="tool2",
                expected_outcome="outcome2",
                dependencies=[1]  # Depends on step 1 - valid
            ),
            PlanStep(
                step_num=3,
                action="Step 3",
                tool="tool3",
                expected_outcome="outcome3",
                dependencies=[2]  # Depends on step 2 - valid
            )
        ]

        has_cycle = planner._has_circular_dependencies(steps)
        assert not has_cycle, "Valid dependencies should not be flagged as circular"
