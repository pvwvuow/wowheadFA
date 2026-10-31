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

Item cards (rarity colour + big preview image) live in item_render.py.
"""
import hashlib
import html
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import item_render  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "data", "articles")
DOCS = os.path.join(ROOT, "docs")
SITE_CONF = os.path.join(ROOT, "config", "site.json")
FONT_SRC = os.path.join(ROOT, "assets", "Vazirmatn.ttf")
NEWS_IMG = os.path.join(ROOT, "data", "news-img")

CONF = json.load(open(SITE_CONF, encoding="utf-8"))
BASE = CONF["base_url"].rstrip("/")
TITLE = CONF["title"]
DESC = CONF["description"]
DISCLAIMER = CONF["disclaimer"]
CONTACT = CONF["contact"]

# Persian UI strings (ASCII-only source, written as unicode escapes)
TAGLINE = "\u0627\u062e\u0628\u0627\u0631 \u0648\u0631\u0644\u062f \u0622\u0648 \u0648\u0627\u0631\u06a9\u0631\u0641\u062a \u0628\u0647 \u0641\u0627\u0631\u0633\u06cc \u2014 \u063a\u06cc\u0631\u0631\u0633\u0645\u06cc"
HOME_FA = "\u062e\u0627\u0646\u0647"
CONTACT_FA = "\u062a\u0645\u0627\u0633 (takedown/DMCA): "
GEN_AUTO_REV = "\u0646\u06af\u0627\u0631\u0634 \u062e\u0648\u062f\u06a9\u0627\u0631 \u0628\u0627 "
AND_REV = " \u0648 \u0628\u0627\u0632\u0628\u06cc\u0646\u06cc \u0628\u0627 "
GEN_AUTO = "\u0646\u06af\u0627\u0631\u0634 \u0648 \u0628\u0627\u0632\u0628\u06cc\u0646\u06cc \u062e\u0648\u062f\u06a9\u0627\u0631 \u0628\u0627 "
GEN_HUMAN = "\u0646\u06af\u0627\u0631\u0634 \u0628\u0627 \u062f\u0633\u062a\u06cc\u0627\u0631 \u0647\u0648\u0634\u0645\u0646\u062f ("
GEN_HUMAN2 = ") + \u0648\u06cc\u0631\u0627\u06cc\u0634 \u0627\u0646\u0633\u0627\u0646\u06cc"
SRC_FA = "\u0645\u0646\u0628\u0639: "
REWRITE_FA = "\u0627\u06cc\u0646 \u0645\u062a\u0646 \u0628\u0627\u0632\u0646\u0648\u06cc\u0633\u06cc \u0627\u0648\u0631\u062c\u06cc\u0646\u0627\u0644 \u0641\u0627\u0631\u0633\u06cc \u0627\u0633\u062a\u060c \u0646\u0647 \u062a\u0631\u062c\u0645\u0647\u0654 \u062a\u062d\u062a\u200c\u0627\u0644\u0644\u0641\u0638\u06cc."
ALL_FA = "\u2190 \u0647\u0645\u0647\u0654 \u0627\u062e\u0628\u0627\u0631"
DRAFT_FA = "\u067e\u06cc\u0634\u200c\u0646\u0648\u06cc\u0633"
LATEST_FA = "\u0622\u062e\u0631\u06cc\u0646 \u0627\u062e\u0628\u0627\u0631"
SOON_FA = "\u0628\u0647\u200c\u0632\u0648\u062f\u06cc"
FIRST_FA = "\u0627\u0648\u0644\u06cc\u0646 \u062e\u0628\u0631\u0647\u0627 \u062f\u0631 \u0631\u0627\u0647 \u0627\u0633\u062a."

# Item directory (SEO landing pages) - Persian UI strings as escapes
ITEMS_NAV = "\u0622\u06cc\u062a\u0645\u200c\u0647\u0627"
ITEMS_H1 = ("\u062f\u0627\u0646\u0634\u0646\u0627\u0645\u0647\u0654 "
            "\u0622\u06cc\u062a\u0645\u200c\u0647\u0627\u06cc "
            "\u0648\u0631\u0644\u062f \u0622\u0648 \u0648\u0627\u0631\u06a9\u0631\u0641\u062a")
ITEMS_DESC = ("\u0645\u0634\u062e\u0635\u0627\u062a\u060c "
              "\u06a9\u06cc\u0641\u06cc\u062a \u0648 \u0646\u062d\u0648\u0647\u0654 "
              "\u06a9\u0633\u0628 \u0622\u06cc\u062a\u0645\u200c\u0647\u0627\u06cc "
              "World of Warcraft \u0628\u0647 \u0641\u0627\u0631\u0633\u06cc")
FILTER_PH = "\u062c\u0633\u062a\u062c\u0648\u06cc \u0622\u06cc\u062a\u0645\u2026"
RELATED_H = "\u0627\u062e\u0628\u0627\u0631 \u0645\u0631\u062a\u0628\u0637"
QLBL = "\u06a9\u06cc\u0641\u06cc\u062a"
KIND_ITEM = "\u0622\u06cc\u062a\u0645"
KIND_DECOR = "\u062f\u06a9\u0648\u0631"
DECOR_LBL = "\u062a\u0632\u0626\u06cc\u0646\u0627\u062a"
NEWS_U = "\u062e\u0628\u0631"
TO_FA = "\u0628\u0647 \u0641\u0627\u0631\u0633\u06cc"
FEAT_FA = "\u0648\u06cc\u0698\u06af\u06cc\u200c\u0647\u0627"
# Persian row labels (as produced by item_cards.translate_card) -> one
# deterministic Persian sentence each, for item-page descriptions.
ROW_SENT = {
    "\u0641\u0631\u0648\u0634\u0646\u062f\u0647": "\u062a\u0648\u0633\u0637 {v} \u0641\u0631\u0648\u062e\u062a\u0647 \u0645\u06cc\u200c\u0634\u0648\u062f.",
    "\u0642\u06cc\u0645\u062a": "\u0642\u06cc\u0645\u062a \u0622\u0646 {v} \u0627\u0633\u062a.",
    "\u0645\u0646\u0637\u0642\u0647": "\u062f\u0631 \u0645\u0646\u0637\u0642\u0647\u0654 {v} \u06cc\u0627\u0641\u062a \u0645\u06cc\u200c\u0634\u0648\u062f.",
    "\u0645\u062d\u0644 \u0642\u0631\u0627\u0631\u06af\u06cc\u0631\u06cc": "\u0642\u0627\u0628\u0644 \u0642\u0631\u0627\u0631\u06af\u06cc\u0631\u06cc \u062f\u0631 {v}.",
    "\u0642\u0627\u0628\u0644 \u0642\u0631\u0627\u0631\u06af\u06cc\u0631\u06cc": "\u0642\u0627\u0628\u0644 \u0642\u0631\u0627\u0631\u06af\u06cc\u0631\u06cc \u062f\u0631 {v}.",
    "\u0627\u0646\u062f\u0627\u0632\u0647": "\u0627\u0646\u062f\u0627\u0632\u0647\u0654 \u0622\u0646 {v} \u0627\u0633\u062a.",
    "\u0627\u06a9\u0633\u067e\u0646\u0634\u0646": "\u0645\u062a\u0639\u0644\u0642 \u0628\u0647 {v} \u0627\u0633\u062a.",
    "\u062c\u0646\u0627\u062d": "\u0648\u06cc\u0698\u0647\u0654 {v} \u0627\u0633\u062a.",
}

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
article h2{font-size:1.25rem;margin:1.4rem 0 .4rem;color:var(--gold)}
article ul,article ol{padding-inline-start:1.4rem}article li{margin:.3rem 0}
article blockquote{border-right:3px solid var(--gold);margin:1rem 0;padding:.4rem .9rem;background:var(--bg2);border-radius:0 8px 8px 0}
article blockquote small{display:block;color:var(--mut);margin-top:.3rem}
article .note{border:1px solid var(--bd);border-radius:8px;background:var(--bg2);padding:.6rem .9rem;margin:1rem 0;font-size:.95rem}
article table{border-collapse:collapse;width:100%;margin:1rem 0;font-size:.92rem}
article th,article td{border:1px solid var(--bd);padding:.4rem .7rem;text-align:right}
article th{background:var(--bg2);color:var(--ac)}
article figure{margin:1rem 0;text-align:center}article img{max-width:100%;border-radius:8px}
article figcaption{color:var(--mut);font-size:.82rem;margin-top:.4rem}
.srcbox{background:#1c1e26;border:1px solid var(--bd);border-radius:8px;padding:.7rem 1rem;margin:1.4rem 0 .4rem;font-size:.9rem;color:var(--mut)}
footer.site{border-top:1px solid var(--bd);color:var(--mut);font-size:.82rem;padding:1.2rem;text-align:center;line-height:1.9}
.badge{background:#6e40c9;color:#fff;border-radius:6px;padding:.05rem .5rem;font-size:.75rem}
.ilinks{list-style:none;padding:0;margin:.4rem 0}
.ilinks li{padding:.35rem 0;border-bottom:1px dashed var(--bd)}
.il{list-style:none;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:.8rem}
.il-card{background:var(--bg2);border:1px solid var(--bd);border-radius:10px;padding:.7rem;display:flex;gap:.7rem;align-items:center}
.il-card:hover{border-color:var(--ac);text-decoration:none}
.il-card img{width:56px;height:56px;object-fit:contain;border-radius:8px;flex:0 0 56px}
.il-card .nm{direction:ltr;text-align:left;font-size:.9rem;font-weight:700;line-height:1.5;word-break:break-word;color:var(--fg)}
.il-card .q{color:var(--gold);font-size:.75rem}
#il-q{width:100%;max-width:24rem;background:var(--bg2);border:1px solid var(--bd);border-radius:8px;color:var(--fg);padding:.5rem .8rem;font-family:inherit;font-size:.95rem;margin:.6rem 0 1rem}
""" + item_render.CSS


