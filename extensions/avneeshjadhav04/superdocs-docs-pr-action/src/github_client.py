"""Minimal GitHub REST API client for the action.

Replaces PyGithub with plain requests so the dependency tree stays
permissively licensed (MIT/Apache/BSD only, no copyleft).
"""

from __future__ import annotations

from typing import Optional

import requests

GITHUB_API = "https://api.github.com"


class GitHubError(RuntimeError):
    """Raised when the GitHub API returns an error we cannot recover from."""


class GitHubClient:
    def __init__(self, token: str, repo: str, api_base: str = GITHUB_API, timeout: int = 60) -> None:
        self._token = token
        self._repo = repo
        self._api_base = api_base.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def _url(self, path: str) -> str:
        return f"{self._api_base}/repos/{self._repo}{path}"

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        response = self._session.request(method, self._url(path), timeout=self._timeout, **kwargs)
        if response.status_code >= 400:
            detail = ""
            try:
                detail = response.json().get("message") or ""
            except ValueError:
                detail = response.text[:300]
            raise GitHubError(f"GitHub API {response.status_code} on {path}: {detail}")
        return response

    def open_pulls(self) -> list[dict]:
        """List open pull requests, most recently created first."""
        response = self._request(
            "GET", "/pulls", params={"state": "open", "sort": "created", "direction": "desc"}
        )
        return response.json()

    def create_pull(self, title: str, body: str, head: str, base: str) -> int:
        response = self._request(
            "POST",
            "/pulls",
            json={"title": title, "body": body, "head": head, "base": base},
        )
        return response.json()["number"]

    def branch_sha(self, branch: str) -> Optional[str]:
        """Return the head commit sha of a branch, or None if it does not exist."""
        try:
            response = self._request("GET", f"/branches/{branch}")
        except GitHubError:
            return None
        return response.json()["commit"]["sha"]

    def create_branch(self, branch: str, sha: str) -> None:
        self._request("POST", "/git/refs", json={"ref": f"refs/heads/{branch}", "sha": sha})

    def file_sha(self, path: str, branch: str) -> Optional[str]:
        """Return the blob sha of a file on a branch, or None if it does not exist."""
        try:
            response = self._request("GET", f"/contents/{path}", params={"ref": branch})
        except GitHubError:
            return None
        return response.json()["sha"]

    def create_file(self, path: str, content: str, branch: str, message: str) -> None:
        import base64

        self._request(
            "PUT",
            f"/contents/{path}",
            json={
                "message": message,
                "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                "branch": branch,
            },
        )

    def update_file(self, path: str, content: str, branch: str, message: str, sha: str) -> None:
        import base64

        self._request(
            "PUT",
            f"/contents/{path}",
            json={
                "message": message,
                "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                "branch": branch,
                "sha": sha,
            },
        )
