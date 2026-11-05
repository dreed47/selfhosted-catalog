"""Weekly pull: closed megathreads into SQLite, then GitHub metadata onto each row."""
import logging
import re
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

import categorize
import config
from feed import (
    FEED_SINCE,
    FEED_THREAD_ID,
    ProjectIndex,
    _GENERIC_NAMES,
    _repo_name_key,
    accept_feed_post,
    identity_of_row,
    normalize_name,
    same_project_name,
)
from github_client import GitHubClient, RateLimited
from models import IngestRun, Project, SessionLocal, Thread, utcnow
from parse import is_placeholder_name, name_needs_repair, parse_comment, parse_feed
from reddit_client import RedditClient, RedditError

logger = logging.getLogger(__name__)

_reddit_lock = threading.Lock()
_github_lock = threading.Lock()
_feed_lock = threading.Lock()
_state = {"running": False, "reason": "", "detail": ""}

_WEEK = re.compile(r"Week of\s+(.+)$", re.I)
_SKIP_BODY = {"", "[removed]", "[deleted]"}


def is_running():
    return _state["running"]


def status_detail():
    return dict(_state)


def week_label(title):
    match = _WEEK.search(title or "")
    return match.group(1).strip() if match else (title or "").strip()


def closed_threads(posts, include_current=False, now=None):
    """The newest thread is still collecting comments. Everything older is done.

    A newest thread older than 6 days is treated as done too, so a late
    Monday post does not leave the previous week sitting uncollected.
    """
    if not posts:
        return []
    now = now or datetime.now(timezone.utc)
    newest = posts[0]
    created = datetime.fromtimestamp(newest["created_utc"], timezone.utc)
    newest_is_closed = (now - created) > timedelta(days=6)
    chosen = list(posts) if (include_current or newest_is_closed) else posts[1:]
    return chosen


def _set_idle():
    if not _reddit_lock.locked() and not _github_lock.locked():
        _state.update(running=False, detail="")


def run_ingest(reason="manual", include_current=False):
    if not _reddit_lock.acquire(blocking=False):
        logger.info("Ingest already running, skipped (%s)", reason)
        return False
    _state.update(running=True, reason=reason, detail="Listing megathreads")
    try:
        _run(reason, include_current)
    finally:
        _reddit_lock.release()
        _set_idle()
    return True


def ingest_feed(reason="schedule"):
    """Daily main-page pull. Does not take the megathread lock."""
    result = _pull_feed(RedditClient())
    if result is None:
        return False
    added, dupes = result
    with SessionLocal() as db:
        run = IngestRun(
            started_at=utcnow(),
            finished_at=utcnow(),
            reason=reason,
            status="ok",
            projects_upserted=added,
            message=f"Main page added {added} projects. {dupes} already stored.",
        )
        db.add(run)
        db.commit()
        logger.info(run.message)
    _enrich(GitHubClient())
    _set_idle()
    return True


def _run(reason, include_current):
    reddit = RedditClient()
    github = GitHubClient()
    with SessionLocal() as db:
        run = IngestRun(started_at=utcnow(), reason=reason, status="running")
        db.add(run)
        db.commit()
        run_id = run.id
    try:
        posts = reddit.list_megathreads()
        wanted = closed_threads(posts, include_current=include_current)
        logger.info("Found %s megathreads, %s selected", len(posts), len(wanted))
        upserted = 0
        with SessionLocal() as db:
            renamed, removed = repair_catalog(db)
            if renamed or removed:
                logger.info("Cleaned %s titles and merged %s duplicate projects", renamed, removed)
            catalog = ProjectIndex(db.query(Project).all())
            for index, post in enumerate(wanted, start=1):
                if _should_skip(db, post, include_current, posts):
                    continue
                _state["detail"] = f"Reading {week_label(post['title'])} ({index}/{len(wanted)})"
                upserted += _ingest_thread(db, reddit, post, posts[0]["id"] if posts else "", catalog)
            run = db.get(IngestRun, run_id)
            run.threads_seen = len(wanted)
            run.projects_upserted = upserted
            db.commit()
        feed_added, feed_dupes = 0, 0
        try:
            _state["detail"] = "Reading the main page"
            result = _pull_feed(reddit)
            if result:
                feed_added, feed_dupes = result
        except Exception:
            logger.exception("Main page pull failed")
        _state["detail"] = "Filling in GitHub stars and topics"
        enriched = _enrich(github)
        with SessionLocal() as db:
            run = db.get(IngestRun, run_id)
            run.status = "ok"
            run.finished_at = utcnow()
            pending = db.query(Project).filter(Project.github_status == "pending").count()
            if enriched is None:
                github_note = "GitHub fill already running."
            else:
                github_note = f"GitHub details updated for {enriched}. {pending} still waiting."
            run.message = (
                f"Added {upserted} new projects across {len(wanted)} weeks. "
                f"Main page added {feed_added}, {feed_dupes} already stored. "
                f"{github_note}"
            )
            db.commit()
            logger.info(run.message)
    except Exception as exc:
        logger.exception("Ingest failed")
        with SessionLocal() as db:
            run = db.get(IngestRun, run_id)
            if run:
                run.status = "error"
                run.finished_at = utcnow()
                run.message = str(exc)[:500]
                db.commit()


