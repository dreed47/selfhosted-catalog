"""Parser and schedule checks. No network."""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DATA_DIR", "/tmp/megathread-test")
os.environ.setdefault("DB_PATH", "/tmp/megathread-test/data.db")
os.environ.setdefault("RUN_ON_START", "0")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parse import parse_comment  # noqa: E402
from ingest import closed_threads  # noqa: E402
from scheduler import next_run  # noqa: E402


NATEL = """
**Project Name:** Natel, the contact editor your CardDAV server is missing

**Demo:** [https://demo.natel.app/contacts](https://demo.natel.app/contacts)
**Website Link:** [https://natel.app](https://natel.app)
**Code (MIT License):** [https://github.com/KewinDousse/natel](https://github.com/KewinDousse/natel)

**Description:** When I moved my contacts from Google to Radicale, I could no longer edit them in a browser. Radicale and Baïkal don't include a contact editor.

**Deployment:** one Docker container.
"""

PINCH = """
**Project Name:** Pinchtube
**Repo:** [https://github.com/CosmicThing2/PinchTub](https://github.com/CosmicThing2/PinchTube)e

**Description:** Host your own YouTube - Pinchflat + Pinchtube
**AI Involvement:** Claude wrote a lot of it.

Hello all, after many years of frustration with YouTube I decided to create my own replacement.
Pinchtube works alongside Pinchflat to display all your downloaded videos in a familiar interface.
"""

FOQB = """
FOQB: Free, Open Quality Bookkeeping

[https://github.com/parkfour/foqb.git](https://github.com/parkfour/foqb.git)

I got tired of subscription pricing, so I built FOQB. It runs our household books and our small LLC's finances.
"""

OCHA = """
**Project Name: OCHA**
**Repo/Website Link:** [**https://github.com/sekiro65/ocha**](https://github.com/sekiro65/ocha)

OCHA is built on Explo (https://github.com/LumePart/Explo). What I added is a Telegram music bot as a download source.
"""

PICTA = """
if ur still reading books without visualization in 2026, ur falling behind...

I built Picta using Magic Hour's API, which creates insane scenes for whatever you're reading. try it out at picta-jet.vercel.app, see how I built it at github.com/defAaron/picta
"""

SALES = """
**Project Name:** Sales Coach
Repo: github.com/Sales-Coach (https://github.com/Yz613/Sales-Coach) (MIT)

Sales Coach is a self-hosted place to practice sales calls.
"""

CATFLOPS = """
**Project Name:** Catflops
**Repo/Website Link:** [**https://github.com/robertziel/catflops\\_fleet**](https://github.com/robertziel/catflops_fleet)

Catflops is a self-hosted fleet tracker for the cats.
"""


YOUTUBE = """
If you keep YouTube channels in Plex, you know the poster situation is rough.

So I built YouTube Poster Creator. Paste a channel link and it gives you a movie-style poster.

Repo + docs: https://github.com/ramair02/youtube-poster-creator
"""

GRYFFI = """
**Project Name:** Gryffi (Community Edition)

**Description:**

I'm Erik, a Linux admin from the Netherlands. I ran Linux servers for years.

Gryffi turns manuals, policies and onboarding documents into short journeys: one small step per screen.

Try it at http://127.0.0.1 and https://get.gryffi.com
"""

PAGER = r"""
\*\*Project Name:\*\* PagerWho

\*\*Description:\*\*

PagerWho is an open-source, self-hosted incident response and on-call management platform.
"""


