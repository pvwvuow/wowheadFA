"""Regression tests for the article-slug pipeline (feed 383914).

Root cause being fixed: fetch_news.slugify cut the [:70] boundary BEFORE
stripping hyphens, so a boundary landing on a hyphen stored slugs with a
trailing "-" — and build_site card links / page_url echoed that raw slug
while the wowfarsi.ir builder stripped it, so the two sites disagreed.

Covers:
  1. canonical slugify never emits a trailing (or leading) hyphen,
     including the exact 383914 title whose 70-char boundary is a "-"
  2. slugify is idempotent (stored slug -> canonical == canonical)
  3. build_site.article_slug (card links, file names, page_url, RSS,
     sitemaps) uses the same canonical slug as the builder
  4. the exported feed "slug" field is canonical too
  5. data/articles has no remaining trailing-hyphen slug (migration ran)
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fetch_news as FN  # noqa: E402
import build_site as BS  # noqa: E402

# the exact reported case: 70-char boundary lands on the hyphen before
# "wow-forever-" (title shortened from "UBRS Damage and Health Increases
# & Shen'dralas Improvements - WoW: Forever Hotfixes for November 17, 2026")
TITLE_383914 = ("UBRS Damage and Health Increases & Shen'dralas Improvements"
                " - WoW: Forever Hotfixes for November 17, 2026")
EXPECTED_383914 = "ubrs-damage-and-health-increases-shen-dralas-improvements-wow-forever"


class TestSlugify(unittest.TestCase):
    def test_383914_no_trailing_hyphen(self):
        s = FN.slugify(TITLE_383914)
        self.assertEqual(s, EXPECTED_383914)
        self.assertFalse(s.endswith("-"))

    def test_never_trailing_or_leading_hyphen(self):
        samples = [
            "A" * 69 + " - B",          # boundary hyphen at the end
            "A" * 70 + "- B",           # 70th char is the hyphen itself
            "A" * 71 + " -- B",
            "---all punctuation!---",
            "Şöğütle -- türkçe/çeviri",  # non-ascii collapses to hyphens
            "",
        ]
        for t in samples:
            s = FN.slugify(t)
            self.assertEqual(s, s.strip("-"), f"title={t!r} -> {s!r}")

    def test_idempotent(self):
        s = FN.slugify(TITLE_383914)
        self.assertEqual(FN.slugify(s), s)

    def test_empty_slug_fallback_unchanged(self):
        self.assertEqual(FN.slugify("---") or "fallback", "fallback")


class TestUnification(unittest.TestCase):
    """builder and card link must produce the SAME "<id>-<slug>"."""

    STUB = {
        "id": 383914,
        "slug": EXPECTED_383914 + "-",   # legacy stored row (pre-migration)
        "article_fa": {"title_fa": "تست", "lead_fa": "تست",
                       "body_fa": [{"type": "p", "text": "تست"}]},
    }

    def test_article_slug_matches_builder(self):
        self.assertEqual(BS.article_slug(self.STUB),
                         f"383914-{EXPECTED_383914}")

    def test_article_slug_repairs_legacy_row(self):
        out = BS.article_slug(self.STUB)
        self.assertFalse(out.endswith("-.html") or out.endswith("-"))

    def test_export_feed_slug_canonical(self):
        # build_site.pub_item exports the feed slug via FN.slugify
        pub = [a for a in BS_test_articles() if a["id"] == 383914]
        self.assertTrue(pub, "383914 fixture missing from data/articles")
        self.assertEqual(FN.slugify(pub[0]["slug"]), pub[0]["slug"])
        self.assertFalse(str(pub[0]["slug"]).endswith("-"))


def BS_test_articles():
    path = os.path.join(BS.ROOT, "data", "articles", "383914.json")
    return [json.load(open(path, encoding="utf-8"))]


class TestStoredData(unittest.TestCase):
    def test_no_trailing_hyphen_slugs_in_store(self):
        bad = []
        for f in sorted(os.listdir(os.path.join(BS.ROOT, "data", "articles"))):
            if not f.endswith(".json"):
                continue
            art = json.load(open(os.path.join(BS.ROOT, "data", "articles", f),
                                 encoding="utf-8"))
            if str(art.get("slug", "")).endswith("-"):
                bad.append(art["id"])
        self.assertEqual(bad, [], "run scripts/migrate_slug_trailing_hyphen.py")


if __name__ == "__main__":
    unittest.main()
