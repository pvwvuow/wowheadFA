#!/usr/bin/env python3
"""One-time migration: data/articles/*.json source_text -> qa_facts.

For every article JSON:
  1. build qa_facts {numbers, entities, chars} from the current
     source_text (salient-number rule mirrors fetch_news.make_qa_facts)
  2. DELETE the source_text field (copyright: never persist source)
Keeps article_fa, metadata, generator untouched.

Run from repo root:  python scripts/migrate_strip_source.py
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "data", "articles")


def numbers_of(text):
    out = set()
    for m in re.finditer(r"\d[\d.,:%]*\d|\d", text):
        s = m.group(0).strip(".,")
        if len(s) >= 2:
            out.add(s)
    return out


def english_tokens(text):
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    return {t.lower().strip(".,:;!?()[]{}\"'") for t in re.findall(
        r"[A-Za-z][A-Za-z+.'-]*", text)}


def make_qa_facts(text, title_en):
    nums = numbers_of(text)
    if len(text) < 1500:
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


def main():
    if not os.path.isdir(ART):
        print("no data/articles dir", file=sys.stderr)
        return 2
    changed = 0
    for fn in sorted(os.listdir(ART)):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(ART, fn)
        art = json.load(open(path, encoding="utf-8"))
        src = art.get("source_text") or ""
        if src:
            art["qa_facts"] = make_qa_facts(src, art.get("title_en", ""))
        art.pop("source_text", None)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(art, fh, ensure_ascii=False, indent=1)
        changed += 1
        f = art.get("qa_facts") or {}
        print(f"{fn}: facts={len(f.get('numbers', []))} nums, "
              f"{len(f.get('entities', []))} tokens"
              + ("" if src else " (no source text present)"))
    print(f"\nmigrated {changed} files - source_text removed everywhere")
    return 0


if __name__ == "__main__":
    sys.exit(main())