def esc(s): return html.escape(s, quote=True)


# v2 body blocks (mirror of wow-repo tools/news_blocks.py - minimal renderer)
BLOCK_TS = {"p", "h", "ul", "ol", "quote", "note", "table", "img", "item"}


def _blk_clean(s, cap):
    return re.sub(r"\s+", " ", str(s if s is not None else "")).strip()[:cap]


def render_blocks(body):
    """v2 blocks -> simple static HTML; plain strings stay paragraphs."""
    out = []
    for b in body or []:
        if isinstance(b, str):
            if b.strip():
                out.append(f"<p>{esc(_blk_clean(b, 8000))}</p>")
            continue
        if not isinstance(b, dict):
            continue
        t = str(b.get("t") or "").lower()
        if t not in BLOCK_TS:
            continue
        if t in ("p", "h", "quote", "note"):
            x = _blk_clean(b.get("x"), 4000)
            if not x:
                continue
            if t == "p":
                out.append(f"<p>{esc(x)}</p>")
            elif t == "h":
                out.append(f"<h2>{esc(x)}</h2>")
            elif t == "quote":
                by = f"<small>\u2014 {esc(_blk_clean(b.get('by'), 120))}</small>" if b.get("by") else ""
                out.append(f"<blockquote><p>{esc(x)}</p>{by}</blockquote>")
            elif t == "note":
                ic = {"tip": "\U0001F4A1", "warn": "\u26A0\uFE0F", "info": "\u2139\uFE0F"}.get(
                    str(b.get("kind") or "tip"), "\U0001F4A1")
                out.append(f'<div class="note">{ic} {esc(x)}</div>')
        elif t in ("ul", "ol"):
            xs = [_blk_clean(x, 600) for x in (b.get("xs") or []) if _blk_clean(x, 600)]
            if xs:
                out.append(f"<{t}>" + "".join(f"<li>{esc(x)}</li>" for x in xs) + f"</{t}>")
        elif t == "table":
            head = [_blk_clean(x, 120) for x in (b.get("head") or []) if _blk_clean(x, 120)]
            rows = [[_blk_clean(c, 240) for c in r[:len(head) or 6]]
                    for r in (b.get("rows") or [])[:12] if isinstance(r, list)]
            if head and rows:
                th = "".join(f"<th>{esc(h)}</th>" for h in head)
                tr = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>"
                             for r in rows)
                out.append(f"<table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>")
        elif t == "img":
            src = str(b.get("src") or "")
            if re.match(r"^https://[\w.-]+/", src):
                cap = f"<figcaption>{esc(_blk_clean(b.get('cap'), 200))}</figcaption>" if b.get("cap") else ""
                out.append(f'<figure><img src="{esc(src[:500])}" alt="" '
                           f'loading="lazy" referrerpolicy="no-referrer">{cap}</figure>')
        elif t == "item":
            ids = b.get("ids") or ([b.get("id")] if b.get("id") is not None else [])
            for iid in ids or [b.get("name")]:
                iid = str(iid)
                out.append(f'<div class="note">\U0001F4E6 \u0622\u06cc\u062a\u0645: '
                           f'<a href="https://www.wowhead.com/item={esc(iid)}" '
                           f'target="_blank" rel="noopener">{esc(iid)}</a> '
                           f'(\u06a9\u0627\u0631\u062a \u06a9\u0627\u0645\u0644 \u062f\u0631 wowfarsi.ir)</div>')
    return "\n".join(out)