def _should_skip(db, post, include_current, posts):
    """Re-read the open week and the newest closed week. Leave older complete weeks alone."""
    del include_current  # selection already happened in closed_threads
    row = db.get(Thread, post["id"])
    if row is None or row.status in {"partial", "open"}:
        return False
    if posts and post["id"] == posts[0]["id"]:
        return False
    if len(posts) >= 2 and post["id"] == posts[1]["id"]:
        return False
    return row.status == "complete"


def _ingest_thread(db, reddit, post, newest_id, catalog):
    created = datetime.fromtimestamp(post["created_utc"], timezone.utc).replace(tzinfo=None)
    row = db.get(Thread, post["id"])
    if row is None:
        row = Thread(id=post["id"], title=post["title"], created_utc=created)
        db.add(row)
    row.title = post["title"]
    row.week_label = week_label(post["title"])
    row.permalink = post["permalink"]
    row.created_utc = created
    row.status = "open" if post["id"] == newest_id else "partial"
    row.updated_at = utcnow()
    db.commit()

    try:
        comments = reddit.comments(post["id"])
    except RedditError as exc:
        row.error = str(exc)[:500]
        row.status = "partial"
        db.commit()
        logger.warning("Comments failed for %s: %s", post["id"], exc)
        return 0

    count = 0
    for comment in comments:
        parent = str(comment.get("parent_id") or "")
        if parent and not parent.startswith("t3_"):
            continue
        body = comment.get("body") or ""
        if body.strip() in _SKIP_BODY:
            continue
        if comment.get("author") in {None, "AutoModerator"}:
            continue
        parsed = parse_comment(body)
        count += _upsert_project(db, post["id"], comment, parsed, catalog)
    row.project_count = (
        db.query(Project).filter(Project.thread_id == post["id"]).count()
    )
    row.status = "open" if post["id"] == newest_id else "complete"
    row.error = None
    row.updated_at = utcnow()
    db.commit()
    logger.info("Week %s: %s projects", row.week_label, row.project_count)
    return count


def _feed_cutoff(db):
    floor = FEED_SINCE
    latest = (
        db.query(func.max(Project.created_utc))
        .filter(Project.source == "feed")
        .scalar()
    )
    if latest is not None:
        recent = latest.replace(tzinfo=timezone.utc) - timedelta(days=2)
        if recent > floor:
            floor = recent
    return floor.timestamp()


def _ensure_feed_thread(db):
    row = db.get(Thread, FEED_THREAD_ID)
    if row is None:
        row = Thread(
            id=FEED_THREAD_ID,
            title="Main page",
            week_label="Main page",
            permalink="https://www.reddit.com/r/selfhosted/",
            created_utc=datetime(2026, 4, 7),
            status="complete",
            project_count=0,
        )
        db.add(row)
        db.commit()
    return row


def _feed_body(post):
    title = (post.get("title") or "").strip()
    body = (post.get("selftext") or "").strip()
    url = (post.get("url") or "").strip()
    parts = []
    if title:
        parts.append(title)
    if body and body != title:
        parts.append(body)
    if url and "reddit.com" not in url and url not in body and url not in title:
        parts.append(url)
    return "\n\n".join(parts)


