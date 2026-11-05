"""Turn GitHub topics, and the post text when topics are missing, into one category."""

# Topics that describe a stack or a license, not what the app is for.
_GENERIC = {
    "self-hosted", "selfhosted", "homelab", "docker", "docker-compose", "podman",
    "opensource", "open-source", "foss", "mit", "apache", "gpl", "agpl",
    "hacktoberfest", "awesome", "linux", "cli", "web", "api", "rest", "sqlite",
    "python", "golang", "go", "rust", "typescript", "javascript", "nodejs",
    "react", "vue", "svelte", "flask", "fastapi", "django",
}

# First match wins. Specific rooms come before broad ones.
_RULES = [
    ("AI", (
        "llm", "mcp", "ollama", "openai", "claude", "gpt", "genai", "machine-learning",
        "artificial-intelligence", "ai-agent", "agents", "chatbot", "rag",
    )),
    ("Music", (
        "navidrome", "subsonic", "music", "audio", "spotify", "listenbrainz",
        "scrobble", "radio", "playlist",
    )),
    ("Photos", ("immich", "photoprism", "photo", "photos", "gallery", "images")),
    ("Media", (
        "jellyfin", "plex", "emby", "sonarr", "radarr", "prowlarr", "video",
        "movies", "tv", "iptv", "streaming", "anime", "media-server",
    )),
    ("Downloads", (
        "torrent", "usenet", "nzb", "sabnzbd", "qbittorrent", "ytdlp", "yt-dlp",
        "*arr", "arr",
    )),
    ("Documents", (
        "paperless", "ocr", "pdf", "ebook", "notes", "wiki", "markdown",
        "knowledge", "note-taking", "documents",
    )),
    ("Finance", (
        "budget", "finance", "accounting", "bookkeeping", "ledger", "invoice",
        "expense", "firefly",
    )),
    ("Monitoring", (
        "uptime", "monitoring", "prometheus", "grafana", "statuspage", "status-page",
        "observability", "alerting", "on-call", "oncall",
    )),
    ("Security", (
        "password", "vault", "sso", "oidc", "oauth", "passkey", "2fa", "auth",
        "security", "firewall",
    )),
    ("Email", ("email", "smtp", "imap", "mail", "webmail", "newsletter")),
    ("Networking", (
        "vpn", "wireguard", "dns", "proxy", "tunnel", "ngrok", "tailscale",
        "reverse-proxy", "networking", "ddns",
    )),
    ("Home automation", (
        "home-assistant", "homeassistant", "mqtt", "zigbee", "tasmota", "esphome",
        "smarthome", "smart-home",
    )),
    ("Dashboards", ("dashboard", "homepage", "homarr", "startpage")),
    ("Games", ("minecraft", "game", "games", "gameserver")),
    ("Communication", (
        "chat", "matrix", "forum", "irc", "xmpp", "messaging",
        "contacts", "carddav", "caldav", "vcard",
    )),
    ("Backup", ("backup", "restic", "borg", "replication")),
    ("Development", (
        "git", "gitea", "ci", "cd", "devops", "kubernetes", "k8s", "deploy",
        "ide", "coding",
    )),
]


def _hit(blob, words):
    for word in words:
        if word in blob:
            return True
    return False


def from_topics(topics):
    """Return a category when a GitHub topic names one, else None."""
    cleaned = []
    for topic in topics or []:
        t = (topic or "").strip().lower()
        if t and t not in _GENERIC:
            cleaned.append(t)
    blob = " " + " ".join(cleaned) + " "
    # Pad so short words match as tokens, and also allow substring for compounds.
    padded = " " + " ".join(cleaned).replace("-", " ") + " "
    for category, words in _RULES:
        for word in words:
            token = word.replace("-", " ")
            if f" {token} " in padded or word in blob:
                return category
    return None


def from_text(*parts):
    blob = " ".join(p for p in parts if p).lower()
    blob = blob.replace("-", " ")
    padded = f" {blob} "
    for category, words in _RULES:
        for word in words:
            token = word.replace("-", " ")
            if f" {token} " in padded:
                return category
    return "Other"


def choose(topics, *text_parts, have_github=False):
    """GitHub topics win. The post text fills in until topics arrive, and after
    they arrive when none of them name a category."""
    found = from_topics(topics) if have_github else None
    if found:
        return found, "github"
    return from_text(*text_parts), "post" if not have_github else "text"
