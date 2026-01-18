"""Git operations service for repository management."""
import subprocess
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()


class GitService:
    """Service for Git operations."""

    def __init__(self, workspace_path: str) -> None:
        """Initialize Git service.

        Args:
            workspace_path: Path to the workspace directory.
        """
        self.workspace_path = Path(workspace_path).resolve()
        if not self.workspace_path.exists():
            self.workspace_path.mkdir(parents=True, exist_ok=True)

    def _run_git_command(self, command: list[str], timeout: int = 30) -> dict[str, Any]:
        """Run a git command safely.

        Args:
            command: Git command as list of strings.
            timeout: Command timeout in seconds.

        Returns:
            dict: Command result with stdout, stderr, and return_code.
        """
        try:
            result = subprocess.run(
                ["git"] + command,
                cwd=str(self.workspace_path),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Command timed out", "return_code": -1}
        except Exception as e:
            logger.error("Git command failed", command=command, error=str(e))
            return {"success": False, "error": str(e), "return_code": -1}

    def is_repo(self) -> bool:
        """Check if workspace is a git repository.

        Returns:
            bool: True if git repository exists.
        """
        result = self._run_git_command(["rev-parse", "--git-dir"])
        return result["success"]

    def init_repo(self) -> dict[str, Any]:
        """Initialize a new git repository.

        Returns:
            dict: Operation result.
        """
        if self.is_repo():
            return {"success": False, "error": "Repository already initialized"}
        return self._run_git_command(["init"])

    def get_status(self) -> dict[str, Any]:
        """Get git status.

        Returns:
            dict: Status information including staged, unstaged, and untracked files.
        """
        if not self.is_repo():
            return {"success": False, "error": "Not a git repository"}

        # Get detailed status
        status_result = self._run_git_command(["status", "--porcelain", "-u"])
        if not status_result["success"]:
            return status_result

        # Parse status output
        staged = []
        unstaged = []
        untracked = []

        for line in status_result["stdout"].strip().split("\n"):
            if not line.strip():
                continue
            status_code = line[:2]
            file_path = line[3:].strip()

            if status_code[0] == "?":
                untracked.append(file_path)
            elif status_code[0] != " ":
                staged.append(file_path)
            if status_code[1] != " ":
                unstaged.append(file_path)

        # Get branch info
        branch_result = self._run_git_command(["branch", "--show-current"])
        current_branch = branch_result["stdout"].strip() if branch_result["success"] else None

        # Get remote info
        remote_result = self._run_git_command(["remote", "-v"])
        remotes = {}
        if remote_result["success"]:
            for line in remote_result["stdout"].strip().split("\n"):
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 2:
                        remote_name = parts[0]
                        remote_url = parts[1]
                        remotes[remote_name] = remote_url

        return {
            "success": True,
            "staged": staged,
            "unstaged": unstaged,
            "untracked": untracked,
            "current_branch": current_branch,
            "remotes": remotes,
            "raw_status": status_result["stdout"],
        }

    def stage_files(self, files: list[str]) -> dict[str, Any]:
        """Stage files for commit.

        Args:
            files: List of file paths to stage (empty list stages all).

        Returns:
            dict: Operation result.
        """
        if not self.is_repo():
            return {"success": False, "error": "Not a git repository"}

        if not files:
            return self._run_git_command(["add", "-A"])
        return self._run_git_command(["add"] + files)

    def unstage_files(self, files: list[str]) -> dict[str, Any]:
        """Unstage files.

        Args:
            files: List of file paths to unstage.

        Returns:
            dict: Operation result.
        """
        if not self.is_repo():
            return {"success": False, "error": "Not a git repository"}

        return self._run_git_command(["reset", "HEAD"] + files)

    def commit(self, message: str, allow_empty: bool = False) -> dict[str, Any]:
        """Create a commit.

        Args:
            message: Commit message.
            allow_empty: Allow empty commits.

        Returns:
            dict: Operation result.
        """
        if not self.is_repo():
            return {"success": False, "error": "Not a git repository"}

        cmd = ["commit", "-m", message]
        if allow_empty:
            cmd.append("--allow-empty")
        return self._run_git_command(cmd)

    def get_branches(self) -> dict[str, Any]:
        """Get all branches.

        Returns:
            dict: List of branches with current branch marked.
        """
        if not self.is_repo():
            return {"success": False, "error": "Not a git repository"}

        result = self._run_git_command(["branch", "-a"])
        if not result["success"]:
            return result

        branches = []
        current_branch = None
        for line in result["stdout"].strip().split("\n"):
            if not line.strip():
                continue
            branch_name = line.strip().lstrip("*").strip()
            is_current = line.startswith("*")
            is_remote = "remotes/" in branch_name

            if is_current:
                current_branch = branch_name

            branches.append(
                {
                    "name": branch_name.replace("remotes/", "").replace("origin/", ""),
                    "full_name": branch_name,
                    "is_current": is_current,
                    "is_remote": is_remote,
                }
            )

        return {"success": True, "branches": branches, "current_branch": current_branch}

    def create_branch(self, branch_name: str) -> dict[str, Any]:
        """Create a new branch.

        Args:
            branch_name: Name of the new branch.

        Returns:
            dict: Operation result.
        """
        if not self.is_repo():
            return {"success": False, "error": "Not a git repository"}

        return self._run_git_command(["checkout", "-b", branch_name])

    def checkout_branch(self, branch_name: str) -> dict[str, Any]:
        """Checkout a branch.

        Args:
            branch_name: Name of the branch to checkout.

        Returns:
            dict: Operation result.
        """
        if not self.is_repo():
            return {"success": False, "error": "Not a git repository"}

        return self._run_git_command(["checkout", branch_name])

    def delete_branch(self, branch_name: str, force: bool = False) -> dict[str, Any]:
        """Delete a branch.

        Args:
            branch_name: Name of the branch to delete.
            force: Force delete even if not merged.

        Returns:
            dict: Operation result.
        """
        if not self.is_repo():
            return {"success": False, "error": "Not a git repository"}

        cmd = ["branch", "-D" if force else "-d", branch_name]
        return self._run_git_command(cmd)

    def get_diff(self, file_path: str | None = None) -> dict[str, Any]:
        """Get diff for files.

        Args:
            file_path: Optional specific file path.

        Returns:
            dict: Diff output.
        """
        if not self.is_repo():
            return {"success": False, "error": "Not a git repository"}

        cmd = ["diff"]
        if file_path:
            cmd.append(file_path)
        return self._run_git_command(cmd)

    def get_staged_diff(self) -> dict[str, Any]:
        """Get diff for staged files.

        Returns:
            dict: Diff output.
        """
        if not self.is_repo():
            return {"success": False, "error": "Not a git repository"}

        return self._run_git_command(["diff", "--cached"])

    def add_remote(self, name: str, url: str) -> dict[str, Any]:
        """Add a remote repository.

        Args:
            name: Remote name (typically 'origin').
            url: Remote URL.

        Returns:
            dict: Operation result.
        """
        if not self.is_repo():
            return {"success": False, "error": "Not a git repository"}

        return self._run_git_command(["remote", "add", name, url])

    def remove_remote(self, name: str) -> dict[str, Any]:
        """Remove a remote repository.

        Args:
            name: Remote name.

        Returns:
            dict: Operation result.
        """
        if not self.is_repo():
            return {"success": False, "error": "Not a git repository"}

        return self._run_git_command(["remote", "remove", name])

    def push(self, remote: str = "origin", branch: str | None = None, set_upstream: bool = False) -> dict[str, Any]:
        """Push to remote repository.

        Args:
            remote: Remote name.
            branch: Branch name (defaults to current).
            set_upstream: Set upstream tracking.

        Returns:
            dict: Operation result.
        """
        if not self.is_repo():
            return {"success": False, "error": "Not a git repository"}

        cmd = ["push"]
        if set_upstream:
            branch_result = self._run_git_command(["branch", "--show-current"])
            current_branch = branch_result["stdout"].strip() if branch_result["success"] else None
            if current_branch:
                cmd.extend(["-u", remote, current_branch])
            else:
                return {"success": False, "error": "No current branch"}
        else:
            cmd.append(remote)
            if branch:
                cmd.append(branch)

        return self._run_git_command(cmd, timeout=60)

    def pull(self, remote: str = "origin", branch: str | None = None) -> dict[str, Any]:
        """Pull from remote repository.

        Args:
            remote: Remote name.
            branch: Branch name (defaults to current).

        Returns:
            dict: Operation result.
        """
        if not self.is_repo():
            return {"success": False, "error": "Not a git repository"}

        cmd = ["pull", remote]
        if branch:
            cmd.append(branch)

        return self._run_git_command(cmd, timeout=60)

    def fetch(self, remote: str | None = None) -> dict[str, Any]:
        """Fetch from remote repository.

        Args:
            remote: Optional remote name (fetches all if not specified).

        Returns:
            dict: Operation result.
        """
        if not self.is_repo():
            return {"success": False, "error": "Not a git repository"}

        cmd = ["fetch"]
        if remote:
            cmd.append(remote)

        return self._run_git_command(cmd, timeout=60)

    def get_log(self, limit: int = 50) -> dict[str, Any]:
        """Get commit log.

        Args:
            limit: Maximum number of commits to return.

        Returns:
            dict: Commit log.
        """
        if not self.is_repo():
            return {"success": False, "error": "Not a git repository"}

        result = self._run_git_command(
            ["log", f"-{limit}", "--pretty=format:%H|%an|%ae|%ad|%s", "--date=iso"]
        )
        if not result["success"]:
            return result

        commits = []
        for line in result["stdout"].strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("|", 4)
            if len(parts) == 5:
                commits.append(
                    {
                        "hash": parts[0],
                        "author": parts[1],
                        "email": parts[2],
                        "date": parts[3],
                        "message": parts[4],
                    }
                )

        return {"success": True, "commits": commits}

    def clone(self, url: str, directory: str | None = None) -> dict[str, Any]:
        """Clone a repository.

        Args:
            url: Repository URL.
            directory: Optional directory name.

        Returns:
            dict: Operation result.
        """
        cmd = ["clone", url]
        if directory:
            cmd.append(directory)

        # Clone to parent directory, not workspace
        parent_path = self.workspace_path.parent
        try:
            result = subprocess.run(
                ["git"] + cmd,
                cwd=str(parent_path),
                capture_output=True,
                text=True,
                timeout=120,
            )
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "return_code": -1}
