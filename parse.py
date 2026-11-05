"""Pull a project name, link, and one sentence out of a megathread comment."""
import html
import re

_LABEL = re.compile(
    r"(?im)^[ \t>*\-•·∙]*#*[ \t]*(?:\d+[.)]\s*)?"
    r"[*_]*\s*"
    r"(here(?:'s| is) the link|"
    r"project\s*name|working\s*title|title|nombre\s+del\s+proyecto|t[ií]tulo|"
    r"project|name|"
    r"repo(?:sitory)?(?:\s*/\s*website)?(?:\s*link)?|"
    r"website(?:\s*/\s*repo)?(?:\s*link)?|"
    r"github|source|link|url|code|enlace(?:\s+a\s+repo)?|"
    r"descripci[oó]n|description|about|summary|"
    r"deployment|install|"
    r"ai\s*involvement|"
    r"features|what it (?:does|is))"
    r"\s*[*_]*\s*[:：]\s*"
)
_PLACEHOLDER_NAMES = {
    "title", "project name", "project", "name", "repo", "description",
    "about", "summary", "link", "url", "code", "github", "website",
    "deployment", "body", "untitled", "what it does", "what it is",
    "repo/website link", "repo website link", "nombre del proyecto",
    "nombre", "titulo", "título", "working title", "descripcion",
    "descripción", "enlace", "enlace a repo", "https", "http",
    "repo/website", "repo website", "repository",
}
_LABEL_PREFIX = re.compile(
    r"^(?:project\s*name|working\s*title|title|nombre\s+del\s+proyecto|t[ií]tulo)\b",
    re.I,
)

_URL = re.compile(r"https?://[^\s)\]>\"']+")
_MD_LINK = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")
_BARE_GH = re.compile(
    r"(?<![\w/])(?:https?://)?(?:www\.)?github\.com/"
    r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)",
    re.I,
)
_BARE_SITE = re.compile(
    r"(?<![\w@./])((?:[a-z0-9-]+\.)+(?:app|dev|io|com|net|org|ai))(?![\w./])",
    re.I,
)
_REPO_HOST = re.compile(
    r"https?://(?:www\.)?(?:github\.com|gitlab\.com|codeberg\.org|"
    r"git\.sr\.ht|gitea\.[^\s/]+)/",
    re.I,
)
_GH = re.compile(
    r"https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)",
    re.I,
)
_SKIP_GH_OWNER = {
    "topics", "features", "collections", "orgs", "settings", "marketplace",
    "site", "about", "apps", "sponsors", "readme", "user-attachments",
}
_SKIP_SITE_HOST = {
    "github.com", "www.github.com", "gitlab.com", "codeberg.org",
    "ghcr.io", "docker.io", "hub.docker.com", "imgur.com",
    "reddit.com", "www.reddit.com", "old.reddit.com",
    "i.redd.it", "preview.redd.it", "v.redd.it",
}
_IMAGE_HOST = ("i.redd.it", "preview.redd.it", "v.redd.it", "imgur.com", "reddit.com")
_DEEP_GH = ("/issues", "/pull/", "/blob/", "/tree/", "/releases", "/discussions", "/wiki")

_BOILER = re.compile(
    r"^(?:"
    r"hi\b|hello\b|hey\b|howdy\b|"
    r"i['’]?m\b|i am\b|im\b|"
    r"i['’]ve been |"
    r"i (?:built|wanted|made|got|use|ran|have|had|decided|developed)\b|"
    r"this is my first |"
    r"sorry\b|feedback\b|yes,|"
    r"project name\b|ai involvement\b|"
    r"full disclosure|honestly|"
    r"happy to |"
    r"repo\b|github\b|website\b|description\b|deployment\b"
    r")",
    re.I,
)
_NAME_STOP = {
    "a", "an", "the", "it", "this", "that", "so", "and", "for", "with", "when",
    "if", "paste", "docker", "clone", "your", "my", "i", "to", "in", "on",
}
_BAD_HOST = re.compile(
    r"localhost|127\.0\.0\.1|0\.0\.0\.0|ghcr\.io|githubusercontent|"
    r"example\.(com|org)|your-site|yourdomain|mydomain|changeme",
    re.I,
)


def _kind(label):
    label = re.sub(r"\s+", " ", label.lower()).strip()
    if label in {
        "project name", "project", "name", "title", "working title",
        "nombre del proyecto", "titulo", "título",
    }:
        return "name"
    if label in {
        "description", "about", "summary", "features", "what it does", "what it is",
        "descripcion", "descripción",
    }:
        return "desc"
    if label in {"deployment", "install", "ai involvement"}:
        return "stop"
    return "link"


