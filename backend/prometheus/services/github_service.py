"""GitHub API integration service."""
from typing import Any

from github import Github
from github.GithubException import GithubException

import structlog

logger = structlog.get_logger()


class GitHubService:
    """Service for GitHub API operations."""

    def __init__(self, token: str | None = None) -> None:
        """Initialize GitHub service.

        Args:
            token: GitHub personal access token.
        """
        self.token = token
        self.github: Github | None = None
        if token:
            try:
                self.github = Github(token)
                # Test authentication
                self.github.get_user().login
            except Exception as e:
                logger.warning("GitHub authentication failed", error=str(e))
                self.github = None

    def is_authenticated(self) -> bool:
        """Check if GitHub is authenticated.

        Returns:
            bool: True if authenticated.
        """
        return self.github is not None

    def create_repository(
        self,
        name: str,
        description: str = "",
        private: bool = False,
        auto_init: bool = False,
    ) -> dict[str, Any]:
        """Create a new GitHub repository.

        Args:
            name: Repository name.
            description: Repository description.
            private: Whether repository is private.
            auto_init: Initialize with README.

        Returns:
            dict: Repository information.
        """
        if not self.github:
            return {"success": False, "error": "Not authenticated with GitHub"}

        try:
            user = self.github.get_user()
            repo = user.create_repo(
                name=name,
                description=description,
                private=private,
                auto_init=auto_init,
            )
            return {
                "success": True,
                "name": repo.name,
                "full_name": repo.full_name,
                "url": repo.html_url,
                "clone_url": repo.clone_url,
                "ssh_url": repo.ssh_url,
            }
        except GithubException as e:
            logger.error("Failed to create repository", error=str(e))
            return {"success": False, "error": str(e)}

    def get_repositories(self) -> dict[str, Any]:
        """Get user's repositories.

        Returns:
            dict: List of repositories.
        """
        if not self.github:
            return {"success": False, "error": "Not authenticated with GitHub"}

        try:
            user = self.github.get_user()
            repos = []
            for repo in user.get_repos():
                repos.append(
                    {
                        "name": repo.name,
                        "full_name": repo.full_name,
                        "url": repo.html_url,
                        "clone_url": repo.clone_url,
                        "ssh_url": repo.ssh_url,
                        "private": repo.private,
                        "description": repo.description,
                        "updated_at": repo.updated_at.isoformat() if repo.updated_at else None,
                    }
                )
            return {"success": True, "repositories": repos}
        except GithubException as e:
            logger.error("Failed to get repositories", error=str(e))
            return {"success": False, "error": str(e)}

    def get_user_info(self) -> dict[str, Any]:
        """Get authenticated user information.

        Returns:
            dict: User information.
        """
        if not self.github:
            return {"success": False, "error": "Not authenticated with GitHub"}

        try:
            user = self.github.get_user()
            return {
                "success": True,
                "login": user.login,
                "name": user.name,
                "email": user.email,
                "avatar_url": user.avatar_url,
                "bio": user.bio,
                "public_repos": user.public_repos,
            }
        except GithubException as e:
            logger.error("Failed to get user info", error=str(e))
            return {"success": False, "error": str(e)}

    # Pull Request operations
    def get_pull_requests(
        self,
        repo_full_name: str,
        state: str = "open",
        limit: int = 30,
    ) -> dict[str, Any]:
        """Get pull requests for a repository.

        Args:
            repo_full_name: Repository full name (owner/repo).
            state: PR state (open, closed, all).
            limit: Maximum number of PRs to return.

        Returns:
            dict: List of pull requests.
        """
        if not self.github:
            return {"success": False, "error": "Not authenticated with GitHub"}

        try:
            repo = self.github.get_repo(repo_full_name)
            prs = []
            for pr in repo.get_pulls(state=state)[:limit]:
                prs.append(
                    {
                        "number": pr.number,
                        "title": pr.title,
                        "body": pr.body,
                        "state": pr.state,
                        "user": pr.user.login if pr.user else None,
                        "created_at": pr.created_at.isoformat() if pr.created_at else None,
                        "updated_at": pr.updated_at.isoformat() if pr.updated_at else None,
                        "merged": pr.merged,
                        "mergeable": pr.mergeable,
                        "head": pr.head.ref if pr.head else None,
                        "base": pr.base.ref if pr.base else None,
                        "url": pr.html_url,
                        "comments": pr.comments,
                        "review_comments": pr.review_comments,
                        "commits": pr.commits,
                        "additions": pr.additions,
                        "deletions": pr.deletions,
                        "changed_files": pr.changed_files,
                    }
                )
            return {"success": True, "pull_requests": prs}
        except GithubException as e:
            logger.error("Failed to get pull requests", error=str(e))
            return {"success": False, "error": str(e)}

    def get_pull_request(self, repo_full_name: str, pr_number: int) -> dict[str, Any]:
        """Get a specific pull request.

        Args:
            repo_full_name: Repository full name (owner/repo).
            pr_number: Pull request number.

        Returns:
            dict: Pull request details.
        """
        if not self.github:
            return {"success": False, "error": "Not authenticated with GitHub"}

        try:
            repo = self.github.get_repo(repo_full_name)
            pr = repo.get_pull(pr_number)
            return {
                "success": True,
                "pull_request": {
                    "number": pr.number,
                    "title": pr.title,
                    "body": pr.body,
                    "state": pr.state,
                    "user": pr.user.login if pr.user else None,
                    "created_at": pr.created_at.isoformat() if pr.created_at else None,
                    "updated_at": pr.updated_at.isoformat() if pr.updated_at else None,
                    "merged": pr.merged,
                    "mergeable": pr.mergeable,
                    "head": pr.head.ref if pr.head else None,
                    "base": pr.base.ref if pr.base else None,
                    "url": pr.html_url,
                    "comments": pr.comments,
                    "review_comments": pr.review_comments,
                    "commits": pr.commits,
                    "additions": pr.additions,
                    "deletions": pr.deletions,
                    "changed_files": pr.changed_files,
                },
            }
        except GithubException as e:
            logger.error("Failed to get pull request", error=str(e))
            return {"success": False, "error": str(e)}

    def create_pull_request(
        self,
        repo_full_name: str,
        title: str,
        head: str,
        base: str,
        body: str = "",
        draft: bool = False,
    ) -> dict[str, Any]:
        """Create a pull request.

        Args:
            repo_full_name: Repository full name (owner/repo).
            title: PR title.
            head: The name of the branch where your changes are implemented.
            base: The name of the branch you want the changes pulled into.
            body: PR description.
            draft: Create as draft PR.

        Returns:
            dict: Created pull request information.
        """
        if not self.github:
            return {"success": False, "error": "Not authenticated with GitHub"}

        try:
            repo = self.github.get_repo(repo_full_name)
            pr = repo.create_pull(title=title, head=head, base=base, body=body, draft=draft)
            return {
                "success": True,
                "number": pr.number,
                "url": pr.html_url,
                "title": pr.title,
                "state": pr.state,
            }
        except GithubException as e:
            logger.error("Failed to create pull request", error=str(e))
            return {"success": False, "error": str(e)}

    def merge_pull_request(
        self,
        repo_full_name: str,
        pr_number: int,
        commit_message: str = "",
        merge_method: str = "merge",
    ) -> dict[str, Any]:
        """Merge a pull request.

        Args:
            repo_full_name: Repository full name (owner/repo).
            pr_number: Pull request number.
            commit_message: Optional commit message.
            merge_method: Merge method (merge, squash, rebase).

        Returns:
            dict: Merge result.
        """
        if not self.github:
            return {"success": False, "error": "Not authenticated with GitHub"}

        try:
            repo = self.github.get_repo(repo_full_name)
            pr = repo.get_pull(pr_number)
            result = pr.merge(commit_message=commit_message, merge_method=merge_method)
            return {
                "success": True,
                "merged": result.merged,
                "message": result.message,
                "sha": result.sha,
            }
        except GithubException as e:
            logger.error("Failed to merge pull request", error=str(e))
            return {"success": False, "error": str(e)}

    def get_pr_comments(self, repo_full_name: str, pr_number: int) -> dict[str, Any]:
        """Get comments on a pull request.

        Args:
            repo_full_name: Repository full name (owner/repo).
            pr_number: Pull request number.

        Returns:
            dict: List of comments.
        """
        if not self.github:
            return {"success": False, "error": "Not authenticated with GitHub"}

        try:
            repo = self.github.get_repo(repo_full_name)
            pr = repo.get_pull(pr_number)
            comments = []
            for comment in pr.get_issue_comments():
                comments.append(
                    {
                        "id": comment.id,
                        "user": comment.user.login if comment.user else None,
                        "body": comment.body,
                        "created_at": comment.created_at.isoformat() if comment.created_at else None,
                        "updated_at": comment.updated_at.isoformat() if comment.updated_at else None,
                    }
                )
            return {"success": True, "comments": comments}
        except GithubException as e:
            logger.error("Failed to get PR comments", error=str(e))
            return {"success": False, "error": str(e)}

    def add_pr_comment(
        self, repo_full_name: str, pr_number: int, body: str
    ) -> dict[str, Any]:
        """Add a comment to a pull request.

        Args:
            repo_full_name: Repository full name (owner/repo).
            pr_number: Pull request number.
            body: Comment body.

        Returns:
            dict: Created comment information.
        """
        if not self.github:
            return {"success": False, "error": "Not authenticated with GitHub"}

        try:
            repo = self.github.get_repo(repo_full_name)
            pr = repo.get_pull(pr_number)
            comment = pr.create_issue_comment(body)
            return {
                "success": True,
                "id": comment.id,
                "body": comment.body,
                "user": comment.user.login if comment.user else None,
            }
        except GithubException as e:
            logger.error("Failed to add PR comment", error=str(e))
            return {"success": False, "error": str(e)}

    # Issue operations
    def get_issues(
        self,
        repo_full_name: str,
        state: str = "open",
        limit: int = 30,
    ) -> dict[str, Any]:
        """Get issues for a repository.

        Args:
            repo_full_name: Repository full name (owner/repo).
            state: Issue state (open, closed, all).
            limit: Maximum number of issues to return.

        Returns:
            dict: List of issues.
        """
        if not self.github:
            return {"success": False, "error": "Not authenticated with GitHub"}

        try:
            repo = self.github.get_repo(repo_full_name)
            issues = []
            for issue in repo.get_issues(state=state)[:limit]:
                if issue.pull_request:  # Skip PRs
                    continue
                issues.append(
                    {
                        "number": issue.number,
                        "title": issue.title,
                        "body": issue.body,
                        "state": issue.state,
                        "user": issue.user.login if issue.user else None,
                        "created_at": issue.created_at.isoformat() if issue.created_at else None,
                        "updated_at": issue.updated_at.isoformat() if issue.updated_at else None,
                        "labels": [label.name for label in issue.labels],
                        "comments": issue.comments,
                        "url": issue.html_url,
                    }
                )
            return {"success": True, "issues": issues}
        except GithubException as e:
            logger.error("Failed to get issues", error=str(e))
            return {"success": False, "error": str(e)}

    def create_issue(
        self,
        repo_full_name: str,
        title: str,
        body: str = "",
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create an issue.

        Args:
            repo_full_name: Repository full name (owner/repo).
            title: Issue title.
            body: Issue body.
            labels: Optional list of label names.

        Returns:
            dict: Created issue information.
        """
        if not self.github:
            return {"success": False, "error": "Not authenticated with GitHub"}

        try:
            repo = self.github.get_repo(repo_full_name)
            issue = repo.create_issue(title=title, body=body, labels=labels or [])
            return {
                "success": True,
                "number": issue.number,
                "url": issue.html_url,
                "title": issue.title,
                "state": issue.state,
            }
        except GithubException as e:
            logger.error("Failed to create issue", error=str(e))
            return {"success": False, "error": str(e)}

    def update_issue(
        self,
        repo_full_name: str,
        issue_number: int,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        """Update an issue.

        Args:
            repo_full_name: Repository full name (owner/repo).
            issue_number: Issue number.
            title: New title (optional).
            body: New body (optional).
            state: New state (open/closed) (optional).
            labels: New labels (optional).

        Returns:
            dict: Updated issue information.
        """
        if not self.github:
            return {"success": False, "error": "Not authenticated with GitHub"}

        try:
            repo = self.github.get_repo(repo_full_name)
            issue = repo.get_issue(issue_number)
            if title:
                issue.edit(title=title)
            if body:
                issue.edit(body=body)
            if state:
                issue.edit(state=state)
            if labels is not None:
                issue.edit(labels=labels)
            return {
                "success": True,
                "number": issue.number,
                "title": issue.title,
                "state": issue.state,
            }
        except GithubException as e:
            logger.error("Failed to update issue", error=str(e))
            return {"success": False, "error": str(e)}

    # Workflow operations
    def get_workflows(self, repo_full_name: str) -> dict[str, Any]:
        """Get workflows for a repository.

        Args:
            repo_full_name: Repository full name (owner/repo).

        Returns:
            dict: List of workflows.
        """
        if not self.github:
            return {"success": False, "error": "Not authenticated with GitHub"}

        try:
            repo = self.github.get_repo(repo_full_name)
            workflows = []
            for workflow in repo.get_workflows():
                workflows.append(
                    {
                        "id": workflow.id,
                        "name": workflow.name,
                        "path": workflow.path,
                        "state": workflow.state,
                        "created_at": workflow.created_at.isoformat() if workflow.created_at else None,
                        "updated_at": workflow.updated_at.isoformat() if workflow.updated_at else None,
                        "url": workflow.html_url,
                    }
                )
            return {"success": True, "workflows": workflows}
        except GithubException as e:
            logger.error("Failed to get workflows", error=str(e))
            return {"success": False, "error": str(e)}

    def get_workflow_runs(
        self,
        repo_full_name: str,
        workflow_id: int | None = None,
        limit: int = 30,
    ) -> dict[str, Any]:
        """Get workflow runs for a repository.

        Args:
            repo_full_name: Repository full name (owner/repo).
            workflow_id: Optional workflow ID to filter by.
            limit: Maximum number of runs to return.

        Returns:
            dict: List of workflow runs.
        """
        if not self.github:
            return {"success": False, "error": "Not authenticated with GitHub"}

        try:
            repo = self.github.get_repo(repo_full_name)
            runs = []
            if workflow_id:
                workflow = repo.get_workflow(workflow_id)
                workflow_runs = workflow.get_runs()[:limit]
            else:
                workflow_runs = repo.get_workflow_runs()[:limit]

            for run in workflow_runs:
                runs.append(
                    {
                        "id": run.id,
                        "name": run.name,
                        "status": run.status,
                        "conclusion": run.conclusion,
                        "workflow_id": run.workflow_id,
                        "created_at": run.created_at.isoformat() if run.created_at else None,
                        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
                        "head_branch": run.head_branch,
                        "head_sha": run.head_sha,
                        "url": run.html_url,
                    }
                )
            return {"success": True, "runs": runs}
        except GithubException as e:
            logger.error("Failed to get workflow runs", error=str(e))
            return {"success": False, "error": str(e)}
