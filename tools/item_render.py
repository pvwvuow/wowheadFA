#!/usr/bin/env python3
"""item_render.py - fantasy-minimal item cards for the static site.

Rarity colour comes from the item's `quality` (Wowhead q0..q8, or a name
like "epic"). The big picture on the left comes from `image` (decor /
item preview) and falls back to the old `icon`.

Optional overlay data/item_meta.json fills gaps for articles written
before those fields existed:
  {"<article id>": {"<item name>": {"quality": "epic", "image": "https://..."}}}

ASCII-only source: Persian strings are written as unicode escapes.
"""
import html
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
META_PATH = os.path.join(ROOT, "data", "item_meta.json")

QUALITY_NAMES = {0: "poor", 1: "common", 2: "uncommon", 3: "rare",
                 4: "epic", 5: "legendary", 6: "artifact",
                 7: "heirloom", 8: "token"}
QUALITY_FA = {
    "poor": "\u0636\u0639\u06cc\u0641",
    "common": "\u0645\u0639\u0645\u0648\u0644\u06cc",
    "uncommon": "\u063a\u06cc\u0631\u0645\u0639\u0645\u0648\u0644",
    "rare": "\u06a9\u0645\u06cc\u0627\u0628",
    "epic": "\u062d\u0645\u0627\u0633\u06cc",
    "legendary": "\u0627\u0641\u0633\u0627\u0646\u0647\u200c\u0627\u06cc",
    "artifact": "\u0622\u0631\u062a\u06cc\u0641\u06a9\u062a",
    "heirloom": "\u0645\u06cc\u0631\u0627\u062b\u06cc",
    "token": "\u062a\u0648\u06a9\u0646",
}
TITLE_FA = "\u0622\u06cc\u062a\u0645\u200c\u0647\u0627 \u0648 \u062c\u0632\u06cc\u06cc\u0627\u062a"
BUDGET_FA = "\u0638\u0631\u0641\u06cc\u062a \u062f\u06a9\u0648\u0631"
IMG_HOSTS = ("https://wow.zamimg.com/",)
FA_DIGITS = {ord(str(i)): chr(0x06F0 + i) for i in range(10)}

SIGIL = ("<svg class=\"ic-sigil\" viewBox=\"0 0 64 64\" aria-hidden=\"true\">"
         "<path d=\"M32 6 58 32 32 58 6 32Z\" fill=\"none\" "
         "stroke=\"currentColor\" stroke-width=\"1.4\"/>"
         "<path d=\"M32 18 46 32 32 46 18 32Z\" fill=\"currentColor\" "
         "opacity=\".35\"/><circle cx=\"32\" cy=\"32\" r=\"3\" "
         "fill=\"currentColor\"/></svg>")

