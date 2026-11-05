# Selfhosted catalog

Find projects people have posted on r/selfhosted. Search by name, topic, or words from the post. Filter by category, language, week, or whether it came from a megathread or the main page. Sort by stars, forks, or newest. Star a search or a category to keep it.

Each project is stored once. A later post for the same repo updates that row. The page shows a one-sentence summary, with the full post and links on the project page. When a post points at GitHub, the catalog fills in stars, forks, language, topics, and a category.

## What it collects

Finished [New Project Megathreads](https://www.reddit.com/r/selfhosted/) are read every Monday at 08:00 America/New_York. The newest thread is still collecting comments, so it is left until the next week, or until it is more than six days old. The newest closed week is read again so late comments are kept. On the Weeks page, "Include the week still open" reads the current thread too.

Each morning at 07:00 it adds posts still up on the main page with the flair Release (AI), Release (No AI), or Product Announcement. The first start backfills every closed week, and those main-page posts back to 7 April 2026.

## Run

```sh
cp sample.env .env
# optional: GITHUB_TOKEN=$(gh auth token)
docker compose up -d --build
```

Open `http://localhost:5010`.

A GitHub token is optional. Without one, star counts fill in at 60 requests an hour and resume after a restart. `./update.sh` pulls the latest code and rebuilds the container. The database stays in `./data`.