def render_items(art):
    """Render structured item-card blocks (art['items']) as rarity cards."""
    return item_render.render_items(art)


def fa_date(iso):
    try:
        d = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
        return d.strftime("%Y-%m-%d %H:%M") + " UTC"
    except Exception:
        return iso


def page(title, desc, body, canonical, extra_head="", ld=None):
    ver = os.environ.get("GSC_VERIFY_TOKEN", "").strip()
    ver_meta = (f'<meta name="google-site-verification" content="{esc(ver)}">'
                if re.fullmatch(r"[A-Za-z0-9_-]{10,64}", ver) else "")
    if ld is None:
        ld = ('{"@context":"https://schema.org","@type":"NewsArticle",'
              '"headline":' + json.dumps(title, ensure_ascii=False) + ','
              '"description":' + json.dumps(desc, ensure_ascii=False) + ','
              '"inLanguage":"fa","url":' + json.dumps(canonical) + ','
              '"publisher":{"@type":"Organization","name":'
              + json.dumps(TITLE, ensure_ascii=False) + '}}')
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
{ver_meta}
<link rel="alternate" type="application/rss+xml" title="{esc(TITLE)}"
      href="{esc(BASE + '/feed.xml')}">
<link rel="stylesheet" href="{esc(BASE + '/assets/style.css')}">
<script type="application/ld+json">
{ld}
</script>
{extra_head}
</head>
<body>
<header class="site">
  <div class="logo">WoWhead FA<small>{TAGLINE}</small></div>
  <nav><a href="{BASE}/">{HOME_FA}</a> · <a href="{BASE}/items.html">{ITEMS_NAV}</a> · <a href="{BASE}/feed.xml">RSS</a></nav>
