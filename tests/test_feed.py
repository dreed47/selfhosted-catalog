"""Main-page posts and duplicate checks. No network."""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

os.environ["DATA_DIR"] = "/tmp/megathread-feed-test"
os.environ["DB_PATH"] = "/tmp/megathread-feed-test/data.db"
os.environ["RUN_ON_START"] = "0"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from feed import ProjectIndex, accept_feed_post  # noqa: E402
from models import Base, Project, SessionLocal, Thread, engine, init_db  # noqa: E402
from ingest import _pull_feed_locked, _upsert_project, repair_catalog  # noqa: E402
from parse import feed_name, parse_comment, repo_identity  # noqa: E402
from scheduler import next_daily  # noqa: E402


def _post(**over):
    row = {
        "id": "abc",
        "title": "Sampler Hub: a self-hosted sync server",
        "selftext": "Sampler Hub is a sync server for a local-first assistant.",
        "url": "https://github.com/example/sampler-hub",
        "created_utc": datetime(2026, 11, 5, tzinfo=timezone.utc).timestamp(),
        "permalink": "https://www.reddit.com/r/selfhosted/comments/abc/sampler/",
        "link_flair_text": "Release (AI)",
        "author": "someone",
        "score": 3,
        "removed_by_category": "",
    }
    row.update(over)
    return row


class FakeReddit:
    def __init__(self, posts):
        self.posts = posts

    def iter_subreddit_posts(self, since_utc):
        return [post for post in self.posts if post["created_utc"] >= since_utc]


