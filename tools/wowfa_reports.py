"""WoWFA reports from Discord (the owner, 25 Nov 2026).

Players paste the line of the addon's Status page (it starts with "WoWFA ") or attach
their WoWFA.lua (WTF/Account/<account>/SavedVariables) in the report channel. Each run
of discord_poster.py calls collect(): the new messages of that channel are read, the
WoWFA parts are saved under data/wowfa_reports/<date>-<message id>.txt, the message
gets a check-mark reaction and the files are staged with git add (the discord workflow
commits what is staged together with its state file).

Only game text is kept: no user names, no user ids, no other chat. From an attached
WoWFA.lua only the WoWFA_Harvest block (English quests / NPC names the addon met) and
the lines that start with "WoWFA " are kept.

Config: data/wowfa_reports/config.json  {"channel": "<channel id>"} - empty = off.
Discord side: the bot needs View Channel, Read Message History and Add Reactions in that
channel, and "Message Content Intent" on (Developer Portal -> Bot), or it reads empty text.
"""
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    requests = None

API = "https://discord.com/api/v10"
UA = "wowfarsi-discord-bot/1.0 (+https://wowfarsi.ir)"
MAX_FILE = 4 * 1024 * 1024
CHECK = "%E2%9C%85"


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _keep_lua(body):
    """the WoWFA_Harvest block of a SavedVariables file (top level, until the next one)"""
    out = []
    keep = False
    for line in body.splitlines():
        top = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if top:
            keep = top.group(1) == "WoWFA_Harvest"
        if keep:
            out.append(line)
    return "\n".join(out)


def _wowfa_lines(text):
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip().startswith("WoWFA ")]


def _stage(root, path):
    try:
        subprocess.run(["git", "add", path], cwd=root, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def collect(root, token):
    base = os.path.join(root, "data", "wowfa_reports")
    cfg_path = os.path.join(base, "config.json")
    try:
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return "off (no data/wowfa_reports/config.json)"
    channel = str(cfg.get("channel") or "").strip()
    if not channel:
        return "off (no channel in config)"
    if not token or requests is None:
        return "off (no token or no requests)"

    s = requests.Session()
    s.headers.update({"Authorization": "Bot " + token, "User-Agent": UA})
    after = str(cfg.get("after") or "").strip()
    url = "%s/channels/%s/messages?limit=100" % (API, channel)
    if after:
        url += "&after=" + after
    r = s.get(url, timeout=30)
    if r.status_code != 200:
        cfg["last"] = "%s read HTTP %s" % (_now(), r.status_code)
        _save(root, cfg_path, cfg)
        return cfg["last"]
    msgs = sorted(r.json(), key=lambda m: int(m.get("id", "0")))
    saved = 0
    empty = 0
    for m in msgs:
        mid = str(m.get("id"))
        if (m.get("author") or {}).get("bot"):
            after = mid
            continue
        lines = _wowfa_lines(m.get("content"))
        blocks = []
        for a in m.get("attachments") or []:
            name = str(a.get("filename") or "").lower()
            if not name.endswith((".lua", ".txt")) or int(a.get("size") or 0) > MAX_FILE:
                continue
            try:
                fr = requests.get(a.get("url"), timeout=60, headers={"User-Agent": UA})
            except Exception:
                continue
            if fr.status_code != 200:
                continue
            body = fr.content.decode("utf-8", "replace")
            lines += _wowfa_lines(body)
            h = _keep_lua(body)
            if h:
                blocks.append(h)
        if not m.get("content") and not m.get("attachments"):
            empty += 1
        if lines or blocks:
            os.makedirs(base, exist_ok=True)
            day = datetime.now(timezone.utc).strftime("%Y%m%d")
            path = os.path.join(base, "%s-%s.txt" % (day, mid))
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
                for b in blocks:
                    f.write("\n--- WoWFA_Harvest ---\n" + b + "\n")
            _stage(root, path)
            try:
                s.put("%s/channels/%s/messages/%s/reactions/%s/@me" % (API, channel, mid, CHECK),
                      timeout=20)
            except Exception:
                pass
            saved += 1
            time.sleep(0.6)
        after = mid
    cfg["after"] = after
    cfg["last"] = "%s read %d, saved %d%s" % (
        _now(), len(msgs), saved,
        (", %d without text (turn on Message Content Intent)" % empty) if empty else "")
    _save(root, cfg_path, cfg)
    return cfg["last"]


def _save(root, path, cfg):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    _stage(root, path)
