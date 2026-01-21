"""Dynamic prompt builder service for task-specific and model-specific optimization.

This service builds optimized prompts by:
1. Detecting task type from user messages
2. Including only relevant guidance and tool descriptions
3. Optimizing for specific model families (reasoning models, Claude, GPT, etc.)
4. Reducing token usage while maintaining effectiveness
"""

from enum import Enum
from typing import Any, Dict, List, Optional
import structlog

logger = structlog.get_logger()


class TaskType(str, Enum):
    """Types of tasks the agent can perform."""
    CODE_GENERATION = "code_generation"  # Writing new code
    CODE_ANALYSIS = "code_analysis"      # Understanding existing code
    DEBUGGING = "debugging"              # Fixing errors
    REFACTORING = "refactoring"          # Restructuring code
    TESTING = "testing"                  # Writing/running tests
    DOCUMENTATION = "documentation"      # Writing docs
    FILE_OPERATIONS = "file_operations"  # File management tasks
    GENERAL = "general"                  # General assistance


class ModelFamily(str, Enum):
    """Model families with different characteristics."""
    REASONING = "reasoning"  # DeepSeek R1, o1, o3 - benefit from thinking space
    CLAUDE = "claude"        # Anthropic Claude models
    GPT = "gpt"              # OpenAI GPT models
    GEMINI = "gemini"        # Google Gemini models
    LOCAL = "local"          # Local models (Ollama, etc.)
    UNKNOWN = "unknown"      # Unknown/generic models


