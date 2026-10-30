#!/usr/bin/env python3
"""
write_article.py - BYOK AI writer for WowheadFA.

Reads a fetched article JSON (status=new), gets the source text (from
the JSON if a legacy field exists, otherwise re-fetches it from the
Wowhead URL - TRANSIENT, memory only), sends it to the model WITH OUR
system prompt + glossary rules, writes an original Persian article back
into the JSON (status=drafted) and runs the QA gates.

COPYRIGHT: the English source text is never persisted. After writing,
the JSON keeps only article_fa + qa_facts (numbers/entities facts for
qa_check G4/G5); any legacy source_text field is stripped.

The API key stays on the writer's machine - nothing is sent anywhere
except the model provider they chose.

Providers (any ONE of):
  --provider openai     --base-url https://api.openai.com/v1 --model gpt-4o-mini
  --provider anthropic  --model claude-sonnet-4-20250514
  --provider compat     --base-url http://localhost:1234/v1  (any OpenAI-compatible)

Keys via --key or env: OPENAI_API_KEY / ANTHROPIC_API_KEY.

Usage:
  python tools/write_article.py --id 383566 --provider openai \
      --model gpt-4o-mini
  python tools/write_article.py --all --provider compat \
      --base-url http://localhost:1234/v1 --model my-model
"""
import argparse
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_news as FN  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "data", "articles")
PROMPT = os.path.join(ROOT, "config", "prompt.md")

OUTPUT_SPEC = (
    "Return ONLY this JSON (no fences, no commentary). body_fa is an array of "
    "plain-string paragraphs AND v2 blocks (see the system prompt): "
    '{"t":"h","x":"..."} heading, {"t":"ul","xs":[...]} list, '
    '{"t":"quote","x":"...","by":"..."}, {"t":"note","x":"...","kind":"tip|warn|info"}, '
    '{"t":"table","head":[...],"rows":[[...]]}, {"t":"item","id":123} for the '
    "article's main items (id only from the source's own item links), plus "
    "inline [[item:Exact EN Name]] markers inside any string. Never translate "
    "item names, never invent ids.\n"
    '{"title_fa": "...", "lead_fa": "...", "body_fa": ["...", {...]},'
    ' "tags_fa": ["...", "..."]}\n\n'
    "ARTICLE SOURCE TEXT (Wowhead):\n"
)


def call_openai_compat(base_url, key, model, system, user, timeout=180):
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps({
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": 0.4,
        }).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    return data["choices"][0]["message"]["content"]


def call_anthropic(key, model, system, user, timeout=180):
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps({
            "model": model, "max_tokens": 4000, "temperature": 0.4,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }).encode(),
        headers={"Content-Type": "application/json",
                 "x-api-key": key,
                 "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    return "".join(b.get("text", "") for b in data["content"])


def parse_json_reply(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(),
                  flags=re.M).strip()
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ValueError("model did not return JSON")
    return json.loads(m.group(0))


def norm_blocks(body):
    """v2 body_fa: keep plain strings and well-formed block dicts, drop junk.
    (Deep validation is qa_check's G9 job; here we only survive garbage.)"""
    out = []
    for b in body or []:
        if isinstance(b, str) and b.strip():
            out.append(b.strip())
        elif isinstance(b, dict) and isinstance(b.get("t"), str) \
                and b.get("t").strip():
            out.append(b)
    return out


def write_one(path: str, args) -> int:
    art = json.load(open(path, encoding="utf-8"))
    if art.get("status") not in ("new", "drafted"):
        print(f"{os.path.basename(path)}: status={art['status']} - skip")
        return 0

    # ---- source text: legacy field, else transient re-fetch (never saved)
    src = art.get("source_text") or ""
    if not src:
        title, src, mode = FN.ingest_url(art.get("url", ""))
        if title and not art.get("title_en"):
            art["title_en"] = title
        if src:
            art.setdefault("source_mode", mode or "summary")
        else:
            print(f"{os.path.basename(path)}: WARNING - could not re-fetch "
                  "source; facts-only QA will still run", file=sys.stderr)
    if src:
        new_facts = FN.make_qa_facts(src, art.get("title_en", ""))
        old = art.get("qa_facts") or {}
        if old:
            merged = {
                "numbers": sorted(set(old.get("numbers") or [])
                                  | set(new_facts["numbers"])),
                "entities": sorted(set(old.get("entities") or [])
                                   | set(new_facts["entities"])),
                "chars": max(old.get("chars") or 0, new_facts["chars"]),
            }
            art["qa_facts"] = merged
        else:
            art["qa_facts"] = new_facts

    system = open(PROMPT, encoding="utf-8").read()
    user = OUTPUT_SPEC + (
        f"TITLE: {art['title_en']}\n"
        f"CATEGORY: {art['category']}\n"
        f"SOURCE URL: {art['url']}\n\n" + src)

    if args.provider == "anthropic":
        raw = call_anthropic(args.key or os.environ.get("ANTHROPIC_API_KEY", ""),
                             args.model, system, user)
    else:
        raw = call_openai_compat(args.base_url, args.key
                                 or os.environ.get("OPENAI_API_KEY", ""),
                                 args.model, system, user)
    out = parse_json_reply(raw)
    for k in ("title_fa", "lead_fa"):
        if not out.get(k):
            raise ValueError(f"model output missing {k}")
    if isinstance(out.get("body_fa"), str):
        out["body_fa"] = [p for p in out["body_fa"].split("\n") if p.strip()]
    out["body_fa"] = norm_blocks(out.get("body_fa"))
    if len(out["body_fa"]) < 2:
        raise ValueError("model output body_fa has <2 usable blocks")

    art["article_fa"] = {k: out[k] for k in
                         ("title_fa", "lead_fa", "body_fa", "tags_fa")
                         if out.get(k) is not None}
    art["status"] = "drafted"
    art.pop("source_text", None)      # copyright: never persist source
    art["generator"] = {"provider": args.provider, "model": args.model,
                        "written_at": __import__("datetime").datetime
                        .now(__import__("datetime").timezone.utc)
                        .strftime("%Y-%m-%dT%H:%M:%SZ")}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(art, fh, ensure_ascii=False, indent=1)

    print(f"{os.path.basename(path)}: drafted -> "
          f"«{art['article_fa']['title_fa'][:60]}»")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", type=int, help="article id")
    ap.add_argument("--all", action="store_true", help="all status=new")
    ap.add_argument("--provider", default="openai",
                    choices=["openai", "compat", "anthropic"])
    ap.add_argument("--base-url", default="https://api.openai.com/v1")
    ap.add_argument("--model", required=True)
    ap.add_argument("--key", default=None,
                    help="API key (or env OPENAI_API_KEY/ANTHROPIC_API_KEY)")
    args = ap.parse_args()

    if args.provider == "compat" and args.base_url.startswith("https://api.openai"):
        sys.exit("--provider compat needs your own --base-url")

    files = []
    if args.all:
        files = [os.path.join(ART, f) for f in sorted(os.listdir(ART))
                 if f.endswith(".json")]
    elif args.id:
        files = [os.path.join(ART, f"{args.id}.json")]
    else:
        ap.error("need --id or --all")

    rc = 0
    for f in files:
        try:
            rc |= write_one(f, args)
        except Exception as e:
            print(f"{os.path.basename(f)}: ERROR {e}", file=sys.stderr)
            rc = 1
    print("\nnext: python tools/qa_check.py " + files[0] +
          "   (pass -> PR, fail -> edit & rewrite)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
