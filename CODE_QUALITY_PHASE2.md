# Code Quality System - Phase 2

## Overview

Phase 2 enhances code generation quality with comprehensive validation, verification, and smart editing capabilities. This phase builds on Phase 1's ReAct intelligence by ensuring the code produced is correct, well-formatted, and thoroughly tested.

## Phase 2 Components

### 1. CodeValidator Service
**File**: `backend/prometheus/services/code_validator.py`

Multi-stage code validation system:

**Validation Stages**:
1. **SYNTAX**: AST parsing with detailed error messages
2. **FORMATTING**: Black formatter integration (auto-fixable)
3. **IMPORTS**: Detect missing/unused imports
4. **TYPES**: Optional mypy type checking (strict mode)

```python
from prometheus.services.code_validator import CodeValidatorService, ValidationStage

validator = CodeValidatorService(
    workspace_path="/workspace",
    strict_mode=False  # Enable for type checking
)

# Validate Python code
results = await validator.validate_python(
    content=code_content,
    file_path="module.py",
    stages=[ValidationStage.SYNTAX, ValidationStage.IMPORTS]
)

# Check results
for result in results:
    if not result.passed:
        print(f"{result.stage}: {result.errors}")
    if result.auto_fixable and result.fixed_content:
        print(f"Auto-fix available for {result.stage}")
```

**Key Features**:
- Detailed syntax error messages with line numbers
- Intelligent fix suggestions for common errors
- Import analysis (missing/unused)
- Auto-formatting with Black
- Optional type checking with mypy

**Syntax Error Suggestions**:
- Unclosed brackets: "Add closing ')'"
- Missing colon: "Missing code block after colon"
- Indentation: "Use consistent 4-space indentation"
- Unterminated string: "Add closing quote"

### 2. VerificationLoop Service
**File**: `backend/prometheus/services/verification_loop.py`

Post-edit verification with escalating warnings:

**Verification Types**:
1. **SYNTAX**: Always runs, blocking on failure
2. **LINT**: Ruff/flake8 checks, non-blocking warnings
3. **TYPE_CHECK**: mypy checks, non-blocking
4. **UNIT_TESTS**: Related tests, user decides on failure

**Verification Levels**:
- **minimal**: Syntax only
- **standard**: Syntax + lint + tests (default)
- **thorough**: All checks including type checking

```python
from prometheus.services.verification_loop import VerificationLoopService

verifier = VerificationLoopService(
    code_validator=validator,
    workspace_path="/workspace",
    verification_level="standard"
)

# Verify after edits
results = await verifier.verify_changes(
    changed_files=["module.py", "utils.py"]
)

# Check for blocking issues
summary = verifier.get_verification_summary(results)
if not summary["can_continue"]:
    print("Blocking failures detected!")
    for result in results:
        if not result.passed and result.blocking:
            print(f"{result.type}: {result.errors}")
```

**Key Features**:
- Automatic test discovery (test_*.py, *_test.py)
- Linter integration (ruff preferred, flake8 fallback)
- Non-blocking warnings for lint/type issues
- Blocking errors for syntax failures
- User decision on test failures

### 3. IncrementalBuilder Service
**File**: `backend/prometheus/services/incremental_builder.py`

Build large files piece-by-piece to avoid truncation:

**Section Types**:
- **IMPORTS**: Import statements
- **CONSTANTS**: Module-level constants
- **CLASS**: Class definitions
- **FUNCTION**: Function definitions
- **MAIN**: Main execution block

