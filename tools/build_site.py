#!/usr/bin/env python3
"""
build_site.py - generate the static Persian site into docs/ (GitHub Pages).

Pages served from main branch /docs folder:
  docs/index.html            latest news list
  docs/article/<id>-<slug>.html
  docs/feed.xml              our own RSS
  docs/sitemap.xml, robots.txt
  docs/assets/style.css, Vazirmatn.woff2

All published articles (status=published) get pages; drafts are listed
only for maintainers (not linked, excluded from sitemap).
"""
import html
import json
import os
import shutil
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "data", "articles")
DOCS = os.path.join(ROOT, "docs")
SITE_CONF = os.path.join(ROOT, "config", "site.json")
FONT_SRC = os.path.join(ROOT, "assets", "Vazirmatn.ttf")

CONF = json.load(open(SITE_CONF, encoding="utf-8"))
BASE = CONF["base_url"].rstrip("/")
TITLE = CONF["title"]
DESC = CONF["description"]
DISCLAIMER = CONF["disclaimer"]
CONTACT = CONF["contact"]

CSS = """:root{--bg:#0d1117;--bg2:#161b22;--bd:#30363d;--fg:#e6edf3;--mut:#8b949e;--ac:#d2a8ff;--gold:#e3b341}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font-family:Vazirmatn,Tahoma,sans-serif;line-height:2;direction:rtl}
a{color:var(--ac);text-decoration:none}a:hover{text-decoration:underline}
header.site{background:var(--bg2);border-bottom:1px solid var(--bd);padding:1rem 1.2rem;display:flex;align-items:center;gap:1rem;flex-wrap:wrap}
header.site .logo{font-size:1.5rem;font-weight:800;color:var(--gold)}
header.site .logo small{color:var(--mut);font-weight:400;font-size:.8rem;display:block}
main{max-width:52rem;margin:0 auto;padding:1.2rem}
.card{background:var(--bg2);border:1px solid var(--bd);border-radius:10px;padding:1rem 1.2rem;margin:1rem 0}
.card h2{margin:.1rem 0 .3rem;font-size:1.15rem}
.card h2 a{color:var(--fg)}
.meta{color:var(--mut);font-size:.85rem;display:flex;gap:1rem;flex-wrap:wrap}
.tag{background:#21262d;border:1px solid var(--bd);border-radius:99px;padding:0 .6rem;font-size:.78rem;color:var(--ac)}
article h1{font-size:1.6rem;margin:.2rem 0}
.lead{color:var(--fg);font-size:1.05rem;border-right:4px solid var(--gold);padding-right:.8rem;margin:1rem 0}
.srcbox{background:#1c1e26;border:1px solid var(--bd);border-radius:8px;padding:.7rem 1rem;margin:1.4rem 0 .4rem;font-size:.9rem;color:var(--mut)}
footer.site{border-top:1px solid var(--bd);color:var(--mut);font-size:.82rem;padding:1.2rem;text-align:center;line-height:1.9}
.badge{background:#6e40c9;color:#fff;border-radius:6px;padding:.05rem .5rem;font-size:.75rem}
"""


def esc(s): return html.escape(s, quote=True)


def fa_date(iso):
    try:
        d = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
        return d.strftime("%Y-%m-%d %H:%M") + " UTC"
    except Exception:
        return iso


def page(title, desc, body, canonical, extra_head=""):
    return f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{esc(canonical)}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="{esc(TITLE)}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{esc(canonical)}">
<meta property="og:locale" content="fa_IR">
<meta name="twitter:card" content="summary">
<link rel="alternate" type="application/rss+xml" title="{esc(TITLE)}"
      href="{esc(BASE + '/feed.xml')}">
<link rel="stylesheet" href="{esc(BASE + '/assets/style.css')}">
<script type="application/ld+json">
{{"@context":"https://schema.org","@type":"NewsArticle",
  "headline":{json.dumps(title, ensure_ascii=False)},
  "description":{json.dumps(desc, ensure_ascii=False)},
  "inLanguage":"fa","url":{json.dumps(canonical)},
  "publisher":{{"@type":"Organization","name":{json.dumps(TITLE, ensure_ascii=False)}}}}}
