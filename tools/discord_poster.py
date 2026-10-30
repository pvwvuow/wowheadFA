#!/usr/bin/env python3
"""Discord news bot — wowfarsi.ir (WoW Forever فارسی)

کاری که می‌کند:
  1. فید news.json را می‌خواند (لوکال docs/news.json یا URL) و خبرهای جدید
     نسبت به data/discord_state.json را پیدا می‌کند.
  2. تصویر هر خبر را برمی‌دارد (ترجیحاً نسخهٔ خودمیزبانِ data/news-img/<id>/)
     و واترمارک واو‌فارسی را با انتخاب خودکار واریانت می‌زند:
       پس‌زمینه تیره  → واترمارک سفید
       پس‌زمینه متوسط → واترمارک طلایی (رنگی)
       پس‌زمینه روشن  → واترمارک مینیمال (مشکی)
  3. با توکن ربات، یک embed فارسی + دکمه‌های لینک به کانال مقصد می‌فرستد.
  4. شناسهٔ خبرهای فرستاده‌شده را در data/discord_state.json ثبت می‌کند
     (CI آن را commit می‌کند تا خبر تکراری نفرستد).

CLI:
  python3 tools/discord_poster.py                 # اجرای عادی (CI)
  python3 tools/discord_poster.py --dry-run       # همه‌چیز به‌جز ارسال
  python3 tools/discord_poster.py --limit 3       # حداکثر ۳ خبر در هر اجرا
  python3 tools/discord_poster.py --id 383659     # اجبارِ ارسال یک خبر مشخص
  python3 tools/discord_poster.py --mark-posted   # فقط ثبت وضعیت فعلی بدون ارسال

Env:
  DISCORD_BOT_TOKEN   توکن ربات (بدون آن، خروج با پیام و کد 0 انجام می‌شود)
  DISCORD_CHANNEL_ID  کانال مقصد (پیش‌فرض: چنل خبر wowfarsi)
  NEWS_JSON           مسیر/URL فید (پیش‌فرض: docs/news.json در همین ریپو)
  STATE_FILE          پیش‌فرض data/discord_state.json
  WATERMARK_DIR       پیش‌فرض assets/watermark
  POST_ON_FIRST_RUN   اگر "1" باشد در اولین اجرا همهٔ خبرهای موجود را می‌فرستد
                      (پیش‌فرض 0 = اولین اجرا فقط وضعیت را seed می‌کند)
  LINK_MODE           wowfarsi (پیش‌فرض) | pages  — مقصد دکمهٔ «مشاهده خبر»
"""
import argparse
import json
import os
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
GOLD = 0xF0B232
UA = "wowfarsi-discord-bot/1.0 (+https://wowfarsi.ir)"

WM_VARIANTS = {          # (فایل، آلفا)
    "white":  ("wf-white.png", 0.92),
    "golden": ("wf-golden.png", 0.94),
    "minimal": ("wf-minimal.png", 0.90),
}

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


# ---------- واترمارک ----------
def _fetch_bytes(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()


def source_image(article):
    """بهترین نسخهٔ تصویر خبر: فایل خودمیزبان لوکال، وگرنه thumb فید."""
    aid = article["id"]
    for base in (os.path.join(ROOT, "data", "news-img", str(aid)),
                 os.path.join(ROOT, "docs", "assets", "news", str(aid))):
        if os.path.isdir(base):
            for name in sorted(os.listdir(base)):
                if name.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                    return os.path.join(base, name)
    thumb = article.get("thumb") or ""
    if thumb.startswith("http"):
        data = _fetch_bytes(thumb)
        fd, p = tempfile.mkstemp(suffix=".img")
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        return p
    return None


def pick_variant(img):
    """روشناییِ ناحیهٔ پایین-راست (جای واترمارک) → واریانت مناسب."""
    w, h = img.size
    region = img.convert("L").crop((int(w * 0.55), int(h * 0.70), w, h))
    hist = region.histogram()
    total = sum(hist) or 1
    mean = sum(i * c for i, c in enumerate(hist)) / total
    if mean < 105:
        return "white"
    if mean > 175:
        return "minimal"
    return "golden"


def watermark_image(src_path, out_path, wm_dir):
    base = Image.open(src_path).convert("RGBA")
    if base.width > 1600:                       # سقف حجم برای دیسکورد
        nh = int(base.height * 1600 / base.width)
        base = base.resize((1600, nh), Image.LANCZOS)
    variant = pick_variant(base)
    fname, alpha = WM_VARIANTS[variant]
    wm = Image.open(os.path.join(wm_dir, fname)).convert("RGBA")
    bbox = wm.getbbox()
    if bbox:
        wm = wm.crop(bbox)
    tw = max(150, min(460, int(base.width * 0.26)))
    wm = wm.resize((tw, max(1, int(wm.height * tw / wm.width))), Image.LANCZOS)
    if alpha < 1.0:
        a = wm.getchannel("A").point(lambda v: int(v * alpha))
        wm.putalpha(a)
    mx = max(14, int(base.width * 0.025))
    px = base.width - wm.width - mx
    py = base.height - wm.height - mx
    if px < 0 or py < 0:                        # تصویر خیلی کوچک
        wm = wm.resize((max(1, base.width // 3), max(1, base.height // 3)), Image.LANCZOS)
        px = base.width - wm.width - 10
        py = base.height - wm.height - 10
    base.alpha_composite(wm, (px, py))
    base.convert("RGB").save(out_path, "JPEG", quality=88, optimize=True)
    return variant, out_path


# ---------- embed دیسکورد ----------
def article_link(article):
    mode = os.environ.get("LINK_MODE", "wowfarsi").strip().lower()
    if mode == "pages":
        return article.get("page_url") or article.get("source_url")
    base = os.environ.get("LINK_BASE", DEFAULT_LINK_BASE)
    return base.format(id=article["id"], slug=article.get("slug", "news"))


def build_payload(article, fname=None, image_url=None):
    aid = article["id"]
    title = article.get("title_fa") or article.get("title_en") or f"خبر {aid}"
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
            "icon_url": "https://pvwvuow.github.io/wowheadFA/assets/watermark/wf-golden.png",
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
            "icon_url": "https://pvwvuow.github.io/wowheadFA/assets/watermark/wf-golden.png",
        },
        "timestamp": article.get("published_at") or None,
    }
    if image_url:
        embed["image"] = {"url": image_url}
    elif fname:
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
                        if (fname and not image_url) else []),
    }
    mention = os.environ.get("DISCORD_MENTION", "").strip()
    if mention:
        payload["content"] = mention
    if components:
        payload["components"] = components
    return payload


