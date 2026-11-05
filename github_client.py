"""Repo metadata used for category, language, and sort."""
import logging
import time

import requests

import config

logger = logging.getLogger(__name__)


class RateLimited(RuntimeError):
    def __init__(self, seconds):
        super().__init__(f"GitHub rate limit, retry in {seconds:.0f}s")
        self.seconds = seconds


class GitHubClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = config.USER_AGENT
        self.session.headers["Accept"] = "application/vnd.github+json"
        self.session.headers["X-GitHub-Api-Version"] = "2022-11-28"
        if config.GITHUB_TOKEN:
            self.session.headers["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"
        self._next_ok = 0.0

    def fetch(self, owner, repo):
        wait = self._next_ok - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        url = f"https://api.github.com/repos/{owner}/{repo}"
        response = self.session.get(url, timeout=config.HTTP_TIMEOUT_S)
        self._next_ok = time.monotonic() + config.GITHUB_GAP_S
        remaining = response.headers.get("X-RateLimit-Remaining")
        reset = response.headers.get("X-RateLimit-Reset")
        if response.status_code == 403 and remaining == "0":
            seconds = max(1, int(reset or 0) - int(time.time()) + 2)
            raise RateLimited(seconds)
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise RuntimeError(f"GitHub {response.status_code} for {owner}/{repo}: {response.text[:160]}")
        # Stay under the hourly cap before the request that would trip it.
        if remaining is not None and int(remaining) <= 1 and reset:
            self._next_ok = max(self._next_ok, float(reset) - time.time() + time.monotonic() + 2)
        data = response.json()
        license_info = data.get("license") or {}
        pushed = data.get("pushed_at") or ""
        full_name = (data.get("full_name") or "").strip()
        canon_owner, canon_repo = owner, repo
        if "/" in full_name:
            canon_owner, canon_repo = full_name.split("/", 1)
        return {
            "owner": canon_owner,
            "repo": canon_repo,
            "description": (data.get("description") or "").strip(),
            "language": data.get("language") or "",
            "stars": int(data.get("stargazers_count") or 0),
            "forks": int(data.get("forks_count") or 0),
            "topics": list(data.get("topics") or []),
            "license": license_info.get("spdx_id") or "",
            "homepage": (data.get("homepage") or "").strip(),
            "archived": bool(data.get("archived")),
            "pushed_at": pushed,
        }
