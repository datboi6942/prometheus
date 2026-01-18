"""API routes for Git and GitHub operations."""
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from prometheus.config import settings, translate_host_path_to_container
from prometheus.database import get_setting
from prometheus.services.git_service import GitService
from prometheus.services.github_service import GitHubService

router = APIRouter(prefix="/api/v1/git")


# Request models
class InitRepoRequest(BaseModel):
    """Request model for initializing a repository."""


class StageFilesRequest(BaseModel):
    """Request model for staging files."""

    files: list[str] = []


class CommitRequest(BaseModel):
    """Request model for creating a commit."""

    message: str
    allow_empty: bool = False


class CreateBranchRequest(BaseModel):
    """Request model for creating a branch."""

    name: str


class CheckoutBranchRequest(BaseModel):
    """Request model for checking out a branch."""

    name: str


class DeleteBranchRequest(BaseModel):
    """Request model for deleting a branch."""

    name: str
    force: bool = False


class AddRemoteRequest(BaseModel):
    """Request model for adding a remote."""

    name: str
    url: str


class PushRequest(BaseModel):
    """Request model for pushing."""

    remote: str = "origin"
    branch: str | None = None
    set_upstream: bool = False


class PullRequest(BaseModel):
    """Request model for pulling."""

    remote: str = "origin"
    branch: str | None = None


class CloneRequest(BaseModel):
    """Request model for cloning a repository."""

    url: str
    directory: str | None = None


# GitHub request models
class CreateRepoRequest(BaseModel):
    """Request model for creating a GitHub repository."""

    name: str
    description: str = ""
    private: bool = False
    auto_init: bool = False


class CreatePRRequest(BaseModel):
    """Request model for creating a pull request."""

    repo_full_name: str
    title: str
    head: str
    base: str
    body: str = ""
    draft: bool = False


class MergePRRequest(BaseModel):
    """Request model for merging a pull request."""

    repo_full_name: str
    pr_number: int
    commit_message: str = ""
    merge_method: str = "merge"


class PRCommentRequest(BaseModel):
    """Request model for adding a PR comment."""

    repo_full_name: str
    pr_number: int
    body: str


class CreateIssueRequest(BaseModel):
    """Request model for creating an issue."""

    repo_full_name: str
    title: str
    body: str = ""
    labels: list[str] = []


class UpdateIssueRequest(BaseModel):
    """Request model for updating an issue."""

    repo_full_name: str
    issue_number: int
    title: str | None = None
    body: str | None = None
    state: str | None = None
    labels: list[str] | None = None


def get_git_service(workspace_path: str | None = None) -> GitService:
    """Dependency to get Git service instance.

    Args:
        workspace_path: Optional workspace path.

    Returns:
        GitService: Git service instance.
    """
    raw_path = workspace_path or settings.workspace_path
    # Translate host paths to container paths (for Docker)
    path = translate_host_path_to_container(raw_path)
    return GitService(path)


async def get_github_service() -> GitHubService:
    """Dependency to get GitHub service instance.

    Returns:
        GitHubService: GitHub service instance.
    """
    token = await get_setting("github_token")
    return GitHubService(token)


# Git endpoints
@router.get("/status")
async def get_status(
    workspace_path: str | None = Query(None),
    git_service: Annotated[GitService, Depends(get_git_service)] = None,
) -> dict[str, Any]:
    """Get git status.

    Args:
        workspace_path: Optional workspace path.
        git_service: Injected Git service.

    Returns:
        dict: Git status information.
    """
    if workspace_path:
        translated_path = translate_host_path_to_container(workspace_path)
        git_service = GitService(translated_path)
    return git_service.get_status()


@router.post("/init")
async def init_repo(
    workspace_path: str | None = Query(None),
    git_service: Annotated[GitService, Depends(get_git_service)] = None,
) -> dict[str, Any]:
    """Initialize a git repository.

    Args:
        workspace_path: Optional workspace path.
        git_service: Injected Git service.

    Returns:
        dict: Operation result.
    """
    if workspace_path:
        translated_path = translate_host_path_to_container(workspace_path)
        git_service = GitService(translated_path)
    result = git_service.init_repo()
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to initialize repository"))
    return result