CSS = """
.ic-wrap{margin:1.6rem 0 .4rem}
.ic-wrap .ic-title{display:flex;align-items:center;gap:.9rem;margin:0 0 1rem;font-size:1.02rem;font-weight:700;line-height:1.8;color:#e3b341}
.ic-wrap .ic-title::before,.ic-wrap .ic-title::after{content:"";flex:1;height:1px;background:linear-gradient(90deg,transparent,rgba(227,179,65,.55),transparent)}
.ic{--q:#c9a232;--qt:#c9a232;--qg:201,162,50;position:relative;display:flex;direction:ltr;align-items:stretch;margin:0 0 1.1rem;border:1px solid rgba(var(--qg),.34);border-radius:14px;overflow:hidden;background:linear-gradient(165deg,rgba(27,22,35,.94),rgba(11,11,17,.97));box-shadow:0 10px 28px rgba(0,0,0,.38);transition:box-shadow .25s,border-color .25s}
.ic::before{content:"";position:absolute;inset:0 0 auto 0;height:1px;background:linear-gradient(90deg,transparent,var(--q),transparent);opacity:.95}
.ic:hover{border-color:rgba(var(--qg),.6);box-shadow:0 12px 34px rgba(0,0,0,.5),0 0 30px rgba(var(--qg),.14)}
.ic-media{flex:0 0 clamp(104px,32%,196px);display:flex;align-items:center;justify-content:center;padding:1rem;background:radial-gradient(circle at 50% 50%,rgba(var(--qg),.24),transparent 70%)}
.ic-media img{display:block;width:100%;max-width:172px;aspect-ratio:1/1;height:auto;object-fit:contain;border:0;border-radius:0;background:none;filter:drop-shadow(0 8px 14px rgba(0,0,0,.6)) drop-shadow(0 0 16px rgba(var(--qg),.38))}
.ic-sigil{width:62%;max-width:110px;color:var(--q);opacity:.7;filter:drop-shadow(0 0 10px rgba(var(--qg),.5))}
.ic-body{flex:1 1 auto;min-width:0;direction:rtl;padding:1rem 1.25rem 1.1rem}
.ic-head{display:flex;align-items:center;flex-wrap:wrap;gap:.35rem .7rem}
.ic-name{margin:0;font-size:1.14rem;font-weight:700;line-height:1.5;color:var(--qt);text-shadow:0 0 18px rgba(var(--qg),.4)}
.ic-rar{font-size:.72rem;line-height:1.7;color:var(--qt);border:1px solid rgba(var(--qg),.5);background:rgba(var(--qg),.08);border-radius:99px;padding:0 .65rem}
.ic-orn{position:relative;height:1px;margin:.6rem 0 .7rem;background:linear-gradient(90deg,transparent,rgba(var(--qg),.7) 28%,rgba(var(--qg),.7) 72%,transparent)}
.ic-orn::after{content:"";position:absolute;left:50%;top:-3px;width:6px;height:6px;transform:translateX(-50%) rotate(45deg);background:var(--q);box-shadow:0 0 8px rgba(var(--qg),.8)}
.ic-rows{display:grid;grid-template-columns:auto 1fr;gap:0 1.1rem;margin:0;font-size:.9rem;line-height:1.9}
.ic-rows dt,.ic-rows dd{padding:.12rem 0;border-bottom:1px dashed rgba(255,255,255,.07)}
.ic-rows dt{color:#9b94aa;white-space:nowrap}
.ic-rows dt::before{content:"\\25C6";display:inline-block;margin-left:.45rem;font-size:.55rem;vertical-align:middle;color:var(--q);opacity:.75}
.ic-rows dd{margin:0;color:#ece7f3;text-align:right}
.ic-rows .ltr,.ic-chip.ltr{direction:ltr;unicode-bidi:embed}
.ic-spec{display:flex;flex-wrap:wrap;gap:.45rem;margin-top:.8rem}
.ic-chip{display:inline-flex;align-items:center;gap:.3rem;font-size:.82rem;line-height:1.8;color:#f3e9c6;border:1px solid rgba(var(--qg),.38);background:rgba(var(--qg),.09);border-radius:99px;padding:0 .75rem}
.ic-chip b{color:var(--qt)}
.q-poor{--q:#9d9d9d;--qt:#b4b4b4;--qg:157,157,157}
.q-common{--q:#ffffff;--qt:#ffffff;--qg:255,255,255}
.q-uncommon{--q:#1eff00;--qt:#1eff00;--qg:30,255,0}
.q-rare{--q:#0070dd;--qt:#3a9bff;--qg:0,112,221}
.q-epic{--q:#a335ee;--qt:#c06cff;--qg:163,53,238}
.q-legendary{--q:#ff8000;--qt:#ff8000;--qg:255,128,0}
.q-artifact{--q:#e6cc80;--qt:#e6cc80;--qg:230,204,128}
.q-heirloom,.q-token{--q:#00ccff;--qt:#00ccff;--qg:0,204,255}
@media(max-width:560px){.ic-media{flex-basis:92px;padding:.6rem}.ic-body{padding:.85rem .9rem}.ic-rows{font-size:.85rem}}
"""


