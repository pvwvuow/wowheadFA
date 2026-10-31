#!/usr/bin/env python3
"""Backfill the ORIGINAL Wowhead publish date into published articles.

Why (owner report 2026-10-31): auto_publish used to stamp published_at
with the bot's own publish time, so a Wowhead story from 3 days ago
appeared as "today's news" on the site and in the Discord embed.

This tool finds the corrupted records and repairs them from the source:

  corrupted = published_at >= fetched_at      (published before we even
                                               fetched it - impossible for
                                               the real date)
            or |published_at - generator.written_at| < 5 minutes

For every corrupted article it downloads the Wowhead page and reads the
JSON-LD "datePublished" (the og: article:published_time meta is not
present on Wowhead). Never raises: a page that fails stays untouched and
is reported, so the pipeline never breaks over branding... er, dating.

Usage:
    python tools/backfill_dates.py            # repair all (1.2s delay)
    python tools/backfill_dates.py --dry-run  # only report
    python tools/backfill_dates.py --id 383634
"""
import argparse
import glob
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "data", "articles")
UA = "wowheadFA-bot/1.0 (+https://wowfarsi.ir; news date backfill)"
MIN_GAP_S = 300          # |published_at - written_at| smaller than this -> corrupted


def _parse_iso(s):
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def is_corrupted(art):
    """True when published_at is the bot's stamp instead of Wowhead's date."""
    pub = art.get("published_at") or ""
    fetched = art.get("fetched_at") or ""
    written = (art.get("generator") or {}).get("written_at") or ""
    try:
        if fetched and pub >= fetched:
            return True
    except Exception:
        pass
    try:
        if written and pub and abs((_parse_iso(pub) - _parse_iso(written)).total_seconds()) < MIN_GAP_S:
            return True
    except Exception:
        pass
    return False


def wowhead_date(aid):
    """Original datePublished from the Wowhead page (ISO, UTC) or None."""
    url = f"https://www.wowhead.com/news={aid}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    html = urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "replace")
    m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', html)
    if not m:
        return None
    try:
        dt = datetime.fromisoformat(m.group(1))          # e.g. 2026-10-29T09:00:00-05:00
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--id", type=int, default=None,
                    help="فقط همین خبر (حتی اگر corrupted نباشد)")
    ap.add_argument("--delay", type=float, default=1.2)
    args = ap.parse_args()

    files = [os.path.join(ART, f"{args.id}.json")] if args.id else \
        sorted(glob.glob(os.path.join(ART, "*.json")))
    n_ok = n_fixed = n_fail = 0
    for f in files:
        try:
            art = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if art.get("status") != "published":
            continue
        if args.id is None and not is_corrupted(art):
            n_ok += 1
            continue
        aid = art["id"]
        try:
            real = wowhead_date(aid)
        except Exception as e:
            print(f"  !! {aid}: fetch failed ({type(e).__name__}: {str(e)[:60]})")
            n_fail += 1
            time.sleep(args.delay)
            continue
        if not real:
            print(f"  !! {aid}: datePublished در صفحهٔ واوهد پیدا نشد")
            n_fail += 1
            time.sleep(args.delay)
            continue
        old = art.get("published_at")
        print(f"  {aid}: {old}  →  {real}")
        if not args.dry_run and real != old:
            art["published_at"] = real
            json.dump(art, open(f, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            n_fixed += 1
        time.sleep(args.delay)
    mode = "dry-run" if args.dry_run else "FIXED"
    print(f"backfill [{mode}]: {n_ok} سالم | {n_fixed} اصلاح شد | {n_fail} ناموفق")
    return 0


if __name__ == "__main__":
    sys.exit(main())