</header>
<main>
{body}
</main>
<footer class="site">{DISCLAIMER}<br>{CONTACT_FA}{esc(CONTACT)}</footer>
</body></html>"""


def article_page(art):
    a = art["article_fa"]
    slug = f"{art['id']}-{art['slug']}"
    url = f"{BASE}/article/{slug}.html"
    paras = render_blocks(a["body_fa"])
    items_html = render_items(art)
    tags = " ".join(f'<span class="tag">{esc(t)}</span>' for t in a.get("tags_fa", []))
    gen = art.get("generator", {})
    genline = ""
    if gen.get("model"):
        via = str(gen.get("via") or "")
        rev = str(gen.get("reviewer") or "")
        if via.startswith("auto"):
            # automated pipeline (any provider: auto-grok / auto-gemini...)
            if rev and rev != gen["model"]:
                genline = (f"<span>{GEN_AUTO_REV}{esc(gen['model'])}"
                           f"{AND_REV}{esc(rev)}</span>")
            else:
                genline = (f"<span>{GEN_AUTO}"
                           f"{esc(gen['model'])}</span>")
        else:
            genline = (f"<span>{GEN_HUMAN}{esc(gen['model'])}"
                       f"{GEN_HUMAN2}</span>")
    body = f"""
<article class="card" itemscope itemtype="https://schema.org/NewsArticle">
  <h1 itemprop="headline">{esc(a['title_fa'])}</h1>
  <div class="meta"><span>{esc(fa_date(art['published_at']))}</span>
    {genline}<span>{tags}</span></div>
  <p class="lead">{esc(a['lead_fa'])}</p>
  {paras}
  {items_html}
  <div class="srcbox">{SRC_FA}<a href="{esc(art['url'])}" rel="noopener"
     target="_blank">Wowhead \u2014 {esc(art['title_en'])}</a><br>
     {REWRITE_FA}</div>
