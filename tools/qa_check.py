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
                           artifacts, no HTML tags, no CJK/foreign-
                           script artifacts (Chinese/Japanese/Korean
                           glyphs leaked into Persian prose)
  G7  shape                title 15..110 chars, lead 20..400 chars,
                           body 2..14 v2 blocks (plain paragraphs >=40
                           chars), tags 0..5, wowhead news source_url
  G9  v2 blocks            body_fa dict blocks are well-formed (types,
                           required fields; see config/prompt.md v2)
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


def _stem(t: str) -> str:
    """Crude plural/singular normalizer so 'legendary' matches
    'legendaries' etc. Only used for the G5 membership test."""
    if t.endswith("ies") and len(t) > 4:
        return t[:-3] + "y"
    if t.endswith("es") and len(t) > 4 and not t.endswith("ses"):
        return t[:-2]
    if t.endswith("s") and not t.endswith("ss") and len(t) > 3:
        return t[:-1]
    return t


def _variants(t: str) -> set:
    """All plural/adverb-ish variants of a token; two tokens match G5
    when their variant sets intersect (charge/charges, retroactive/
    retroactively, legendary/legendaries)."""
    out = {t}
    st = _stem(t)
    out.add(st)
    if t.endswith("ly") and len(t) > 4:
        out.add(t[:-2])                    # retroactively -> retroactive
    if st.endswith("ly") and len(st) > 4:
        out.add(st[:-2])
    if t.endswith("es") and len(t) > 4:    # charges -> charge (s-strip too)
        out.add(t[:-1])
    if t.endswith("ies") and len(t) > 4:
        out.add(t[:-3])
    if "-" in t:                           # lore-related -> lore, related...
        parts = [p for p in t.split("-") if p]
        out.update(parts)
        out.add("".join(parts))
    return out


# ---- v2 body blocks (see config/prompt.md): strings are paragraphs,
# dicts are structured blocks. QA gates run on the flattened text. ----
KNOWN_T = {"p", "h", "ul", "ol", "quote", "note", "table", "img", "item"}
MARKER = re.compile(r"\[\[item:([^\]|]+?)(?:\|([^\]]+))?\]\]")


def block_texts(x):
    """yield every plain-text piece of a body_fa entry (str or dict block)"""
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        t = x.get("t")
        if t in ("p", "h", "quote", "note") and isinstance(x.get("x"), str):
            yield x["x"]
        if t in ("ul", "ol") and isinstance(x.get("xs"), list):
            for i in x["xs"]:
                if isinstance(i, str):
                    yield i
        if t == "table":
            for h in x.get("head") or []:
                if isinstance(h, str):
                    yield h
            for r in x.get("rows") or []:
                if isinstance(r, list):
                    for c in r:
                        if isinstance(c, str):
                            yield c


def block_issues(body):
    """G9: shape validation of v2 blocks (empty list = ok)"""
    iss = []
    for n, b in enumerate(body):
        if isinstance(b, str):
            continue
        if not isinstance(b, dict):
            iss.append(f"G9 block {n + 1} is not a string or object")
            continue
        t = str(b.get("t") or "").lower()
        if t not in KNOWN_T:
            iss.append(f"G9 block {n + 1}: unknown type {t!r}")
            continue
        if t in ("p", "h", "quote", "note"):
            if not str(b.get("x") or "").strip():
                iss.append(f"G9 block {n + 1}: {t} needs non-empty x")
            if t == "note" and str(b.get("kind") or "tip") not in ("tip", "warn", "info"):
                iss.append(f"G9 block {n + 1}: note kind must be tip|warn|info")
        elif t in ("ul", "ol"):
            xs = b.get("xs")
            if not (isinstance(xs, list) and len(xs) >= 2):
                iss.append(f"G9 block {n + 1}: {t} needs xs list (2+)")
        elif t == "table":
            if not (isinstance(b.get("head"), list) and isinstance(b.get("rows"), list)
                    and b["head"] and b["rows"]):
                iss.append(f"G9 block {n + 1}: table needs head + rows")
        elif t == "img":
            if not re.match(r"^https://", str(b.get("src") or "")):
                iss.append(f"G9 block {n + 1}: img src must be https")
        elif t == "item":
            ids = b.get("ids") or ([b.get("id")] if b.get("id") is not None else [])
            if not ids and not str(b.get("name") or "").strip():
                iss.append(f"G9 block {n + 1}: item needs id/ids/name")
    return iss


