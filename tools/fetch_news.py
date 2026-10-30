#!/usr/bin/env python3
"""
fetch_news.py - poll Wowhead news RSS, store new items as article JSONs.

Each item -> data/articles/<id>.json with:
  id, slug, url, title_en, category, published_at, fetched_at,
  source_mode ("full" if content:encoded yielded text, else "summary"),
  qa_facts {numbers, entities, chars} - non-copyrightable FACTS only
  (salient numbers + English token list) used later by qa_check G4/G5,
  status: "new"

COPYRIGHT: the full English source text is NEVER written to disk or git.
It lives only in process memory for the duration of one pipeline run
(rewrite -> QA -> publish). qa_facts are uncopyrightable facts
(numbers, proper-noun tokens, char counts), safe to publish.

Idempotent: existing ids are skipped.

Single ingest (metadata + qa_facts only, text discarded):
  python tools/fetch_news.py --url https://www.wowhead.com/news=383566
  (tries direct fetch, then r.jina.ai, then allorigins - also imported
   by write_article/publish_from_issue, which keep the text in memory
   only)

stdlib only. Run on a schedule (GitHub Actions cron) or locally.
"""
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

FEED = "https://www.wowhead.com/news/rss/all"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "articles")


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last_err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read()
        except Exception as e:  # Cloudflare blips happen - retry
            last_err = e
            print(f"  retry {attempt + 1}: {e}", file=sys.stderr)
    raise last_err


def strip_html(raw: str) -> list:
    """content:encoded -> list of plain-text paragraphs."""
    raw = re.sub(r"<script.*?</script>", "", raw, flags=re.S | re.I)
    raw = re.sub(r"<style.*?</style>", "", raw, flags=re.S | re.I)
    # paragraph-ish block boundaries
    raw = re.sub(r"(?i)<(br|/p|/div|/li|/h[1-6])[^>]*>", "\n", raw)
    txt = re.sub(r"<[^>]+>", " ", raw)
    txt = html.unescape(txt)
    paras = []
    for p in re.split(r"\n+", txt):
        p = re.sub(r"\s+", " ", p).strip()
        # drop boilerplate / nav leftovers
        if len(p) < 40:
            continue
        if re.match(r"^(related|tweet|load|follow us|was this|quadrant|"
                    r"live PTR|classic\)|the wowhead client)", p, re.I):
            continue
        paras.append(p)
    return paras


def numbers_of(text: str) -> set:
    out = set()
    for m in re.finditer(r"\d[\d.,:%]*\d|\d", text):
        s = m.group(0).strip(".,")
        if len(s) >= 2:
            out.add(s)
    return out


def english_tokens(text: str) -> set:
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    return {t.lower().strip(".,:;!?()[]{}\"'") for t in re.findall(
        r"[A-Za-z][A-Za-z+.'-]*", text)}


def make_qa_facts(text: str, title_en: str = "") -> dict:
    """Extract non-copyrightable FACTS from source text for later QA.

    numbers  - salient numbers: appear in title, appear >=2x, or are
               decimal/percent numbers (mirrors the old G4 salient rule)
    entities - unique lowercase English tokens (word list, not prose)
    chars    - source length, for sanity checks
    """
    nums = numbers_of(text)
    if len(text) < 1500:                      # short source: keep all
        salient = nums
    else:
        salient = {n for n in nums
                   if n in (title_en or "")
                   or text.count(n) >= 2
                   or "." in n or "%" in n}
    return {
        "numbers": sorted(salient),
        "entities": sorted(t for t in english_tokens(text) if t),
        "chars": len(text),
    }


def slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return re.sub(r"-{2,}", "-", s)[:70]