</script>
{extra_head}
</head>
<body>
<header class="site">
  <div class="logo">WoWhead FA<small>اخبار ورلد آو وارکرفت به فارسی — غیررسمی</small></div>
  <nav><a href="{BASE}/">خانه</a> · <a href="{BASE}/feed.xml">RSS</a></nav>
</header>
<main>
{body}
</main>
<footer class="site">{DISCLAIMER}<br>تماس (takedown/DMCA): {esc(CONTACT)}</footer>
</body></html>"""


def article_page(art):
    a = art["article_fa"]
    slug = f"{art['id']}-{art['slug']}"
    url = f"{BASE}/article/{slug}.html"
    paras = "\n".join(f"<p>{esc(p)}</p>" for p in a["body_fa"])
    tags = " ".join(f'<span class="tag">{esc(t)}</span>' for t in a.get("tags_fa", []))
    gen = art.get("generator", {})
    genline = ""
    if gen.get("model"):
        via = str(gen.get("via") or "")
        rev = str(gen.get("reviewer") or "")
        if via.startswith("auto"):
            # automated pipeline (any provider: auto-grok / auto-gemini…)
            if rev and rev != gen["model"]:
                genline = (f"<span>نگارش خودکار با {esc(gen['model'])} "
                           f"و بازبینی با {esc(rev)}</span>")
            else:
                genline = (f"<span>نگارش و بازبینی خودکار با "
                           f"{esc(gen['model'])}</span>")
        else:
            genline = (f"<span>نگارش با دستیار هوشمند ({esc(gen['model'])}) "
                       f"+ ویرایش انسانی</span>")
    body = f"""
<article class="card" itemscope itemtype="https://schema.org/NewsArticle">
  <h1 itemprop="headline">{esc(a['title_fa'])}</h1>
  <div class="meta"><span>{esc(fa_date(art['published_at']))}</span>
    {genline}<span>{tags}</span></div>
  <p class="lead">{esc(a['lead_fa'])}</p>
  {paras}
  <div class="srcbox">منبع: <a href="{esc(art['url'])}" rel="noopener"
     target="_blank">Wowhead — {esc(art['title_en'])}</a><br>
     این متن بازنویسی اورجینال فارسی است، نه ترجمهٔ تحت‌اللفظی.</div>
</article>
<p><a href="{BASE}/">← همهٔ اخبار</a></p>"""
    return page(a["title_fa"], a["lead_fa"], body, url)


def index_page(arts):
    cards = []
    for art in arts:
        a = art["article_fa"]
        slug = f"{art['id']}-{art['slug']}"
        draft = "" if art["status"] == "published" else \
            ' <span class="badge">پیش‌نویس</span>'
        tags = " ".join(f'<span class="tag">{esc(t)}</span>'
                        for t in a.get("tags_fa", [])[:3])
        cards.append(f"""
<div class="card">
  <h2><a href="{BASE}/article/{esc(slug)}.html">{esc(a['title_fa'])}</a>{draft}</h2>
  <p style="margin:.2rem 0">{esc(a['lead_fa'][:180])}…</p>
  <div class="meta"><span>{esc(fa_date(art['published_at']))}</span>
  <a href="{esc(art['url'])}" target="_blank" rel="noopener">منبع: Wowhead</a>
  <span>{tags}</span></div>
</div>""")
    body = ("\n<h1>آخرین اخبار</h1>\n" + "\n".join(cards)
            if cards else "\n<h1>به‌زودی</h1>\n<p>اولین خبرها در راه است.</p>")
    return page(TITLE, DESC, body, BASE + "/")


def main():
    arts = []
    for f in sorted(os.listdir(ART)):
        if f.endswith(".json"):
            art = json.load(open(os.path.join(ART, f), encoding="utf-8"))
            if art.get("status") in ("published",) or \
                    (art.get("status") == "drafted"):
                arts.append(art)
    arts.sort(key=lambda x: x.get("published_at", ""), reverse=True)

    if os.path.isdir(DOCS):
        shutil.rmtree(DOCS)
    os.makedirs(os.path.join(DOCS, "article"))
    os.makedirs(os.path.join(DOCS, "assets"))

    with open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(index_page(arts))

    pub = [a for a in arts if a["status"] == "published"]
    for art in pub:
        slug = f"{art['id']}-{art['slug']}"
        with open(os.path.join(DOCS, "article", f"{slug}.html"), "w",
                  encoding="utf-8") as fh:
            fh.write(article_page(art))

    # our RSS
    items = []
    for art in pub[:30]:
        a = art["article_fa"]
        slug = f"{art['id']}-{art['slug']}"
        items.append(f"""<item><title>{esc(a['title_fa'])}</title>
