#!/usr/bin/env python3
"""
migrate_slug_trailing_hyphen.py - one-shot data migration for the slug
root-cause fix (branch fix/slug-trailing-hyphen-383914).

fetch_news.slugify used to cut the [:70] boundary BEFORE stripping
hyphens, so titles whose 70-char boundary lands on a hyphen stored slugs
with a trailing "-" (11 rows, e.g. 383914
"ubrs-damage-and-health-increases-shen-dralas-improvements-wow-forever-").
The builder now strips after the cut; this migration re-slugifies every
stored article so data/articles, docs/news.json (page_url) and the site
cards agree on one canonical slug.

Run AFTER updating tools/ (fetch_news.py / build_site.py), BEFORE the
next site build:
    python scripts/migrate_slug_trailing_hyphen.py
    python tools/qa_check.py --all
    python tools/build_site.py          # rebuilds docs/ (renames files)

Idempotent: rows already canonical are left untouched.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))
import fetch_news as FN  # noqa: E402

ART = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "data", "articles")


def main():
    changed = []
    for f in sorted(os.listdir(ART)):
        if not f.endswith(".json"):
            continue
        path = os.path.join(ART, f)
        art = json.load(open(path, encoding="utf-8"))
        old = str(art.get("slug") or "")
        new = FN.slugify(old)
        if not old or old == new:
            continue
        art["slug"] = new
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(art, fh, ensure_ascii=False, indent=1)
        changed.append((art.get("id"), old, new))
    for id_, old, new in changed:
        print(f"{id_}: '{old}' -> '{new}'")
    print(f"migrated {len(changed)} article(s)")


if __name__ == "__main__":
    main()
