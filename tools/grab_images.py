#!/usr/bin/env python3
"""Grab the images of a Wowhead news article and SELF-HOST them on our GitHub.

- og:image (hero) + content images from the article body (zamimg/media.wowhead)
- downloads into data/news-img/<id>/  (build_site copies them to
  docs/assets/news/<id>/ so they are served from pvwvuow.github.io/wowheadFA)
- writes art["images"] = [{"src": <our URL>, "cap": ""}, ...] and
  art["thumb"] = <our URL of the hero>

Never raises: image failure must not break the news fetch pipeline.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import urllib.request

IMG_DIR = os.path.join(ROOT, "data", "news-img")
BASE = "https://pvwvuow.github.io/wowheadFA/assets/news"
MAX_IMAGES = 6
MIN_BYTES = 4000  # skip icons/sprites
JUNK = re.compile(r"favicon|/logo|sprite|avatar|/icons/(small|medium)/|\.css|\.js",
                  re.I)


UA = "wowheadFA-bot/1.0 (+https://wowfarsi.ir; news image mirror)"


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last_err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read()
        except Exception as e:
            last_err = e
    raise last_err


def _candidate_images(page_html: str):
    urls = []
    m = re.search(r'property=["\']og:image["\'] content="([^"]+)"', page_html)
    if m:
        urls.append(m.group(1))
    # content images inside the article body
    for c in re.findall(r'<article[^>]*>(.*?)</article>', page_html,
                        flags=re.S | re.I):
        urls += re.findall(r'(https://(?:media\.wowhead\.com|wow\.zamimg\.com)'
                           r'[^"\s\']+?\.(?:jpg|jpeg|png|webp))', c, flags=re.I)
    out = []
    for u in urls:
        u = u.replace("&amp;", "&")
        if JUNK.search(u) or u.startswith("data:"):
            continue
        if u not in out:
            out.append(u)
    return out[:MAX_IMAGES]


def grab(art: dict) -> dict:
    """Fetch page images for one article dict; mutates and returns it."""
    try:
        url = art.get("url") or ""
        aid = int(art["id"])
        html = _fetch(url).decode("utf-8", "replace")
        cands = _candidate_images(html)
        if not cands:
            return art
        outdir = os.path.join(IMG_DIR, str(aid))
        os.makedirs(outdir, exist_ok=True)
        images = []
        for i, u in enumerate(cands, 1):
            ext = ".jpg"
            m = re.search(r"\.(jpe?g|png|webp)(?:[?#].*)?$", u, re.I)
            if m:
                ext = "." + {"jpeg": "jpg"}.get(m.group(1).lower(),
                                                m.group(1).lower())
            raw = _fetch(u)
            if len(raw) < MIN_BYTES:
                continue
            fn = f"{i}{ext}"
            with open(os.path.join(outdir, fn), "wb") as fh:
                fh.write(raw)
            images.append({"src": f"{BASE}/{aid}/{fn}", "cap": ""})
        if images:
            art["images"] = images
            art["thumb"] = images[0]["src"]
            print(f"+ images: {len(images)} for {aid}")
    except Exception as e:  # never break the pipeline
        print(f"[warn] grab_images({art.get('id')}): {e}", file=sys.stderr)
    return art


def main():
    # standalone: (re)grab images for articles that have none
    import glob
    n = 0
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "articles", "*.json"))):
        art = json.load(open(f, encoding="utf-8"))
        if art.get("images"):
            continue
        before = art.get("thumb")
        grab(art)
        if art.get("thumb") != before:
            json.dump(art, open(f, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            n += 1
    print(f"grab_images done: {n} article(s) updated")


if __name__ == "__main__":
    sys.exit(main())
