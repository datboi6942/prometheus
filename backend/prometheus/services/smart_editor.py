"""Smart editor service with diff preview and rollback capabilities.

This service provides:
1. Diff preview before applying edits
2. Automatic checkpoints before edits
3. Rollback to any checkpoint
4. Edit history tracking
"""

import difflib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
import structlog

logger = structlog.get_logger()


class EditOperation(BaseModel):
    """Record of a single edit operation."""
    operation_id: str
    file_path: str
    edit_type: str  # "replace_lines", "search_replace", "insert", "delete"
    original_content: str
    new_content: str
    diff: str
    timestamp: str
    checkpoint_id: Optional[str] = None


class Checkpoint(BaseModel):
    """A checkpoint for rollback."""
    checkpoint_id: str
    file_path: str
    content: str
    timestamp: str
    description: str


class SmartEditorService:
    """Intelligent editing with preview and rollback."""

    def __init__(self, workspace_path: str):
        """Initialize smart editor.

        Args:
            workspace_path: Workspace root path
        """
        self.workspace_path = Path(workspace_path)
        self.edit_history: List[EditOperation] = []
        self.checkpoints: Dict[str, Checkpoint] = {}

    async def preview_edit(
        self,
        file_path: str,
        edit_type: str,
        **edit_args
    ) -> Dict[str, Any]:
        """Preview edit without applying it.

        Args:
            file_path: File to edit (relative to workspace)
            edit_type: Type of edit (replace_lines, search_replace, etc.)
            **edit_args: Edit-specific arguments

        Returns:
            Preview with diff
        """
        full_path = self.workspace_path / file_path

        try:
            # Read current content
            if not full_path.exists():
                return {
                    "success": False,
                    "error": f"File not found: {file_path}"
                }

            original_content = full_path.read_text()

            # Simulate edit
            if edit_type == "replace_lines":
                new_content = self._simulate_replace_lines(
                    original_content,
                    edit_args.get("start_line"),
                    edit_args.get("end_line"),
                    edit_args.get("replacement")
                )
            elif edit_type == "search_replace":
                new_content = original_content.replace(
                    edit_args.get("search", ""),
                    edit_args.get("replace", ""),
                    edit_args.get("count", -1)
                )
            elif edit_type == "insert":
                new_content = self._simulate_insert(
                    original_content,
                    edit_args.get("line_number"),
                    edit_args.get("content")
                )
            elif edit_type == "delete":
                new_content = self._simulate_delete(
                    original_content,
                    edit_args.get("start_line"),
                    edit_args.get("end_line")
                )
            else:
                return {
                    "success": False,
                    "error": f"Unknown edit type: {edit_type}"
                }

            # Generate diff
            diff = self._generate_unified_diff(
                original_content, new_content, file_path
            )

            # Count changes
            lines_changed = self._count_changed_lines(diff)

            return {
                "success": True,
                "file_path": file_path,
                "edit_type": edit_type,
                "diff": diff,
                "lines_added": lines_changed["added"],
                "lines_removed": lines_changed["removed"],
                "lines_changed": lines_changed["total"],
                "preview_content": new_content[:500]  # First 500 chars
            }

        except Exception as e:
            logger.error("Preview failed", file_path=file_path, error=str(e))
            return {
                "success": False,
                "error": f"Preview failed: {str(e)}"
            }

    async def apply_edit_with_checkpoint(
        self,
        file_path: str,
        edit_type: str,
        description: Optional[str] = None,
        **edit_args
    ) -> Dict[str, Any]:
        """Apply edit with automatic checkpoint.

        Args:
            file_path: File to edit
            edit_type: Type of edit
            description: Optional description for checkpoint
            **edit_args: Edit-specific arguments

        Returns:
            Result with checkpoint ID
        """
        full_path = self.workspace_path / file_path

        try:
            # Read original content
            if not full_path.exists():
                return {
                    "success": False,
                    "error": f"File not found: {file_path}"
                }

            original_content = full_path.read_text()

            # Create checkpoint
            checkpoint_id = await self.create_checkpoint(
                file_path=file_path,
                content=original_content,
                description=description or f"Before {edit_type} on {file_path}"
            )

            # Apply edit
            if edit_type == "replace_lines":
                new_content = self._simulate_replace_lines(
                    original_content,
                    edit_args.get("start_line"),
                    edit_args.get("end_line"),
                    edit_args.get("replacement")
                )
            elif edit_type == "search_replace":
                new_content = original_content.replace(
                    edit_args.get("search", ""),
                    edit_args.get("replace", ""),
                    edit_args.get("count", -1)
                )
            elif edit_type == "insert":
                new_content = self._simulate_insert(
                    original_content,
                    edit_args.get("line_number"),
                    edit_args.get("content")
                )
            elif edit_type == "delete":
                new_content = self._simulate_delete(
                    original_content,
                    edit_args.get("start_line"),
                    edit_args.get("end_line")
                )
            else:
                return {
                    "success": False,
                    "error": f"Unknown edit type: {edit_type}"
                }

            # Write new content
            full_path.write_text(new_content)

            # Generate diff
            diff = self._generate_unified_diff(
                original_content, new_content, file_path
            )

            # Record in history
            operation = EditOperation(
                operation_id=str(uuid.uuid4()),
                file_path=file_path,
                edit_type=edit_type,
                original_content=original_content,
                new_content=new_content,
                diff=diff,
                timestamp=datetime.now(timezone.utc).isoformat(),
                checkpoint_id=checkpoint_id
            )
            self.edit_history.append(operation)

            logger.info(
                "Edit applied with checkpoint",
                file_path=file_path,
                edit_type=edit_type,
                checkpoint_id=checkpoint_id
            )

            # Automatically clean up old checkpoints to prevent memory growth
            # Keep last 10 checkpoints per file
            if len(self.checkpoints) > 20:  # Only clean if we have many checkpoints
                self.clear_old_checkpoints(keep_last=10)

            return {
                "success": True,
                "file_path": file_path,
                "edit_type": edit_type,
                "checkpoint_id": checkpoint_id,
                "operation_id": operation.operation_id,
                "diff": diff,
                "can_rollback": True
            }

        except Exception as e:
            logger.error(
                "Edit failed",
                file_path=file_path,
                edit_type=edit_type,
                error=str(e)
            )
            return {
                "success": False,
                "error": f"Edit failed: {str(e)}"
            }

    async def create_checkpoint(
        self,
        file_path: str,
        content: str,
        description: str
    ) -> str:
        """Create a checkpoint for rollback.

        Args:
            file_path: File path
            content: File content to save
            description: Checkpoint description

        Returns:
            Checkpoint ID
        """
        checkpoint_id = str(uuid.uuid4())

        checkpoint = Checkpoint(
            checkpoint_id=checkpoint_id,
            file_path=file_path,
            content=content,
            timestamp=datetime.now(timezone.utc).isoformat(),
            description=description
        )

        self.checkpoints[checkpoint_id] = checkpoint

        logger.debug(
            "Checkpoint created",
            checkpoint_id=checkpoint_id,
            file_path=file_path
        )

        return checkpoint_id

    async def rollback_to_checkpoint(self, checkpoint_id: str) -> Dict[str, Any]:
        """Rollback file to a checkpoint.

        Args:
            checkpoint_id: Checkpoint to restore

        Returns:
            Result dictionary
        """
        if checkpoint_id not in self.checkpoints:
            return {
                "success": False,
                "error": f"Checkpoint not found: {checkpoint_id}"
            }

        checkpoint = self.checkpoints[checkpoint_id]
        full_path = self.workspace_path / checkpoint.file_path

        try:
            # Restore content
            full_path.write_text(checkpoint.content)

            logger.info(
                "Rolled back to checkpoint",
                checkpoint_id=checkpoint_id,
                file_path=checkpoint.file_path
            )

            return {
                "success": True,
                "checkpoint_id": checkpoint_id,
                "file_path": checkpoint.file_path,
                "description": checkpoint.description,
                "timestamp": checkpoint.timestamp
            }

        except Exception as e:
            logger.error(
                "Rollback failed",
                checkpoint_id=checkpoint_id,
                error=str(e)
            )
            return {
                "success": False,
                "error": f"Rollback failed: {str(e)}"
            }

    async def rollback_last_edit(self) -> Dict[str, Any]:
        """Rollback the last edit operation.

        Returns:
            Result dictionary
        """
        if not self.edit_history:
            return {
                "success": False,
                "error": "No edits to rollback"
            }

        last_edit = self.edit_history[-1]

        if not last_edit.checkpoint_id:
            return {
                "success": False,
                "error": "No checkpoint available for last edit"
            }

        # Rollback to checkpoint
        result = await self.rollback_to_checkpoint(last_edit.checkpoint_id)

        if result["success"]:
            # Remove from history
            self.edit_history.pop()

        return result

    def _simulate_replace_lines(
        self,
        content: str,
        start_line: int,
        end_line: int,
        replacement: str
    ) -> str:
        """Simulate replace_lines operation."""
        lines = content.splitlines()

        # Replace lines (1-indexed)
        new_lines = (
            lines[:start_line - 1] +
            replacement.splitlines() +
            lines[end_line:]
        )

        return "\n".join(new_lines)

    def _simulate_insert(
        self,
        content: str,
        line_number: int,
        insert_content: str
    ) -> str:
        """Simulate insert operation."""
        lines = content.splitlines()

        # Insert at line (1-indexed)
        insert_index = line_number - 1
        new_lines = (
            lines[:insert_index] +
            insert_content.splitlines() +
            lines[insert_index:]
        )

        return "\n".join(new_lines)

    def _simulate_delete(
        self,
        content: str,
        start_line: int,
        end_line: int
    ) -> str:
        """Simulate delete operation."""
        lines = content.splitlines()

        # Delete lines (1-indexed)
        new_lines = lines[:start_line - 1] + lines[end_line:]

        return "\n".join(new_lines)

    def _generate_unified_diff(
        self,
        original: str,
        new: str,
        file_path: str
    ) -> str:
        """Generate unified diff between original and new content."""
        original_lines = original.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)

        diff = difflib.unified_diff(
            original_lines,
            new_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
            lineterm=""
        )

        return "".join(diff)

    def _count_changed_lines(self, diff: str) -> Dict[str, int]:
        """Count added/removed lines in diff."""
        added = 0
        removed = 0

        for line in diff.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                added += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed += 1

        return {
            "added": added,
            "removed": removed,
            "total": added + removed
        }

    def get_edit_history(self, file_path: Optional[str] = None) -> List[EditOperation]:
        """Get edit history, optionally filtered by file.

        Args:
            file_path: Optional file path to filter by

        Returns:
            List of edit operations
        """
        if file_path:
            return [e for e in self.edit_history if e.file_path == file_path]
        return self.edit_history

    def get_checkpoints(self, file_path: Optional[str] = None) -> List[Checkpoint]:
        """Get checkpoints, optionally filtered by file.

        Args:
            file_path: Optional file path to filter by

        Returns:
            List of checkpoints
        """
        checkpoints = list(self.checkpoints.values())

        if file_path:
            checkpoints = [c for c in checkpoints if c.file_path == file_path]

        # Sort by timestamp (newest first)
        checkpoints.sort(key=lambda c: c.timestamp, reverse=True)

        return checkpoints

    def clear_old_checkpoints(self, keep_last: int = 10):
        """Clear old checkpoints, keeping only recent ones.

        Args:
            keep_last: Number of recent checkpoints to keep per file
        """
        # Group by file
        by_file: Dict[str, List[Checkpoint]] = {}
        for checkpoint in self.checkpoints.values():
            if checkpoint.file_path not in by_file:
                by_file[checkpoint.file_path] = []
            by_file[checkpoint.file_path].append(checkpoint)

        # Keep only recent checkpoints per file
        to_remove = []
        for file_path, checkpoints in by_file.items():
            # Sort by timestamp
            checkpoints.sort(key=lambda c: c.timestamp, reverse=True)

            # Mark old ones for removal
            if len(checkpoints) > keep_last:
                to_remove.extend([c.checkpoint_id for c in checkpoints[keep_last:]])

        # Remove
        for checkpoint_id in to_remove:
            del self.checkpoints[checkpoint_id]

        logger.info(
            "Cleared old checkpoints",
            removed=len(to_remove),
            remaining=len(self.checkpoints)
        )