# ---------- انتشار تصویر واترمارک‌خورده روی گیت‌هاب خودمان ----------
PAGES_BASE = "https://pvwvuow.github.io/wowheadFA/assets/news"


def publish_images_to_git():
    """تصاویر واترمارک‌خوردهٔ docs/assets/news را commit+push می‌کند (فقط CI).
    برمی‌گرداند True اگر push موفق بود."""
    if not os.path.isdir(os.path.join(ROOT, ".git")):
        return False
    import subprocess
    try:
        subprocess.run(["git", "config", "user.name", "wowfarsi-bot"], cwd=ROOT, check=True)
        subprocess.run(["git", "config", "user.email", "bot@wowfarsi.ir"], cwd=ROOT, check=True)
        subprocess.run(["git", "add", "docs/assets/news"], cwd=ROOT, check=True)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode == 0:
            return True                                   # چیزی تازه نیست
        subprocess.run(["git", "commit", "-m",
                        "discord: watermarked images [skip ci]"], cwd=ROOT, check=True)
        for attempt in range(3):
            subprocess.run(["git", "pull", "--no-rebase", "origin", "main"], cwd=ROOT,
                           check=False, capture_output=True)
            p = subprocess.run(["git", "push", "origin", "main"], cwd=ROOT,
                               capture_output=True)
            if p.returncode == 0:
                return True
            time.sleep(4)
        return False
    except Exception as e:
        print(f"   !! انتشار تصاویر روی گیت‌هاب ناموفق: {e}")
        return False


def wait_url_ready(url, timeout_s=150, step=12):
    """منتظر 200 شدن URL تصویر (تاخیر دیپلوی Pages) — تا سقف timeout_s."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(step)
    return False


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
    wm_dir = os.environ.get("WATERMARK_DIR") or os.path.join(ROOT, "assets", "watermark")
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
    wm_files = []
    variants = {}
    for a in targets:
        aid = a["id"]
        fname = f"{aid}-wm.jpg"
        img_path = None
        try:
            src = source_image(a)
            if src:
                img_path = os.path.join(tempfile.gettempdir(), f"wf-{fname}")
                variant, img_path = watermark_image(src, img_path, wm_dir)
                variants[aid] = variant
                if args.dry_run:
                    pv = os.path.join(ROOT, "data", "discord-preview")
                    os.makedirs(pv, exist_ok=True)
                    import shutil
                    shutil.copyfile(img_path, os.path.join(pv, fname))
                    print(f"   preview → {pv}/{fname} (variant={variant})")
                else:
                    # نسخهٔ دائمی برای سرو از GitHub Pages خودمان
                    docs_dir = os.path.join(ROOT, "docs", "assets", "news", str(aid))
                    os.makedirs(docs_dir, exist_ok=True)
                    import shutil
                    shutil.copyfile(img_path, os.path.join(docs_dir, "wm.jpg"))
                    wm_files.append(str(aid))
        except Exception as e:
            print(f"   !! تصویر خبر {aid} ناموفق ({e}) — بدون تصویر ارسال می‌شود")
            img_path = None

    # اگر تصویر تازه‌ای ساخته شد، اول روی گیت‌هاب خودمان ببرش تا embed لینک مستقیم داشته باشد
    use_pages = False
    if wm_files and not args.dry_run:
        use_pages = publish_images_to_git()
        if use_pages:
            print(f"images published to git: {', '.join(wm_files)}")
        else:
            print("!! انتشار تصویر روی Pages ناموفق → fallback به پیوست دیسکورد")

    for a in targets:
        aid = a["id"]
        fname = f"{aid}-wm.jpg"
        img_path = os.path.join(tempfile.gettempdir(), f"wf-{fname}")
        if not os.path.exists(img_path):
            img_path = None
        image_url = None
        if use_pages and os.path.exists(os.path.join(ROOT, "docs", "assets", "news",
                                                     str(aid), "wm.jpg")):
            image_url = f"{PAGES_BASE}/{aid}/wm.jpg"
            if not wait_url_ready(image_url):
                print(f"   !! URL تصویر {aid} آماده نشد → fallback به پیوست")
                image_url = None

        payload = build_payload(a, fname=fname if img_path else None, image_url=image_url)
        if args.dry_run:
            print(f"– [{aid}] {a.get('title_fa', '')[:60]}")
            print(json.dumps(payload, ensure_ascii=False, indent=1)[:1200])
            continue
        r = post_message(token, channel, payload, img_path if not image_url else None,
                         fname if (img_path and not image_url) else None)
        if r.status_code in (200, 201):
            posted[str(aid)] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            sent += 1
            published_any = True
            print(f"✔ {aid} → کانال {channel} (variant={variants.get(aid)}, "
                  f"image={'pages-url' if image_url else 'attachment'})")
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
