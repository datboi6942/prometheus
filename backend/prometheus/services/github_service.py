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