class FeedTests(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        init_db()
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()

    def test_names_from_titles(self):
        self.assertEqual(feed_name("Sampler Hub: a self-hosted sync server"), "Sampler Hub")
        self.assertEqual(feed_name("I built Arenet — a self-hosted reverse proxy"), "Arenet")
        self.assertEqual(feed_name("Sablier, 4 years later: start your apps on demand"), "Sablier")
        self.assertEqual(feed_name("Kyoo now released on Android TV with v5.3.0"), "Kyoo")
        self.assertEqual(feed_name("NoteDiscovery 0.33.0, wikilink autocomplete"), "NoteDiscovery")
        self.assertEqual(feed_name("BackVault v3.0 RC1"), "BackVault")
        self.assertEqual(
            feed_name("You can now selfhost Gryffi, an open source platform"),
            "Gryffi",
        )
        self.assertIn("TUI", feed_name("A TUI to get into self-hosting"))

    def test_accepts_live_release_only(self):
        self.assertTrue(accept_feed_post(_post()))
        self.assertFalse(accept_feed_post(_post(link_flair_text="Need Help")))
        self.assertFalse(accept_feed_post(_post(removed_by_category="reddit")))
        self.assertFalse(accept_feed_post(_post(title="[ Removed by moderator ]")))
        self.assertFalse(accept_feed_post(_post(selftext="[removed]")))
        self.assertFalse(accept_feed_post(_post(title="New Project Megathread - Week of 29 Oct 2026")))
        self.assertTrue(accept_feed_post(_post(link_flair_text="Product Announcement")))

    def test_repo_identity_ignores_deep_link(self):
        self.assertEqual(
            repo_identity("https://github.com/Example/Sampler-Hub/tree/main"),
            ("github.com", "example", "sampler-hub"),
        )
        self.assertIsNone(repo_identity("https://example.com/docs"))

    def test_same_repo_is_one_project(self):
        now = datetime(2026, 10, 29)
        self.db.add(Thread(
            id="t1", title="Week", week_label="29 Oct 2026",
            permalink="", created_utc=now, status="complete",
        ))
        self.db.add(Project(
            comment_id="c1", thread_id="t1", author="meg", score=2, created_utc=now,
            name="Sampler Hub", summary="From the thread.", body="From the thread.",
            repo_url="https://github.com/example/sampler-hub",
            github_owner="example", github_repo="sampler-hub",
            category="Other", source="megathread", permalink="https://reddit/c1",
        ))
        self.db.commit()
        newer = _post(id="new1", created_utc=datetime(2026, 11, 5, tzinfo=timezone.utc).timestamp())
        added, dupes = _pull_feed_locked(FakeReddit([newer]))
        self.assertEqual((added, dupes), (0, 1))
        rows = self.db.query(Project).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].body, "From the thread.")
        self.assertEqual(rows[0].feed_permalink, newer["permalink"])
        self.assertEqual(rows[0].source, "megathread")

    def test_two_feed_posts_keep_the_newer_text(self):
        older = _post(
            id="old",
            title="Sampler Hub: first release",
            selftext="Sampler Hub is a sync server.",
            created_utc=datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp(),
            score=1,
        )
        newer = _post(
            id="new",
            title="Sampler Hub: now with backups",
            selftext="Sampler Hub is a sync server with backups.",
            created_utc=datetime(2026, 11, 5, tzinfo=timezone.utc).timestamp(),
            score=9,
        )
        added, dupes = _pull_feed_locked(FakeReddit([newer, older]))
        self.assertEqual((added, dupes), (1, 1))
        row = self.db.query(Project).one()
        self.assertEqual(row.source, "feed")
        self.assertEqual(row.comment_id, "t3_new")
        self.assertIn("backups", row.summary)
        self.assertEqual(row.score, 9)

    def test_different_repos_stay_separate(self):
        one = _post(id="a", title="Alpha: one app", url="https://github.com/a/alpha", selftext="Alpha is a notes app.")
        two = _post(id="b", title="Alpha: another app", url="https://github.com/b/alpha", selftext="Alpha is a music app.")
        added, dupes = _pull_feed_locked(FakeReddit([one, two]))
        self.assertEqual(added, 2)
        self.assertEqual(dupes, 0)

    def test_same_name_without_a_repo_is_one_project(self):
        one = _post(id="a", title="Sidewave: a player", url="", selftext="Sidewave is a music player you host.")
        two = _post(id="b", title="Sidewave", url="", selftext="Sidewave is a music player for your server.")
        added, dupes = _pull_feed_locked(FakeReddit([one, two]))
        self.assertEqual((added, dupes), (1, 1))

    def test_repost_of_the_same_repo_is_not_a_second_project(self):
        self.db.add(Thread(
            id="week",
            title="New Project Megathread Week of 2 Jul 2026",
            week_label="2 Jul 2026",
            created_utc=datetime(2026, 7, 2),
        ))
        self.db.commit()
        catalog = ProjectIndex([])
        body = (
            "**Project Name:** openGym\n\n"
            "Repo: https://github.com/DuarteSantos8/openGym\n\n"
            "Description: openGym is a self-hosted workout tracker.\n"
        )
        first = {
            "id": "c1",
            "created_utc": datetime(2026, 7, 21, tzinfo=timezone.utc).timestamp(),
            "author": "a",
            "score": 1,
            "body": body,
            "permalink": "https://www.reddit.com/c1",
        }
        self.assertEqual(_upsert_project(self.db, "week", first, parse_comment(body), catalog), 1)
        update = (
            "Title: openGym update — self-hosted gym tracker, now with notifications\n\n"
            "https://github.com/DuarteSantos8/openGym\n"
        )
        second = dict(first, id="c2", body=update)
        self.assertEqual(_upsert_project(self.db, "week", second, parse_comment(update), catalog), 0)
        rows = self.db.query(Project).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].name, "openGym")

    def test_repair_fixes_labels_and_merges_reposts(self):
        self.db.add(Thread(
            id="week",
            title="Week",
            week_label="2 Jul 2026",
            created_utc=datetime(2026, 7, 2),
            project_count=4,
        ))
        when = datetime(2026, 11, 5, 16, 55, 42)
        rows = [
            Project(
                comment_id="a", thread_id="week", created_utc=datetime(2026, 7, 21),
                name="Title", summary="If you tried it before.",
                body="Title: openGym update — self-hosted gym tracker\n\nhttps://github.com/DuarteSantos8/openGym\n",
                repo_url="https://github.com/DuarteSantos8/openGym",
                github_owner="DuarteSantos8", github_repo="openGym",
                stars=100, forks=2, github_status="done", github_pushed_at=when,
            ),
            Project(
                comment_id="b", thread_id="week", created_utc=datetime(2026, 7, 24),
                name="openGym", summary="openGym is a self-hosted workout tracker.",
                body="**Project Name:** openGym\n\nDescription: openGym is a self-hosted workout tracker.\n",
                repo_url="https://github.com/DuarteSantos8/openGym",
                github_owner="DuarteSantos8", github_repo="openGym",
                stars=100, forks=2, github_status="done", github_pushed_at=when,
            ),
            Project(
                comment_id="c", thread_id="week", created_utc=datetime(2026, 7, 5),
                name="EdgeEver", summary="EdgeEver is a self-hosted notes workspace.",
                body="Project Name: EdgeEver\n\nRepo: https://github.com/msh01/edgeever\n",
                repo_url="https://github.com/msh01/edgeever",
                github_owner="msh01", github_repo="edgeever",
                stars=50, forks=1, github_status="done", github_pushed_at=when,
            ),
            Project(
                comment_id="d", thread_id="week", created_utc=datetime(2026, 9, 13),
                name="EdgeEver", summary="An open-source, self-hosted notes workspace.",
                body="Project Name: EdgeEver\n\nRepo: https://github.com/tianma-if/edgeever\n",
                repo_url="https://github.com/tianma-if/edgeever",
                github_owner="tianma-if", github_repo="edgeever",
                stars=50, forks=1, github_status="done", github_pushed_at=when,
            ),
            Project(
                comment_id="e", thread_id="week", created_utc=datetime(2026, 8, 1),
                name="Atlas", summary="Atlas is a map.",
                body="Atlas\n\nhttps://github.com/one/atlas\n",
                repo_url="https://github.com/one/atlas",
                github_owner="one", github_repo="atlas",
                stars=3, forks=0, github_status="done", github_pushed_at=datetime(2026, 8, 1),
            ),
            Project(
                comment_id="f", thread_id="week", created_utc=datetime(2026, 8, 2),
                name="Atlas", summary="Atlas is a photo app.",
                body="Atlas\n\nhttps://github.com/two/atlas\n",
                repo_url="https://github.com/two/atlas",
                github_owner="two", github_repo="atlas",
                stars=9, forks=1, github_status="done", github_pushed_at=datetime(2026, 8, 2),
            ),
        ]
        self.db.add_all(rows)
        self.db.commit()
        renamed, removed = repair_catalog(self.db)
        self.assertGreaterEqual(renamed, 1)
        self.assertGreaterEqual(removed, 2)
        names = sorted(row.name for row in self.db.query(Project).all())
        self.assertEqual(names.count("openGym"), 1)
        self.assertEqual(names.count("EdgeEver"), 1)
        self.assertEqual(names.count("Atlas"), 2)
        self.assertNotIn("Title", names)

    def test_index_skips_generic_names(self):
        row = Project(comment_id="c", name="App", repo_url=None, github_owner=None, github_repo=None)
        index = ProjectIndex([row])
        self.assertIsNone(index.match({"name": "App", "repo_url": "", "github_owner": "", "github_repo": ""}, "other"))

    def test_next_daily(self):
        tz = timezone(timedelta(hours=-5))
        morning = datetime(2026, 11, 5, 6, 30, tzinfo=tz)
        self.assertEqual(next_daily(morning, 7, 0), datetime(2026, 11, 5, 7, 0, tzinfo=tz))
        later = datetime(2026, 11, 5, 7, 0, tzinfo=tz)
        self.assertEqual(next_daily(later, 7, 0), datetime(2026, 11, 6, 7, 0, tzinfo=tz))


if __name__ == "__main__":
    unittest.main()