def esc(s):
    return html.escape(str(s), quote=True)


def norm_quality(v):
    """int 0-8 / "q4" / "epic" -> canonical lowercase name or ""."""
    if v is None or isinstance(v, bool) or v == "":
        return ""
    if isinstance(v, (int, float)):
        return QUALITY_NAMES.get(int(v), "")
    s = str(v).strip().lower()
    if s.startswith("q") and s[1:].isdigit():
        s = s[1:]
    if s.isdigit():
        return QUALITY_NAMES.get(int(s), "")
    return s if s in QUALITY_FA else ""


def safe_img(u):
    u = str(u or "")
    return u if u.startswith(IMG_HOSTS) and '"' not in u else ""


def load_meta():
    try:
        with open(META_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def merged_items(art, meta=None):
    """art['items'] with quality/image filled from data/item_meta.json."""
    meta = load_meta() if meta is None else meta
    over = meta.get(str(art.get("id")), {}) or {}
    out = []
    for blk in art.get("items") or []:
        it = dict((blk or {}).get("item") or {})
        extra = over.get(it.get("name", ""), {}) or {}
        q = norm_quality(it.get("quality")) or norm_quality(extra.get("quality"))
        img = safe_img(it.get("image")) or safe_img(extra.get("image"))
        if q:
            it["quality"] = q
        if img:
            it["image"] = img
        out.append({"item": it})
    return out


def _val(v):
    v = str(v)
    latin = re.search("[A-Za-z]", v)
    arabic = re.search("[\u0600-\u06FF]", v)
    if latin and not arabic:
        return '<span class="ltr">' + esc(v) + "</span>"
    return esc(v)


def _chips(spec):
    out = []
    for s in spec:
        s = str(s).strip()
        m = re.match("^([0-9]+)[ ]+([+][0-9].*)$", s)
        if m:
            out.append('<span class="ic-chip"><b>'
                       + m.group(1).translate(FA_DIGITS) + "</b> "
                       + BUDGET_FA + "</span>")
            out.append('<span class="ic-chip ltr">' + esc(m.group(2)) + "</span>")
        elif s:
            out.append('<span class="ic-chip ltr">' + esc(s) + "</span>")
    return "".join(out)


def render_items(art, meta=None):
    """Render the article's item blocks as rarity-coloured cards."""
    cards = []
    for blk in merged_items(art, meta):
        it = blk["item"]
        name = str(it.get("name") or "")
        rows = it.get("rows") or []
        spec = it.get("spec") or []
        if not name and not rows and not spec:
            continue
        q = it.get("quality") or ""
        img = safe_img(it.get("image")) or safe_img(it.get("icon"))
        if img:
            media = ('<img src="' + esc(img) + '" alt="' + esc(name)
                     + '" width="172" height="172" loading="lazy" '
                     'decoding="async" '
                     'onerror="this.style.visibility=&quot;hidden&quot;">')
        else:
            media = SIGIL
        pill = ('<span class="ic-rar">' + QUALITY_FA[q] + "</span>") if q else ""
        rows_html = "".join(
            "<dt>" + esc(lbl) + ":</dt><dd>" + _val(val) + "</dd>"
            for lbl, val in rows)
        spec_html = _chips(spec)
        cards.append(
            '<div class="ic' + ((" q-" + q) if q else "") + '">'
            '<div class="ic-media">' + media + "</div>"
            '<div class="ic-body">'
            '<div class="ic-head"><h3 class="ic-name" dir="ltr">' + esc(name)
            + "</h3>" + pill + "</div>"
            '<div class="ic-orn"></div>'
            '<dl class="ic-rows">' + rows_html + "</dl>"
            + ('<div class="ic-spec">' + spec_html + "</div>" if spec_html else "")
            + "</div></div>")
    if not cards:
        return ""
    return ('<section class="ic-wrap"><div class="ic-title">' + TITLE_FA
            + "</div>" + "".join(cards) + "</section>")
