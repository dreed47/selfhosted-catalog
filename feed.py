"""Main-page release posts. The same repo or name is one catalog row."""
import re
from datetime import datetime, timezone

from parse import is_placeholder_name, repo_identity

FEED_THREAD_ID = "feed"
FEED_SINCE = datetime(2026, 4, 7, tzinfo=timezone.utc)

_FLAIRS = {"release (ai)", "release (no ai)", "product announcement"}
_GENERIC_NAMES = {
    "selfhosted", "selfhost", "dashboard", "release", "project", "server",
    "app", "tool", "github", "docker", "opensource", "homelab", "new",
}
_GENERIC_REPOS = _GENERIC_NAMES | {
    "web", "api", "www", "docs", "website", "homepage", "config", "dotfiles",
    "self-hosted", "list", "demo",
}


def normalize_name(name):
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def is_removed_post(row):
    title = (row.get("title") or "").strip().lower()
    if title.startswith("[removed") or title.startswith("[ removed"):
        return True
    if (row.get("removed_by_category") or "").strip():
        return True
    body = (row.get("selftext") or "").strip().lower()
    return body in {"[removed]", "[deleted]"}


def accept_feed_post(row):
    """Live Release and Product Announcement posts. Removed posts have no body left."""
    if not row.get("id"):
        return False
    if is_removed_post(row):
        return False
    title = (row.get("title") or "").strip()
    if not title or title.startswith("New Project Megathread"):
        return False
    if (row.get("author") or "") in {"AutoModerator"}:
        return False
    flair = re.sub(r"\s+", " ", (row.get("link_flair_text") or "").strip().lower())
    return flair in _FLAIRS


def identity_of_row(row):
    found = repo_identity(row.repo_url)
    if found:
        return found
    owner = (row.github_owner or "").strip().lower()
    repo = (row.github_repo or "").strip().lower()
    if owner and repo:
        return ("github.com", owner, repo)
    return None


def identity_of_parsed(parsed):
    found = repo_identity(parsed.get("repo_url"))
    if found:
        return found
    owner = (parsed.get("github_owner") or "").strip().lower()
    repo = (parsed.get("github_repo") or "").strip().lower()
    if owner and repo:
        return ("github.com", owner, repo)
    return None


def _repo_name_key(ident):
    """Host plus repo name, ignoring the owner. A moved repo keeps the name."""
    if not ident:
        return None
    repo = ident[2]
    if len(repo) < 4 or repo in _GENERIC_REPOS:
        return None
    return ident[0], repo


def same_project_name(left, right):
    """True when two titles are the same project, or one title is a form label."""
    if is_placeholder_name(left) or is_placeholder_name(right):
        return True
    a, b = normalize_name(left), normalize_name(right)
    if len(a) < 3 or len(b) < 3 or a in _GENERIC_NAMES or b in _GENERIC_NAMES:
        return False
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 4 and long.startswith(short)


class ProjectIndex:
    """In-memory dup check for one pull. First row wins when two share a key."""

    def __init__(self, rows):
        self.by_repo = {}
        self.by_name = {}
        for row in rows:
            self.add(row)

    def add(self, row):
        ident = identity_of_row(row)
        if ident and ident not in self.by_repo:
            self.by_repo[ident] = row
        if is_placeholder_name(row.name):
            return
        key = normalize_name(row.name)
        if len(key) >= 3 and key not in _GENERIC_NAMES and key not in self.by_name:
            self.by_name[key] = row

    def match(self, parsed, comment_id):
        ident = identity_of_parsed(parsed)
        if ident:
            row = self.by_repo.get(ident)
            if row is not None and row.comment_id != comment_id:
                return row
        key = normalize_name(parsed.get("name"))
        if len(key) < 3 or key in _GENERIC_NAMES or is_placeholder_name(parsed.get("name")):
            return None
        row = self.by_name.get(key)
        if row is None or row.comment_id == comment_id:
            return None
        existing = identity_of_row(row)
        if ident and existing and ident != existing:
            return None
        return row
