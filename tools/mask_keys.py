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

Failover (added 1 Nov 2026): auto_publish.py imports this module (for
split_keys) BEFORE it reads any provider setting. When it is run as the
publish step (`python tools/auto_publish.py`, no flags) and the xAI side
is unusable (secret empty, key rejected with 400/401/403, or XAI_MODEL
not in the key's model list), failover() switches the writer/reviewer
roles that point at xAI over to Gemini by editing os.environ in-process
(AI_WRITER / AI_REVIEWER / GEMINI_MODEL / REVIEWER_MODEL). Nothing is
persisted; the moment xAI works again the original settings apply. A
::warning:: annotation says what happened. Before this, a dead xAI key
made every run bail out silently and nothing was published.
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


GEM_URL = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200"


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
            code, data, err = _get(GEM_URL, {"x-goog-api-key": k}, allk)
            n = len((data or {}).get("models") or []) if code == 200 else 0
            res.append("key#%d HTTP %s%s" % (i, code, (" %d models" % n) if code == 200 else (" " + err[:80])))
        lvl = "notice" if any(" 200 " in r + " " for r in res) else "warning"
        print("::%s title=probe Gemini::%s" % (lvl, " | ".join(res)[:600]), flush=True)


# ------------------------------------------------------------- failover
SKIP_MODEL = re.compile(r"lite|preview|exp|image|audio|tts|live|thinking|8b|"
                        r"embed|gemma|learnlm|vision", re.I)


def pick_gemini_model(models, wanted=""):
    """Keep GEMINI_MODEL when it is valid; otherwise a stable flash id."""
    if wanted and wanted in models:
        return wanted
    for pref in ("gemini-2.5-flash", "gemini-flash-latest", "gemini-2.0-flash"):
        if pref in models:
            return pref
    fl = [m for m in models if "flash" in m.lower() and not SKIP_MODEL.search(m)]
    return sorted(fl, reverse=True)[0] if fl else ""


def xai_problem(allk):
    """Reason string when xAI cannot be used, else ''. Only hard
    auth/config problems count (transient network/5xx errors do not)."""
    xkeys = split_keys(os.environ.get("XAI_API_KEY") or "")
    if not xkeys:
        return "XAI_API_KEY empty"
    code, data, _err = _get("https://api.x.ai/v1/models",
                            {"Authorization": "Bearer " + xkeys[0]}, allk)
    if code in (400, 401, 403):
        return "xAI key rejected (HTTP %d)" % code
    if code == 200 and data:
        ids = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
        model = (os.environ.get("XAI_MODEL") or "").strip()
        if not model:
            return "XAI_MODEL not set"
        if ids and model not in ids:
            return "XAI_MODEL %r not in xAI model list" % model
    return ""


def failover():
    """See module docstring. Never raises; no-op outside publish mode."""
    if os.path.basename(sys.argv[0]) != "auto_publish.py" or len(sys.argv) > 1:
        return
    wr = (os.environ.get("AI_WRITER") or "xai").strip().lower()
    rv = (os.environ.get("AI_REVIEWER") or "xai").strip().lower()
    if "xai" not in (wr, rv):
        return
    gkeys = split_keys(os.environ.get("GEMINI_API_KEY") or "")
    allk = split_keys(os.environ.get("XAI_API_KEY") or "") + gkeys
    why = xai_problem(allk)
    if not why:
        return
    models = []
    for k in gkeys:
        code, data, _e = _get(GEM_URL, {"x-goog-api-key": k}, allk)
        if code == 200 and data:
            models = [m.get("name", "").split("/", 1)[-1]
                      for m in (data.get("models") or []) if m.get("name")]
            break
    model = pick_gemini_model(models, (os.environ.get("GEMINI_MODEL") or "").strip())
    if not model:
        print("::warning title=failover::xAI unusable (%s) and no usable "
              "Gemini model - nothing will be published" % why, flush=True)
        return
    os.environ["GEMINI_MODEL"] = model
    if wr == "xai":
        os.environ["AI_WRITER"] = "gemini"
    if rv == "xai":
        os.environ["AI_REVIEWER"] = "gemini"
    if (os.environ.get("AI_REVIEWER") or "").strip().lower() == "gemini":
        rm = (os.environ.get("REVIEWER_MODEL") or "").strip()
        if rm not in models:
            os.environ["REVIEWER_MODEL"] = model
    msg = ("%s -> failover to Gemini %s (writer=%s reviewer=%s). Fix the "
           "xAI secret/variable to switch back."
           % (why, model, os.environ.get("AI_WRITER"), os.environ.get("AI_REVIEWER")))
    print("::warning title=failover::" + msg, flush=True)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write("- failover: " + msg + "\n")
        except Exception:  # noqa: BLE001
            pass


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
else:
    try:
        failover()
    except Exception as e:  # noqa: BLE001 - failover must never break the import
        print(f"failover skipped: {type(e).__name__}", flush=True)
