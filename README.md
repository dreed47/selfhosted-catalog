# Selfhosted catalog

A catalog of projects posted on r/selfhosted. Each Monday morning it reads every finished New Project Megathread. Each morning it also reads release posts that are still up on the main page. The same repo, or the same project name, is stored once. GitHub fills in stars, language, topics, and a category. The full post is kept, with a one-sentence summary for the list.

The layout matches [iptv-manager](https://github.com/dreed47/iptv-manager): FastAPI, SQLite in `./data`, and the same `update.sh` / `restart_container.sh` flow. It is meant to sit beside that app on the Docker CT. The container is named `selfhosted-catalog` and listens on port 5010.

```sh
cp sample.env .env
# optional: GITHUB_TOKEN=$(gh auth token)
docker compose up -d --build
```

Then open `http://<host>:5010`.

The Monday job skips the newest thread, because that week is still collecting comments. If that thread is already more than six days old, it is read anyway. The newest closed week is refreshed each run so late comments are kept. On the Weeks page, "Include the week still open" reads the current thread too and marks it open so the next run reads it again.

The first start backfills every closed week, and main-page release posts back to 7 Apr 2026. Comment fetches are paced. GitHub enrichment continues in the background and resumes after a restart if the rate limit stops it. A token makes that first pass much shorter. A project already saved from a megathread is not added again when the same repo or name shows up on the main page.

`./update.sh` pulls the git remote and rebuilds the container. The database stays in `./data`.
