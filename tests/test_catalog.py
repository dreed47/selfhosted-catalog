"""Star and fork filters, and saved searches. No network."""
import os
import sys
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

os.environ["DATA_DIR"] = "/tmp/megathread-fav-test"
os.environ["DB_PATH"] = "/tmp/megathread-fav-test/data.db"
os.environ["RUN_ON_START"] = "0"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import IngestRun, Project, SessionLocal, Thread, init_db, engine, Base  # noqa: E402
from routes import _SORTS, _at_least, _clock, _favorites, _filter, refresh_stats, toggle_favorite  # noqa: E402


class CatalogTests(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        init_db()
        self.db = SessionLocal()
        now = datetime(2026, 10, 29)
        self.db.add(Thread(
            id="t1", title="Week", week_label="29 Oct 2026",
            permalink="", created_utc=now, status="complete",
        ))
        self.db.add_all([
            self._project("a", "Big", now, stars=100, forks=20),
            self._project("b", "Small", now, stars=2, forks=0),
            self._project("c", "Unknown", now, stars=None, forks=None),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _project(self, comment_id, name, when, stars, forks):
        return Project(
            comment_id=comment_id,
            thread_id="t1",
            author="someone",
            score=1,
            created_utc=when,
            name=name,
            summary=name,
            body=name,
            category="Other",
            stars=stars,
            forks=forks,
        )

    def names(self, query):
        return [row.name for row in query.all()]

    def test_at_least(self):
        self.assertEqual(_at_least(""), 0)
        self.assertEqual(_at_least("0"), 0)
        self.assertEqual(_at_least("-4"), 0)
        self.assertEqual(_at_least("no"), 0)
        self.assertEqual(_at_least("10"), 10)

    def test_floors_drop_missing_and_small(self):
        base = self.db.query(Project)
        self.assertEqual(self.names(_filter(base, "", "", None, None, 10, 0)), ["Big"])
        self.assertEqual(self.names(_filter(base, "", "", None, None, 0, 5)), ["Big"])
        self.assertEqual(
            set(self.names(_filter(base, "", "", None, None, 1, 0))),
            {"Big", "Small"},
        )

    def test_fork_sort_puts_unknown_last(self):
        rows = _filter(self.db.query(Project), "", "", None, None).order_by(
            _SORTS["forks"], Project.id.desc(),
        )
        self.assertEqual(self.names(rows), ["Big", "Small", "Unknown"])

    def test_favorite_toggles(self):
        self.assertIsNone(toggle_favorite(self.db, "nope", "AI"))
        self.assertIsNone(toggle_favorite(self.db, "search", "   "))
        self.assertTrue(toggle_favorite(self.db, "search", " natel "))
        self.assertFalse(toggle_favorite(self.db, "search", "natel"))
        self.assertTrue(toggle_favorite(self.db, "category", "AI"))
        searches, categories = _favorites(self.db)
        self.assertEqual(searches, [])
        self.assertEqual(categories, ["AI"])

    def test_clock_phrases(self):
        now = datetime(2026, 11, 5, 16, 0, tzinfo=ZoneInfo("America/New_York"))
        self.assertEqual(_clock(None, now), "Not yet")
        self.assertEqual(_clock(datetime(2026, 11, 5, 20, 44), now), "Today, 3:44 PM")
        self.assertEqual(_clock(datetime(2026, 11, 6, 12, 0), now), "Tomorrow, 7:00 AM")
        self.assertEqual(_clock(datetime(2026, 11, 9, 13, 0), now), "Mon 9 Nov, 8:00 AM")

    def test_refresh_stats_counts_and_last_run(self):
        self.db.add(IngestRun(
            started_at=datetime(2026, 11, 5, 20, 43),
            finished_at=datetime(2026, 11, 5, 20, 44),
            reason="startup",
            status="ok",
            projects_upserted=1,
            message="Added 1 new projects across 1 weeks. Main page added 0.",
        ))
        self.db.commit()
        stats = refresh_stats(self.db)
        self.assertEqual(stats["projects"], "3")
        self.assertEqual(stats["with_stars"], "2")
        self.assertEqual(stats["from_weeks"], "3")
        self.assertEqual(stats["from_feed"], "0")
        self.assertEqual(stats["weeks"], 1)
        self.assertEqual(stats["waiting"], "none waiting on GitHub")
        self.assertEqual(stats["last_note"], "Added 1 new projects across 1 weeks")
        self.assertIn("3:44 PM", stats["last_when"])
        self.assertFalse(stats["running"])
        if stats["soon_what"] == "Main page":
            self.assertEqual(stats["later_what"], "megathreads")
        else:
            self.assertEqual(stats["soon_what"], "Megathreads")
            self.assertEqual(stats["later_what"], "main page")


if __name__ == "__main__":
    unittest.main()
