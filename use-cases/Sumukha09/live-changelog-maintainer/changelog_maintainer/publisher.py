"""Optional GitHub PR publisher for the Living Changelog Maintainer.

Uses ``urllib.request`` against the GitHub REST API (no third-party deps).
Supports:

- Creating a branch on a public repo (default branch `main`).
- Committing the exported ``CHANGELOG.md`` plus ``.pdf`` and ``.docx``.
- Opening a pull request.

This module is intentionally narrow: it only knows how to publish the
ALREADY-EXPORTED files that the exporter produced. It never reads or
re-generates the changelog content — that is the maintainer's job.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


class GitHubError(RuntimeError):
    """Raised for any GitHub API failure."""


@dataclass(frozen=True)
class GitHubConfig:
    token: Optional[str] = None
    api_base: str = "https://api.github.com"

    @classmethod
    def from_env(cls, token: Optional[str] = None) -> "GitHubConfig":
        return cls(
            token=token or os.environ.get("GITHUB_TOKEN"),
            api_base=os.environ.get("GITHUB_API_BASE", "https://api.github.com"),
        )


@dataclass(frozen=True)
class PullRequestResult:
    url: str
    number: int
    branch: str


class GitHubPublisher:
    def __init__(self, config: GitHubConfig | None = None) -> None:
        self.config = config or GitHubConfig.from_env()
        if not self.config.token:
            raise GitHubError(
                "GitHub token missing. Set GITHUB_TOKEN or pass --github-token."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def publish(
        self,
        repo: str,
        files: dict[str, bytes],
        title: str,
        body: str,
        base_branch: str = "main",
        extensions_subdir: str = "extensions",
    ) -> PullRequestResult:
        """Commit `files` under ``extensions_subdir/<release>/`` and open a PR.

        `files` is a mapping of leaf filename -> bytes, e.g.
        ``{"CHANGELOG.md": b"...", "changelog.pdf": b"..."}``.
        The leaf names will be placed inside a per-release folder so the PR
        does not clobber previous releases.
        """
        if "/" not in repo:
            raise GitHubError(
                f"repo must be 'owner/repo'; got {repo!r}"
            )
        # Use the title slug as the per-release folder name.
        slug = _slugify(title)
        branch = f"changelog/{slug}"

        # 1. Look up the default branch HEAD sha.
        head_sha = self._get_head_sha(repo, base_branch)
        # 2. Create the new branch.
        self._create_ref(repo, branch, head_sha)
        # 3. Commit files to the new branch.
        for leaf, payload in files.items():
            path = f"{extensions_subdir}/{slug}/{leaf}"
            self._commit_file(
                repo=repo,
                branch=branch,
                path=path,
                content_b64=base64.b64encode(payload).decode("ascii"),
                message=f"docs(changelog): publish {slug}",
            )
        # 4. Open the PR.
        pr = self._open_pr(
            repo=repo,
            title=title,
            body=body,
            head=branch,
            base=base_branch,
        )
        return PullRequestResult(url=pr["html_url"], number=pr["number"], branch=branch)

    # ------------------------------------------------------------------
    # GitHub transport
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        url: str,
        body: Optional[dict] = None,
    ) -> dict | list:
        headers = {
            "Authorization": f"Bearer {self.config.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "live-changelog-maintainer/1.0",
        }
        data: Optional[bytes] = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                if not raw:
                    return {}
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GitHubError(
                f"GitHub API {exc.code} on {method} {url}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise GitHubError(f"GitHub unreachable: {exc}") from exc

    def _get_head_sha(self, repo: str, branch: str) -> str:
        resp = self._request(
            "GET",
            f"{self.config.api_base}/repos/{repo}/git/ref/heads/{branch}",
        )
        sha = (resp or {}).get("object", {}).get("sha")
        if not sha:
            raise GitHubError(f"could not resolve HEAD sha for {repo}@{branch}")
        return sha

    def _create_ref(self, repo: str, branch: str, sha: str) -> None:
        # 422 means the ref already exists; that's fine for an idempotent retry.
        try:
            self._request(
                "POST",
                f"{self.config.api_base}/repos/{repo}/git/refs",
                body={"ref": f"refs/heads/{branch}", "sha": sha},
            )
        except GitHubError as exc:
            if "422" in str(exc) and "Reference already exists" in str(exc):
                return
            raise

    def _commit_file(
        self,
        repo: str,
        branch: str,
        path: str,
        content_b64: str,
        message: str,
    ) -> None:
        # Look up existing blob sha (if any) so the API updates rather than 422s.
        try:
            existing = self._request(
                "GET",
                f"{self.config.api_base}/repos/{repo}/contents/{urllib.parse.quote(path, safe='/')}?ref={branch}",
            )
            sha = existing.get("sha") if isinstance(existing, dict) else None
        except GitHubError:
            sha = None

        body: dict = {
            "message": message,
            "branch": branch,
            "content": content_b64,
        }
        if sha:
            body["sha"] = sha
        self._request(
            "PUT",
            f"{self.config.api_base}/repos/{repo}/contents/{urllib.parse.quote(path, safe='/')}",
            body=body,
        )

    def _open_pr(
        self,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str,
    ) -> dict:
        resp = self._request(
            "POST",
            f"{self.config.api_base}/repos/{repo}/pulls",
            body={"title": title, "body": body, "head": head, "base": base},
        )
        if not isinstance(resp, dict) or "html_url" not in resp:
            raise GitHubError(f"PR creation returned unexpected response: {resp!r}")
        return resp


def _slugify(text: str) -> str:
    import re

    s = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return s or "release"


__all__ = [
    "GitHubConfig",
    "GitHubError",
    "GitHubPublisher",
    "PullRequestResult",
]