<link>{BASE}/article/{esc(slug)}.html</link>
<guid>{BASE}/article/{esc(slug)}.html</guid>
<pubDate>{art['published_at']}</pubDate>
<description>{esc(a['lead_fa'])}</description></item>""")
    with open(os.path.join(DOCS, "feed.xml"), "w", encoding="utf-8") as fh:
        fh.write(f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>{esc(TITLE)}</title>
<link>{BASE}/</link><description>{esc(DESC)}</description>
{''.join(items)}</channel></rss>""")

    # sitemap + robots
    urls = [BASE + "/"] + [f"{BASE}/article/{a['id']}-{a['slug']}.html"
                           for a in pub]
    with open(os.path.join(DOCS, "sitemap.xml"), "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                 + "".join(f"<url><loc>{esc(u)}</loc></url>" for u in urls)
                 + "</urlset>")
    with open(os.path.join(DOCS, "robots.txt"), "w") as fh:
        fh.write(f"User-agent: *\nAllow: /\nSitemap: {BASE}/sitemap.xml\n")

    # JSON API for the main wowfarsi site (fetched cross-origin;
    # GitHub Pages serves everything with CORS:*)
    def pub_item(art):
        a = art["article_fa"]
        return {
            "id": art["id"], "slug": art["slug"],
            "title_fa": a["title_fa"], "lead_fa": a["lead_fa"],
            "body_fa": a["body_fa"], "tags_fa": a.get("tags_fa", []),
            "title_en": art.get("title_en", ""),
            "source_url": art["url"],
            "page_url": f"{BASE}/article/{art['id']}-{art['slug']}.html",
            "published_at": art.get("published_at", ""),
            "model": (art.get("generator") or {}).get("model", ""),
            "via": (art.get("generator") or {}).get("via", ""),
            "reviewer": (art.get("generator") or {}).get("reviewer", ""),
        }

    queue = []
    for f in sorted(os.listdir(ART)):
        if not f.endswith(".json"):
            continue
        try:
            art = json.load(open(os.path.join(ART, f), encoding="utf-8"))
        except Exception:
            continue
        if art.get("status") == "new":
            queue.append({"id": art["id"], "title_en": art.get("title_en", ""),
                          "url": art["url"], "category": art.get("category", ""),
                          "published_at": art.get("published_at", "")})
    queue.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    api = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "base_url": BASE,
        "site": "wowheadFA",
        "published": [pub_item(a) for a in pub[:30]],
        "queue": queue[:40],
    }
    with open(os.path.join(DOCS, "news.json"), "w", encoding="utf-8") as fh:
        json.dump(api, fh, ensure_ascii=False, indent=1)

    # assets
    with open(os.path.join(DOCS, "assets", "style.css"), "w",
              encoding="utf-8") as fh:
        fh.write(CSS)
    if os.path.exists(FONT_SRC):
        shutil.copy(FONT_SRC, os.path.join(DOCS, "assets", "Vazirmatn.ttf"))

    # font-face injection (append to css so template stays readable)
    with open(os.path.join(DOCS, "assets", "style.css"), "a",
              encoding="utf-8") as fh:
        fh.write("\n@font-face{font-family:Vazirmatn;"
                 "src:url('Vazirmatn.ttf') format('truetype');"
                 "font-display:swap;font-weight:100 900}\n")

    print(f"site built: {len(pub)} published, "
          f"{len(arts) - len(pub)} drafts listed, "
          f"{len(pub)} article pages, sitemap {len(urls)} urls")
    return 0


if __name__ == "__main__":
    sys.exit(main())
