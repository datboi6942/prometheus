"""Incremental file builder service for constructing large files piece-by-piece.

This service helps avoid truncation issues when creating large files by:
1. Creating a skeleton with placeholders
2. Adding sections incrementally in dependency order
3. Validating after each addition
4. Rollback on failures
"""

from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
import structlog

from prometheus.services.code_validator import CodeValidatorService, ValidationStage

logger = structlog.get_logger()


class SectionType(str, Enum):
    """Types of code sections."""
    IMPORTS = "imports"
    CONSTANTS = "constants"
    CLASS = "class"
    FUNCTION = "function"
    MAIN = "main"
    DOCSTRING = "docstring"


class CodeSection(BaseModel):
    """A section of code to be added incrementally."""
    section_id: str
    section_type: SectionType
    content: str
    dependencies: List[str] = Field(default_factory=list)  # Other section IDs
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    description: Optional[str] = None


class BuildStep(BaseModel):
    """A single step in incremental build."""
    step_num: int
    section: CodeSection
    status: str  # "pending", "in_progress", "completed", "failed"
    error: Optional[str] = None


class IncrementalBuilderService:
    """Build large files incrementally to avoid truncation."""

    def __init__(
        self,
        code_validator: CodeValidatorService,
        workspace_path: str,
        max_section_lines: int = 50
    ):
        """Initialize incremental builder.

        Args:
            code_validator: CodeValidator instance
            workspace_path: Workspace root path
            max_section_lines: Maximum lines per section (for splitting)
        """
        self.code_validator = code_validator
        self.workspace_path = Path(workspace_path)
        self.max_section_lines = max_section_lines

    async def build_file_incrementally(
        self,
        file_path: str,
        sections: List[CodeSection],
        language: str = "python"
    ) -> Dict[str, Any]:
        """Build file section by section with validation.

        Args:
            file_path: Target file path (relative to workspace)
            sections: List of code sections to add
            language: Programming language

        Returns:
            Result dictionary with success status
        """
        logger.info(
            "Starting incremental build",
            file_path=file_path,
            sections=len(sections),
            language=language
        )

        full_path = self.workspace_path / file_path

        # Step 1: Create skeleton
        skeleton = self._create_skeleton(sections, language)

        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(skeleton)

            logger.debug("Skeleton created", file_path=file_path, lines=len(skeleton.splitlines()))

        except Exception as e:
            logger.error("Failed to create skeleton", file_path=file_path, error=str(e))
            return {
                "success": False,
                "error": f"Failed to create skeleton: {str(e)}"
            }

        # Step 2: Order sections by dependencies
        ordered_sections = self._order_by_dependencies(sections)

        # Step 3: Add sections incrementally
        build_steps = []

        for i, section in enumerate(ordered_sections, 1):
            step = BuildStep(
                step_num=i,
                section=section,
                status="in_progress"
            )
            build_steps.append(step)

            logger.debug(
                "Adding section",
                step=i,
                section_id=section.section_id,
                type=section.section_type.value
            )

            try:
                # Read current content
                current_content = full_path.read_text()

                # Find insertion point
                insert_line = self._find_insertion_point(
                    current_content, section, language
                )

                # Insert section
                new_content = self._insert_section_at_line(
                    current_content, section.content, insert_line
                )

                # Write updated content
                full_path.write_text(new_content)

                # Validate after addition
                if language == "python":
                    validation = await self._validate_current_state(new_content, file_path)

                    if not validation["valid"]:
                        logger.error(
                            "Validation failed after adding section",
                            section=section.section_id,
                            error=validation["error"]
                        )

                        step.status = "failed"
                        step.error = validation["error"]

                        return {
                            "success": False,
                            "error": f"Validation failed after {section.section_id}: {validation['error']}",
                            "section_id": section.section_id,
                            "completed_steps": i - 1,
                            "total_steps": len(ordered_sections),
                            "build_steps": [s.dict() for s in build_steps]
                        }

                step.status = "completed"
                logger.debug("Section added successfully", section_id=section.section_id)

            except Exception as e:
                logger.error(
                    "Failed to add section",
                    section=section.section_id,
                    error=str(e)
                )

                step.status = "failed"
                step.error = str(e)

                return {
                    "success": False,
                    "error": f"Failed to add section {section.section_id}: {str(e)}",
                    "section_id": section.section_id,
                    "completed_steps": i - 1,
                    "total_steps": len(ordered_sections),
                    "build_steps": [s.dict() for s in build_steps]
                }

        # Build complete
        final_content = full_path.read_text()
        final_lines = len(final_content.splitlines())

        logger.info(
            "Incremental build complete",
            file_path=file_path,
            sections_added=len(sections),
            final_lines=final_lines
        )

        return {
            "success": True,
            "file_path": file_path,
            "sections_added": len(sections),
            "final_lines": final_lines,
            "build_steps": [s.dict() for s in build_steps]
        }

    def _create_skeleton(self, sections: List[CodeSection], language: str) -> str:
        """Create file skeleton with TODOs.

        Args:
            sections: List of sections
            language: Programming language

        Returns:
            Skeleton content
        """
        if language == "python":
            lines = ['#!/usr/bin/env python3', '"""Module docstring."""', '']

            # Add import placeholders
            import_sections = [s for s in sections if s.section_type == SectionType.IMPORTS]
            if import_sections:
                lines.append("# Imports will be added here")
                lines.append("")

            # Add section placeholders
            for section in sections:
                if section.section_type != SectionType.IMPORTS:
                    desc = section.description or section.section_id
                    lines.append(f"# TODO: Add {desc}")

            lines.append("")  # Blank line at end

            return "\n".join(lines)

        # Default skeleton for unknown languages
        return f"# Skeleton for {language} file\n\n"

    def _order_by_dependencies(self, sections: List[CodeSection]) -> List[CodeSection]:
        """Order sections by dependencies.

        Args:
            sections: Unordered sections

        Returns:
            Sections ordered such that dependencies come first
        """
        # Build dependency graph
        section_map = {s.section_id: s for s in sections}
        ordered = []
        added = set()

        def add_section(section_id: str):
            if section_id in added:
                return

            section = section_map.get(section_id)
            if not section:
                return

            # Add dependencies first
            for dep_id in section.dependencies:
                add_section(dep_id)

            # Then add this section
            ordered.append(section)
            added.add(section_id)

        # Add all sections (respecting dependencies)
        for section in sections:
            add_section(section.section_id)

        return ordered

    def _find_insertion_point(
        self,
        current_content: str,
        section: CodeSection,
        language: str
    ) -> int:
        """Find the line number where section should be inserted.

        Args:
            current_content: Current file content
            section: Section to insert
            language: Programming language

        Returns:
            Line number (1-indexed)
        """
        lines = current_content.splitlines()

        if language == "python":
            # Find appropriate insertion point based on section type
            if section.section_type == SectionType.IMPORTS:
                # Insert after module docstring
                for i, line in enumerate(lines):
                    if '"""' in line or "'''" in line:
                        # Find closing docstring
                        for j in range(i + 1, len(lines)):
                            if '"""' in lines[j] or "'''" in lines[j]:
                                return j + 2  # After closing docstring + blank line
                return 3  # Default: after first 3 lines

            elif section.section_type == SectionType.CONSTANTS:
                # After imports
                last_import = 0
                for i, line in enumerate(lines):
                    if line.startswith("import ") or line.startswith("from "):
                        last_import = i
                return last_import + 2

            elif section.section_type == SectionType.FUNCTION:
                # Find the TODO marker for this section
                for i, line in enumerate(lines):
                    if f"TODO: Add {section.section_id}" in line:
                        return i + 1
                # Default: end of file
                return len(lines)

            elif section.section_type == SectionType.CLASS:
                # Find the TODO marker or after constants
                for i, line in enumerate(lines):
                    if f"TODO: Add {section.section_id}" in line:
                        return i + 1
                # Default: end of file
                return len(lines)

            elif section.section_type == SectionType.MAIN:
                # End of file
                return len(lines)

        # Default: end of file
        return len(lines)

    def _insert_section_at_line(
        self,
        current_content: str,
        section_content: str,
        line_number: int
    ) -> str:
        """Insert section at specified line.

        Args:
            current_content: Current file content
            section_content: Content to insert
            line_number: Line number (1-indexed)

        Returns:
            Updated content
        """
        lines = current_content.splitlines()

        # Insert at line (0-indexed)
        insert_index = max(0, line_number - 1)

        # Split section content into lines
        section_lines = section_content.splitlines()

        # Insert
        new_lines = lines[:insert_index] + section_lines + lines[insert_index:]

        return "\n".join(new_lines)

    async def _validate_current_state(
        self,
        content: str,
        file_path: str
    ) -> Dict[str, Any]:
        """Validate current file state.

        Args:
            content: File content
            file_path: File path

        Returns:
            Validation result
        """
        try:
            results = await self.code_validator.validate_python(
                content=content,
                file_path=file_path,
                stages=[ValidationStage.SYNTAX]
            )

            syntax_result = results[0]

            return {
                "valid": syntax_result.passed,
                "error": syntax_result.errors[0] if syntax_result.errors else None
            }

        except Exception as e:
            return {
                "valid": False,
                "error": f"Validation failed: {str(e)}"
            }

    def split_large_content(
        self,
        content: str,
        section_type: SectionType
    ) -> List[CodeSection]:
        """Split large content into smaller sections.

        Args:
            content: Content to split
            section_type: Type of sections

        Returns:
            List of code sections
        """
        lines = content.splitlines()

        if len(lines) <= self.max_section_lines:
            # No split needed
            return [CodeSection(
                section_id=f"{section_type.value}_1",
                section_type=section_type,
                content=content
            )]

        # Split into chunks
        sections = []
        chunk_num = 1

        for i in range(0, len(lines), self.max_section_lines):
            chunk_lines = lines[i:i + self.max_section_lines]
            chunk_content = "\n".join(chunk_lines)

            section = CodeSection(
                section_id=f"{section_type.value}_{chunk_num}",
                section_type=section_type,
                content=chunk_content,
                dependencies=[f"{section_type.value}_{chunk_num-1}"] if chunk_num > 1 else []
            )
            sections.append(section)
            chunk_num += 1

        return sections