@router.post("/stage")
async def stage_files(
    request: StageFilesRequest,
    workspace_path: str | None = Query(None),
    git_service: Annotated[GitService, Depends(get_git_service)] = None,
) -> dict[str, Any]:
    """Stage files.

    Args:
        request: Files to stage.
        workspace_path: Optional workspace path.
        git_service: Injected Git service.

    Returns:
        dict: Operation result.
    """
    if workspace_path:
        translated_path = translate_host_path_to_container(workspace_path)
        git_service = GitService(translated_path)
    result = git_service.stage_files(request.files)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to stage files"))
    return result


@router.post("/unstage")
async def unstage_files(
    request: StageFilesRequest,
    workspace_path: str | None = Query(None),
    git_service: Annotated[GitService, Depends(get_git_service)] = None,
) -> dict[str, Any]:
    """Unstage files.

    Args:
        request: Files to unstage.
        workspace_path: Optional workspace path.
        git_service: Injected Git service.

    Returns:
        dict: Operation result.
    """
    if workspace_path:
        translated_path = translate_host_path_to_container(workspace_path)
        git_service = GitService(translated_path)
    result = git_service.unstage_files(request.files)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to unstage files"))
    return result


@router.post("/commit")
async def commit(
    request: CommitRequest,
    workspace_path: str | None = Query(None),
    git_service: Annotated[GitService, Depends(get_git_service)] = None,
) -> dict[str, Any]:
    """Create a commit.

    Args:
        request: Commit details.
        workspace_path: Optional workspace path.
        git_service: Injected Git service.

    Returns:
        dict: Operation result.
    """
    if workspace_path:
        translated_path = translate_host_path_to_container(workspace_path)
        git_service = GitService(translated_path)
    result = git_service.commit(request.message, request.allow_empty)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to create commit"))
    return result


@router.get("/branches")
async def get_branches(
    workspace_path: str | None = Query(None),
    git_service: Annotated[GitService, Depends(get_git_service)] = None,
) -> dict[str, Any]:
    """Get all branches.

    Args:
        workspace_path: Optional workspace path.
        git_service: Injected Git service.

    Returns:
        dict: List of branches.
    """
    if workspace_path:
        translated_path = translate_host_path_to_container(workspace_path)
        git_service = GitService(translated_path)
    return git_service.get_branches()


@router.post("/branches")
async def create_branch(
    request: CreateBranchRequest,
    workspace_path: str | None = Query(None),
    git_service: Annotated[GitService, Depends(get_git_service)] = None,
) -> dict[str, Any]:
    """Create a new branch.

    Args:
        request: Branch details.
        workspace_path: Optional workspace path.
        git_service: Injected Git service.

    Returns:
        dict: Operation result.
    """
    if workspace_path:
        translated_path = translate_host_path_to_container(workspace_path)
        git_service = GitService(translated_path)
    result = git_service.create_branch(request.name)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to create branch"))
    return result


@router.post("/checkout")
async def checkout_branch(
    request: CheckoutBranchRequest,
    workspace_path: str | None = Query(None),
    git_service: Annotated[GitService, Depends(get_git_service)] = None,
) -> dict[str, Any]:
    """Checkout a branch.

    Args:
        request: Branch name.
        workspace_path: Optional workspace path.
        git_service: Injected Git service.

    Returns:
        dict: Operation result.
    """
    if workspace_path:
        translated_path = translate_host_path_to_container(workspace_path)
        git_service = GitService(translated_path)
    result = git_service.checkout_branch(request.name)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to checkout branch"))
    return result


@router.delete("/branches")
async def delete_branch(
    request: DeleteBranchRequest,
    workspace_path: str | None = Query(None),
    git_service: Annotated[GitService, Depends(get_git_service)] = None,
) -> dict[str, Any]:
    """Delete a branch.

    Args:
        request: Branch details.
        workspace_path: Optional workspace path.
        git_service: Injected Git service.

    Returns:
        dict: Operation result.
    """
    if workspace_path:
        translated_path = translate_host_path_to_container(workspace_path)
        git_service = GitService(translated_path)
    result = git_service.delete_branch(request.name, request.force)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to delete branch"))
    return result