def _abs_permalink(post):
    permalink = post.get("permalink") or ""
    if permalink and not permalink.startswith("http"):
        permalink = "https://www.reddit.com" + permalink
    return permalink


def _pull_feed(reddit):
    if not _feed_lock.acquire(blocking=False):
        logger.info("Main page pull already running, skipped")
        return None
    try:
        return _pull_feed_locked(reddit)
    finally:
        _feed_lock.release()


def _pull_feed_locked(reddit):
    with SessionLocal() as db:
        since = _feed_cutoff(db)
    posts = reddit.iter_subreddit_posts(since)
    chosen = [post for post in posts if accept_feed_post(post)]
    logger.info("Main page: %s posts listed, %s release posts kept", len(posts), len(chosen))
    added = 0
    dupes = 0
    with SessionLocal() as db:
        _ensure_feed_thread(db)
        index = ProjectIndex(db.query(Project).all())
        for post in chosen:
            if _store_feed_post(db, index, post):
                added += 1
            else:
                dupes += 1
        thread = db.get(Thread, FEED_THREAD_ID)
        thread.project_count = (
            db.query(Project).filter(Project.thread_id == FEED_THREAD_ID).count()
        )
        thread.updated_at = utcnow()
        thread.status = "complete"
        db.commit()
    logger.info("Main page stored %s new, %s already in the catalog", added, dupes)
    return added, dupes


def _store_feed_post(db, index, post):
    """Insert a main-page post. Return True when a new row was created."""
    comment_id = "t3_" + post["id"]
    created = datetime.fromtimestamp(float(post["created_utc"]), timezone.utc).replace(tzinfo=None)
    body = _feed_body(post)
    parsed = parse_feed(post.get("title") or "", post.get("selftext") or "", post.get("url") or "")
    permalink = _abs_permalink(post)[:400]
    existing = db.query(Project).filter(Project.comment_id == comment_id).one_or_none()
    if existing is not None:
        existing.score = int(post.get("score") or 0)
        if body and body != existing.body:
            existing.body = body
            existing.summary = parsed["summary"]
        _fill_missing_links(existing, parsed)
        db.commit()
        return False
    other = index.match(parsed, comment_id)
    if other is not None:
        _note_duplicate(db, other, post, parsed, created, permalink)
        index.add(other)
        return False
    category, source = categorize.choose([], parsed["name"], parsed["summary"], have_github=False)
    row = Project(
        comment_id=comment_id,
        thread_id=FEED_THREAD_ID,
        created_utc=created,
        author=post.get("author") or "",
        score=int(post.get("score") or 0),
        name=parsed["name"][:200],
        summary=parsed["summary"],
        body=body,
        repo_url=parsed["repo_url"][:400] if parsed["repo_url"] else None,
        website_url=parsed["website_url"][:400] if parsed["website_url"] else None,
        github_owner=parsed["github_owner"] or None,
        github_repo=parsed["github_repo"] or None,
        category=category,
        category_source=source,
        permalink=permalink,
        source="feed",
        github_status="pending" if parsed["github_owner"] else "none",
    )
    db.add(row)
    db.commit()
    index.add(row)
    return True


def _fill_missing_links(row, parsed):
    if not row.repo_url and parsed["repo_url"]:
        row.repo_url = parsed["repo_url"][:400]
    if not row.github_owner and parsed["github_owner"]:
        row.github_owner = parsed["github_owner"]
        row.github_repo = parsed["github_repo"] or None
        if row.github_status in {None, "", "none", "error"}:
            row.github_status = "pending"
    if not row.website_url and parsed["website_url"]:
        row.website_url = parsed["website_url"][:400]


def _note_duplicate(db, row, post, parsed, created, permalink):
    """Keep the existing project. A newer main-page post can refresh a feed row."""
    if permalink and permalink != (row.permalink or ""):
        if row.source == "feed" and created >= (row.created_utc or created):
            row.summary = parsed["summary"]
            row.body = _feed_body(post)
            row.score = int(post.get("score") or 0)
            row.created_utc = created
            row.permalink = permalink
            row.name = parsed["name"][:200]
        elif row.feed_permalink != permalink:
            row.feed_permalink = permalink
    _fill_missing_links(row, parsed)
    db.commit()


