"""Catalog pages."""
import html
import re
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from markupsafe import Markup
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

import config
import ingest
from models import Favorite, IngestRun, Project, SessionLocal, Thread, utcnow
from scheduler import describe_schedule, next_daily, next_run

router = APIRouter()
templates = Jinja2Templates(directory="templates")

_URL = re.compile(r"https?://[^\s<>\"']+")
_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_SORTS = {
    "new": Project.created_utc.desc(),
    "stars": Project.stars.desc().nullslast(),
    "forks": Project.forks.desc().nullslast(),
    "name": Project.name.asc(),
    "updated": Project.github_pushed_at.desc().nullslast(),
    "score": Project.score.desc(),
}
_STAR_STEPS = (1, 10, 50, 100, 500)
_FORK_STEPS = (1, 5, 10, 25, 50)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _readable(value):
    """Turn Reddit markdown into plain text before it is escaped and linkified."""
    text = value.replace("\\*", "*").replace("\\_", "_").replace("\\-", "-")

    def repl(match):
        label = match.group(1).replace("*", "").strip()
        url = match.group(2)
        if label.startswith("http") or label in url:
            return url
        return f"{label} ({url})"

    text = _MD_LINK.sub(repl, text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"\1", text)
    return text


def _linkify(value):
    if not value:
        return ""
    escaped = html.escape(_readable(value))
    linked = _URL.sub(
        r'<a href="\g<0>" target="_blank" rel="noopener noreferrer">\g<0></a>',
        escaped,
    )
    return Markup(linked)


def _stars(value):
    if value is None:
        return "—"
    if value >= 1000:
        return f"{value / 1000:.1f}k".replace(".0k", "k")
    return str(value)


def _date(value):
    if not value:
        return ""
    return value.strftime("%-d %b %Y")


def _clock(value, now):
    """Local phrase for a timestamp. `now` is timezone-aware. Naive values are UTC."""
    if value is None:
        return "Not yet"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    local = value.astimezone(now.tzinfo)
    clock = local.strftime("%-I:%M %p")
    if local.date() == now.date():
        label = "Today"
    elif local.date() == now.date() + timedelta(days=1):
        label = "Tomorrow"
    else:
        label = f"{_WEEKDAYS[local.weekday()]} {local.day} {_MONTHS[local.month - 1]}"
    return f"{label}, {clock}"


_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def refresh_stats(db):
    """Last finished pull, the next two scheduled pulls, and catalog counts."""
    now = datetime.now(ZoneInfo(config.TZ_NAME))
    last = (
        db.query(IngestRun)
        .filter(IngestRun.finished_at.isnot(None))
        .order_by(IngestRun.id.desc())
        .first()
    )
    by_source = dict(db.query(Project.source, func.count(Project.id)).group_by(Project.source).all())
    by_github = dict(
        db.query(Project.github_status, func.count(Project.id)).group_by(Project.github_status).all()
    )
    projects = sum(by_source.values())
    with_stars = db.query(func.count(Project.id)).filter(Project.stars.isnot(None)).scalar() or 0
    weeks = db.query(func.count(Thread.id)).filter(Thread.id != "feed").scalar() or 0
    pending = by_github.get("pending", 0) or 0
    failed = by_github.get("error", 0) or 0
    waiting = f"{pending:,} waiting on GitHub" if pending else "none waiting on GitHub"
    if failed:
        waiting += f" · {failed:,} lookups failed"
    weekly = next_run(now, config.PULL_WEEKDAY, config.PULL_HOUR, config.PULL_MINUTE)
    daily = next_daily(now, config.FEED_HOUR, config.FEED_MINUTE)
    if weekly <= daily:
        soon_what, soon, later_what, later = "Megathreads", weekly, "main page", daily
    else:
        soon_what, soon, later_what, later = "Main page", daily, "megathreads", weekly
    note = ""
    if last and last.message:
        note = last.message.split(". ")[0].rstrip(".")
    return {
        "running": ingest.is_running(),
        "detail": (ingest.status_detail().get("detail") or "").strip(),
        "last_when": _clock(last.finished_at if last else None, now),
        "last_note": note,
        "last_status": last.status if last else "",
        "last_message": last.message if last else "",
        "soon_what": soon_what,
        "soon_when": _clock(soon, now),
        "later_what": later_what,
        "later_when": _clock(later, now),
        "project_count": projects,
        "projects": f"{projects:,}",
        "with_stars": f"{with_stars:,}",
        "from_weeks": f"{by_source.get('megathread', 0) or 0:,}",
        "from_feed": f"{by_source.get('feed', 0) or 0:,}",
        "weeks": weeks,
        "waiting": waiting,
    }


templates.env.filters["linkify"] = _linkify
templates.env.filters["stars"] = _stars
templates.env.filters["shortdate"] = _date
templates.env.globals["schedule"] = describe_schedule()