</article>
<p><a href="{BASE}/">{ALL_FA}</a></p>"""
    return page(a["title_fa"], a["lead_fa"], body, url)


def index_page(arts):
    cards = []
    for art in arts:
        a = art["article_fa"]
        slug = f"{art['id']}-{art['slug']}"
        draft = "" if art["status"] == "published" else \
            f' <span class="badge">{DRAFT_FA}</span>'
        tags = " ".join(f'<span class="tag">{esc(t)}</span>'
                        for t in a.get("tags_fa", [])[:3])
        cards.append(f"""
<div class="card">
  <h2><a href="{BASE}/article/{esc(slug)}.html">{esc(a['title_fa'])}</a>{draft}</h2>
  <p style="margin:.2rem 0">{esc(a['lead_fa'][:180])}...</p>
  <div class="meta"><span>{esc(fa_date(art['published_at']))}</span>
  <a href="{esc(art['url'])}" target="_blank" rel="noopener">{SRC_FA}Wowhead</a>
  <span>{tags}</span></div>
</div>""")
    body = (f"\n<h1>{LATEST_FA}</h1>\n" + "\n".join(cards)
            if cards else f"\n<h1>{SOON_FA}</h1>\n<p>{FIRST_FA}</p>")
    return page(TITLE, DESC, body, BASE + "/")


# ------------------------------------------------- item directory (SEO)
def item_slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not s:
        s = "item-" + hashlib.md5(name.encode("utf-8")).hexdigest()[:8]
    return s


def _clip(s, n=158):
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) <= n:
        return s
    return s[:n].rsplit(" ", 1)[0].rstrip(" \u060c,.:;") + "\u2026"


def item_desc_plain(rec):
    """Deterministic Persian summary built from the item's factual rows
    (same policy as item_cards: facts only, no prose from the source)."""
    kind = KIND_DECOR if any(str(r[0]) == DECOR_LBL for r in rec["rows"]) \
        else KIND_ITEM
    q = item_render.norm_quality(rec.get("quality"))
    out = [f"{kind} \u00ab{rec['name']}\u00bb \u062f\u0631 World of Warcraft."]
    if q:
        out.append(QLBL + " \u0622\u0646 "
                   + item_render.QUALITY_FA[q] + " \u0627\u0633\u062a.")
    seen = set()
    for lbl, val in rec["rows"][:6]:
        tpl = ROW_SENT.get(str(lbl))
        if tpl:
            s = tpl.format(v=str(val))
            if s not in seen:
                seen.add(s)
                out.append(s)
    if rec["spec"]:
        out.append(FEAT_FA + ": "
                   + "\u060c ".join(str(s) for s in rec["spec"][:3]) + ".")
    return _clip(" ".join(out))


def item_lastmod(rec):
    return max((a.get("published_at", "") for a in rec["arts"]),
               default="")[:10]


def item_page(rec):
    name = rec["name"]
    url = f"{BASE}/item/{item_slug(name)}.html"
    desc = item_desc_plain(rec)
    arts = sorted(rec["arts"], key=lambda a: a.get("published_at", ""),
                  reverse=True)
    fa_n = str(len(arts)).translate(item_render.FA_DIGITS)
    q = item_render.norm_quality(rec["quality"])
    qline = (f"<span>{QLBL}: <bdi>{esc(item_render.QUALITY_FA[q])}</bdi></span>"
             if q else "")
    lrows = []
    for a in arts[:12]:
        aslug = f"{a['id']}-{a['slug']}"
        atitle = esc(a["article_fa"]["title_fa"])
        adate = esc(fa_date(a["published_at"]))
        lrows.append(f'<li><a href="{BASE}/article/{aslug}.html">{atitle}</a>'
                     f' <span class="meta">{adate}</span></li>')
    links = "\n".join(lrows)
    card = item_render.render_items({"items": [{"item": {
        "name": name, "rows": rec["rows"], "spec": rec["spec"],
        "quality": rec["quality"], "image": rec["image"],
        "icon": rec["image"]}}]})
    ld = json.dumps({
        "@context": "https://schema.org", "@type": "ItemPage",
        "name": name, "url": url, "inLanguage": "fa",
        "description": desc,
        **({"image": [rec["image"]]} if rec["image"] else {}),
        "breadcrumb": {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": HOME_FA,
             "item": BASE + "/"},
            {"@type": "ListItem", "position": 2, "name": ITEMS_NAV,
             "item": BASE + "/items.html"},
            {"@type": "ListItem", "position": 3, "name": name}]},
    }, ensure_ascii=False)
    og = (f'<meta property="og:image" content="{esc(rec["image"])}">'
          if rec["image"] else "")
    body = f"""