def repair_catalog(db):
    """Replace form-label titles, then keep one row per project."""
    renamed = 0
    for row in db.query(Project).all():
        parsed = _reparse(row)
        if name_needs_repair(row.name) and parsed["name"] and not name_needs_repair(parsed["name"]):
            row.name = parsed["name"][:200]
            if parsed["summary"] and parsed["summary"] != "No description in the post.":
                row.summary = parsed["summary"]
            renamed += 1
            if row.category_source != "github":
                category, source = categorize.choose(
                    [], row.name, row.summary, have_github=False
                )
                row.category = category
                row.category_source = source
        if not row.repo_url and parsed.get("repo_url"):
            row.repo_url = parsed["repo_url"][:400]
        if not row.github_owner and parsed.get("github_owner"):
            row.github_owner = parsed["github_owner"]
            row.github_repo = parsed["github_repo"] or None
            if row.github_status in {None, "", "none", "error"}:
                row.github_status = "pending"
        elif _repo_follows_name(row, parsed):
            row.github_owner = parsed["github_owner"]
            row.github_repo = parsed["github_repo"] or None
            if parsed.get("repo_url"):
                row.repo_url = parsed["repo_url"][:400]
            row.stars = None
            row.forks = None
            row.github_status = "pending"
            row.github_error = None
        if not row.website_url and parsed.get("website_url"):
            row.website_url = parsed["website_url"][:400]
    removed = _collapse_duplicates(db)
    db.commit()
    return renamed, removed


def _repo_follows_name(row, parsed):
    """The title names the repo, and the stored repo is a different project."""
    parsed_repo = parsed.get("github_repo") or ""
    if not parsed.get("github_owner") or not parsed_repo:
        return False
    if (row.github_owner or "").lower() == parsed["github_owner"].lower() and (
        (row.github_repo or "").lower() == parsed_repo.lower()
    ):
        return False
    return _name_is_repo(row.name, parsed_repo) and not _name_is_repo(row.name, row.github_repo)


def _name_is_repo(name, repo):
    left, right = normalize_name(name), normalize_name(repo)
    if not left or not right:
        return False
    if left == right:
        return True
    if len(left) < 4 or len(right) < 4:
        return False
    return left.startswith(right) or right.startswith(left)


def _reparse(row):
    if row.source == "feed":
        title, sep, rest = (row.body or "").partition("\n\n")
        return parse_feed(title, rest if sep else "", row.repo_url or "")
    return parse_comment(row.body or "")


def _redirect_key(row, ident):
    if row.stars is None or row.github_pushed_at is None:
        return None
    repo_name = _repo_name_key(ident)
    if not repo_name:
        return None
    return repo_name + (row.stars, row.forks, row.github_pushed_at)


def _keep_rank(row):
    real = 0 if name_needs_repair(row.name) else 1
    repo_named = 1 if row.github_repo and normalize_name(row.name) == normalize_name(row.github_repo) else 0
    described = 1 if re.search(r"self-hosted|is a|is an", row.summary or "", re.I) else 0
    done = 1 if row.github_status == "done" else 0
    return (real, repo_named, described, done, row.stars or 0, row.created_utc or datetime.min)


def _copy_github(dest, src):
    dest.github_owner = src.github_owner
    dest.github_repo = src.github_repo
    dest.stars = src.stars
    dest.forks = src.forks
    dest.language = src.language
    dest.license = src.license
    dest.topics = src.topics
    dest.github_description = src.github_description
    dest.github_pushed_at = src.github_pushed_at
    dest.archived = src.archived
    dest.github_status = src.github_status
    dest.github_error = None
    if src.repo_url:
        dest.repo_url = src.repo_url
    if src.category_source == "github":
        dest.category = src.category
        dest.category_source = "github"