def _at_least(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _favorites(db):
    rows = db.query(Favorite).order_by(Favorite.created_at.desc()).all()
    searches = [row.value for row in rows if row.kind == "search"]
    categories = [row.value for row in rows if row.kind == "category"]
    return searches, categories


def toggle_favorite(db, kind, value):
    value = (value or "").strip()[:200]
    if kind not in {"search", "category"} or not value:
        return None
    row = db.query(Favorite).filter(Favorite.kind == kind, Favorite.value == value).one_or_none()
    if row:
        db.delete(row)
        db.commit()
        return False
    db.add(Favorite(kind=kind, value=value, created_at=utcnow()))
    db.commit()
    return True


def _facets(db, q, week, min_stars, min_forks):
    base = _filter(
        db.query(Project), q, week, None, None, min_stars, min_forks,
    )
    categories = (
        base.with_entities(Project.category, func.count(Project.id))
        .group_by(Project.category)
        .order_by(func.count(Project.id).desc())
        .all()
    )
    languages = (
        base.filter(Project.language.isnot(None), Project.language != "")
        .with_entities(Project.language, func.count(Project.id))
        .group_by(Project.language)
        .order_by(func.count(Project.id).desc())
        .limit(14)
        .all()
    )
    return categories, languages, base.order_by(None).count()


def _filter(query, q, week, category, language, min_stars=0, min_forks=0):
    if week:
        query = query.filter(Project.thread_id == week)
    if category:
        query = query.filter(Project.category == category)
    if language:
        query = query.filter(Project.language == language)
    if min_stars:
        query = query.filter(Project.stars >= min_stars)
    if min_forks:
        query = query.filter(Project.forks >= min_forks)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(
            Project.name.ilike(like),
            Project.summary.ilike(like),
            Project.body.ilike(like),
            Project.topics.ilike(like),
            Project.language.ilike(like),
            Project.category.ilike(like),
        ))
    return query


def _qs(**parts):
    clean = {key: value for key, value in parts.items() if value not in (None, "", 0)}
    return urlencode(clean)


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/api/status")
def api_status(db: Session = Depends(get_db)):
    last = db.query(IngestRun).order_by(IngestRun.id.desc()).first()
    pending = db.query(Project).filter(Project.github_status == "pending").count()
    return {
        "running": ingest.is_running(),
        "detail": ingest.status_detail().get("detail") or "",
        "pending_github": pending,
        "last": None if last is None else {
            "status": last.status,
            "message": last.message,
            "reason": last.reason,
            "started_at": last.started_at.isoformat() if last.started_at else "",
        },
    }


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    db: Session = Depends(get_db),
    q: str = "",
    category: str = "",
    language: str = "",
    week: str = "",
    sort: str = "new",
    page: int = 1,
    min_stars: str = "",
    min_forks: str = "",
):
    sort = sort if sort in _SORTS else "new"
    page = max(1, page)
    min_stars_n = _at_least(min_stars)
    min_forks_n = _at_least(min_forks)
    categories, languages, facet_total = _facets(db, q, week, min_stars_n, min_forks_n)
    query = _filter(db.query(Project), q, week, category, language, min_stars_n, min_forks_n)
    total = query.count()
    pages = max(1, (total + config.PAGE_SIZE - 1) // config.PAGE_SIZE)
    page = min(page, pages)
    rows = (
        query.order_by(_SORTS[sort], Project.id.desc())
        .offset((page - 1) * config.PAGE_SIZE)
        .limit(config.PAGE_SIZE)
        .all()
    )
    weeks = db.query(Thread).order_by(Thread.created_utc.desc()).all()
    week_name = {item.id: item.week_label for item in weeks}
    stats = refresh_stats(db)
    fav_searches, fav_categories = _favorites(db)
    return templates.TemplateResponse(request, "index.html", {
        "rows": rows,
        "q": q,
        "category": category,
        "language": language,
        "week": week,
        "sort": sort,
        "page": page,
        "pages": pages,
        "total": total,
        "project_count": stats["project_count"],
        "stats": stats,
        "facet_total": facet_total,
        "categories": categories,
        "languages": languages,
        "weeks": weeks,
        "week_name": week_name,
        "running": stats["running"],
        "qs": _qs,
        "min_stars": min_stars_n,
        "min_forks": min_forks_n,
        "star_steps": _STAR_STEPS,
        "fork_steps": _FORK_STEPS,
        "fav_searches": fav_searches,
        "fav_categories": fav_categories,
    })


@router.get("/p/{project_id}", response_class=HTMLResponse)
def project_page(project_id: int, request: Request, db: Session = Depends(get_db)):
    row = db.get(Project, project_id)
    if row is None:
        return RedirectResponse("/", status_code=303)
    thread = db.get(Thread, row.thread_id)
    topics = [part for part in (row.topics or "").split(",") if part]
    return templates.TemplateResponse(request, "project.html", {
        "row": row,
        "thread": thread,
        "topics": topics,
    })


@router.get("/weeks", response_class=HTMLResponse)
def weeks_page(request: Request, db: Session = Depends(get_db)):
    rows = db.query(Thread).filter(Thread.id != "feed").order_by(Thread.created_utc.desc()).all()
    project_count = db.query(func.count(Project.id)).scalar() or 0
    return templates.TemplateResponse(request, "weeks.html", {
        "rows": rows,
        "project_count": project_count,
        "running": ingest.is_running(),
    })


@router.get("/logs", response_class=HTMLResponse)
def logs_page(request: Request):
    from logbuf import lines
    return templates.TemplateResponse(request, "logs.html", {
        "lines": list(reversed(lines())),
    })


@router.post("/api/favorites")
def favorites_toggle(kind: str = Form(""), value: str = Form(""), db: Session = Depends(get_db)):
    saved = toggle_favorite(db, kind, value)
    if saved is None:
        return JSONResponse({"ok": False}, status_code=400)
    return {"ok": True, "saved": saved, "kind": kind, "value": value.strip()[:200]}


@router.post("/ingest")
def ingest_now(include_current: str = Form("")):
    _start_ingest(include_current == "1")
    return RedirectResponse("/weeks", status_code=303)


@router.post("/api/ingest")
def ingest_async(include_current: str = Form("")):
    if ingest.is_running():
        return JSONResponse({"ok": False, "running": True})
    _start_ingest(include_current == "1")
    return JSONResponse({"ok": True, "running": True})


def _start_ingest(include_current):
    threading.Thread(
        target=ingest.run_ingest,
        kwargs={"reason": "manual", "include_current": include_current},
        name="manual-pull",
        daemon=True,
    ).start()
