#!/usr/bin/env python3
"""seo_ping.py - after docs/ is pushed, tell search engines what changed.

Google (one-time setup: see SEO_SETUP_FA.md):
  * GSC_SA_JSON (secret) - service-account JSON key. We refresh one OAuth
    token (webmasters + indexing scopes) and then
      - submit sitemap.xml + news-sitemap.xml to the Search Console API
        for every property listed in GSC_SITES (comma-separated base
        URLs, default: our own BASE + "/")
      - best-effort Indexing API urlNotifications:publish for up to 10
        changed URLs per run. NOTE: Google officially supports the
        Indexing API only for pages with JobPosting/BroadcastEvent
        structured data and may silently ignore others; sitemaps +
        internal links remain the reliable, fully-supported path.
Bing / Yandex / Seznam (IndexNow - official for ALL content types):
  * INDEXNOW_KEY (secret). build_site.py writes docs/<key>.txt when the
    INDEXNOW_KEY env is set at build time. Our site lives in a
    subdirectory of pvwvuow.github.io, so requests carry keyLocation
    pointing at that file (allowed by the IndexNow protocol).
State: data/seo_state.json {url: {h, ts}} - a URL is submitted only when
its content hash changed AND it was last submitted > MIN_INTERVAL ago,
so the 20-minute pipeline never spams the engines.
Never raises on network/API errors; always exits 0 (build must pass).
ASCII-only source.
"""
import glob
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONF = json.load(open(os.path.join(ROOT, "config", "site.json"),
                      encoding="utf-8"))
BASE = CONF["base_url"].rstrip("/")
HOST = urllib.parse.urlparse(BASE).netloc
STATE = os.path.join(ROOT, "data", "seo_state.json")

MIN_INTERVAL = 3600          # seconds between submissions of one URL
MAX_INDEXNOW = 60            # URLs per IndexNow batch (protocol cap 10k)
MAX_GINDEX = 10              # Indexing API notifications per run
SCOPES = ["https://www.googleapis.com/auth/webmasters",
          "https://www.googleapis.com/auth/indexing"]


def log(msg):
    print(f"seo: {msg}", flush=True)


def _h(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:12]


def item_slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or ("item-" + hashlib.md5(name.encode("utf-8")).hexdigest()[:8])


def load_pub():
    arts = []
    for f in glob.glob(os.path.join(ROOT, "data", "articles", "*.json")):
        try:
            a = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if a.get("status") == "published":
            arts.append(a)
    arts.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    return arts


def targets():
    """[(url, content_hash)] - every URL we keep indexed."""
    arts = load_pub()
    out = [(BASE + "/", _h(json.dumps(
        [(a["id"], a["article_fa"].get("title_fa", "")) for a in arts[:20]])))]
    item_urls = {}
    for a in arts:
        slug = f"{a['id']}-{a['slug']}"
        u = f"{BASE}/article/{slug}.html"
        h = _h(json.dumps({"t": a["article_fa"].get("title_fa", ""),
                           "l": a["article_fa"].get("lead_fa", ""),
                           "b": len(a["article_fa"].get("body_fa") or []),
                           "i": a.get("items") or []}, sort_keys=True,
                          ensure_ascii=False))
        out.append((u, h))
        for blk in a.get("items") or []:
            it = (blk or {}).get("item") or {}
            name = str(it.get("name") or "").strip()
            if not name:
                continue
            iu = f"{BASE}/item/{item_slug(name)}.html"
            item_urls.setdefault(iu, []).append(
                [name, it.get("quality", ""), it.get("rows") or [],
                 it.get("spec") or [], a["id"]])
    out.append((BASE + "/items.html", _h(json.dumps(sorted(item_urls)))))
    for iu, vals in item_urls.items():
        out.append((iu, _h(json.dumps(vals, sort_keys=True,
                                      ensure_ascii=False))))
    return out


# ---------------------------------------------------------------- google
def google_token(sa_json):
    try:
        from google.oauth2 import service_account
        from google.auth.transport import requests as greq
    except Exception as e:
        log(f"google-auth unavailable ({e}) - run: pip install google-auth")
        return None
    try:
        creds = service_account.Credentials.from_service_account_info(
            json.loads(sa_json), scopes=SCOPES)
        creds.refresh(greq.Request())
        return creds.token
    except Exception as e:
        log(f"GSC token refresh failed: {e}")
        return None