<article class="card" itemscope itemtype="https://schema.org/ItemPage">
  <h1 itemprop="name" dir="ltr">{esc(name)}</h1>
  <div class="meta">{qline}<span>{fa_n} {NEWS_U} {RELATED_H}</span></div>
  <p class="lead">{esc(desc)}</p>
  {card}
  <h2>{RELATED_H}</h2>
  <ul class="ilinks">{links}</ul>
  <div class="srcbox">{SRC_FA}<a href="{esc(arts[0]['url'])}" rel="noopener"
     target="_blank">Wowhead \u2014 {esc(arts[0]['title_en'])}</a></div>
</article>
<p><a href="{BASE}/items.html">{ITEMS_NAV}</a> \u00b7 <a href="{BASE}/">{ALL_FA}</a></p>"""
    return page(f"{name} \u2014 WoW {KIND_ITEM} {TO_FA}", desc, body, url,
                extra_head=og, ld=ld)


def items_index_page(recs):
    cards = []
    for r in recs:
        islug = item_slug(r["name"])
        q = item_render.norm_quality(r["quality"])
        qfa = item_render.QUALITY_FA.get(q, "")
        iname = esc(r["name"])
        media = (f'<img src="{esc(r["image"])}" alt="{iname}"'
                 ' width="56" height="56" loading="lazy" decoding="async">'
                 if r["image"] else "")
        cards.append(
            f'<li><a class="il-card" href="{BASE}/item/{islug}.html">'
            f'{media}<span><span class="nm">{iname}</span><br>'
            f'<span class="q">{esc(qfa)}</span></span></a></li>')
    body = f"""
<h1>{ITEMS_H1}</h1>
<p>{esc(ITEMS_DESC)}</p>
<input id="il-q" type="search" placeholder="{esc(FILTER_PH)}"
       aria-label="{esc(FILTER_PH)}">