def is_placeholder_name(name):
    """True when the text is a form label, not a project name."""
    cleaned = re.sub(r"[^a-z0-9/+ ]+", " ", (name or "").lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" /")
    cleaned = re.sub(r"^\d+\s*", "", cleaned).strip()
    if cleaned in _PLACEHOLDER_NAMES:
        return True
    return cleaned.replace("/", " ") in _PLACEHOLDER_NAMES


def name_needs_repair(name):
    if not name or is_placeholder_name(name):
        return True
    lowered = name.strip().lower()
    if lowered.startswith(("http://", "https://", "[](", "\\")):
        return True
    if lowered in {"or", "and", "but", "sh", "bash"}:
        return True
    if name.rstrip().endswith("?") or re.match(r"(?i)^what\b", name.strip()):
        return True
    return bool(_LABEL_PREFIX.match(name.strip()))


def _sections(body):
    hits = []
    for match in _LABEL.finditer(body):
        hits.append((match.start(), match.end(), _kind(match.group(1))))
    return hits


def _chunk(body, hits, kind):
    for i, (_start, end, found) in enumerate(hits):
        if found != kind:
            continue
        stop = hits[i + 1][0] if i + 1 < len(hits) else len(body)
        return body[end:stop].strip()
    return ""


def _clean_url(url):
    url = html.unescape(url).strip().rstrip(".,);]*>\"'")
    url = re.sub(r"[\\*]+$", "", url)
    url = re.sub(r"\.git$", "", url, flags=re.I)
    return url


def _urls(text):
    """Return (urls, bare_site_urls). Bare sites are domains written without a scheme."""
    found = []
    bare = []
    for _label, url in _MD_LINK.findall(text):
        found.append(_clean_url(url))
    for url in _URL.findall(text):
        found.append(_clean_url(url))
    for owner, repo in _BARE_GH.findall(text):
        found.append(_clean_url(f"https://github.com/{owner}/{repo}"))
    for host in _BARE_SITE.findall(text):
        if host.lower() in _SKIP_SITE_HOST:
            continue
        url = "https://" + host
        found.append(url)
        bare.append(url)
    seen = set()
    out = []
    for url in found:
        if url and url not in seen:
            seen.add(url)
            out.append(url)
    return out, bare


def _is_image(url):
    low = url.lower()
    if any(host in low for host in _IMAGE_HOST):
        return True
    if "user-attachments" in low:
        return True
    return bool(re.search(r"\.(png|jpe?g|gif|webp)(\?|$)", low))


def _is_repo(url):
    return bool(_REPO_HOST.match(url)) and not _is_image(url)


def github_slug(url):
    if not url:
        return None
    match = _GH.search(url)
    if not match:
        return None
    owner, repo = match.group(1), match.group(2)
    if owner.lower() in _SKIP_GH_OWNER:
        return None
    repo = re.sub(r"\.git$", "", repo, flags=re.I)
    return owner, repo


def _repo_rank(url):
    low = url.lower()
    if any(part in low for part in _DEEP_GH):
        return 2
    return 0


def _site_rank(url):
    host = re.sub(r"^https?://", "", url).split("/")[0].lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    path = "/" + url.split("/", 3)[-1] if url.count("/") >= 3 else ""
    if host.startswith(("demo.", "docs.", "blog.", "status.")) or "localhost" in host:
        return 2
    if host.endswith(".github.io"):
        return 1
    if re.search(r"(^|/)(docs|demo|blog)(/|$)", path, re.I):
        return 1
    return 0


def _best(urls, rank):
    if not urls:
        return ""
    best_rank = min(rank(url) for url in urls)
    for url in urls:
        if rank(url) == best_rank:
            return url
    return urls[0]


def _strip_marker(line):
    """Drop a heading mark, list number, or bullet in front of a label."""
    previous = None
    while line != previous:
        previous = line
        line = re.sub(r"^\s*(?:#{1,6}\s+|\d+[.)]\s+|[-*•·∙]+\s+)", "", line)
        line = re.sub(r"^\s*[^\w\s]{1,4}\s+", "", line)
    return line