def _collapse_duplicates(db):
    rows = db.query(Project).all()
    parent = {item.id: item.id for item in rows}

    def find(item):
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(left, right):
        left, right = find(left), find(right)
        if left != right:
            parent[right] = left

    by_repo = {}
    by_repo_name = {}
    by_name = {}
    for row in rows:
        ident = identity_of_row(row)
        if ident:
            if ident in by_repo:
                union(row.id, by_repo[ident].id)
            else:
                by_repo[ident] = row
            # A moved repo answers with the new owner's stars and the same push time.
            key = _redirect_key(row, ident)
            if key:
                other = by_repo_name.get(key)
                if other is None:
                    by_repo_name[key] = row
                elif same_project_name(other.name, row.name):
                    union(row.id, other.id)
        if is_placeholder_name(row.name):
            continue
        key = normalize_name(row.name)
        if len(key) < 3 or key in _GENERIC_NAMES:
            continue
        other = by_name.get(key)
        if other is None:
            by_name[key] = row
            continue
        left, right = identity_of_row(other), identity_of_row(row)
        if left and right and left != right:
            continue
        union(row.id, other.id)

    groups = {}
    for row in rows:
        groups.setdefault(find(row.id), []).append(row)
    removed = 0
    for members in groups.values():
        if len(members) < 2:
            continue
        keeper = max(members, key=_keep_rank)
        richest = max(members, key=lambda item: (item.github_status == "done", item.stars or 0, item.forks or 0))
        if richest is not keeper and richest.github_status == "done":
            _copy_github(keeper, richest)
        for other in members:
            if other is keeper:
                continue
            _fill_missing_links(keeper, {
                "repo_url": other.repo_url or "",
                "website_url": other.website_url or "",
                "github_owner": other.github_owner or "",
                "github_repo": other.github_repo or "",
            })
            if other.permalink and other.permalink != (keeper.permalink or ""):
                if other.source == "feed" and not keeper.feed_permalink:
                    keeper.feed_permalink = other.permalink
            if other.feed_permalink and not keeper.feed_permalink:
                keeper.feed_permalink = other.feed_permalink
            db.delete(other)
            removed += 1
    db.flush()
    for thread in db.query(Thread).all():
        thread.project_count = db.query(Project).filter(Project.thread_id == thread.id).count()
    return removed


def _absorb_duplicate(row, comment, parsed):
    """A later post of a project already stored updates a label, not a good title."""
    if name_needs_repair(row.name) and parsed["name"] and not name_needs_repair(parsed["name"]):
        row.name = parsed["name"][:200]
        row.summary = parsed["summary"]
        row.body = comment.get("body") or row.body
    elif not re.search(r"self-hosted|is a|is an", row.summary or "", re.I):
        if re.search(r"self-hosted|is a|is an", parsed.get("summary") or "", re.I):
            row.summary = parsed["summary"]
            if parsed["name"] and not name_needs_repair(parsed["name"]):
                row.name = parsed["name"][:200]
    _fill_missing_links(row, parsed)


def _upsert_project(db, thread_id, comment, parsed, catalog=None):
    created = datetime.fromtimestamp(float(comment["created_utc"]), timezone.utc).replace(tzinfo=None)
    permalink = comment.get("permalink") or ""
    if permalink and not permalink.startswith("http"):
        permalink = "https://www.reddit.com" + permalink
    category, source = categorize.choose(
        [],
        parsed["name"],
        parsed["summary"],
        have_github=False,
    )
    row = db.query(Project).filter(Project.comment_id == comment["id"]).one_or_none()
    if row is None and catalog is not None:
        other = catalog.match(parsed, comment["id"])
        if other is not None:
            _absorb_duplicate(other, comment, parsed)
            db.commit()
            catalog.add(other)
            return 0
    fresh = row is None
    if fresh:
        row = Project(comment_id=comment["id"], thread_id=thread_id, created_utc=created)
        db.add(row)
    row.thread_id = thread_id
    row.author = comment.get("author") or ""
    row.score = int(comment.get("score") or 0)
    row.created_utc = created
    row.name = parsed["name"][:200]
    row.summary = parsed["summary"]
    row.body = comment.get("body") or ""
    row.repo_url = parsed["repo_url"][:400] if parsed["repo_url"] else None
    row.website_url = parsed["website_url"][:400] if parsed["website_url"] else None
    row.permalink = permalink[:400]
    if row.category_source != "github":
        row.category = category
        row.category_source = source
    slug_changed = (row.github_owner or "") != (parsed["github_owner"] or "") or (
        row.github_repo or ""
    ) != (parsed["github_repo"] or "")
    row.github_owner = parsed["github_owner"] or None
    row.github_repo = parsed["github_repo"] or None
    if parsed["github_owner"] and (slug_changed or row.github_status in {None, "", "none", "error"}):
        row.github_status = "pending"
    elif not parsed["github_owner"]:
        row.github_status = "none"
    db.commit()
    if catalog is not None:
        catalog.add(row)
    return 1 if fresh else 0


