"""Find New Project Megathreads and download their comments.

Arctic Shift is the source that answers from this network. Reddit's own JSON
is tried first and used when it is not blocked.
"""
import logging
import time

import requests

import config

logger = logging.getLogger(__name__)

_SLOW = "slow down"


class RedditError(RuntimeError):
    pass


class RedditClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = config.USER_AGENT
        self._next_ok = 0.0

    def _pace(self):
        wait = self._next_ok - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._next_ok = time.monotonic() + config.REQUEST_GAP_S

    def _get_json(self, url, params=None, paced=True, attempts=5, timeout=None):
        last_error = None
        timeout = config.HTTP_TIMEOUT_S if timeout is None else timeout
        for attempt in range(attempts):
            if paced:
                self._pace()
            try:
                response = self.session.get(url, params=params, timeout=timeout)
            except requests.RequestException as exc:
                last_error = exc
                time.sleep(2 + attempt * 3)
                continue
            if response.status_code == 403:
                return None
            if response.status_code in (422, 429, 503):
                last_error = RedditError(f"{response.status_code} {response.text[:120]}")
                delay = 8 * (attempt + 1)
                if _SLOW in response.text.lower():
                    delay = 12 * (attempt + 1)
                logger.info("Reddit source asked us to wait (%ss): %s", delay, url)
                time.sleep(delay)
                continue
            if response.status_code >= 400:
                last_error = RedditError(f"{response.status_code} {response.text[:160]}")
                time.sleep(2 + attempt * 2)
                continue
            try:
                return response.json()
            except ValueError as exc:
                last_error = exc
                time.sleep(2)
        raise RedditError(f"Failed to fetch {url}: {last_error}")

    def list_megathreads(self):
        """Newest first. Title match is the weekly AutoModerator post."""
        try:
            posts = self._from_reddit_search()
        except RedditError as exc:
            logger.info("Reddit search unavailable: %s", exc)
            posts = []
        if not posts:
            posts = self._from_arctic()
        if not posts:
            raise RedditError("Could not list megathreads from Reddit or Arctic Shift")
        posts.sort(key=lambda post: post["created_utc"], reverse=True)
        return posts

    def _from_reddit_search(self):
        url = f"{config.REDDIT_BASE}/r/selfhosted/search.json"
        payload = self._get_json(url, {
            "q": 'title:"New Project Megathread"',
            "restrict_sr": "1",
            "sort": "new",
            "limit": "100",
            "type": "link",
            "raw_json": "1",
        }, paced=False, attempts=1, timeout=8)
        if not payload:
            return []
        children = (payload.get("data") or {}).get("children") or []
        return [self._reddit_post(child.get("data") or {}) for child in children if self._is_mega(child.get("data") or {})]

    def _from_arctic(self):
        url = f"{config.ARCTIC_SHIFT_BASE}/api/posts/search"
        found = []
        before = None
        for _page in range(10):
            params = {
                "subreddit": "selfhosted",
                "title": "New Project Megathread",
                "limit": 100,
                "sort": "desc",
            }
            if before is not None:
                params["before"] = before
            payload = self._get_json(url, params)
            rows = (payload or {}).get("data") or []
            if not rows:
                break
            for row in rows:
                if self._is_mega(row):
                    found.append(self._arctic_post(row))
            if len(rows) < 100:
                break
            before = min(row["created_utc"] for row in rows)
        return found

    def iter_subreddit_posts(self, since_utc):
        """r/selfhosted posts at or after since_utc, newest first.

        Reddit's new listing is included when it answers, so a post that is
        not in Arctic Shift yet is still seen. Arctic Shift pages back to
        since_utc for the first fill.
        """
        found = {}
        try:
            for row in self._reddit_new_posts():
                if row["id"] and row["created_utc"] >= since_utc:
                    found[row["id"]] = row
        except RedditError as exc:
            logger.info("Reddit new listing unavailable: %s", exc)
        before = None
        pages = 0
        while pages < 220:
            pages += 1
            params = {"subreddit": "selfhosted", "limit": 100, "sort": "desc"}
            if before is not None:
                params["before"] = before
            payload = self._get_json(f"{config.ARCTIC_SHIFT_BASE}/api/posts/search", params)
            rows = (payload or {}).get("data") or []
            if not rows:
                break
            oldest = min(float(row["created_utc"]) for row in rows)
            for row in rows:
                created = float(row.get("created_utc") or 0)
                if created < since_utc or not row.get("id"):
                    continue
                item = self._feed_post(row)
                prev = found.get(item["id"])
                if prev is None or (not prev.get("selftext") and item.get("selftext")):
                    found[item["id"]] = item
            if pages == 1 or pages % 20 == 0:
                logger.info("Main page listing: page %s, %s posts kept", pages, len(found))
            if oldest < since_utc or len(rows) < 100:
                break
            # Arctic Shift rejects a fractional epoch in before.
            before = int(oldest)
        else:
            logger.warning("Main page listing stopped at %s pages, still newer than the cutoff", pages)
        posts = list(found.values())
        posts.sort(key=lambda post: post["created_utc"], reverse=True)
        return posts

    def _reddit_new_posts(self):
        url = f"{config.REDDIT_BASE}/r/selfhosted/new.json"
        payload = self._get_json(
            url, {"limit": "100", "raw_json": "1"},
            paced=False, attempts=1, timeout=8,
        )
        if not payload:
            return []
        children = (payload.get("data") or {}).get("children") or []
        return [self._feed_post(child.get("data") or {}) for child in children]

    @staticmethod
    def _feed_post(row):
        permalink = row.get("permalink") or ""
        if permalink and not permalink.startswith("http"):
            permalink = "https://www.reddit.com" + permalink
        return {
            "id": row.get("id") or "",
            "title": row.get("title") or "",
            "selftext": row.get("selftext") or "",
            "url": row.get("url") or "",
            "created_utc": float(row.get("created_utc") or 0),
            "permalink": permalink,
            "link_flair_text": row.get("link_flair_text") or "",
            "author": row.get("author") or "",
            "score": int(row.get("score") or 0),
            "removed_by_category": row.get("removed_by_category") or "",
        }

    def comments(self, post_id):
        rows = self._arctic_comments(post_id)
        if rows:
            return rows
        return self._reddit_comments(post_id)

    def _arctic_comments(self, post_id):
        url = f"{config.ARCTIC_SHIFT_BASE}/api/comments/search"
        found = []
        seen = set()
        before = None
        for _page in range(30):
            params = {"link_id": post_id, "limit": 100, "sort": "desc"}
            if before is not None:
                params["before"] = before
            payload = self._get_json(url, params)
            rows = (payload or {}).get("data") or []
            if not rows:
                break
            for row in rows:
                if row.get("id") in seen:
                    continue
                seen.add(row.get("id"))
                found.append(row)
            if len(rows) < 100:
                break
            before = min(row["created_utc"] for row in rows)
        return found

    def _reddit_comments(self, post_id):
        url = f"{config.REDDIT_BASE}/r/selfhosted/comments/{post_id}.json"
        payload = self._get_json(
            url, {"limit": 500, "raw_json": "1", "depth": 1},
            paced=False, attempts=1, timeout=8,
        )
        if not isinstance(payload, list) or len(payload) < 2:
            return []
        children = ((payload[1].get("data") or {}).get("children")) or []
        out = []
        for child in children:
            data = child.get("data") or {}
            if data.get("id"):
                out.append(data)
        return out

    @staticmethod
    def _is_mega(row):
        title = (row.get("title") or "").strip()
        return title.startswith("New Project Megathread")

    @staticmethod
    def _arctic_post(row):
        return {
            "id": row["id"],
            "title": row.get("title") or "",
            "created_utc": float(row["created_utc"]),
            "permalink": "https://www.reddit.com" + (row.get("permalink") or f"/r/selfhosted/comments/{row['id']}/"),
        }

    @staticmethod
    def _reddit_post(row):
        permalink = row.get("permalink") or ""
        if permalink and not permalink.startswith("http"):
            permalink = "https://www.reddit.com" + permalink
        return {
            "id": row.get("id"),
            "title": row.get("title") or "",
            "created_utc": float(row.get("created_utc") or 0),
            "permalink": permalink,
        }