def strip_markers(text):
    """[[item:Name|label]] -> label (for punctuation/markup gates)"""
    return MARKER.sub(lambda m: (m.group(2) or m.group(1)).strip(), text)


def flat_body_text(body):
    """all body text; markers flattened so G4/G5 still see the names"""
    out = []
    for b in body:
        for t in block_texts(b):
            out.append(MARKER.sub(lambda m: " ".join(
                filter(None, (m.group(1).strip(), (m.group(2) or "").strip()))), t))
    return "\n".join(out)


def card_texts(art: dict) -> str:
    """Plain text of the structured item-card blocks (items[]), if any."""
    try:
        from item_cards import cards_text
        return cards_text(art.get("items") or [])
    except Exception:
        return ""


def check(path: str) -> list:
    art = json.load(open(path, encoding="utf-8"))
    issues = []
    a = art.get("article_fa") or {}
    title = a.get("title_fa", "").strip()
    lead = a.get("lead_fa", "").strip()
    body = a.get("body_fa", [])
    if isinstance(body, str):
        body = [b for b in re.split(r"\n\s*\n", body) if b.strip()]
    # v2: strings are paragraphs; dicts are structured blocks. Plain-string
    # paragraphs (plus quote/note text) feed the prose-shape gates (G7/G8).
    paras = [b.strip() for b in body if isinstance(b, str) and b.strip()]
    paras += [str(b.get("x")).strip() for b in body
              if isinstance(b, dict) and b.get("t") in ("quote", "note")
              and str(b.get("x") or "").strip()]
    tags = a.get("tags_fa", [])
    # item-card blocks are deterministic code-rendered facts; their text
    # participates in G1..G6 but not in the prose-shape gates (G7/G8).
    items_txt = card_texts(art)
    whole = "\n".join([title, lead, flat_body_text(body)]
                      + ([items_txt] if items_txt else []))
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
        # the English title is part of the source too
        src_tokens = set(src_tokens) | english_tokens(
            art.get("title_en", ""))
        src_variants = set()
        for t in src_tokens:
            src_variants |= _variants(t)
        for t in english_tokens(whole):
            if not (_variants(t) & src_variants) and t not in ALLOW \
                    and len(t) > 2 and not t.isdigit() and "+" not in t:
                issues.append(f"G5 English token not in source: {t}")
    # G6
    if re.search(r"\bمی\s+[آابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی]", whole):
        issues.append("G6 'می ' with space - use نیم‌فاصله (می‌شود)")
    if "  " in whole:
        issues.append("G6 double space")
    if re.search(r"\s[،؛:!]", whole):
        issues.append("G6 space before punctuation")
    # [[item:...]] markers are legal v2 syntax - anything else is an artifact
    if re.search(r"(\[\[(?!item:)|\*\*|##|<\/?[a-z]+>)", strip_markers(whole)):
        issues.append("G6 markdown/HTML artifact")
    cjk = re.findall(r"[\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]+", whole)
    if cjk:
        issues.append("G6 CJK characters leaked into Persian prose: "
                      + ", ".join(c[:10] for c in cjk[:4]))
    # G7
    if not (15 <= len(title) <= 110):
        issues.append(f"G7 title length {len(title)} not in 15..110")
    if not (20 <= len(lead) <= 400):
        issues.append(f"G7 lead length {len(lead)} not in 20..400")
    if not (2 <= len(body) <= 14):
        issues.append(f"G7 body: need 2..14 blocks (got {len(body)})")
    elif any(len(b) < 40 for b in paras):
        issues.append("G7 body: plain paragraphs must be >=40 chars")
    if not (0 <= len(tags) <= 5):
        issues.append("G7 tags count > 5")
    if not re.match(r"https://(www\.)?wowhead\.com/news", art.get("url", "")):
        issues.append("G7 source_url is not a wowhead news link")
    # G9 (v2 block shape)
    issues += block_issues(body)
    # G8 lead duplication (dots between digits are NOT sentence ends:
    # "پچ 12.1.7" must not be split into fragments)
    SENT_END = re.compile(r"(?<!\d)\.|[!؟\n]")
    lead_sents = {re.sub(r"\s+", " ", s.lower()) for s in
                  SENT_END.split(lead) if len(s) > 25}
    body_sents = {re.sub(r"\s+", " ", s.lower()) for b in paras for s in
                  SENT_END.split(b) if len(s) > 25}
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
