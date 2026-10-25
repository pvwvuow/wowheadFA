#!/usr/bin/env python3
"""
qa_check.py - deterministic QA gates for WowheadFA articles.

Gates (all fail -> exit 1, issue list printed):
  G1  Persian ratio        >= 55% Persian chars in lead+body
  G2  Arabic chars         no ي ك (must be Persian ی ک)
  G3  English runs         no run of >12 consecutive English words
                           (proper nouns we keep are single words, fine)
  G4  numbers preserved    every salient number from the source appears
                           in the article (hallucination/fact-drop guard)
  G5  entity whitelist     English tokens in article must exist in the
                           source vocabulary or builtin allowlist
                           (no invented names)
  G6  typography           no "می " + letter (needs ZWNJ), no double
                           spaces, no space before ،؛:!., no markdown
                           artifacts, no HTML tags
  G7  shape                title 15..110 chars, lead 20..400 chars,
                           body 2..8 paragraphs each >=40 chars,
                           tags 0..5, source_url is a wowhead news link
  G8  not near-copy        self-duplication between lead and body
                           sentences

COPYRIGHT: source text is no longer stored in article JSONs. G4/G5 run
against qa_facts = {numbers, entities, chars} extracted at fetch time
(uncopyrightable facts). If an old JSON still carries source_text, it
is used as a fallback so mixed states keep passing.

Usage:  python tools/qa_check.py data/articles/383566.json
        python tools/qa_check.py --all          # every drafted/published
Exit 0 = all checked files pass.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FA = re.compile(r"[\u0600-\u06FF]")
ALLOW = {
    "wow", "wowhead", "blizzard", "ptr", "beta", "mythic", "mythic+",
    "pvp", "pve", "raid", "dungeon", "addon", "addons", "hotfix",
    "hotfixes", "nerf", "nerfs", "buff", "buffs", "tier", "set", "token",
    "patch", "class", "spec", "specs", "tank", "healer", "dps", "cc",
    "aoe", "dot", "ddos", "blizzcon", "crossfade", "trading", "post",
    "shop", "cash", "xp", "exp", "level", "leveling", "renown", "gear",
    "ilvl", "cooldown", "cd", "mobs", "boss", "bosses", "world", "drop",
    "drops", "loot", "quest", "quests", "weekly", "reset", "season",
    "season", "potion", "potions", "elixir", "flask", "food", "feast",
    "augment", "rune", "enchant", "gem", "catalyst", "great", "vault",
    "delves", "delve", "keys", "key", "crest", "crests", "flight",
    "stones", "whisper", "fractured", "paths", "midnight", "forever",
    "hallow", "end", "hallows", "end", "event", "events", "sale",
    "sales", "store", "mount", "mounts", "pet", "pets", "toy", "toys",
    "transmog", "set", "hr", "anniversary", "classic", "hardcore",
    "sanctum", "domains", "sha", "sha", "soridormi", "cache", "infinity",
}


def fa_ratio(text: str) -> float:
    letters = re.findall(r"[A-Za-z\u0600-\u06FF]", text)
    if not letters:
        return 0.0
    fa = sum(1 for c in letters if FA.match(c))
    return fa / len(letters)


def numbers_of(text: str) -> set:
    out = set()
    for m in re.finditer(r"\d[\d.,:%]*\d|\d", text):
        s = m.group(0).strip(".,")
        if len(s) >= 2:
            out.add(s)
    return out


def english_tokens(text: str) -> set:
    text = text.replace("\u2019", "'").replace("\u2018", "'")  # curly -> straight
    return {t.lower().strip(".,:;!?()[]{}\"'") for t in re.findall(
        r"[A-Za-z][A-Za-z+.'-]*", text)}


def check(path: str) -> list:
    art = json.load(open(path, encoding="utf-8"))
    issues = []
    a = art.get("article_fa") or {}
    title = a.get("title_fa", "").strip()
    lead = a.get("lead_fa", "").strip()
    body = [b.strip() for b in a.get("body_fa", []) if b.strip()]
    tags = a.get("tags_fa", [])
    whole = "\n".join([title, lead] + body)
    src = art.get("source_text", "")
    facts = art.get("qa_facts") or {}

    # G1
    r = fa_ratio(whole)
    if r < 0.55:
        issues.append(f"G1 Persian ratio {r:.0%} < 55%")
    # G2
    for ch, name in (("ي", "Arabic Yeh"), ("ك", "Arabic Kaf")):
        if ch in whole:
            issues.append(f"G2 contains {name} - use Persian ی/ک")
    # G3
    for run in re.findall(r"[A-Za-z][A-Za-z0-9+.'-]*(?:\s+[A-Za-z][A-Za-z0-9+.'-]*){12,}", whole):
        issues.append(f"G3 long English run: {run[:70]}...")
    # G4 - salient numbers must appear in the article.
    # Preferred data: qa_facts.numbers (precomputed at fetch time).
    # Fallback: derive from source_text if an old JSON still has it.
    if facts.get("numbers") is not None:
        salient = set(facts["numbers"])
    elif src:
        nums = numbers_of(src)
        salient = {n for n in nums
                   if n in art.get("title_en", "")
                   or nums and list(nums).count(n) >= 1
                   and src.count(n) >= 2
                   or "." in n or "%" in n}
        if len(src) < 1500:          # short source: keep everything
            salient = nums
    else:
        salient = set()
    if salient:
        def tolerated(n: str) -> bool:
            fa = n.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
            if n in whole or fa in whole:
                return True
            if n.endswith("%") and (fa.rstrip("%") + " درصد") in whole:
                return True
            if n.endswith("%") and (n.rstrip("%") + " percent") in whole:
                return True
            return False

        missing = {n for n in salient if not tolerated(n)}
        if missing:
            issues.append("G4 numbers from source missing in article: "
                          + ", ".join(sorted(missing)[:8]))
    # G5 - English tokens must exist in the source vocabulary
    # (qa_facts.entities preferred, source_text fallback)
    if facts.get("entities") is not None:
        src_tokens = set(facts["entities"])
    elif src:
        src_tokens = english_tokens(src)
    else:
        src_tokens = None        # no reference at all - skip gate
    if src_tokens is not None:
        for t in english_tokens(whole):
            if t not in src_tokens and t not in ALLOW and len(t) > 2 \
                    and not t.isdigit() and "+" not in t:
                issues.append(f"G5 English token not in source: {t}")
    # G6
    if re.search(r"\bمی\s+[آابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی]", whole):
        issues.append("G6 'می ' with space - use نیم‌فاصله (می‌شود)")
    if "  " in whole:
        issues.append("G6 double space")
    if re.search(r"\s[،؛:!]", whole):
        issues.append("G6 space before punctuation")
    if re.search(r"(\*\*|##|\[\]|<\/?[a-z]+>)", whole):
        issues.append("G6 markdown/HTML artifact")
    # G7
    if not (15 <= len(title) <= 110):
        issues.append(f"G7 title length {len(title)} not in 15..110")
    if not (20 <= len(lead) <= 400):
        issues.append(f"G7 lead length {len(lead)} not in 20..400")
    if not (2 <= len(body) <= 8) or any(len(b) < 40 for b in body):
        issues.append("G7 body: need 2..8 paragraphs, each >=40 chars")
    if not (0 <= len(tags) <= 5):
        issues.append("G7 tags count > 5")
    if not re.match(r"https://(www\.)?wowhead\.com/news", art.get("url", "")):
        issues.append("G7 source_url is not a wowhead news link")
    # G8 lead duplication
    lead_sents = {re.sub(r"\s+", " ", s.lower()) for s in
                  re.split(r"[.!؟\n]", lead) if len(s) > 25}
    body_sents = {re.sub(r"\s+", " ", s.lower()) for b in body for s in
                  re.split(r"[.!؟\n]", b) if len(s) > 25}
    dup = lead_sents & body_sents
    if dup:
        issues.append("G8 lead sentence duplicated in body")
    return issues


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--all":
        files = [os.path.join(ROOT, "data", "articles", f)
                 for f in sorted(os.listdir(os.path.join(ROOT, "data", "articles")))
                 if f.endswith(".json")]
    else:
        files = sys.argv[1:]
    bad = 0
    for f in files:
        art = json.load(open(f, encoding="utf-8"))
        if art.get("status") == "new":
            print(f"{os.path.basename(f)}: skipped (status=new)")
            continue
        issues = check(f)
        if issues:
            bad += 1
            print(f"{os.path.basename(f)}: FAIL")
            for i in issues:
                print(f"   - {i}")
        else:
            print(f"{os.path.basename(f)}: OK")
    print(f"\n{len(files)} checked, {bad} failing")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