def _req(url, data=None, headers=None, method="POST"):
    req = urllib.request.Request(url, data=data, headers=headers or {},
                                 method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]
    except Exception as e:
        return 0, str(e)[:300]


def gsc_sitemaps(token, sites):
    ok = 0
    for site in sites:
        for sm in ("sitemap.xml", "news-sitemap.xml"):
            feed = site.rstrip("/") + "/" + sm
            u = ("https://www.googleapis.com/webmasters/v3/sites/"
                 + urllib.parse.quote(site, safe="")
                 + "/sitemaps/" + urllib.parse.quote(feed, safe=""))
            code, body = _req(u, data=b"", method="PUT", headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json"})
            if code in (200, 201, 204):
                ok += 1
                log(f"GSC sitemap submitted: {feed} -> property {site}")
            else:
                log(f"GSC sitemap {feed} -> {site}: HTTP {code} {body[:160]}")
    return ok


def indexing_publish(token, urls):
    ok = 0
    for u in urls:
        data = json.dumps({"url": u, "type": "URL_UPDATED"}).encode("utf-8")
        code, body = _req(
            "https://indexing.googleapis.com/v3/urlNotifications:publish",
            data=data, headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json"})
        if code in (200, 201):
            ok += 1
        else:
            log(f"indexing api {u}: HTTP {code} {body[:160]}")
    return ok


# --------------------------------------------------------------- indexnow
def indexnow(key, urls):
    data = json.dumps({"host": HOST, "key": key,
                       "keyLocation": f"{BASE}/{key}.txt",
                       "urlList": urls}).encode("utf-8")
    code, body = _req("https://api.indexnow.org/indexnow", data=data,
                      headers={"Content-Type":
                               "application/json; charset=utf-8"})
    if code in (200, 202):
        log(f"IndexNow accepted {len(urls)} URLs (HTTP {code})")
        return urls
    log(f"IndexNow: HTTP {code} {body[:200]}")
    return []


# ------------------------------------------------------------------ main
def main():
    sa = os.environ.get("GSC_SA_JSON", "").strip()
    key = os.environ.get("INDEXNOW_KEY", "").strip()
    if not sa and not key:
        log("no GSC_SA_JSON / INDEXNOW_KEY configured - nothing to do "
            "(one-time setup: SEO_SETUP_FA.md)")
        return 0

    tg = targets()
    cur = {u for u, _ in tg}
    try:
        state = json.load(open(STATE, encoding="utf-8"))
    except Exception:
        state = {}
    now = int(time.time())

    todo = []
    for u, h in tg:
        st = state.get(u) or {}
        if st.get("h") == h:
            continue
        if now - int(st.get("ts") or 0) < MIN_INTERVAL:
            continue
        todo.append((u, h))
    log(f"{len(todo)} changed URL(s) of {len(tg)} to submit")
    if not todo:
        return 0
    urls = [u for u, _ in todo][:MAX_INDEXNOW]

    done = set()
    if key:
        done.update(indexnow(key, urls))
    if sa:
        tok = google_token(sa)
        if tok:
            sites = [s.strip() for s in
                     os.environ.get("GSC_SITES", BASE + "/").split(",")
                     if s.strip()]
            gsc_sitemaps(tok, sites)
            n = indexing_publish(tok, urls[:MAX_GINDEX])
            log(f"Indexing API notified {n}/{min(len(urls), MAX_GINDEX)} "
                "URL(s)")
            # attempt-once semantics: quota-limited API rejections are
            # not retried forever; sitemap submission already covers
            # discovery for everything we skipped.
            done.update(urls[:MAX_GINDEX])

    state = {u: v for u, v in state.items()
             if u in cur and now - int((v or {}).get("ts") or 0)
             < 90 * 86400}
    for u, h in todo:
        if u in done:
            state[u] = {"h": h, "ts": now}
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1)
    log(f"state saved: {len(state)} url(s), {len(done)} submitted this run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
