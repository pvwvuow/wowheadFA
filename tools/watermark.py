#!/usr/bin/env python3
"""wowfarsi watermark — stamps every news image with the site brand.

Two official logo variants (supplied by the site owner, 2026-10-31):

  assets/watermark/logo-gold.png    golden WF emblem  -> DARK backgrounds
  assets/watermark/logo-ivory.png   ivory/silver WF   -> LIGHT backgrounds

watermark_file() samples the mean luminance of the actual stamp region
and picks the variant that stays readable there. Originals in
data/news-img stay pristine, and build_site.py regenerates docs/ from
scratch on every run, so a watermark can never be applied twice.

If the logo files are missing the code falls back to the legacy
assets/watermark.png banner; without Pillow the caller copies images
through unwatermarked (never breaks the pipeline).

Usage:
    python tools/watermark.py --all data/news-img     # bulk (dry inspect)
    python tools/watermark.py --file path/to/1.jpg    # single file

build_site.py imports watermark_tree() directly; the CLI is for manual
backfills and testing.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WM_DIR = os.path.join(ROOT, "assets", "watermark")
WM_GOLD = os.path.join(WM_DIR, "logo-gold.png")      # dark backgrounds
WM_IVORY = os.path.join(WM_DIR, "logo-ivory.png")    # light backgrounds
WM_PATH = os.path.join(ROOT, "assets", "watermark.png")   # legacy fallback
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}

# sizing rules: the emblem is roughly square, so it needs a smaller width
# ratio than the old wide text banner; clamped so small thumbnails are not
# covered and big hero shots do not get a stamp the size of a postcode
WIDTH_RATIO = 0.16
MIN_W = 90
MAX_W = 240
MARGIN_RATIO = 0.03
MIN_MARGIN = 12
MIN_IMG_W = 140          # skip tiny icons/avatars
MIN_IMG_H = 100
LUM_THRESHOLD = 128      # region mean < threshold -> gold, else ivory


def _region_luma(img, x, y, w, h):
    """Mean 0..255 luminance of the (downsampled) stamp region."""
    from PIL import Image

    box = img.crop((max(0, x), max(0, y), max(0, x) + w, max(0, y) + h))
    box = box.convert("L")
    box.thumbnail((64, 64))
    px = list(box.getdata())
    return sum(px) / max(1, len(px))


def _load_logos():
    """(gold, ivory, fallback) - only existing files are returned."""
    from PIL import Image

    gold = ivory = None
    if os.path.exists(WM_GOLD):
        gold = Image.open(WM_GOLD)
        gold.load()
    if os.path.exists(WM_IVORY):
        ivory = Image.open(WM_IVORY)
        ivory.load()
    if gold is None and ivory is None and os.path.exists(WM_PATH):
        legacy = Image.open(WM_PATH)
        legacy.load()
        return None, None, legacy
    return gold, ivory, None


def watermark_file(path, wm_img=None):
    """Stamp one image in place. Returns True when written, False when
    skipped (too small / unsupported) — raises ImportError without Pillow.
    `wm_img` overrides logo selection entirely (kept for manual tests)."""
    from PIL import Image

    ext = os.path.splitext(path)[1].lower()
    if ext not in IMG_EXT:
        return False
    img = Image.open(path)
    img.load()
    w, h = img.size
    if w < MIN_IMG_W or h < MIN_IMG_H:
        return False

    tw = max(MIN_W, min(MAX_W, round(w * WIDTH_RATIO)))
    margin = max(MIN_MARGIN, round(w * MARGIN_RATIO))
    x = w - tw - margin
    y = max(margin, h - round(tw * 1.1) - margin)   # emblem ~square+text

    if wm_img is not None:
        wm = wm_img
    else:
        gold, ivory, legacy = _load_logos()
        if legacy is not None:
            wm = legacy
        elif gold is not None and ivory is not None:
            luma = _region_luma(img, x, y, tw, tw)
            wm = gold if luma < LUM_THRESHOLD else ivory
        else:
            wm = gold or ivory
        if wm is None:
            return False
    th = max(1, round(wm.height * tw / wm.width))
    wm = wm.resize((tw, th), Image.LANCZOS)

    base = img.convert("RGBA")
    # keep the stamp inside the canvas even for tall emblems
    y = max(0, min(y, h - th - 1))
    base.alpha_composite(wm, (x, y))

    if ext in (".jpg", ".jpeg"):
        base.convert("RGB").save(path, quality=88, optimize=True)
    elif ext == ".png":
        base.save(path, optimize=True)
    elif ext == ".webp":
        base.save(path, quality=88, method=4)
    return True


def watermark_tree(root):
    """Stamp every image under root (in place). Returns count written."""
    from PIL import Image  # noqa: F401  (fail fast if pillow is missing)

    _gold, _ivory, _legacy = _load_logos()
    n = 0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            p = os.path.join(dirpath, name)
            try:
                if watermark_file(p):
                    n += 1
            except Exception as e:  # noqa: BLE001 - one bad image never
                print(f"watermark: skip {p}: {type(e).__name__}: {e}",
                      file=sys.stderr)
    return n


def main():
    import argparse
    ap = argparse.ArgumentParser(description="stamp the wowfarsi watermark")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--file", help="stamp a single image in place")
    g.add_argument("--all", dest="all_dir", help="stamp every image in a tree")
    args = ap.parse_args()
    if args.file:
        ok = watermark_file(args.file)
        print("stamped" if ok else "skipped (size/unsupported)")
        return 0
    print(f"stamped {watermark_tree(args.all_dir)} image(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