@router.get("/diff")
async def get_diff(
    file_path: str | None = Query(None),
    workspace_path: str | None = Query(None),
    git_service: Annotated[GitService, Depends(get_git_service)] = None,
) -> dict[str, Any]:
    """Get diff.

    Args:
        file_path: Optional file path.
        workspace_path: Optional workspace path.
        git_service: Injected Git service.

    Returns:
        dict: Diff output.
    """
    if workspace_path:
        translated_path = translate_host_path_to_container(workspace_path)
        git_service = GitService(translated_path)
    return git_service.get_diff(file_path)


@router.get("/diff/staged")
async def get_staged_diff(
    workspace_path: str | None = Query(None),
    git_service: Annotated[GitService, Depends(get_git_service)] = None,
) -> dict[str, Any]:
    """Get staged diff.

    Args:
        workspace_path: Optional workspace path.
        git_service: Injected Git service.

    Returns:
        dict: Staged diff output.
    """
    if workspace_path:
        translated_path = translate_host_path_to_container(workspace_path)
        git_service = GitService(translated_path)
    return git_service.get_staged_diff()


@router.post("/remote")
async def add_remote(
    request: AddRemoteRequest,
    workspace_path: str | None = Query(None),
    git_service: Annotated[GitService, Depends(get_git_service)] = None,
) -> dict[str, Any]:
    """Add a remote.

    Args:
        request: Remote details.
        workspace_path: Optional workspace path.
        git_service: Injected Git service.

    Returns:
        dict: Operation result.
    """
    if workspace_path:
        translated_path = translate_host_path_to_container(workspace_path)
        git_service = GitService(translated_path)
    result = git_service.add_remote(request.name, request.url)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to add remote"))
    return result


@router.post("/push")
async def push(
    request: PushRequest,
    workspace_path: str | None = Query(None),
    git_service: Annotated[GitService, Depends(get_git_service)] = None,
) -> dict[str, Any]:
    """Push to remote.

    Args:
        request: Push details.
        workspace_path: Optional workspace path.
        git_service: Injected Git service.

    Returns:
        dict: Operation result.
    """
    if workspace_path:
        translated_path = translate_host_path_to_container(workspace_path)
        git_service = GitService(translated_path)
    result = git_service.push(request.remote, request.branch, request.set_upstream)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to push"))
    return result


@router.post("/pull")
async def pull(
    request: PullRequest,
    workspace_path: str | None = Query(None),
    git_service: Annotated[GitService, Depends(get_git_service)] = None,
) -> dict[str, Any]:
    """Pull from remote.

    Args:
        request: Pull details.
        workspace_path: Optional workspace path.
        git_service: Injected Git service.

    Returns:
        dict: Operation result.
    """
    if workspace_path:
        translated_path = translate_host_path_to_container(workspace_path)
        git_service = GitService(translated_path)
    result = git_service.pull(request.remote, request.branch)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to pull"))
    return result


@router.post("/fetch")
async def fetch(
    remote: str | None = Query(None),
    workspace_path: str | None = Query(None),
    git_service: Annotated[GitService, Depends(get_git_service)] = None,
) -> dict[str, Any]:
    """Fetch from remote.

    Args:
        remote: Optional remote name.
        workspace_path: Optional workspace path.
        git_service: Injected Git service.

    Returns:
        dict: Operation result.
    """
    if workspace_path:
        translated_path = translate_host_path_to_container(workspace_path)
        git_service = GitService(translated_path)
    result = git_service.fetch(remote)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to fetch"))
    return result


@router.get("/log")
async def get_log(
    limit: int = Query(50),
    workspace_path: str | None = Query(None),
    git_service: Annotated[GitService, Depends(get_git_service)] = None,
) -> dict[str, Any]:
    """Get commit log.

    Args:
        limit: Maximum number of commits.
        workspace_path: Optional workspace path.
        git_service: Injected Git service.

    Returns:
        dict: Commit log.
    """
    if workspace_path:
        translated_path = translate_host_path_to_container(workspace_path)
        git_service = GitService(translated_path)
    return git_service.get_log(limit)


