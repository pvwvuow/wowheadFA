#!/usr/bin/env python3
"""Discord news bot — wowfarsi.ir (WoW Forever فارسی)

کاری که می‌کند:
  1. فید news.json را می‌خواند (لوکال docs/news.json یا URL) و خبرهای جدید
     نسبت به data/discord_state.json را پیدا می‌کند.
  2. تصویر هر خبر را برمی‌دارد و واترمارک رسمی واو‌فارسی (دو لوگوی خودِ
     صاحب سایت) را می‌زند:
       پس‌زمینهٔ تیره  → لوگوی طلایی  (assets/watermark/logo-gold.png)
       پس‌زمینهٔ روشن → لوگوی صدفی (assets/watermark/logo-ivory.png)
  3. تصویر را **مستقیم به‌عنوان پیوست دیسکورد** می‌فرستد (attachment://).
     پیوست روی CDN خود دیسکورد ذخیره می‌شود و برخلاف لینک خارجی هیچ‌وقت
     از دست نمی‌رود — تصویر خبر همیشه در embed نمایش داده می‌شود.
  4. شناسهٔ خبرهای فرستاده‌شده را در data/discord_state.json ثبت می‌کند
     (CI آن را commit می‌کند تا خبر تکراری نفرستد).

چرا پیوست و نه لینک تصویر Pages؟ (ریشهٔ باگ «عکس خبر در دیسکورد نمی‌آید»)
  نسخهٔ قبلی embed.image را روی لینک
  pvwvuow.github.io/wowheadFA/assets/news/<id>/wm.jpg می‌گذاشت. ولی
  build_site.py در هر اجرا کل docs/ را rmtree و از نو می‌سازد و wm.jpg را
  هرگز دوباره تولید نمی‌کرد → چند دقیقه بعد از پست، لینک ۴۰۴ می‌شد و
  دیسکورد تصویر را از embed حذف می‌کرد. پیوست دیسکورد نقطهٔ شکست خارجی
  ندارد؛ برای همین مسیر publish-to-Pages کاملاً حذف شد.

منبع تصویر (به ترتیب):
  1. data/news-img/<id>/      — نسخهٔ اصلی (واترمارک اینجا زده می‌شود)
  2. docs/assets/news/<id>/   — خروجی build_site (خودش مهر خورده؛ دوباره
                                 مهر نمی‌زنیم که واترمارک دوتایی نشود)
  3. thumb فید               — URL بیرونی مهر می‌خورد؛ اگر لینک خودِ ما
                                 (Pages) باشد یعنی مهر خورده است

CLI:
  python3 tools/discord_poster.py                 # اجرای عادی (CI)
  python3 tools/discord_poster.py --dry-run       # همه‌چیز به‌جز ارسال
  python3 tools/discord_poster.py --limit 3       # حداکثر ۳ خبر در هر اجرا
  python3 tools/discord_poster.py --id 383659     # اجبارِ ارسال یک خبر مشخص
  python3 tools/discord_poster.py --mark-posted   # فقط ثبت وضعیت، بدون ارسال

Env:
  DISCORD_BOT_TOKEN   توکن ربات (بدون آن، خروج با پیام و کد 0 انجام می‌شود)
  DISCORD_CHANNEL_ID  کانال مقصد (پیش‌فرض: چنل خبر wowfarsi)
  NEWS_JSON           مسیر/URL فید (پیش‌فرض: docs/news.json در همین ریپو)
  STATE_FILE          پیش‌فرض data/discord_state.json
  POST_ON_FIRST_RUN   اگر "1" باشد در اولین اجرا همهٔ خبرها را می‌فرستد
                      (پیش‌فرض 0 = اولین اجرا فقط وضعیت را seed می‌کند)
  LINK_MODE           wowfarsi (پیش‌فرض) | pages  — مقصد دکمهٔ «مشاهده خبر»
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

try:
    from PIL import Image
except ImportError:
    Image = None
try:
    import requests
except ImportError:
    requests = None

API = "https://discord.com/api/v10"
DEFAULT_CHANNEL = "1565441578225504378"   # چنل خبر — discord.com/channels/1565219490554183681/1565441578225504378
DEFAULT_LINK_BASE = "https://wowfarsi.ir/news/{id}-{slug}.html"
PAGES_BASE = "https://pvwvuow.github.io/wowheadFA/assets/news"
SITE_ICON = "https://wowfarsi.ir/assets/img/logo.webp"   # آیکون author/footer — URL پایدار سایت اصلی
GOLD = 0xF0B232
UA = "wowfarsi-discord-bot/1.0 (+https://wowfarsi.ir)"
MAX_W = 1600          # سقف عرض تصویر برای حجم پیوست دیسکورد
JPEG_Q = 88

# ---------- تقویم شمسی (همان الگوریتم build_news واو‌فارسی) ----------
FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
J_MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
            "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]


def fa_digits(v):
    return str(v).translate(FA_DIGITS)


def g2j(gy, gm, gd):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) \
        + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1]
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


def fa_date(iso):
    """«۳ آبان ۱۴۰۴»"""
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        jy, jm, jd = g2j(dt.year, dt.month, dt.day)
        return f"{fa_digits(jd)} {J_MONTHS[jm - 1]} {fa_digits(jy)}"
    except Exception:
        return str(iso or "")


# ---------- فید و وضعیت ----------
def load_feed(src):
    if src.startswith("http"):
        req = urllib.request.Request(src, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read().decode("utf-8"))
    with open(src, encoding="utf-8") as f:
        return json.load(f)


def load_state(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"posted": {}}


def save_state(path, st):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    st["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")


# ---------- تصویر و واترمارک ----------
def _fetch_bytes(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()


def _first_local_img(aid):
    """(مسیر تصویر خودمیزبان، ریشه‌ای که پیدا شد) — یا (None, None)."""
    for base in (os.path.join(ROOT, "data", "news-img", str(aid)),
                 os.path.join(ROOT, "docs", "assets", "news", str(aid))):
        if os.path.isdir(base):
            for name in sorted(os.listdir(base)):
                if name.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                    return os.path.join(base, name), base
    return None, None


def prepare_image(article):
    """تصویر آمادهٔ پیوست: jpg با عرض ≤ MAX_W و واترمارک رسمی.
    خروجی: مسیر فایل، یا None اگر خبر تصویری نداشت / تصویر خراب بود."""
    if Image is None:                       # بدون Pillow ارسال بی‌واترمارک
        local, _ = _first_local_img(article["id"])
        return local
    aid = article["id"]
    path, base = _first_local_img(aid)
    stamped = False
    if path is not None:
        # docs = خروجی build_site که خودش watermark_tree زده → دوباره مهر
        # نزنیم؛ data/news-img = نسخهٔ اصلی و تمیز.
        stamped = os.path.join("data", "news-img") not in base
    else:
        thumb = article.get("thumb") or ""
        if not thumb.startswith("http"):
            return None
        fd, path = tempfile.mkstemp(suffix=".img")
        with os.fdopen(fd, "wb") as f:
            f.write(_fetch_bytes(thumb))
        # لینک thumb خودِ ما (Pages) خروجی build_site است → مهر خورده
        stamped = thumb.startswith(PAGES_BASE)

    img = Image.open(path)
    img.load()
    if img.width > MAX_W:
        img = img.resize((MAX_W, max(1, int(img.height * MAX_W / img.width))),
                         Image.LANCZOS)
    if not stamped:
        # واترمارک رسمی صاحب سایت: طلایی روی زمینهٔ تیره، صدفی روی روشن
        # (انتخاب خودکار بر اساس روشنایی ناحیهٔ مهر — tools/watermark.py)
        import watermark
        tmp = os.path.join(tempfile.gettempdir(), f"wf-{aid}-raw.png")
        img.convert("RGBA").save(tmp)
        if watermark.watermark_file(tmp):
            img = Image.open(tmp)
            img.load()
    out = os.path.join(tempfile.gettempdir(), f"wf-{aid}-wm.jpg")
    img.convert("RGB").save(out, "JPEG", quality=JPEG_Q, optimize=True)
    return out


# ---------- embed دیسکورد ----------
def article_link(article):
    mode = os.environ.get("LINK_MODE", "wowfarsi").strip().lower()
    if mode == "pages":
        return article.get("page_url") or article.get("source_url")
    base = os.environ.get("LINK_BASE", DEFAULT_LINK_BASE)
    return base.format(id=article["id"], slug=article.get("slug", "news"))


def build_payload(article, fname=None):
    title = article.get("title_fa") or article.get("title_en") or f"خبر {article['id']}"
    lead = (article.get("lead_fa") or "").strip()
    if len(lead) > 380:
        lead = lead[:377].rsplit(" ", 1)[0].rstrip("،.؛ ") + "…"
    tags = article.get("tags_fa") or []
    cat = article.get("category") or (tags[0] if tags else "اخبار")
    link = article_link(article)
    src = article.get("source_url") or ""
    desc = lead
    if tags:
        desc += "\n\n" + " · ".join(f"**{t}**" for t in tags[:4])

    embed = {
        "author": {
            "name": "وو فارسی | WoWfarsi.ir",
            "url": "https://wowfarsi.ir",
            "icon_url": SITE_ICON,
        },
        "title": title,
        "url": link,
        "description": desc,
        "color": GOLD,
        "fields": [
            {"name": "🗂 دسته", "value": str(cat)[:80], "inline": True},
            {"name": "📅 تاریخ خبر", "value": fa_date(article.get("published_at")) or "—", "inline": True},
        ],
        "footer": {
            "text": "بازنویسی خبر از Wowhead • وو فارسی",
            "icon_url": SITE_ICON,
        },
        "timestamp": article.get("published_at") or None,
    }
    if fname:
        embed["image"] = {"url": f"attachment://{fname}"}
    embed = {k: v for k, v in embed.items() if v is not None}

    components = [{"type": 1, "components": []}]
    if link and link.startswith("http"):
        components[0]["components"].append(
            {"type": 2, "style": 5, "label": "مشاهده خبر در وو فارسی", "url": link})
    if src.startswith("http"):
        components[0]["components"].append(
            {"type": 2, "style": 5, "label": "منبع: Wowhead", "url": src})
    if not components[0]["components"]:
        components = []

    payload = {
        "embeds": [embed],
        "attachments": ([{"id": 0, "filename": fname,
                          "description": str(article.get("title_en") or title)[:200]}]
                        if fname else []),
    }
    mention = os.environ.get("DISCORD_MENTION", "").strip()
    if mention:
        payload["content"] = mention
    if components:
        payload["components"] = components
    return payload


# ---------- ارسال ----------
def post_message(token, channel, payload, img_path=None, fname=None):
    files = None
    data = {"payload_json": json.dumps(payload, ensure_ascii=False)}
    if img_path and fname:
        with open(img_path, "rb") as f:
            img_bytes = f.read()
        files = {"files[0]": (fname, img_bytes, "image/jpeg")}
    headers = {"Authorization": f"Bot {token}",
               "User-Agent": UA}
    for attempt in range(3):
        r = requests.post(f"{API}/channels/{channel}/messages",
                          data=data, files=files, headers=headers, timeout=40)
        if r.status_code == 429:
            time.sleep(min(float(r.json().get("retry_after", 2)) + 0.5, 15))
            continue
        return r
    return r


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=int(os.environ.get("POST_LIMIT", "5")))
    ap.add_argument("--id", type=int, default=None, help="اجبار ارسال یک خبر مشخص")
    ap.add_argument("--mark-posted", action="store_true",
                    help="ثبت همهٔ خبرهای فعلی به‌عنوان فرستاده‌شده، بدون ارسال")
    args = ap.parse_args()

    feed_path = os.environ.get("NEWS_JSON") or os.path.join(ROOT, "docs", "news.json")
    state_path = os.environ.get("STATE_FILE") or os.path.join(ROOT, "data", "discord_state.json")
    channel = os.environ.get("DISCORD_CHANNEL_ID") or DEFAULT_CHANNEL
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()

    feed = load_feed(feed_path)
    articles = sorted(feed.get("published", []),
                      key=lambda a: a.get("published_at") or "", reverse=True)
    by_id = {a["id"]: a for a in articles}
    state = load_state(state_path)
    posted = state.setdefault("posted", {})

    if args.id:
        targets = [by_id[args.id]] if args.id in by_id else []
        if not targets:
            print(f"!! id {args.id} در فید نیست")
            return 1
    elif args.mark_posted:
        for a in articles:
            posted[str(a["id"])] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        save_state(state_path, state)
        print(f"seed: {len(articles)} خبر به‌عنوان فرستاده‌شده ثبت شد → {state_path}")
        return 0
    else:
        pending = [a for a in articles if str(a["id"]) not in posted]
        if (not posted and os.environ.get("POST_ON_FIRST_RUN", "0") != "1"
                and not args.dry_run and not args.mark_posted):
            print(f"first run: {len(pending)} خبر موجود است؛ "
                  "بدون ارسال seed می‌شود (POST_ON_FIRST_RUN=1 برای ارسال همه)")
            for a in articles:
                posted[str(a["id"])] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            save_state(state_path, state)
            return 0
        targets = sorted(pending, key=lambda a: a.get("published_at") or "")[:max(0, args.limit)]

    if args.dry_run:
        print(f"dry-run: {len(targets)} خبر برای ارسال — channel {channel}")
    elif not token:
        print("!! DISCORD_BOT_TOKEN تنظیم نیست — رد شد (کد 0 تا CI قرمز نشود)")
        return 0

    sent = 0
    published_any = False
    for a in targets:
        aid = a["id"]
        fname = f"{aid}-wm.jpg"
        img_path = None
        try:
            img_path = prepare_image(a)
        except Exception as e:
            print(f"   !! تصویر خبر {aid} ناموفق ({type(e).__name__}: {e}) — "
                  "بدون تصویر ارسال می‌شود")
            img_path = None

        if img_path and args.dry_run:
            pv = os.path.join(ROOT, "data", "discord-preview")
            os.makedirs(pv, exist_ok=True)
            shutil.copyfile(img_path, os.path.join(pv, fname))
            print(f"   preview → data/discord-preview/{fname} "
                  f"({os.path.getsize(img_path) // 1024} KB)")
        elif not img_path:
            print(f"   (خبر {aid} تصویری ندارد)")

        payload = build_payload(a, fname=fname if img_path else None)
        if args.dry_run:
            print(f"– [{aid}] {a.get('title_fa', '')[:60]}")
            print(json.dumps(payload, ensure_ascii=False, indent=1)[:1200])
            continue
        r = post_message(token, channel, payload, img_path, fname if img_path else None)
        if r.status_code in (200, 201):
            posted[str(aid)] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            sent += 1
            published_any = True
            print(f"✔ {aid} → کانال {channel} (image=attachment "
                  f"{os.path.getsize(img_path) // 1024} KB)"
                  if img_path else f"✔ {aid} → کانال {channel} (بدون تصویر)")
        else:
            print(f"✘ {aid}: HTTP {r.status_code} {r.text[:200]}")
            if r.status_code in (401, 403, 404):
                break                      # توکن/دسترسی خراب — بی‌خود ادامه نده
        time.sleep(1.2)

    if not args.dry_run:
        if published_any:                  # بدون bump بی‌دلیل timestamp
            save_state(state_path, state)
        print(f"done: {sent} posted | state → {state_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
