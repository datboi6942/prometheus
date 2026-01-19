import difflib
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class FileReadRequest(BaseModel):
    path: str
    offset: int | None = None  # Starting line (1-indexed)
    limit: int | None = None   # Number of lines to read


class FileWriteRequest(BaseModel):
    path: str
    content: str


class ShellExecuteRequest(BaseModel):
    command: str
    cwd: str | None = None


class GrepRequest(BaseModel):
    pattern: str
    path: str
    recursive: bool = False
    case_insensitive: bool = False
    show_line_numbers: bool = True
    files_only: bool = False
    context_lines: int = 0


class MCPTools:
    """Model Context Protocol tools for filesystem and shell operations."""

    def __init__(self, workspace_path: str) -> None:
        self.workspace_path = Path(workspace_path).resolve()
        if not self.workspace_path.exists():
            self.workspace_path.mkdir(parents=True, exist_ok=True)

    def _validate_path(self, path: str) -> Path:
        """Validate that path is within workspace.

        Args:
            path (str): The file path to validate.

        Returns:
            Path: The resolved absolute path.

        Raises:
            ValueError: If path is outside workspace.
        """
        full_path = (self.workspace_path / path).resolve()
        if not str(full_path).startswith(str(self.workspace_path)):
            raise ValueError(f"Path {path} is outside workspace")
        return full_path

    def _generate_diff(
        self, path: str, old_content: str, new_content: str
    ) -> dict[str, Any] | None:
        """Generate structured diff data using difflib.

        Args:
            path (str): File path for context.
            old_content (str): Original file content.
            new_content (str): New file content.

        Returns:
            dict[str, Any] | None: Structured diff data or None if no changes.
        """
        # Skip diff generation for very large files (>10,000 lines)
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        if len(old_lines) > 10000 or len(new_lines) > 10000:
            return None

        # Generate unified diff
        diff_lines = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                lineterm="",
            )
        )

        if not diff_lines:
            return None

        # Parse diff into hunks
        hunks = []
        current_hunk = None
        lines_added = 0
        lines_removed = 0

        for line in diff_lines:
            # Skip header lines
            if line.startswith("---") or line.startswith("+++"):
                continue

            # Hunk header line
            if line.startswith("@@"):
                if current_hunk:
                    hunks.append(current_hunk)
                current_hunk = {"header": line, "changes": []}
                continue

            # Content lines
            if current_hunk is not None:
                if line.startswith("+"):
                    current_hunk["changes"].append(
                        {"type": "added", "line": line[1:]}
                    )
                    lines_added += 1
                elif line.startswith("-"):
                    current_hunk["changes"].append(
                        {"type": "removed", "line": line[1:]}
                    )
                    lines_removed += 1
                else:
                    # Context line (starts with space or is empty)
                    current_hunk["changes"].append(
                        {"type": "context", "line": line[1:] if line else ""}
                    )

        # Add last hunk
        if current_hunk:
            hunks.append(current_hunk)

        lines_changed = min(lines_added, lines_removed)

        return {
            "format": "unified",
            "stats": {
                "lines_added": lines_added,
                "lines_removed": lines_removed,
                "lines_changed": lines_changed,
            },
            "hunks": hunks,
        }

    def filesystem_read(
        self, path: str, offset: int | None = None, limit: int | None = None
    ) -> dict[str, Any]:
        """Read a file from the workspace.

        Args:
            path (str): Relative path within workspace.
            offset (int | None): Starting line number (1-indexed). If None, starts from beginning.
            limit (int | None): Number of lines to read. If None, reads to end.

        Returns:
            dict[str, Any]: File content and metadata.
        """
        try:
            full_path = self._validate_path(path)
            if not full_path.exists():
                return {"error": f"File not found: {path}"}

            with open(full_path, "r", encoding="utf-8") as f:
                all_lines = f.readlines()

            total_lines = len(all_lines)

            # Apply offset and limit if provided
            if offset is not None or limit is not None:
                start_idx = (offset - 1) if offset and offset > 0 else 0
                end_idx = (start_idx + limit) if limit else total_lines

                # Clamp to valid range
                start_idx = max(0, min(start_idx, total_lines))
                end_idx = max(start_idx, min(end_idx, total_lines))

                selected_lines = all_lines[start_idx:end_idx]
                content = "".join(selected_lines)

                # Add line numbers for context
                numbered_content = ""
                for i, line in enumerate(selected_lines, start=start_idx + 1):
                    numbered_content += f"{i:6d}\t{line}"

                return {
                    "success": True,
                    "path": path,
                    "content": numbered_content,
                    "raw_content": content,
                    "total_lines": total_lines,
                    "showing_lines": f"{start_idx + 1}-{end_idx}",
                    "offset": start_idx + 1,
                    "limit": end_idx - start_idx,
                }
            else:
                # Return full content with line numbers for files under 2000 lines
                content = "".join(all_lines)

                if total_lines <= 2000:
                    numbered_content = ""
                    for i, line in enumerate(all_lines, start=1):
                        numbered_content += f"{i:6d}\t{line}"
                    display_content = numbered_content
                else:
                    # For very large files, show truncated with hint
                    display_content = "".join(all_lines[:1000])
                    display_content += f"\n\n... [{total_lines - 2000} lines omitted] ...\n\n"
                    display_content += "".join(all_lines[-1000:])

                return {
                    "success": True,
                    "path": path,
                    "content": display_content,
                    "raw_content": content,
                    "total_lines": total_lines,
                    "size": len(content),
                }
        except Exception as e:
            return {"error": str(e)}

    def filesystem_write(self, path: str, content: str) -> dict[str, Any]:
        """Write content to a file in the workspace.

        Args:
            path (str): Relative path within workspace.
            content (str): Content to write.

        Returns:
            dict[str, Any]: Operation result with optional diff.
        """
        try:
            full_path = self._validate_path(path)
            file_existed = full_path.exists()
            old_content = None

            # Read old content if file exists
            if file_existed:
                try:
                    with open(full_path, "r", encoding="utf-8") as f:
                        old_content = f.read()
                except Exception:
                    # If read fails, treat as new file
                    old_content = None

            full_path.parent.mkdir(parents=True, exist_ok=True)

            # Write new content
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)

            result = {
                "success": True,
                "path": path,
                "size": len(content),
                "action": "modified" if file_existed else "created",
                "content": content,  # Include content for frontend animation
            }

            # Generate diff for modified files
            if file_existed and old_content is not None:
                diff_data = self._generate_diff(path, old_content, content)
                if diff_data:
                    result["diff"] = diff_data

            return result
        except Exception as e:
            return {"error": str(e)}

    def filesystem_replace_lines(
        self, path: str, start_line: int, end_line: int, replacement: str
    ) -> dict[str, Any]:
        """Replace a specific range of lines in a file.

        Args:
            path (str): Relative path within workspace.
            start_line (int): Starting line number (1-indexed).
            end_line (int): Ending line number (1-indexed, inclusive).
            replacement (str): New content to replace the line range.

        Returns:
            dict[str, Any]: Operation result with diff.
        """
        try:
            full_path = self._validate_path(path)

            if not full_path.exists():
                return {"error": f"File not found: {path}"}

            # Read existing content
            with open(full_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            old_content = "".join(lines)

            # Validate line numbers
            if start_line < 1 or end_line < start_line or start_line > len(lines):
                return {
                    "error": f"Invalid line range: {start_line}-{end_line} (file has {len(lines)} lines)"
                }

            # Perform replacement
            end_line = min(end_line, len(lines))
            new_lines = (
                lines[: start_line - 1]
                + [replacement if replacement.endswith("\n") else replacement + "\n"]
                + lines[end_line:]
            )
            new_content = "".join(new_lines)

            # Write modified content
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(new_content)

            result = {
                "success": True,
                "path": path,
                "action": "modified",
                "lines_replaced": f"{start_line}-{end_line}",
            }

            # Generate diff
            diff_data = self._generate_diff(path, old_content, new_content)
            if diff_data:
                result["diff"] = diff_data

            return result
        except Exception as e:
            return {"error": str(e)}

    def filesystem_search_replace(
        self, path: str, search: str, replace: str, count: int = -1
    ) -> dict[str, Any]:
        """Search and replace text in a file.

        Args:
            path (str): Relative path within workspace.
            search (str): Text to search for (exact match).
            replace (str): Text to replace with.
            count (int): Maximum number of replacements (-1 for all).

        Returns:
            dict[str, Any]: Operation result with diff.
        """
        try:
            full_path = self._validate_path(path)

            if not full_path.exists():
                return {"error": f"File not found: {path}"}

            # Read existing content
            with open(full_path, "r", encoding="utf-8") as f:
                old_content = f.read()

            # Check if search text exists
            if search not in old_content:
                return {
                    "success": False,
                    "error": f"Search text not found in file: {search[:50]}...",
                }

            # Perform replacement
            new_content = old_content.replace(search, replace, count)
            num_replacements = old_content.count(search) if count == -1 else min(count, old_content.count(search))

            # Write modified content
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(new_content)

            result = {
                "success": True,
                "path": path,
                "action": "modified",
                "replacements": num_replacements,
            }

            # Generate diff
            diff_data = self._generate_diff(path, old_content, new_content)
            if diff_data:
                result["diff"] = diff_data

            return result
        except Exception as e:
            return {"error": str(e)}

    def filesystem_insert(
        self, path: str, line_number: int, content: str
    ) -> dict[str, Any]:
        """Insert content at a specific line in a file.

        Args:
            path (str): Relative path within workspace.
            line_number (int): Line number to insert at (1-indexed, inserts before this line).
            content (str): Content to insert.

        Returns:
            dict[str, Any]: Operation result with diff.
        """
        try:
            full_path = self._validate_path(path)

            if not full_path.exists():
                return {"error": f"File not found: {path}"}

            # Read existing content
            with open(full_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            old_content = "".join(lines)

            # Validate line number
            if line_number < 1 or line_number > len(lines) + 1:
                return {
                    "error": f"Invalid line number: {line_number} (file has {len(lines)} lines)"
                }

            # Insert content
            content_with_newline = content if content.endswith("\n") else content + "\n"
            new_lines = lines[: line_number - 1] + [content_with_newline] + lines[line_number - 1 :]
            new_content = "".join(new_lines)

            # Write modified content
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(new_content)

            result = {
                "success": True,
                "path": path,
                "action": "modified",
                "inserted_at": line_number,
            }

            # Generate diff
            diff_data = self._generate_diff(path, old_content, new_content)
            if diff_data:
                result["diff"] = diff_data

            return result
        except Exception as e:
            return {"error": str(e)}

    def filesystem_list(self, path: str = "") -> dict[str, Any]:
        """List contents of a directory in the workspace.

        Args:
            path (str): Relative path within workspace (empty for root).

        Returns:
            dict[str, Any]: Directory listing with files and subdirectories.
        """
        try:
            if path:
                full_path = self._validate_path(path)
            else:
                full_path = self.workspace_path

            if not full_path.exists():
                return {"error": f"Directory not found: {path}"}

            if not full_path.is_dir():
                return {"error": f"Path is not a directory: {path}"}

            items = []
            for item in sorted(full_path.iterdir()):
                # Skip hidden files
                if item.name.startswith("."):
                    continue

                item_info = {
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "path": str(item.relative_to(self.workspace_path)),
                }

                if item.is_file():
                    item_info["size"] = item.stat().st_size

                items.append(item_info)

            return {
                "success": True,
                "path": path,
                "items": items,
            }
        except Exception as e:
            return {"error": str(e)}

    def filesystem_delete(self, path: str) -> dict[str, Any]:
        """Delete a file or directory in the workspace.

        Args:
            path (str): Relative path within workspace.

        Returns:
            dict[str, Any]: Operation result.
        """
        try:
            full_path = self._validate_path(path)

            if not full_path.exists():
                return {"error": f"File not found: {path}"}

            if full_path.is_dir():
                full_path.rmdir()
                action = "deleted_directory"
            else:
                full_path.unlink()
                action = "deleted"

            return {"success": True, "path": path, "action": action}
        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": str(e)}

    def grep(
        self,
        pattern: str,
        path: str = "",
        recursive: bool = False,
        case_insensitive: bool = False,
        show_line_numbers: bool = True,
        files_only: bool = False,
        context_lines: int = 0,
    ) -> dict[str, Any]:
        """Search for pattern in files (like Linux grep).

        Args:
            pattern (str): Regular expression pattern to search for.
            path (str): File or directory path to search (empty for workspace root).
            recursive (bool): Search recursively in directories.
            case_insensitive (bool): Case-insensitive search.
            show_line_numbers (bool): Show line numbers in results.
            files_only (bool): Only show filenames with matches (like grep -l).
            context_lines (int): Number of context lines to show around matches.

        Returns:
            dict[str, Any]: Search results with matches.
        """
        try:
            if path:
                full_path = self._validate_path(path)
            else:
                full_path = self.workspace_path

            if not full_path.exists():
                return {"error": f"Path not found: {path}"}

            # Compile regex pattern
            flags = re.IGNORECASE if case_insensitive else 0
            try:
                regex = re.compile(pattern, flags)
            except re.error as e:
                return {"error": f"Invalid regex pattern: {e}"}

            matches = []
            files_searched = 0
            total_matches = 0

            def search_file(file_path: Path) -> None:
                """Search a single file for pattern matches."""
                nonlocal files_searched, total_matches

                try:
                    # Skip binary files and very large files
                    if file_path.stat().st_size > 10_000_000:  # Skip files > 10MB
                        return

                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()

                    files_searched += 1
                    matched_lines = []

                    for line_num, line in enumerate(lines, start=1):
                        if regex.search(line):
                            matched_lines.append(line_num)

                    if matched_lines:
                        total_matches += len(matched_lines)
                        relative_path = str(file_path.relative_to(self.workspace_path))

                        if files_only:
                            # Just return filename
                            matches.append({
                                "file": relative_path,
                                "match_count": len(matched_lines)
                            })
                        else:
                            # Return detailed matches with context
                            file_matches = []
                            for line_num in matched_lines:
                                match_info = {
                                    "line_number": line_num,
                                    "line": lines[line_num - 1].rstrip()
                                }

                                # Add context lines if requested
                                if context_lines > 0:
                                    context_before = []
                                    context_after = []

                                    for i in range(1, context_lines + 1):
                                        if line_num - i > 0:
                                            context_before.insert(0, {
                                                "line_number": line_num - i,
                                                "line": lines[line_num - i - 1].rstrip()
                                            })
                                        if line_num + i <= len(lines):
                                            context_after.append({
                                                "line_number": line_num + i,
                                                "line": lines[line_num + i - 1].rstrip()
                                            })

                                    if context_before:
                                        match_info["context_before"] = context_before
                                    if context_after:
                                        match_info["context_after"] = context_after

                                file_matches.append(match_info)

                            matches.append({
                                "file": relative_path,
                                "match_count": len(matched_lines),
                                "matches": file_matches
                            })

                except (UnicodeDecodeError, PermissionError):
                    # Skip files that can't be read
                    pass

            # Search files
            if full_path.is_file():
                # Search single file
                search_file(full_path)
            elif full_path.is_dir():
                # Search directory
                if recursive:
                    # Recursive search
                    for file_path in full_path.rglob("*"):
                        if file_path.is_file() and not file_path.name.startswith("."):
                            search_file(file_path)
                else:
                    # Non-recursive search (only immediate files)
                    for file_path in full_path.iterdir():
                        if file_path.is_file() and not file_path.name.startswith("."):
                            search_file(file_path)
            else:
                return {"error": f"Path is neither file nor directory: {path}"}

            return {
                "success": True,
                "pattern": pattern,
                "path": path or ".",
                "files_searched": files_searched,
                "total_matches": total_matches,
                "files_with_matches": len(matches),
                "matches": matches,
                "case_insensitive": case_insensitive,
                "recursive": recursive,
            }

        except Exception as e:
            return {"error": str(e)}

    def run_python(
        self, file_path: str, stdin_input: str = "", args: str = ""
    ) -> dict[str, Any]:
        """Run a Python file with optional stdin input for testing.

        Args:
            file_path (str): Path to Python file within workspace.
            stdin_input (str): Input to provide via stdin (for testing interactive programs).
            args (str): Command line arguments to pass.

        Returns:
            dict[str, Any]: Execution result with stdout, stderr, return code.
        """
        try:
            full_path = self._validate_path(file_path)
            if not full_path.exists():
                return {"error": f"File not found: {file_path}"}

            cmd = ["python3", str(full_path)]
            if args:
                cmd.extend(shlex.split(args))

            result = subprocess.run(
                cmd,
                shell=False,
                cwd=str(self.workspace_path),
                capture_output=True,
                text=True,
                timeout=10,
                input=stdin_input if stdin_input else None,
            )

            return {
                "success": result.returncode == 0,
                "file": file_path,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {
                "error": "Script timed out after 10 seconds (may need stdin input)",
                "file": file_path,
                "hint": "Use stdin_input parameter to provide test input for interactive scripts",
            }
        except Exception as e:
            return {"error": str(e), "file": file_path}

    def run_tests(self, test_path: str = "") -> dict[str, Any]:
        """Run pytest on test files in the workspace.

        Args:
            test_path (str): Specific test file or directory (empty for all tests).

        Returns:
            dict[str, Any]: Test results.
        """
        try:
            cmd = ["python3", "-m", "pytest", "-v", "--tb=short"]
            if test_path:
                full_path = self._validate_path(test_path)
                cmd.append(str(full_path))
            else:
                cmd.append(str(self.workspace_path))

            result = subprocess.run(
                cmd,
                shell=False,
                cwd=str(self.workspace_path),
                capture_output=True,
                text=True,
                timeout=60,
            )

            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"error": "Tests timed out after 60 seconds"}
        except Exception as e:
            return {"error": str(e)}

    def shell_execute(
        self, command: str, cwd: str | None = None, dry_run: bool = False
    ) -> dict[str, Any]:
        """Execute a shell command in the workspace.

        Args:
            command (str): Shell command to execute.
            cwd (str | None): Working directory (relative to workspace).
            dry_run (bool): If True, only validate without executing.

        Returns:
            dict[str, Any]: Execution result.
        """
        # Security: Block dangerous command patterns using regex
        dangerous_patterns = [
            r'rm\s+-rf\s+/',  # rm -rf /
            r'rm\s+-fr\s+/',  # rm -fr / (alternate flag order)
            r'rm\s+-rf\s+/\*',  # rm -rf /*
            r':\(\)\{.*\}',  # Fork bomb
            r'dd\s+if=',  # Disk destruction
            r'mkfs\s+',  # Format filesystem
            r'format\s+',  # Format command
            r'>\s*/dev/sd',  # Write to block device
            r'wget.*\|.*sh',  # Download and pipe to shell
            r'curl.*\|.*sh',  # Download and pipe to shell
        ]
        if any(re.search(pattern, command, re.IGNORECASE) for pattern in dangerous_patterns):
            return {"error": "Command blocked for security reasons", "command": command}

        # Note: shell=False with shlex.split() below already prevents command injection
        # by treating the command as a single executable, not shell commands

        if dry_run:
            return {"dry_run": True, "command": command, "status": "would_execute"}

        try:
            work_dir = self.workspace_path
            if cwd:
                work_dir = self._validate_path(cwd)

            # Security: Use shell=False with shlex.split() to prevent injection
            # This only allows single commands, not pipes/redirections
            command_parts = shlex.split(command)
            if not command_parts:
                return {"error": "Empty command", "command": command}

            result = subprocess.run(
                command_parts,
                shell=False,
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                timeout=30,
            )

            return {
                "success": result.returncode == 0,
                "command": command,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"error": "Command timed out after 30 seconds", "command": command}
        except Exception as e:
            return {"error": str(e), "command": command}