```python
from prometheus.services.incremental_builder import (
    IncrementalBuilderService,
    CodeSection,
    SectionType
)

builder = IncrementalBuilderService(
    code_validator=validator,
    workspace_path="/workspace",
    max_section_lines=50
)

# Define sections
sections = [
    CodeSection(
        section_id="imports",
        section_type=SectionType.IMPORTS,
        content="import os\nimport sys"
    ),
    CodeSection(
        section_id="helper_func",
        section_type=SectionType.FUNCTION,
        content="def helper():\n    return True"
    ),
    CodeSection(
        section_id="main_class",
        section_type=SectionType.CLASS,
        content="class MyClass:\n    pass",
        dependencies=["helper_func"]  # Depends on helper_func
    )
]

# Build incrementally
result = await builder.build_file_incrementally(
    file_path="large_module.py",
    sections=sections,
    language="python"
)

if result["success"]:
    print(f"Built {result['sections_added']} sections")
    print(f"Final file: {result['final_lines']} lines")
```

**Build Process**:
1. Create skeleton with TODO placeholders
2. Order sections by dependencies
3. Add sections one at a time
4. Validate after each addition
5. Rollback on validation failure

**Benefits**:
- Prevents JSON truncation (no 2000+ token files)
- Validates incrementally (catches errors early)
- Dependency-aware ordering
- Automatic section splitting for large content

### 4. SmartEditor Service
**File**: `backend/prometheus/services/smart_editor.py`

Intelligent editing with diff preview and rollback:

```python
from prometheus.services.smart_editor import SmartEditorService

editor = SmartEditorService(workspace_path="/workspace")

# Preview edit before applying
preview = await editor.preview_edit(
    file_path="module.py",
    edit_type="replace_lines",
    start_line=10,
    end_line=15,
    replacement="def new_function():\n    pass"
)

print(f"Changes: +{preview['lines_added']} -{preview['lines_removed']}")
print(f"Diff:\n{preview['diff']}")

# Apply with automatic checkpoint
result = await editor.apply_edit_with_checkpoint(
    file_path="module.py",
    edit_type="replace_lines",
    description="Refactor authentication",
    start_line=10,
    end_line=15,
    replacement="def new_function():\n    pass"
)

print(f"Checkpoint ID: {result['checkpoint_id']}")

# Rollback if needed
if something_went_wrong:
    await editor.rollback_to_checkpoint(result['checkpoint_id'])
    # or
    await editor.rollback_last_edit()
```

**Edit Types Supported**:
- **replace_lines**: Replace line range
- **search_replace**: Find and replace text
- **insert**: Insert at line number
- **delete**: Delete line range

**Key Features**:
- Unified diff generation
- Automatic checkpoints before edits
- Rollback to any checkpoint
- Edit history tracking
- Change metrics (lines added/removed)

## Integration

### Environment Variables

```bash
# Enable Phase 2 features
export ENABLE_CODE_VALIDATION=true      # CodeValidator
export ENABLE_VERIFICATION_LOOP=true    # VerificationLoop
export ENABLE_INCREMENTAL_BUILD=true    # IncrementalBuilder
export ENABLE_SMART_EDITOR=true         # SmartEditor

# Verification level
export VERIFICATION_LEVEL=standard      # minimal | standard | thorough

# Validator strict mode
export STRICT_VALIDATION=false          # Enable type checking
```

### Usage in Agent Loop

The services integrate with the ReAct executor from Phase 1:

```python
# In ReAct observation phase (after tool execution)

# 1. Validate code after write
if tool_name == "filesystem_write":
    validator = CodeValidatorService(workspace_path)
    results = await validator.validate_python(
        content=written_content,
        file_path=file_path
    )

    if not all(r.passed for r in results):
        # Report validation errors to agent
        pass

# 2. Verify after all edits in iteration
if iteration_complete and files_changed:
    verifier = VerificationLoopService(validator, workspace_path)
    results = await verifier.verify_changes(files_changed)

    summary = verifier.get_verification_summary(results)
    if not summary["can_continue"]:
        # Block and request fixes
        pass

# 3. Use incremental builder for large files
if estimated_lines > 150:
    builder = IncrementalBuilderService(validator, workspace_path)
    # Split into sections and build incrementally
    pass

# 4. Use smart editor for preview
if preview_requested:
    editor = SmartEditorService(workspace_path)
    preview = await editor.preview_edit(...)
    # Show diff to user
    pass
```

