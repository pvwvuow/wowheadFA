#!/usr/bin/env python3
"""wowfarsi watermark — stamps every news image with the site brand.

The watermark asset (assets/watermark.png, semi-transparent text baked
once, no font needed at runtime) is composited onto the docs copy of the
news images. Originals in data/news-img stay pristine, and build_site.py
regenerates docs/ from scratch on every run, so a watermark can never be
applied twice.

Usage:
    python tools/watermark.py --all data/news-img     # bulk (dry inspect)
    python tools/watermark.py --file path/to/1.jpg    # single file

build_site.py imports watermark_tree() directly; the CLI is for manual
backfills and testing. If Pillow is missing the caller copies images
through unwatermarked (never breaks the pipeline).
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WM_PATH = os.path.join(ROOT, "assets", "watermark.png")
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}

# sizing rules: watermark width scales with the photo, clamped so small
# thumbnails are not covered and big hero shots do not get a stamp the
# size of a postcode
WIDTH_RATIO = 0.26
MIN_W = 110
MAX_W = 380
MARGIN_RATIO = 0.025
MIN_MARGIN = 10
MIN_IMG_W = 140          # skip tiny icons/avatars
MIN_IMG_H = 100


def watermark_file(path, wm_img=None):
    """Stamp one image in place. Returns True when written, False when
    skipped (too small / unsupported) — raises ImportError without Pillow."""
    from PIL import Image

    ext = os.path.splitext(path)[1].lower()
    if ext not in IMG_EXT:
        return False
    img = Image.open(path)
    img.load()
    w, h = img.size
    if w < MIN_IMG_W or h < MIN_IMG_H:
        return False

    wm = wm_img or Image.open(WM_PATH)
    tw = max(MIN_W, min(MAX_W, round(w * WIDTH_RATIO)))
    th = max(1, round(wm.height * tw / wm.width))
    wm = wm.resize((tw, th), Image.LANCZOS)

    margin = max(MIN_MARGIN, round(w * MARGIN_RATIO))
    x = w - tw - margin
    y = h - th - margin

    base = img.convert("RGBA")
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

    wm = Image.open(WM_PATH)
    n = 0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            p = os.path.join(dirpath, name)
            try:
                if watermark_file(p, wm_img=wm):
                    n += 1
            except Exception as e:  # noqa: BLE001 - one bad image never
                print(f"watermark: skip {p}: {type(e).__name__}: {e}",
                      file=sys.stderr)
    return n


def main():
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