class ParseTests(unittest.TestCase):
    def test_natel_prefers_the_site_over_the_demo(self):
        parsed = parse_comment(NATEL)
        self.assertEqual(parsed["name"], "Natel")
        self.assertEqual(parsed["github_owner"], "KewinDousse")
        self.assertEqual(parsed["github_repo"], "natel")
        self.assertEqual(parsed["website_url"], "https://natel.app")
        self.assertIn("Radicale", parsed["summary"])
        self.assertFalse(parsed["summary"].lower().startswith("i "))

    def test_pinchtube_uses_the_real_repo_and_a_full_sentence(self):
        parsed = parse_comment(PINCH)
        self.assertEqual(parsed["github_repo"], "PinchTube")
        self.assertEqual(parsed["repo_url"], "https://github.com/CosmicThing2/PinchTube")
        self.assertIn("Pinchflat", parsed["summary"])
        self.assertGreaterEqual(len(parsed["summary"].split()), 8)

    def test_git_suffix_and_short_name(self):
        parsed = parse_comment(FOQB)
        self.assertEqual(parsed["name"], "FOQB")
        self.assertEqual(parsed["github_owner"], "parkfour")
        self.assertEqual(parsed["github_repo"], "foqb")
        self.assertFalse(parsed["repo_url"].endswith(".git"))

    def test_later_github_link_does_not_replace_the_project_repo(self):
        parsed = parse_comment(OCHA)
        self.assertEqual(parsed["name"], "OCHA")
        self.assertEqual((parsed["github_owner"], parsed["github_repo"]), ("sekiro65", "ocha"))

    def test_bare_github_and_built_name(self):
        parsed = parse_comment(PICTA)
        self.assertEqual(parsed["name"], "Picta")
        self.assertEqual(parsed["github_repo"], "picta")
        self.assertIn("picta-jet.vercel.app", parsed["website_url"])

    def test_parenthetical_repo_wins_over_a_short_slug(self):
        parsed = parse_comment(SALES)
        self.assertEqual(parsed["github_owner"], "Yz613")
        self.assertEqual(parsed["github_repo"], "Sales-Coach")

    def test_escaped_underscore_in_the_label(self):
        parsed = parse_comment(CATFLOPS)
        self.assertEqual(parsed["github_repo"], "catflops_fleet")
        self.assertNotIn("github.com", parsed["summary"])

    def test_multiword_name_from_i_built(self):
        parsed = parse_comment(YOUTUBE)
        self.assertEqual(parsed["name"], "YouTube Poster Creator")
        self.assertEqual(parsed["github_repo"], "youtube-poster-creator")

    def test_greeting_is_not_the_summary_and_localhost_is_not_the_site(self):
        parsed = parse_comment(GRYFFI)
        self.assertEqual(parsed["name"], "Gryffi (Community Edition)")
        self.assertTrue(parsed["summary"].startswith("Gryffi turns"))
        self.assertEqual(parsed["website_url"], "https://get.gryffi.com")

    def test_escaped_bold_markers_still_find_the_description(self):
        parsed = parse_comment(PAGER)
        self.assertEqual(parsed["name"], "PagerWho")
        self.assertIn("incident response", parsed["summary"])

    def test_title_label_is_not_the_project_name(self):
        parsed = parse_comment(
            "**Title:** Reverse Panels: a native iOS reader for your self-hosted comics\n\n"
            "Repo: https://github.com/josh-eg112/reverse-panels\n"
        )
        self.assertEqual(parsed["name"], "Reverse Panels")
        self.assertEqual(parsed["github_repo"], "reverse-panels")

    def test_project_name_on_the_next_line(self):
        parsed = parse_comment(
            "**Project Name:**\n\nWPL7 - Self-hosted WordPress powerhouse\n\n"
            "Repo: https://github.com/andyfo/wpl7\n\n"
            "Description: WPL7 is a free server app.\n"
        )
        self.assertEqual(parsed["name"], "WPL7")

    def test_heading_and_spanish_label(self):
        headed = parse_comment("# Project Name: Home-EM\n\nDescription: Home-EM is a household app.\n")
        self.assertEqual(headed["name"], "Home-EM")
        spanish = parse_comment(
            "Nombre del proyecto: AirLib\n\n"
            "Enlace a repo: https://github.com/camilokurk/AirLib\n\n"
            "Descripción: AirLib is a tool that turns photos of book pages into an EPUB.\n"
        )
        self.assertEqual(spanish["name"], "AirLib")

    def test_label_without_a_colon_and_a_glued_image(self):
        parsed = parse_comment(
            "[](https://preview.redd.it/x.png)**Project Name:** FilesNest\n\n"
            "Repo: https://github.com/moontechs/files-nest\n\n"
            "Description: FilesNest is a small macOS app that keeps local files in sync.\n"
        )
        self.assertEqual(parsed["name"], "FilesNest")
        plain = parse_comment("Project name OmniChat\n\nrepo: https://github.com/eyal-gor/p_107_omnichat\n")
        self.assertEqual(plain["name"], "OmniChat")

    def test_code_fence_and_a_later_project_link(self):
        parsed = parse_comment(
            "I used to rely on ngrok.\n\n"
            "Then I went through [awesome-tunneling](https://github.com/anderspitman/awesome-tunneling).\n\n"
            "So I made a self-hosted alternative to ngrok.\n\n"
            "```sh\n# or\nw share 8080\n```\n\n"
            "Here is the link: https://github.com/eznix86/w-share\n"
        )
        self.assertEqual(parsed["name"], "w-share")
        self.assertEqual(parsed["github_repo"], "w-share")


class ScheduleTests(unittest.TestCase):
    def test_closed_threads_leave_a_fresh_week_alone(self):
        now = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
        posts = [
            {"id": "new", "created_utc": (now - timedelta(days=1)).timestamp()},
            {"id": "old", "created_utc": (now - timedelta(days=8)).timestamp()},
        ]
        self.assertEqual([p["id"] for p in closed_threads(posts, now=now)], ["old"])
        self.assertEqual(
            [p["id"] for p in closed_threads(posts, include_current=True, now=now)],
            ["new", "old"],
        )

    def test_a_stale_newest_thread_is_closed(self):
        now = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)
        posts = [{"id": "only", "created_utc": (now - timedelta(days=7)).timestamp()}]
        self.assertEqual([p["id"] for p in closed_threads(posts, now=now)], ["only"])

    def test_next_monday_morning(self):
        tz = timezone(timedelta(hours=-5))
        wednesday = datetime(2026, 11, 4, 15, tzinfo=tz)
        nxt = next_run(wednesday, 0, 8, 0)
        self.assertEqual(nxt.weekday(), 0)
        self.assertEqual((nxt.hour, nxt.minute), (8, 0))
        self.assertGreater(nxt, wednesday)

        monday_after = datetime(2026, 11, 2, 9, tzinfo=tz)
        nxt = next_run(monday_after, 0, 8, 0)
        self.assertEqual(nxt.date(), datetime(2026, 11, 9, tzinfo=tz).date())

        monday_before = datetime(2026, 11, 2, 7, tzinfo=tz)
        nxt = next_run(monday_before, 0, 8, 0)
        self.assertEqual(nxt.date(), monday_before.date())


if __name__ == "__main__":
    unittest.main()