## Testing

### Unit Tests

```bash
cd backend
poetry run pytest tests/test_code_validator.py -v
poetry run pytest tests/test_verification_loop.py -v
poetry run pytest tests/test_incremental_builder.py -v
poetry run pytest tests/test_smart_editor.py -v
```

### Integration Testing

```bash
# Enable all Phase 2 features
export ENABLE_CODE_VALIDATION=true
export ENABLE_VERIFICATION_LOOP=true
export ENABLE_INCREMENTAL_BUILD=true
export ENABLE_SMART_EDITOR=true

# Start Prometheus
docker compose up --build

# Test scenarios:
# 1. Write file with syntax error → Should block
# 2. Write file with lint warning → Should warn but continue
# 3. Create 200-line file → Should use incremental builder
# 4. Edit with preview → Should show diff before applying
```

## Workflow Examples

### Example 1: Simple Edit with Validation

```
User: "Add a hello() function to utils.py"

Agent:
1. Read utils.py
2. Generate new content
3. **CodeValidator**: Check syntax ✓
4. Write file
5. **VerificationLoop**: Run lint ⚠️ (warning: line too long)
6. Report: "Function added, lint warning: line 42 exceeds 100 chars"
```

### Example 2: Large File Creation

```
User: "Create a new TestSuite class with 20 test methods"

Agent:
1. Estimate: 250+ lines
2. **IncrementalBuilder**: Split into sections
   - Skeleton with TODOs
   - Add imports
   - Add class definition
   - Add method 1-10
   - Add method 11-20
3. Validate after each addition
4. Report: "TestSuite created with 20 methods, 287 lines"
```

### Example 3: Refactor with Preview

```
User: "Refactor the auth logic to use async"

Agent:
1. Read current auth code
2. Generate refactored version
3. **SmartEditor**: Preview diff
4. Show: "+45 lines, -32 lines"
5. User approves
6. **SmartEditor**: Apply with checkpoint
7. **VerificationLoop**: Run tests
8. Tests fail → **SmartEditor**: Rollback
9. Report: "Refactor caused test failures, rolled back"
```

## Success Metrics

After Phase 2 implementation:

✅ **Zero indentation errors** - Validation catches before write
✅ **90% fewer truncation issues** - Incremental building
✅ **Lint compliance** - Non-blocking warnings guide fixes
✅ **Test coverage maintained** - Verification catches breaks
✅ **Easy rollback** - Checkpoints enable quick recovery

## Backwards Compatibility

Phase 2 is fully backwards compatible:

- Feature flags default to OFF
- Falls back gracefully if tools missing (black, mypy, ruff)
- Existing validation preserved
- No breaking API changes
- Optional strict mode for type checking

## Troubleshooting

### Validation Too Strict

```bash
# Disable strict mode
export STRICT_VALIDATION=false

# Reduce verification level
export VERIFICATION_LEVEL=minimal
```

### Tools Not Found

Phase 2 gracefully degrades if tools missing:
- Black not installed → Skip formatting
- Mypy not installed → Skip type checking
- Ruff/flake8 not installed → Skip linting
- Pytest not installed → Skip test execution

Install optional tools:
```bash
pip install black mypy ruff pytest
```

### Incremental Build Too Slow

```bash
# Increase section size (default: 50 lines)
# Modify in IncrementalBuilderService initialization:
builder = IncrementalBuilderService(
    code_validator=validator,
    workspace_path=workspace,
    max_section_lines=100  # Larger sections
)
```

## Next Steps (Phase 3)

Planned for Phase 3:
- Advanced code analysis tools (import graphs, usage finder)
- Context optimization and caching
- GitHub MCP integration (PR creation, review parsing)
- Browser MCP integration (docs lookup)

---

**Version**: Phase 2 (Code Quality)
**Status**: Ready for testing
**Last Updated**: 2026-01-21