@router.post("/clone")
async def clone_repo(
    request: CloneRequest,
    workspace_path: str | None = Query(None),
    git_service: Annotated[GitService, Depends(get_git_service)] = None,
) -> dict[str, Any]:
    """Clone a repository.

    Args:
        request: Clone details.
        workspace_path: Optional workspace path.
        git_service: Injected Git service.

    Returns:
        dict: Operation result.
    """
    if workspace_path:
        translated_path = translate_host_path_to_container(workspace_path)
        git_service = GitService(translated_path)
    result = git_service.clone(request.url, request.directory)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to clone repository"))
    return result


# GitHub endpoints
@router.get("/github/auth")
async def check_github_auth(
    github_service: Annotated[GitHubService, Depends(get_github_service)],
) -> dict[str, Any]:
    """Check GitHub authentication status.

    Args:
        github_service: Injected GitHub service.

    Returns:
        dict: Authentication status and user info.
    """
    if not github_service.is_authenticated():
        return {"authenticated": False}

    user_info = github_service.get_user_info()
    return {"authenticated": True, "user": user_info}


@router.get("/github/repos")
async def get_github_repos(
    github_service: Annotated[GitHubService, Depends(get_github_service)],
) -> dict[str, Any]:
    """Get user's GitHub repositories.

    Args:
        github_service: Injected GitHub service.

    Returns:
        dict: List of repositories.
    """
    return github_service.get_repositories()