def _enrich(github):
    """Walk pending GitHub repos. On the public rate limit, wait and continue.

    A second caller returns without waiting, so the Monday pull can read
    Reddit while a fill is already walking repos. New pending rows are picked
    up by the walk that is already running.
    """
    if not _github_lock.acquire(blocking=False):
        logger.info("GitHub fill already running")
        return None
    _state.update(running=True, reason=_state.get("reason") or "github", detail="Filling in GitHub stars and topics")
    try:
        return _enrich_locked(github)
    finally:
        _github_lock.release()
        _set_idle()


def _enrich_locked(github):
    done = 0
    while True:
        with SessionLocal() as db:
            row = (
                db.query(Project)
                .filter(Project.github_status == "pending")
                .order_by(Project.id)
                .first()
            )
            if row is None:
                return done
            project_id = row.id
            owner, repo_name = row.github_owner, row.github_repo
        if not owner or not repo_name:
            _mark_github(project_id, status="none")
            continue
        try:
            meta = github.fetch(owner, repo_name)
        except RateLimited as exc:
            logger.info("%s", exc)
            _state["detail"] = f"Waiting on GitHub rate limit ({exc.seconds:.0f}s)"
            # Public limit is an hour. Sleep in the background thread, not the web worker.
            time_left = exc.seconds
            while time_left > 0:
                step = min(30, time_left)
                threading.Event().wait(step)
                time_left -= step
                _state["detail"] = f"Waiting on GitHub rate limit ({max(time_left, 0):.0f}s)"
            continue
        except Exception as exc:
            logger.warning("GitHub %s/%s: %s", owner, repo_name, exc)
            _mark_github(project_id, status="error", error=str(exc)[:300])
            continue
        _apply_github(project_id, meta)
        done += 1
        if done % 25 == 0:
            _state["detail"] = f"GitHub details {done} updated"


def _mark_github(project_id, status, error=None):
    with SessionLocal() as db:
        row = db.get(Project, project_id)
        if row:
            row.github_status = status
            row.github_error = error
            db.commit()


def _apply_github(project_id, meta):
    with SessionLocal() as db:
        row = db.get(Project, project_id)
        if row is None:
            return
        if meta is None:
            row.github_status = "error"
            row.github_error = "Repo not found"
            db.commit()
            return
        from datetime import datetime as _dt

        pushed = None
        if meta["pushed_at"]:
            pushed = _dt.strptime(meta["pushed_at"], "%Y-%m-%dT%H:%M:%SZ")
        canon_owner = (meta.get("owner") or row.github_owner or "").strip()
        canon_repo = (meta.get("repo") or row.github_repo or "").strip()
        if canon_owner and canon_repo and (
            (row.github_owner or "").lower() != canon_owner.lower()
            or (row.github_repo or "") != canon_repo
        ):
            row.github_owner = canon_owner
            row.github_repo = canon_repo
            if row.repo_url and "github.com" in row.repo_url.lower():
                row.repo_url = f"https://github.com/{canon_owner}/{canon_repo}"[:400]
        row.language = meta["language"] or None
        row.stars = meta["stars"]
        row.forks = meta["forks"]
        license_name = meta["license"] or ""
        if license_name in {"NOASSERTION", "OTHER"}:
            license_name = ""
        row.license = license_name or None
        row.github_description = meta["description"] or None
        row.github_pushed_at = pushed
        row.archived = 1 if meta["archived"] else 0
        row.topics = ",".join(meta["topics"])[:500]
        if meta["homepage"] and not row.website_url:
            row.website_url = meta["homepage"][:400]
        category, source = categorize.choose(
            meta["topics"],
            row.name,
            row.summary,
            meta["description"],
            have_github=True,
        )
        row.category = category
        row.category_source = source
        row.github_status = "done"
        row.github_error = None
        db.commit()