def parse_item(it) -> dict | None:
    def txt(tag, default=""):
        el = it.find(tag)
        return (el.text or default).strip() if el is not None else default

    guid = txt("guid") or txt("link")
    m = re.search(r"news=(\d+)", guid) or re.search(r"/news/.*?-(\d+)", guid)
    if not m:
        return None
    link = txt("link")
    m2 = re.search(r"/news=(\d+)", link)
    if m2:  # canonicalise weird "news=ID/slug" links
        link = f"https://www.wowhead.com/news={m2.group(1)}"
    cat = txt("category", "News")
    full = ""
    enc = it.find("{http://purl.org/rss/1.0/modules/content/}encoded")
    if enc is not None and enc.text:
        full = "\n\n".join(strip_html(enc.text))
    paras = full.split("\n\n") if full else strip_html(txt("description"))
    pub = txt("pubDate")
    try:
        published = parsedate_to_datetime(pub).astimezone(timezone.utc) \
            .strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        published = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    text = "\n\n".join(paras)
    art = {
        "id": int(m.group(1)),
        "slug": slugify(txt("title")),
        "url": link,
        "title_en": txt("title"),
        "category": cat,
        "published_at": published,
        "fetched_at": datetime.now(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_mode": "full" if full else "summary",
        "qa_facts": make_qa_facts(text, txt("title")),
        "status": "new",
    }
    try:
        import grab_images
        grab_images.grab(art)  # self-host article images on our GitHub
    except Exception:
        pass
    return art


def url_to_id(url: str):
    m = re.search(r"[?&]news=(\d+)", url) or \
        re.search(r"/news(?:/[^?]*?)-(\d+)(?:[/?#]|$)", url) or \
        re.search(r"/news=(\d+)", url)
    return int(m.group(1)) if m else None


def extract_from_html(page_html: str):
    """Adaptive article-body extraction from a Wowhead article page.
    Returns (title, text) or (None, None)."""
    title = None
    m = re.search(r'property=["\']og:title["\'] content="([^"]+)"', page_html)
    if not m:
        m = re.search(r"<title>([^<]+)</title>", page_html)
    if m:
        title = html.unescape(m.group(1)).strip()
        title = re.sub(r"\s*-\s*Wowhead News\s*$", "", title, flags=re.I)
        title = re.sub(r"\s*-\s*Wowhead\s*$", "", title, flags=re.I)

    # candidate containers, most specific first
    candidates = re.findall(
        r'<article[^>]*class="[^"]*(?:news|article)[^"]*"[^>]*>(.*?)</article>',
        page_html, flags=re.S | re.I)
    m = re.search(r'<div[^>]*class="[^"]*news-article-body[^"]*"[^>]*>'
                  r"(.*?)</div>\s*<div", page_html, flags=re.S | re.I)
    if m:
        candidates.append(m.group(1))
    m = re.search(r"<article[^>]*>(.*?)</article>", page_html, flags=re.S | re.I)
    if m:
        candidates.append(m.group(1))
    m = re.search(r"<main[^>]*>(.*?)</main>", page_html, flags=re.S | re.I)
    if m:
        candidates.append(m.group(1))
    candidates.append(page_html)  # last resort: whole page

    best, best_score = None, 0
    for c in candidates:
        paras = strip_html(c)
        score = sum(len(p) for p in paras)
        if score > best_score:
            best, best_score = paras, score
    if not best or best_score < 400:
        return (title, None)
    return (title, "\n\n".join(best))


def extract_from_markdown(md: str):
    """r.jina.ai returns markdown - keep prose lines, drop links/images."""
    lines = []
    for ln in md.splitlines():
        ln = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", ln)
        ln = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", ln)
        ln = re.sub(r"^#{1,6}\s*", "", ln)
        ln = ln.strip()
        if len(ln) >= 40 and not re.match(
                r"^(related|tweet|load|follow us|was this|quadrant)", ln, re.I):
            lines.append(ln)
    return "\n\n".join(lines)


def ingest_url(url: str):
    """Fetch one Wowhead news article page; returns (title, text, mode)."""
    attempts = [
        ("direct", lambda: fetch(url).decode("utf-8", "replace")),
        ("jina", lambda: fetch("https://r.jina.ai/" + url)
            .decode("utf-8", "replace")),
        ("allorigins", lambda: fetch(
            "https://api.allorigins.win/raw?url=" + urllib.parse.quote(url,
                                                                     safe=""))
            .decode("utf-8", "replace")),
    ]
    errs = []
    for name, fn in attempts:
        try:
            raw = fn()
            if name == "jina":
                text = extract_from_markdown(raw)
                title = None
                m = re.search(r"^Title:\s*(.+)$", raw, flags=re.M)
                if m:
                    title = m.group(1).strip()
            else:
                title, text = extract_from_html(raw)
            if text and len(text) >= 400:
                print(f"  ingest via {name}: {len(text)} chars", file=sys.stderr)
                return title, text, ("full" if len(text) >= 1500 else "summary")
            errs.append(f"{name}: too short/empty")
        except Exception as e:
            errs.append(f"{name}: {e}")
    print("  ingest failed: " + "; ".join(errs), file=sys.stderr)
    return None, None, None


def ingest_url_cli(url: str) -> int:
    art_id = url_to_id(url)
    if not art_id:
        print(f"cannot parse a news id out of: {url}", file=sys.stderr)
        return 2
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{art_id}.json")
    if os.path.exists(path):
        print(f"{art_id}.json already exists - nothing to do")
        return 0
    title, text, mode = ingest_url(url)
    art = {
        "id": art_id,
        "slug": slugify(title or "") or f"news-{art_id}",
        "url": url if url.startswith("http") else \
            f"https://www.wowhead.com/news={art_id}",
        "title_en": title or f"Wowhead news {art_id}",
        "category": "News",
        "published_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_mode": mode or "summary",
        "qa_facts": make_qa_facts(text or "", title or ""),
        "status": "new",
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(art, fh, ensure_ascii=False, indent=1)
    print(f"+ {art_id}.json [{art['source_mode']}] {art['title_en'][:60]} "
          f"({art['qa_facts']['chars']} ch, {len(art['qa_facts']['numbers'])} nums, "
          f"{len(art['qa_facts']['entities'])} tokens)")
    return 0


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--url":
        sys.exit(ingest_url_cli(sys.argv[2]))
    os.makedirs(OUT, exist_ok=True)
    xml = fetch(FEED)
    items = ET.fromstring(xml).findall(".//item")
    added = skipped = 0
    for it in items:
        art = parse_item(it)
        if not art:
            continue
        path = os.path.join(OUT, f"{art['id']}.json")
        if os.path.exists(path):
            skipped += 1
            continue
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(art, fh, ensure_ascii=False, indent=1)
        added += 1
        print(f"+ {art['id']} [{art['status']}] {art['title_en'][:60]} "
              f"({art['source_mode']}, {art['qa_facts']['chars']} ch)")
    print(f"fetch done: {added} new, {skipped} known, "
          f"{len(items)} in feed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