@router.post("/github/repos")
async def create_github_repo(
    request: CreateRepoRequest,
    github_service: Annotated[GitHubService, Depends(get_github_service)],
) -> dict[str, Any]:
    """Create a GitHub repository.

    Args:
        request: Repository details.
        github_service: Injected GitHub service.

    Returns:
        dict: Created repository information.
    """
    result = github_service.create_repository(
        name=request.name,
        description=request.description,
        private=request.private,
        auto_init=request.auto_init,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to create repository"))
    return result


# Pull Request endpoints
@router.get("/github/pulls")
async def get_pull_requests(
    repo_full_name: str = Query(...),
    state: str = Query("open"),
    limit: int = Query(30),
    github_service: Annotated[GitHubService, Depends(get_github_service)] = None,
) -> dict[str, Any]:
    """Get pull requests for a repository.

    Args:
        repo_full_name: Repository full name (owner/repo).
        state: PR state (open, closed, all).
        limit: Maximum number of PRs.
        github_service: Injected GitHub service.

    Returns:
        dict: List of pull requests.
    """
    result = github_service.get_pull_requests(repo_full_name, state, limit)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to get pull requests"))
    return result


@router.get("/github/pulls/{pr_number}")
async def get_pull_request(
    repo_full_name: str = Query(...),
    pr_number: int = ...,
    github_service: Annotated[GitHubService, Depends(get_github_service)] = None,
) -> dict[str, Any]:
    """Get a specific pull request.

    Args:
        repo_full_name: Repository full name (owner/repo).
        pr_number: Pull request number.
        github_service: Injected GitHub service.

    Returns:
        dict: Pull request details.
    """
    result = github_service.get_pull_request(repo_full_name, pr_number)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to get pull request"))
    return result


@router.post("/github/pulls")
async def create_pull_request(
    request: CreatePRRequest,
    github_service: Annotated[GitHubService, Depends(get_github_service)],
) -> dict[str, Any]:
    """Create a pull request.

    Args:
        request: PR details.
        github_service: Injected GitHub service.

    Returns:
        dict: Created pull request information.
    """
    result = github_service.create_pull_request(
        repo_full_name=request.repo_full_name,
        title=request.title,
        head=request.head,
        base=request.base,
        body=request.body,
        draft=request.draft,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to create pull request"))
    return result


@router.post("/github/pulls/merge")
async def merge_pull_request(
    request: MergePRRequest,
    github_service: Annotated[GitHubService, Depends(get_github_service)],
) -> dict[str, Any]:
    """Merge a pull request.

    Args:
        request: Merge details.
        github_service: Injected GitHub service.

    Returns:
        dict: Merge result.
    """
    result = github_service.merge_pull_request(
        repo_full_name=request.repo_full_name,
        pr_number=request.pr_number,
        commit_message=request.commit_message,
        merge_method=request.merge_method,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to merge pull request"))
    return result


@router.get("/github/pulls/{pr_number}/comments")
async def get_pr_comments(
    repo_full_name: str = Query(...),
    pr_number: int = ...,
    github_service: Annotated[GitHubService, Depends(get_github_service)] = None,
) -> dict[str, Any]:
    """Get comments on a pull request.

    Args:
        repo_full_name: Repository full name (owner/repo).
        pr_number: Pull request number.
        github_service: Injected GitHub service.

    Returns:
        dict: List of comments.
    """
    result = github_service.get_pr_comments(repo_full_name, pr_number)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to get PR comments"))
    return result


@router.post("/github/pulls/comments")
async def add_pr_comment(
    request: PRCommentRequest,
    github_service: Annotated[GitHubService, Depends(get_github_service)],
) -> dict[str, Any]:
    """Add a comment to a pull request.

    Args:
        request: Comment details.
        github_service: Injected GitHub service.

    Returns:
        dict: Created comment information.
    """
    result = github_service.add_pr_comment(
        repo_full_name=request.repo_full_name,
        pr_number=request.pr_number,
        body=request.body,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to add PR comment"))
    return result


# Issue endpoints
@router.get("/github/issues")
async def get_issues(
    repo_full_name: str = Query(...),
    state: str = Query("open"),
    limit: int = Query(30),
    github_service: Annotated[GitHubService, Depends(get_github_service)] = None,
) -> dict[str, Any]:
    """Get issues for a repository.

    Args:
        repo_full_name: Repository full name (owner/repo).
        state: Issue state (open, closed, all).
        limit: Maximum number of issues.
        github_service: Injected GitHub service.

    Returns:
        dict: List of issues.
    """
    result = github_service.get_issues(repo_full_name, state, limit)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to get issues"))
    return result


@router.post("/github/issues")
async def create_issue(
    request: CreateIssueRequest,
    github_service: Annotated[GitHubService, Depends(get_github_service)],
) -> dict[str, Any]:
    """Create an issue.

    Args:
        request: Issue details.
        github_service: Injected GitHub service.

    Returns:
        dict: Created issue information.
    """
    result = github_service.create_issue(
        repo_full_name=request.repo_full_name,
        title=request.title,
        body=request.body,
        labels=request.labels if request.labels else None,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to create issue"))
    return result


@router.patch("/github/issues")
async def update_issue(
    request: UpdateIssueRequest,
    github_service: Annotated[GitHubService, Depends(get_github_service)],
) -> dict[str, Any]:
    """Update an issue.

    Args:
        request: Issue update details.
        github_service: Injected GitHub service.

    Returns:
        dict: Updated issue information.
    """
    result = github_service.update_issue(
        repo_full_name=request.repo_full_name,
        issue_number=request.issue_number,
        title=request.title,
        body=request.body,
        state=request.state,
        labels=request.labels,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to update issue"))
    return result


# Workflow endpoints
@router.get("/github/workflows")
async def get_workflows(
    repo_full_name: str = Query(...),
    github_service: Annotated[GitHubService, Depends(get_github_service)] = None,
) -> dict[str, Any]:
    """Get workflows for a repository.

    Args:
        repo_full_name: Repository full name (owner/repo).
        github_service: Injected GitHub service.

    Returns:
        dict: List of workflows.
    """
    result = github_service.get_workflows(repo_full_name)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to get workflows"))
    return result


@router.get("/github/workflows/runs")
async def get_workflow_runs(
    repo_full_name: str = Query(...),
    workflow_id: int | None = Query(None),
    limit: int = Query(30),
    github_service: Annotated[GitHubService, Depends(get_github_service)] = None,
) -> dict[str, Any]:
    """Get workflow runs for a repository.

    Args:
        repo_full_name: Repository full name (owner/repo).
        workflow_id: Optional workflow ID to filter by.
        limit: Maximum number of runs.
        github_service: Injected GitHub service.

    Returns:
        dict: List of workflow runs.
    """
    result = github_service.get_workflow_runs(repo_full_name, workflow_id, limit)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to get workflow runs"))
    return result
