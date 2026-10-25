#!/usr/bin/env python3
"""
publish_from_issue.py - turn a translator's GitHub issue into a published
article (or a QA failure report).

Flow:
  1. parse the JSON payload from the issue body (first ```json fence that
     contains "title_fa", or the <!-- wowheadfa-payload --> markers)
  2. re-derive the article id SERVER-SIDE from source_url (never trust the
     client's id), fetch source text server-side when possible
  3. merge Persian fields into data/articles/<id>.json (status=drafted)
  4. run qa_check gates; publish only if everything passes
  5. print RESULT=<published|qa-failed|duplicate|error> and write details
     to --out file (default /tmp/wfa_publish_result.txt) for the workflow

This script only touches files - git push and issue comments belong to
the workflow. stdlib only.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_news as FN  # noqa: E402
import qa_check  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "data", "articles")


def parse_payload(body: str):
    """Extract the article payload JSON from an issue body."""
    m = re.search(r"<!--\s*wowheadfa-payload\s*-->(.*?)"
                  r"<!--\s*/wowheadfa-payload\s*-->", body, flags=re.S)
    if m:
        blob = m.group(1)
    else:
        blob = body
    fences = re.findall(r"```(?:json)?\s*(.*?)```", blob, flags=re.S)
    for f in fences:
        f = f.strip()
        if '"title_fa"' in f:
            try:
                return json.loads(f), None
            except Exception as e:
                return None, f"payload JSON parse error: {e}"
    # last resort: whole body as JSON
    if '"title_fa"' in blob:
        m2 = re.search(r"\{.*\}", blob, flags=re.S)
        if m2:
            try:
                return json.loads(m2.group(0)), None
            except Exception as e:
                return None, f"payload JSON parse error: {e}"
    return None, "no payload found (need a ```json block with title_fa)"


def clean_str(v, max_len):
    s = str(v or "").strip()
    s = s.replace("\u200c", "\u200c")  # keep ZWNJ
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", s)
    s = re.sub(r"[ \t]+", " ", s).strip()
    return s[:max_len]


def sanitize_payload(p):
    """Validate/normalize payload fields; returns (data, [errors])."""
    errs = []
    url = clean_str(p.get("source_url") or p.get("url") or "", 300)
    if not re.match(r"https://(www\.)?wowhead\.com/news", url):
        errs.append("source_url must be a wowhead.com/news link")
    art_id = FN.url_to_id(url)
    if art_id is None:
        errs.append("cannot parse news id from source_url")
    title = clean_str(p.get("title_fa"), 130)
    lead = clean_str(p.get("lead_fa"), 420)
    body = p.get("body_fa") or []
    if isinstance(body, str):
        body = [b for b in re.split(r"\n\s*\n", body) if b.strip()]
    body = [clean_str(b, 4000) for b in body if clean_str(b, 4000)]
    if not (2 <= len(body) <= 8):
        errs.append(f"body_fa must have 2..8 paragraphs (got {len(body)})")
    tags = p.get("tags_fa") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    tags = [clean_str(t, 30) for t in tags][:5]
    if not title:
        errs.append("title_fa is empty")
    if not lead:
        errs.append("lead_fa is empty")
    data = {
        "id": art_id,
        "url": url,
        "title_fa": title,
        "lead_fa": lead,
        "body_fa": body,
        "tags_fa": tags,
        "title_en": clean_str(p.get("title_en"), 300),
        "model": clean_str(p.get("model"), 80),
    }
    # NOTE: source_text_client is deliberately ignored since the
    # copyright cleanup - the full English source must never be stored,
    # not in git and not re-saved from issue payloads.
    return data, errs


def result(kind, lines):
    out = "\n".join(lines)
    print(f"RESULT={kind}")
    print(out)
    with open("/tmp/wfa_publish_result.txt", "w", encoding="utf-8") as fh:
        fh.write(kind + "\n" + out)
    return 0 if kind == "published" else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--issue", type=int, default=0)
    ap.add_argument("--author", default="anonymous")
    a = ap.parse_args()

    body = open(a.body_file, encoding="utf-8").read()
    p, err = parse_payload(body)
    if p is None:
        return result("error", [f"payload: {err}"])
    data, errs = sanitize_payload(p)
    if errs:
        return result("error", ["payload invalid:"] + [f"  - {e}" for e in errs])

    art_id = data["id"]
    path = os.path.join(ART, f"{art_id}.json")
    lines = [f"issue #{a.issue} by @{a.author} - article {art_id}"]

    # ---- facts reference: ensure qa_facts WITHOUT storing any source text
    if os.path.exists(path):
        art = json.load(open(path, encoding="utf-8"))
        if art.get("status") == "published":
            return result("duplicate",
                          lines + ["this article is already published "
                                   f"(status=published in {art_id}.json)"])
    else:
        title, text, mode = FN.ingest_url(data["url"])
        art = {
            "id": art_id,
            "slug": FN.slugify(data["title_en"] or title or "") or
                f"news-{art_id}",
            "url": data["url"],
            "title_en": data["title_en"] or title or f"Wowhead news {art_id}",
            "category": "News",
            "published_at": FN.datetime.now(FN.timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fetched_at": FN.datetime.now(FN.timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_mode": mode or "summary",
            "status": "new",
        }
        lines.append(f"source ingest server-side: mode={art['source_mode']} "
                     f"len={len(text or '')}")
        art["qa_facts"] = FN.make_qa_facts(text or "", art["title_en"])

    if not art.get("qa_facts"):
        # legacy JSON without facts: derive them transiently, store only facts
        _t, text, _m = FN.ingest_url(art.get("url", ""))
        if text:
            art["qa_facts"] = FN.make_qa_facts(text, art.get("title_en", ""))
            lines.append(f"qa_facts derived transiently "
                         f"({len(art['qa_facts']['numbers'])} nums, "
                         f"{len(art['qa_facts']['entities'])} tokens)")
        else:
            art["qa_facts"] = {"numbers": [], "entities": [], "chars": 0}
            lines.append("WARNING: no facts reference available - "
                         "G4/G5 skipped for this run")

    # ---- merge Persian article ----
    art["article_fa"] = {
        "title_fa": data["title_fa"],
        "lead_fa": data["lead_fa"],
        "body_fa": data["body_fa"],
        "tags_fa": data["tags_fa"],
    }
    art["generator"] = {
        "model": data["model"] or "unknown",
        "via": "web-byok",
        "issue": a.issue,
        "author": a.author,
    }
    art["status"] = "drafted"
    art.pop("source_text", None)      # copyright: never persist source

    # ---- QA gates ----
    os.makedirs(ART, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(art, fh, ensure_ascii=False, indent=1)
    issues = qa_check.check(path)
    if issues:
        return result("qa-failed", lines +
                      ["QA gates failed - article saved as draft:"] +
                      [f"  - {i}" for i in issues])

    art["status"] = "published"
    art["published_at"] = FN.datetime.now(FN.timezone.utc) \
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(art, fh, ensure_ascii=False, indent=1)
    lines.append("QA gates passed - published")
    return result("published", lines)


if __name__ == "__main__":
    sys.exit(main())
