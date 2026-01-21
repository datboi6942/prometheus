#!/usr/bin/env python3
"""Simple integration test for ReAct services.

Run this to verify that the ReAct services are working correctly.
"""

import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from prometheus.services.task_planner import TaskPlannerService, TaskComplexity
from prometheus.services.self_corrector import SelfCorrectorService
from prometheus.services.prompt_builder import PromptBuilder, TaskType


async def test_task_planner():
    """Test TaskPlanner service."""
    print("\n=== Testing TaskPlanner ===")

    planner = TaskPlannerService()

    # Test complexity detection
    test_cases = [
        ("Fix typo on line 42", TaskComplexity.SIMPLE),
        ("Add validation to 3 functions", TaskComplexity.MODERATE),
        ("Refactor authentication system", TaskComplexity.COMPLEX),
    ]

    for task, expected in test_cases:
        complexity = await planner.analyze_complexity(task)
        status = "✓" if complexity == expected else "✗"
        print(f"{status} Task: '{task[:40]}...' -> {complexity.value} (expected {expected.value})")

    # Test plan creation
    plan = await planner.create_plan("Test task", TaskComplexity.MODERATE)
    print(f"✓ Created plan with {len(plan.steps)} steps")
    print(f"  - Plan ID: {plan.plan_id}")
    print(f"  - Estimated files: {plan.estimated_files}")
    print(f"  - Approval required: {plan.approval_required}")

    return True


def test_self_corrector():
    """Test SelfCorrector service."""
    print("\n=== Testing SelfCorrector ===")

    corrector = SelfCorrectorService()

    # Test action recording
    for i in range(6):
        corrector.record_action(
            iteration=i + 1,
            tool="filesystem_read",
            args={"path": "test.py"},
            success=True
        )

    print(f"✓ Recorded {len(corrector.action_history)} actions")

    # Test loop detection
    loop = corrector.detect_loops(recent_window=10)
    if loop:
        print(f"✓ Loop detected: {loop.loop_type}")
        print(f"  - Severity: {loop.severity}/10")
        print(f"  - Evidence: {loop.evidence[0][:60]}...")
    else:
        print("✗ Loop not detected (expected read loop)")
        return False

    # Test summary
    summary = corrector.get_summary()
    print(f"✓ Summary: {summary['total_actions']} actions, {summary['files_read']} files read")

    return True


def test_prompt_builder():
    """Test PromptBuilder service."""
    print("\n=== Testing PromptBuilder ===")

    builder = PromptBuilder()

    # Test task type detection
    messages = [
        {"role": "user", "content": "Fix the bug in utils.py"}
    ]

    task_type = builder.detect_task_type(messages)
    print(f"✓ Detected task type: {task_type.value}")

    # Test model family detection
    models = [
        ("gpt-4", "gpt"),
        ("claude-3-opus", "claude"),
        ("deepseek-r1", "reasoning"),
        ("ollama/llama3.2", "local"),
    ]

    for model, expected_family in models:
        family = builder.detect_model_family(model)
        status = "✓" if expected_family in family.value else "✗"
        print(f"{status} Model '{model}' -> {family.value} (expected {expected_family})")

    # Test prompt building
    prompt = builder.build(
        task_type=TaskType.DEBUGGING,
        model="gpt-4",
        tools_description="Test tools",
        rules_text="",
        memories_text=""
    )

    token_estimate = builder.get_token_estimate(prompt)
    print(f"✓ Built prompt: ~{token_estimate} tokens")

    return True


async def main():
    """Run all integration tests."""
    print("=" * 60)
    print("ReAct Intelligence - Integration Tests")
    print("=" * 60)

    results = []

    try:
        # Test TaskPlanner
        result = await test_task_planner()
        results.append(("TaskPlanner", result))
    except Exception as e:
        print(f"✗ TaskPlanner test failed: {e}")
        results.append(("TaskPlanner", False))

    try:
        # Test SelfCorrector
        result = test_self_corrector()
        results.append(("SelfCorrector", result))
    except Exception as e:
        print(f"✗ SelfCorrector test failed: {e}")
        results.append(("SelfCorrector", False))

    try:
        # Test PromptBuilder
        result = test_prompt_builder()
        results.append(("PromptBuilder", result))
    except Exception as e:
        print(f"✗ PromptBuilder test failed: {e}")
        results.append(("PromptBuilder", False))

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print("\n❌ Some tests failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