class PromptBuilder:
    """Build optimized prompts based on task type and model."""

    # Base identity (always included)
    BASE_IDENTITY = """You are Prometheus, an expert AI coding assistant with deep knowledge of software engineering, architecture, and best practices.

You operate autonomously by:
1. Analyzing tasks and creating execution plans
2. Using tools to read, search, and modify code
3. Validating changes and learning from errors
4. Communicating clearly about your progress and reasoning"""

    # Task-specific guidance
    CODE_GENERATION_GUIDANCE = """
CODE GENERATION MODE:
- Plan file structure before writing
- Start with interfaces/types, then implementation
- Build incrementally and validate each piece
- Follow existing code style and patterns
- Add appropriate error handling
- Include docstrings for public APIs"""

    CODE_ANALYSIS_GUIDANCE = """
CODE ANALYSIS MODE:
- Use codebase_search to understand structure
- Read files systematically (don't re-read unnecessarily)
- Document your findings clearly
- Identify patterns and relationships
- Note any issues or improvements
- Create a mental map before suggesting changes"""

    DEBUGGING_GUIDANCE = """
DEBUGGING MODE:
1. Read the file containing the error
2. Understand the error message fully
3. Identify root cause (not just symptoms)
4. Make minimal, targeted fix
5. Validate the fix works
6. Test related functionality

Common debugging steps:
- Check syntax errors with read_diagnostics
- Verify imports are correct
- Look for typos in variable/function names
- Check file paths and permissions"""

    REFACTORING_GUIDANCE = """
REFACTORING MODE:
1. Understand current implementation fully
2. Identify what needs to change and why
3. Plan refactoring steps
4. Make ONE change at a time
5. Validate after EACH change
6. Keep tests passing throughout

Refactoring principles:
- Preserve existing behavior
- Improve code structure/readability
- Reduce duplication
- Simplify complexity
- Update related tests"""

    TESTING_GUIDANCE = """
TESTING MODE:
- Understand what needs testing
- Write clear, focused test cases
- Follow existing test patterns
- Test both success and failure cases
- Use descriptive test names
- Run tests after writing them"""

    # Model-specific optimizations
    REASONING_MODEL_GUIDANCE = """
You are using a reasoning model. Take advantage of this by:
- Thinking through complex problems step-by-step
- Considering multiple approaches before acting
- Explaining your reasoning clearly
- Self-correcting when you notice mistakes"""

    CLAUDE_MODEL_GUIDANCE = """
Leverage Claude's strengths:
- Strong at understanding context and nuance
- Good at following complex instructions
- Excellent at structured output
- Benefits from clear examples"""

    # Core operational rules (always included)
    CORE_RULES = """
CRITICAL OPERATIONAL RULES:

1. AVOID LOOPS:
   - Don't read the same file multiple times unnecessarily
   - If you've read a file, use that information
   - After 3 reads of the same file, you MUST take action
   - If stuck in syntax errors (3+ on same file), DELETE and rebuild

2. MAKE PROGRESS:
   - Every action should move toward the goal
   - If an approach isn't working after 2-3 attempts, try something different
   - Ask for help if truly stuck

3. VALIDATE CHANGES:
   - Check syntax after edits (use read_diagnostics)
   - Verify files exist before editing
   - Confirm changes worked before moving on

4. BE EFFICIENT:
   - Use codebase_search instead of reading many files
   - Make targeted edits instead of rewriting entire files
   - Batch related changes when possible

5. COMMUNICATE CLEARLY:
   - Explain what you're doing and why
   - Report errors honestly
   - Ask for clarification when requirements are unclear"""

    def __init__(self):
        """Initialize the prompt builder."""
        self.task_type_keywords = {
            TaskType.DEBUGGING: ["debug", "fix", "error", "bug", "broken", "not working", "issue"],
            TaskType.CODE_GENERATION: ["add", "create", "implement", "write", "new", "build", "generate"],
            TaskType.CODE_ANALYSIS: ["explain", "understand", "analyze", "how does", "what is", "find", "search"],
            TaskType.REFACTORING: ["refactor", "restructure", "reorganize", "improve", "optimize", "clean up"],
            TaskType.TESTING: ["test", "pytest", "unittest", "coverage", "verify"],
            TaskType.DOCUMENTATION: ["document", "doc", "readme", "comment", "docstring"],
            TaskType.FILE_OPERATIONS: ["rename", "move", "delete", "copy", "organize files"],
        }

    def detect_task_type(self, messages: List[Dict[str, str]]) -> TaskType:
        """Detect the task type from conversation messages.

        Args:
            messages: List of conversation messages

        Returns:
            TaskType enum value
        """
        # Get last user message
        user_messages = [m for m in messages if m.get("role") == "user"]
        if not user_messages:
            return TaskType.GENERAL

        last_message = user_messages[-1].get("content", "").lower()

        # Check for keyword matches
        for task_type, keywords in self.task_type_keywords.items():
            if any(keyword in last_message for keyword in keywords):
                logger.debug("Task type detected", task_type=task_type, keywords_matched=keywords)
                return task_type

        return TaskType.GENERAL

    def detect_model_family(self, model: str) -> ModelFamily:
        """Detect the model family from model name.

        Args:
            model: Model identifier string

        Returns:
            ModelFamily enum value
        """
        model_lower = model.lower()

        # Reasoning models
        if any(x in model_lower for x in ["r1", "o1", "o3", "reasoner", "reasoning", "deepseek-r1"]):
            return ModelFamily.REASONING

        # Claude models
        if "claude" in model_lower:
            return ModelFamily.CLAUDE

        # GPT models
        if "gpt" in model_lower or "openai" in model_lower:
            return ModelFamily.GPT

        # Gemini models
        if "gemini" in model_lower:
            return ModelFamily.GEMINI

        # Local models (Ollama)
        if "ollama" in model_lower or "local" in model_lower:
            return ModelFamily.LOCAL

        return ModelFamily.UNKNOWN

    def build(
        self,
        task_type: TaskType,
        model: str,
        tools_description: str,
        rules_text: str = "",
        memories_text: str = "",
        plan_context: Optional[str] = None
    ) -> str:
        """Build an optimized system prompt.

        Args:
            task_type: The type of task being performed
            model: Model identifier
            tools_description: Description of available tools
            rules_text: User-defined rules
            memories_text: Relevant memories
            plan_context: Optional execution plan context

        Returns:
            Complete system prompt
        """
        sections = [self.BASE_IDENTITY]

        # Add task-specific guidance
        if task_type == TaskType.CODE_GENERATION:
            sections.append(self.CODE_GENERATION_GUIDANCE)
        elif task_type == TaskType.CODE_ANALYSIS:
            sections.append(self.CODE_ANALYSIS_GUIDANCE)
        elif task_type == TaskType.DEBUGGING:
            sections.append(self.DEBUGGING_GUIDANCE)
        elif task_type == TaskType.REFACTORING:
            sections.append(self.REFACTORING_GUIDANCE)
        elif task_type == TaskType.TESTING:
            sections.append(self.TESTING_GUIDANCE)

        # Add core operational rules
        sections.append(self.CORE_RULES)

        # Add model-specific guidance
        model_family = self.detect_model_family(model)
        if model_family == ModelFamily.REASONING:
            sections.append(self.REASONING_MODEL_GUIDANCE)
        elif model_family == ModelFamily.CLAUDE:
            sections.append(self.CLAUDE_MODEL_GUIDANCE)

        # Add plan context if available
        if plan_context:
            sections.append(f"\nEXECUTION PLAN:\n{plan_context}")

        # Add tools description
        sections.append(f"\nAVAILABLE TOOLS:\n{tools_description}")

        # Add user rules if present
        if rules_text:
            sections.append(f"\nUSER-DEFINED RULES:\n{rules_text}")

        # Add memories if present
        if memories_text:
            sections.append(f"\nRELEVANT MEMORIES:\n{memories_text}")

        # Combine all sections
        full_prompt = "\n\n".join(sections)

        # Log prompt stats
        token_estimate = len(full_prompt.split())
        logger.info(
            "Prompt built",
            task_type=task_type.value,
            model_family=model_family.value,
            estimated_tokens=token_estimate,
            sections=len(sections)
        )

        return full_prompt

    def build_planning_prompt(
        self,
        task: str,
        context: Dict[str, Any],
        available_tools: List[str]
    ) -> List[Dict[str, str]]:
        """Build a prompt for task planning (used by TaskPlanner).

        Args:
            task: User's task description
            context: Context information (workspace, recent changes, etc.)
            available_tools: List of available tool names

        Returns:
            List of messages for the planning LLM call
        """
        system_prompt = """You are a task planning expert for an AI coding assistant.

Your job is to analyze a task and create an execution plan with:
1. Complexity assessment (SIMPLE, MODERATE, or COMPLEX)
2. Estimated file count and line count
3. Step-by-step execution plan
4. Risk identification
5. Dependencies

Be realistic and thorough in your analysis."""

        user_prompt = f"""Analyze this task and create an execution plan:

TASK: {task}

CONTEXT:
- Workspace: {context.get('workspace_path', 'unknown')}
- Available tools: {', '.join(available_tools[:20])}  # First 20 tools

Provide:
1. Complexity level (SIMPLE/MODERATE/COMPLEX)
2. Why this complexity level?
3. Estimated files to modify
4. Estimated lines of code
5. 3-5 key execution steps
6. Any risks or concerns
7. Should user approval be required? (yes/no)

Be concise but thorough."""

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

    def format_plan_for_prompt(self, plan: Any) -> str:
        """Format an execution plan for inclusion in the main prompt.

        Args:
            plan: ExecutionPlan object

        Returns:
            Formatted plan text
        """
        lines = [
            f"Task Complexity: {plan.complexity.value.upper()}",
            f"Estimated Files: {plan.estimated_files}",
            f"Estimated Lines: {plan.estimated_lines}",
            "",
            "Execution Steps:"
        ]

        for step in plan.steps[:5]:  # First 5 steps
            lines.append(f"{step.step_num}. {step.action}")
            if step.validation:
                lines.append(f"   Validation: {step.validation}")

        if plan.risks:
            lines.append("")
            lines.append("Risks to consider:")
            for risk in plan.risks:
                lines.append(f"⚠️  {risk}")

        return "\n".join(lines)

    def get_token_estimate(self, text: str) -> int:
        """Estimate token count for text.

        This is a rough estimate (not exact tokenization).

        Args:
            text: Text to estimate tokens for

        Returns:
            Estimated token count
        """
        # Rough estimate: 1 token ≈ 0.75 words
        # Or about 4 characters per token
        word_count = len(text.split())
        char_count = len(text)

        # Use the more conservative estimate
        token_by_words = int(word_count * 1.3)
        token_by_chars = int(char_count / 4)

        return max(token_by_words, token_by_chars)