def _prepare(body):
    body = (body or "").replace("\r\n", "\n").replace("\r", "\n")
    body = body.replace("\\*", "*").replace("\\_", "_").replace("\\#", "#").replace("\\-", "-").replace("\\`", "`")
    body = re.sub(r"[\u200b\u200c\u200d\ufeff\ufffc\u2060]", "", body)

    def _empty_link(match):
        url = match.group(1)
        if re.search(r"redd\.it|reddit\.com|reddithelp\.com", url, re.I):
            return "\n"
        return "\n" + url + "\n"

    body = re.sub(r"!?\[[ \t]*\]\((https?://[^)\s]+)\)", _empty_link, body)
    body = re.sub(r"```[^\n]*\n.*?```", "\n", body, flags=re.S)
    return "\n".join(_strip_marker(line) for line in body.split("\n"))


def _strip_md(text):
    text = html.unescape(text or "")
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"[*_#>]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" \t-|")


def _sentences(text):
    text = _strip_md(text)
    text = _URL.sub(" ", text)
    text = re.sub(
        r"\b(repo/website link|github|website(?: and docs)?|project name|description|deployment)\s*:\s*",
        " ",
        text,
        flags=re.I,
    )
    text = re.sub(r"(?:^|\s)-\s+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    text = text.replace("…", ". ")
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"“])", text)
    return [part.strip(" -|") for part in parts if part.strip(" -|")]


def _mostly_link(sentence):
    if sentence.lower().startswith("http"):
        return True
    urls = _URL.findall(sentence)
    if not urls:
        return False
    return len(" ".join(urls)) > len(sentence) * 0.35


def _useful(sentences):
    useful = []
    for sentence in sentences:
        if len(sentence) < 20 or _mostly_link(sentence):
            continue
        if "--" in sentence or sentence.lower().count("openssl") or sentence.count(":") > 2:
            continue
        # A short greeting is noise. A long "I built X, which …" sentence is the description.
        if _BOILER.match(sentence) and len(sentence.split()) < 14:
            continue
        useful.append(sentence)
    return useful


def _pick(name, useful):
    first_name = re.split(r"[,:(]", name or "")[0].strip().lower()

    def mentions(sentence):
        return bool(first_name) and len(first_name) > 2 and first_name[:16] in sentence.lower()

    for sentence in useful:
        if mentions(sentence) and re.search(
            r"\b(is|are|lets|turns|keeps|gives|works)\b", sentence, re.I
        ):
            return sentence
    for sentence in useful:
        if re.search(r"\b(is a|is an|self-hosted|self hosted)\b", sentence, re.I):
            return sentence
    for sentence in useful:
        if not _BOILER.match(sentence):
            return sentence
    for sentence in useful:
        if mentions(sentence):
            return sentence
    return useful[0]


_TOKEN_SKIP = {
    "cross", "seed", "self", "host", "open", "home", "your", "with", "from",
    "that", "this", "http", "https", "github", "docker", "cloud", "media",
    "local", "stack", "server", "video", "music", "email", "proxy",
}


def _focus(name, sentence):
    """When a bio runs on for a long time, start near the project name."""
    if not sentence or not name or len(sentence) < 180:
        return sentence
    idx = sentence.lower().find(name.lower()[:24])
    if idx < 50:
        return sentence
    words = sentence[:idx].split()
    if len(words) <= 10:
        return sentence
    tail = " ".join(words[-5:]) + " " + sentence[idx:]
    return tail[:1].upper() + tail[1:]


def _cap(name, chosen):
    chosen = _focus(name, chosen)
    chosen = chosen.strip()
    if len(chosen) > 140:
        head = re.split(r"\)\s+(?=[A-Z])", chosen, maxsplit=1)[0]
        if 40 < len(head) < len(chosen) and re.search(r"self-hosted|is a|is an", head, re.I):
            chosen = head
    if len(chosen) > 320:
        cut = chosen[:320].rsplit(" ", 1)[0].rstrip(",;:")
        chosen = cut + "…"
    if chosen and chosen[-1] not in ".!?…":
        chosen += "."
    return chosen


def _sentence_ok(sentence):
    """A tagline with no period is weaker than the next real sentence in the post."""
    if not sentence:
        return False
    words = sentence.split()
    if len(words) >= 12:
        return True
    return len(words) >= 6 and sentence[-1] in ".!?…"


def _one_sentence(name, description, extra=""):
    primary = _useful(_sentences(description))
    solid = [sentence for sentence in primary if _sentence_ok(sentence)]
    chosen = _pick(name, solid or primary) if primary else ""
    if _sentence_ok(chosen):
        return _cap(name, chosen)
    more = _useful(_sentences(extra))
    if more:
        return _cap(name, _pick(name, more))
    if chosen:
        return _cap(name, chosen)
    leftover = [s for s in _sentences(description or extra) if len(s) > 20 and not _mostly_link(s)]
    if leftover:
        return _cap(name, leftover[0])
    return "No description in the post."