<ul class="il" id="il-list">{''.join(cards)}</ul>
<script>(function(){{var q=document.getElementById("il-q"),
l=document.getElementById("il-list");if(!q||!l)return;
q.addEventListener("input",function(){{var v=q.value.trim().toLowerCase();
Array.prototype.forEach.call(l.children,function(li){{
li.style.display=!v||li.textContent.toLowerCase().indexOf(v)>-1?"":"none";
}});}});}})();</script>"""
    return page(ITEMS_H1, ITEMS_DESC, body, BASE + "/items.html")


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
    if os.path.isdir(NEWS_IMG):
        shutil.copytree(NEWS_IMG, os.path.join(DOCS, "assets", "news"),
                        dirs_exist_ok=True)
        # wowfarsi watermark on every news image. Originals stay pristine
        # in data/news-img; docs/ is rebuilt from scratch each run, so the
        # stamp is never applied twice. No Pillow -> copy unwatermarked
        # (the pipeline never breaks over branding).
        try:
            import watermark
            n = watermark.watermark_tree(os.path.join(DOCS, "assets", "news"))
            print(f"watermark: {n} image(s) stamped")
        except ImportError:
            print("watermark skipped: pillow not installed")

    with open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(index_page(arts))

    pub = [a for a in arts if a["status"] == "published"]
    for art in pub:
        slug = f"{art['id']}-{art['slug']}"
        with open(os.path.join(DOCS, "article", f"{slug}.html"), "w",
                  encoding="utf-8") as fh:
            fh.write(article_page(art))

    # item directory: one SEO landing page per unique item name
    items_index = {}
    for art in pub:  # newest first -> newest non-empty meta wins
        for blk in item_render.merged_items(art):
            it = (blk or {}).get("item") or {}
            name = str(it.get("name") or "").strip()
            if not name:
                continue
            s = item_slug(name)
            rec = items_index.setdefault(s, {"name": name, "quality": "",
                                             "image": "", "rows": [],
                                             "spec": [], "arts": []})
            if not rec["quality"]:
                rec["quality"] = it.get("quality", "") or ""
            if not rec["image"]:
                rec["image"] = (item_render.safe_img(it.get("image"))
                                or item_render.safe_img(it.get("icon")))
            if not rec["rows"]:
                rec["rows"] = it.get("rows") or []
            if not rec["spec"]:
                rec["spec"] = it.get("spec") or []
            rec["arts"].append(art)
    os.makedirs(os.path.join(DOCS, "item"), exist_ok=True)
    recs = sorted(items_index.values(),
                  key=lambda r: max((a.get("published_at", "")
                                     for a in r["arts"]), default=""),
                  reverse=True)
    with open(os.path.join(DOCS, "items.html"), "w", encoding="utf-8") as fh:
        fh.write(items_index_page(recs))
    for r in recs:
        with open(os.path.join(DOCS, "item",
                               item_slug(r["name"]) + ".html"),
                  "w", encoding="utf-8") as fh:
            fh.write(item_page(r))

    # our RSS
    items = []
    for art in pub[:60]:
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

    # sitemap (with lastmod) + news-sitemap + robots + IndexNow key file
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    urls = [(BASE + "/", today)]
    urls += [(f"{BASE}/article/{a['id']}-{a['slug']}.html",
              a.get("published_at", "")[:10] or today) for a in pub]
    urls += [(BASE + "/items.html", today)]
    urls += [(f"{BASE}/item/{item_slug(r['name'])}.html",
              item_lastmod(r) or today) for r in recs]
    with open(os.path.join(DOCS, "sitemap.xml"), "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                 + "".join(f"<url><loc>{esc(u)}</loc>"
                           f"<lastmod>{m}</lastmod></url>" for u, m in urls)
                 + "</urlset>")

    def _hours(iso):
        try:
            d = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
            return abs((datetime.now(timezone.utc)
                        - d.replace(tzinfo=timezone.utc)).total_seconds()) / 3600
        except Exception:
            return 1e9

    recent = [a for a in pub if _hours(a.get("published_at", "")) <= 48]
    news_rows = []
    for a in recent[:1000]:
        aslug = f"{a['id']}-{a['slug']}"
        at = esc(a["article_fa"]["title_fa"])
        news_rows.append(
            f"<url><loc>{BASE}/article/{aslug}.html</loc>"
            "<news:news><news:publication><news:name>" + esc(TITLE)
            + "</news:name><news:language>fa</news:language>"
            "</news:publication><news:publication_date>"
            + a.get("published_at", "") + "</news:publication_date>"
            "<news:title>" + at + "</news:title></news:news></url>")
    with open(os.path.join(DOCS, "news-sitemap.xml"), "w",
              encoding="utf-8") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
                 'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">'
                 + "".join(news_rows) + "</urlset>")

    with open(os.path.join(DOCS, "robots.txt"), "w") as fh:
        fh.write(f"User-agent: *\nAllow: /\nSitemap: {BASE}/sitemap.xml\n"
                 f"Sitemap: {BASE}/news-sitemap.xml\n")

    ikey = os.environ.get("INDEXNOW_KEY", "").strip()
    if ikey and re.fullmatch(r"[A-Za-z0-9_-]{8,64}", ikey):
        with open(os.path.join(DOCS, ikey + ".txt"), "w") as fh:
            fh.write(ikey + "\n")

    # JSON API for the main wowfarsi site (fetched cross-origin;
    # GitHub Pages serves everything with CORS:*)
    def pub_item(art):
        a = art["article_fa"]
        return {
            "id": art["id"], "slug": art["slug"],
            "title_fa": a["title_fa"], "lead_fa": a["lead_fa"],
            "body_fa": a["body_fa"], "tags_fa": a.get("tags_fa", []),
            "items": item_render.merged_items(art),
            "title_en": art.get("title_en", ""),
            "source_url": art["url"],
            "page_url": f"{BASE}/article/{art['id']}-{art['slug']}.html",
            "published_at": art.get("published_at", ""),
            "model": (art.get("generator") or {}).get("model", ""),
            "via": (art.get("generator") or {}).get("via", ""),
            "reviewer": (art.get("generator") or {}).get("reviewer", ""),
            "thumb": art.get("thumb", ""),
            "images": art.get("images", []),
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
        "published": [pub_item(a) for a in pub[:60]],
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
          f"{len(pub)} article pages, {len(recs)} item pages, "
          f"sitemap {len(urls)} urls, news-sitemap {len(recent)} urls")
    return 0


if __name__ == "__main__":
    sys.exit(main())
