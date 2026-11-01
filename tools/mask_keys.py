#!/usr/bin/env python3
"""mask_keys.py - register ::add-mask:: for every API key before any
other step runs.

GitHub auto-masks SINGLE-line secrets in logs, but a MULTILINE secret
(like GEMINI_API_KEY with one key per line) is NOT masked line by line -
only the exact full raw value is. So every individual key is echoed here
through the ::add-mask:: workflow command (GitHub redacts the value and
all later occurrences). The keys themselves are never printed anywhere
else; only key POSITIONS (#1, #2...) ever appear in reports.

Diagnostics: after masking, probe() makes ONE light list-models call per
provider and reports the HTTP status / model count as a ::notice:: (or
::warning:: on failure) workflow annotation. Annotations are readable via
the public checks API even when the job logs are not, so a silent
auto-publish bail-out (7-second runs) can be explained from outside.
No key material is ever printed; the probe never raises.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

VARS = ("XAI_API_KEY", "GEMINI_API_KEY")


def split_keys(raw):
    """Parse a multi-key secret: newline- or comma-separated, whitespace
    around entries ignored, empty entries dropped, duplicates removed."""
    out = []
    for part in re.split(r"[\n,]+", raw or ""):
        k = part.strip()
        if k and k not in out:
            out.append(k)
    return out


def _clean(s, keys):
    s = re.sub(r"\s+", " ", str(s))
    for k in keys:
        if k:
            s = s.replace(k, "[KEY]")
    return s[:300]


def _get(url, headers, keys):
    """(http_code, parsed_json_or_None, error_text)"""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.load(r), ""
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        return e.code, None, _clean(body, keys)
    except Exception as e:  # noqa: BLE001
        return 0, None, _clean(e, keys)


def probe():
    xkeys = split_keys(os.environ.get("XAI_API_KEY") or "")
    gkeys = split_keys(os.environ.get("GEMINI_API_KEY") or "")
    allk = xkeys + gkeys
    # ---- xAI
    if not xkeys:
        print("::warning title=probe xAI::XAI_API_KEY secret is EMPTY", flush=True)
    else:
        code, data, err = _get("https://api.x.ai/v1/models",
                               {"Authorization": "Bearer " + xkeys[0]}, allk)
        if code == 200 and data:
            ids = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
            print("::notice title=probe xAI::HTTP 200, %d models: %s"
                  % (len(ids), ", ".join(ids)[:600]), flush=True)
        else:
            print("::warning title=probe xAI::HTTP %s %s" % (code, err), flush=True)
    # ---- Gemini (first key that answers)
    if not gkeys:
        print("::warning title=probe Gemini::GEMINI_API_KEY secret is EMPTY", flush=True)
    else:
        res = []
        for i, k in enumerate(gkeys, 1):
            code, data, err = _get(
                "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                {"x-goog-api-key": k}, allk)
            n = len((data or {}).get("models") or []) if code == 200 else 0
            res.append("key#%d HTTP %s%s" % (i, code, (" %d models" % n) if code == 200 else (" " + err[:80])))
        lvl = "notice" if any(" 200 " in r + " " for r in res) else "warning"
        print("::%s title=probe Gemini::%s" % (lvl, " | ".join(res)[:600]), flush=True)


def main():
    n = 0
    for var in VARS:
        for k in split_keys(os.environ.get(var) or ""):
            print(f"::add-mask::{k}", flush=True)
            n += 1
    print(f"masks registered: {n}", flush=True)
    try:
        probe()
    except Exception as e:  # noqa: BLE001 - diagnostics must never fail the job
        print(f"probe skipped: {type(e).__name__}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