def _short_name(line):
    line = re.split(r"\s+[—–-]\s+", line, maxsplit=1)[0]
    line = re.sub(r"\s+v?\d+\.\d+(?:\.\d+)?$", "", line).strip()
    if _LABEL_PREFIX.match(line):
        parts = re.split(r"[:：]", line, maxsplit=1)
        if len(parts) == 2 and parts[1].strip():
            return _short_name(parts[1].strip())
        rest = _LABEL_PREFIX.sub("", line).strip(" :.-")
        if rest:
            return _short_name(rest)
    comma = re.match(r"^([^,]{1,48}),\s+(?:a|an|the|your|my|for)\b", line, re.I)
    if comma and len(comma.group(1).split()) <= 5:
        return comma.group(1).strip()
    if ":" in line or "：" in line:
        left, right = re.split(r"[:：]", line, maxsplit=1)
        left, right = left.strip(), right.strip()
        if right and len(left) <= 32 and 1 <= len(left.split()) <= 4 and not is_placeholder_name(left):
            if re.match(r"https?://", right, re.I):
                return ""
            return left
    return line.strip(" !")


def _looks_like_name(line):
    words = line.split()
    if not words or len(words) > 6 or len(line) > 48:
        return False
    if is_placeholder_name(line):
        return False
    if line.rstrip().endswith("?") or re.match(r"(?i)^what\b", line):
        return False
    if line.endswith(".") and len(words) > 2:
        return False
    if re.match(r"(?i)^(then|after|but|because|once|when|and|that|you|we|they|here|there)\b", line):
        return False
    if line.lower() in {"or", "and", "but", "for", "the", "with", "from", "via"}:
        return False
    if re.match(r"^(if|when|so|this|just|hey|hi|hello|i|i'm|im|check|try)\b", line, re.I):
        return False
    if line.lower().startswith("http") or "www." in line.lower() or line.startswith("[]("):
        return False
    if "`" in line or "\\" in line:
        return False
    if "." in line and " " not in line:
        return False
    return True


def _name_token_ok(word):
    if word.lower() in _NAME_STOP:
        return False
    if word[0].isupper() or word.isupper():
        return True
    return "-" in word or "." in word


def _built_name(body):
    match = re.search(
        r"\b(?:built|introducing|called|named|announcing|released|releasing)\s+([^\n.]{2,80})",
        body,
        re.I,
    )
    if not match:
        return ""
    words = []
    for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9.+-]*", match.group(1)):
        if not _name_token_ok(word):
            break
        words.append(word)
        if len(words) == 5:
            break
    return " ".join(words)


def _candidate_lines(text):
    lines = []
    for raw in (text or "").split("\n"):
        line = _strip_md(raw)
        line = re.sub(r"\s+", " ", line).strip(" *#`\"'")
        if not line or line.startswith(("http://", "https://", "[](")):
            continue
        lines.append(line)
    return lines


def _name_from(chunk, body):
    lines = _candidate_lines(chunk)
    if not lines:
        lines = _candidate_lines(body)
    for line in lines[:8]:
        short = _short_name(line)
        if _looks_like_name(short):
            return short
        head = re.split(r"\.\s+", line, maxsplit=1)[0].strip()
        if head != line and _looks_like_name(head):
            return head
    built = _built_name(body)
    if built and _looks_like_name(built):
        return built
    return ""


def _host(url):
    host = re.sub(r"^https?://", "", url).split("/")[0].lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def _bad_site(url):
    host = _host(url)
    if "." not in host or _BAD_HOST.search(host):
        return True
    return host.endswith(".md")


def _related_site(url, name, repo):
    blob = url.lower()
    for token in re.findall(r"[a-z0-9]{4,}", f"{name} {repo}".lower()):
        if token in _TOKEN_SKIP:
            continue
        if token in blob:
            return True
    return False


def _on_site_line(url, body):
    host = _host(url)
    for line in body.split("\n"):
        if url not in line and host not in line.lower():
            continue
        if re.search(r"\b(website|demo|docs|homepage|site|code)\b", line, re.I):
            return True
    return False


def parse_comment(body):
    """Return name, summary, repo_url, website_url, github owner/repo from a comment."""
    body = _prepare(body)
    hits = _sections(body)
    name = _name_from(_chunk(body, hits, "name"), body)
    desc = _chunk(body, hits, "desc")
    if not desc:
        kept = []
        for line in body.split("\n"):
            line = line.strip()
            if not line or line.startswith(("http", "!", "[")):
                continue
            if re.match(r"^[*_>\-\s]*(project|repo|website|github|code|link|url)\b", line, re.I):
                continue
            kept.append(line)
        desc = " ".join(kept[:8])
    link_text = _chunk(body, hits, "link")
    link_urls, link_bare = _urls(link_text) if link_text else ([], [])
    body_urls, body_bare = _urls(body)
    ordered = []
    seen = set()
    for url in link_urls + body_urls:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    bare = set(link_bare + body_bare)
    repos = [url for url in ordered if _is_repo(url)]
    sites = [
        url for url in ordered
        if not _is_repo(url) and not _is_image(url) and not _bad_site(url)
    ]
    repo_url = _best(repos, _repo_rank)
    slug = github_slug(repo_url)
    if (not name or not _looks_like_name(name)) and slug:
        name = slug[1]
    repo_name = slug[1] if slug else ""
    site_choices = []
    for site in sites:
        if site.rstrip("/") == (repo_url or "").rstrip("/"):
            continue
        if not _related_site(site, name, repo_name) and not _on_site_line(site, body):
            continue
        site_choices.append(site)
    return {
        "name": name or "Untitled",
        "summary": _one_sentence(name, desc, body),
        "repo_url": repo_url,
        "website_url": _best(site_choices, _site_rank),
        "github_owner": slug[0] if slug else "",
        "github_repo": repo_name,
    }


_REPO_ID = re.compile(
    r"https?://(?:www\.)?(github\.com|gitlab\.com|codeberg\.org|git\.sr\.ht)/"
    r"([^/\s?#]+)/([^/\s?#]+)",
    re.I,
)
_FEED_LEAD = re.compile(
    r"^(?:i\s+(?:just\s+)?(?:built|made|created|wrote|released)|"
    r"introducing|announcing|releasing|released|showing)\s+",
    re.I,
)
_FEED_STOP = _NAME_STOP | {
    "im", "most", "you", "here", "now", "made", "self", "this", "just", "new",
}


def repo_identity(url):
    """(host, owner, repo) for a code host, or None. Deep links still match the repo."""
    if not url:
        return None
    match = _REPO_ID.search(url)
    if not match:
        return None
    host, owner, repo = (part.lower() for part in match.groups())
    repo = re.sub(r"\.git$", "", repo)
    if host == "github.com" and owner in _SKIP_GH_OWNER:
        return None
    return host, owner, repo


def feed_name(title):
    """A short project name from a main-page title."""
    raw = _strip_md(_prepare(title))
    raw = re.sub(r"\s+", " ", raw).strip(" \"'*")
    aside = re.match(r"^([^,]{1,48}),\s+\S", raw)
    if aside and 1 <= len(aside.group(1).split()) <= 4:
        candidate = re.sub(r"\s+v?\d+(?:\.\d+){1,2}$", "", aside.group(1)).strip()
        if candidate and candidate[:1].isupper():
            raw = candidate
    raw = _FEED_LEAD.sub("", raw).strip(" -:")
    raw = _short_name(raw)
    raw = _FEED_LEAD.sub("", raw).strip(" -:")
    raw = _short_name(raw)
    words = raw.split()
    if (
        len(words) >= 2
        and len(words[0]) >= 3
        and words[0][:1].isupper()
        and words[0].lower() not in _FEED_STOP
        and words[1][:1].islower()
    ):
        return words[0][:200]
    if len(words) > 4:
        hosted = re.search(r"\bself-?host(?:ing|ed)?\s+([A-Z][\w.+-]{2,})", raw)
        if hosted:
            return hosted.group(1)[:200]
    return (raw or "Untitled")[:200]


def parse_feed(title, body, url=""):
    """Parse a main-page release post. The title supplies the name."""
    name = feed_name(title)
    combined = _prepare(body or "")
    if url and "reddit.com" not in url:
        combined = (combined + "\n" + url).strip()
    parsed = parse_comment(combined or title)
    parsed["name"] = name
    if url and _is_repo(url):
        cleaned = _clean_url(url)
        if not parsed["repo_url"] or _repo_rank(cleaned) < _repo_rank(parsed["repo_url"]):
            parsed["repo_url"] = cleaned
    slug = github_slug(parsed["repo_url"])
    parsed["github_owner"] = slug[0] if slug else ""
    parsed["github_repo"] = slug[1] if slug else ""
    summary = _one_sentence(name, body or "", title)
    if summary:
        parsed["summary"] = summary
    return parsed
