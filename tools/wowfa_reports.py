"""WoWFA reports from a Discord forum (the owner, 25 Nov 2026).

The owner made a Forum channel for reports. Every post (thread) in it is read: players
write their bug report / any text, paste the line of the addon's Status page (it starts
with "WoWFA ") or attach their WoWFA.lua (WTF/Account/<account>/SavedVariables).

Each run of discord_poster.py (the discord workflow, every 30 min) calls collect():
  1. pages: the bot opens its own posts in the forum.
     - config "pages": [{"title": ..., "text": ...}] -> each is created once
       (remembered in "made"), so the first run opens the welcome page by itself.
     - command: the server owner writes in any post of the forum
           !page <title>
           <text lines, optional>
       and the bot opens a new post with that title and text (reacts with a check mark
       to the command). Only the server owner may do it (owner_id of the server).
  2. reports: the new messages of every post in the forum are read; the text, the
     WoWFA lines and the WoWFA_Harvest block of an attached WoWFA.lua are saved under
     data/wowfa_reports/<date>-<message id>.txt, the message gets a check mark and the
     files are staged with git add (the workflow commits them with its state file).

No user names and no user ids are saved: only the post title and the message text.

Config: data/wowfa_reports/config.json {"forum": "<forum channel id>"} - empty = off.
Discord side: Message Content Intent on (Developer Portal -> Bot), and in the forum the
bot needs View Channel, Read Message History, Send Messages, Create Posts,
Send Messages in Threads and Add Reactions.
Live slash commands need a bot that is always online; this one runs from GitHub Actions,
so the command is a text command that is seen at the next run (at most 30 min later).
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
MAX_TEXT = 6000
CHECK = "%E2%9C%85"
FORUM_TYPE = 15
REQUIRE_TAG = 1 << 4
PAGE_CMD = ("!page", "!\u0635\u0641\u062d\u0647")

WELCOME = {
    "title": "\u06af\u0632\u0627\u0631\u0634\u200c\u0647\u0627\u06cc WoWFA | \u0628\u0627\u06af\u060c \u062a\u0631\u062c\u0645\u0647\u0654 \u063a\u0644\u0637\u060c \u0647\u0631 \u0686\u06cc\u0632\u06cc",
    "text": (
        "\u0633\u0644\u0627\u0645! \u0647\u0631 \u0686\u06cc\u0632\u06cc \u062f\u0631\u0628\u0627\u0631\u0647\u0654 \u0627\u0641\u0632\u0648\u0646\u0647\u0654 \u0641\u0627\u0631\u0633\u06cc WoWFA \u062f\u0627\u0631\u06cc\u062f \u0647\u0645\u06cc\u0646\u200c\u062c\u0627 \u0628\u0641\u0631\u0633\u062a\u06cc\u062f:\n"
        "\u2022 \u0628\u0627\u06af \u06cc\u0627 \u0645\u0634\u06a9\u0644 (\u0627\u06af\u0631 \u0645\u06cc\u200c\u0634\u0648\u062f \u0628\u0627 \u0639\u06a9\u0633)\n"
        "\u2022 \u062a\u0631\u062c\u0645\u0647\u0654 \u063a\u0644\u0637 \u06cc\u0627 \u062c\u0627\u0627\u0641\u062a\u0627\u062f\u0647\n"
        "\u2022 \u062e\u0637 \u0648\u0636\u0639\u06cc\u062a \u0627\u0641\u0632\u0648\u0646\u0647: \u062f\u0631 \u0628\u0627\u0632\u06cc `/wowfa` \u2190 \u0628\u062e\u0634 \u00ab\u0648\u0636\u0639\u06cc\u062a\u00bb \u2190 \u00ab\u0627\u0646\u062a\u062e\u0627\u0628 \u0628\u0631\u0627\u06cc \u06a9\u067e\u06cc\u00bb \u2190 "
        "Ctrl+C \u0648 \u0627\u06cc\u0646\u062c\u0627 Ctrl+V (\u062e\u0637\u06cc \u06a9\u0647 \u0628\u0627 `WoWFA ` \u0634\u0631\u0648\u0639 \u0645\u06cc\u200c\u0634\u0648\u062f)\n"
        "\u2022 \u06cc\u0627 \u0641\u0627\u06cc\u0644 `WoWFA.lua` \u0627\u0632 \u067e\u0648\u0634\u0647\u0654 `WTF/Account/<\u062d\u0633\u0627\u0628>/SavedVariables`\n\n"
        "\u0631\u0628\u0627\u062a \u0647\u0631 \u0646\u06cc\u0645 \u0633\u0627\u0639\u062a \u067e\u06cc\u0627\u0645\u200c\u0647\u0627 \u0631\u0627 \u0645\u06cc\u200c\u062e\u0648\u0627\u0646\u062f \u0648 \u0628\u0627 \u2705 \u062a\u0623\u06cc\u06cc\u062f \u0645\u06cc\u200c\u06a9\u0646\u062f. \u0646\u0627\u0645 \u0634\u0645\u0627 \u0630\u062e\u06cc\u0631\u0647 \u0646\u0645\u06cc\u200c\u0634\u0648\u062f."
    ),
}


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


def _save(root, path, cfg):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    _stage(root, path)


class Api:
    def __init__(self, token):
        self.s = requests.Session()
        self.s.headers.update({"Authorization": "Bot " + token, "User-Agent": UA})
        self.calls = 0

    def req(self, method, path, **kw):
        r = None
        for _ in range(4):
            self.calls += 1
            try:
                r = self.s.request(method, API + path, timeout=30, **kw)
            except Exception:
                time.sleep(2)
                continue
            if r.status_code == 429:
                try:
                    wait = float(r.json().get("retry_after", 2)) + 0.3
                except Exception:
                    wait = 2.5
                time.sleep(min(wait, 15))
                continue
            return r
        return r

    def get(self, path):
        r = self.req("GET", path)
        if r is None or r.status_code != 200:
            return None, (r.status_code if r is not None else 0)
        try:
            return r.json(), 200
        except Exception:
            return None, 0

    def react(self, channel, mid):
        self.req("PUT", "/channels/%s/messages/%s/reactions/%s/@me" % (channel, mid, CHECK))
        time.sleep(0.4)


def _threads(api, guild, forum):
    """active + recently archived public posts of the forum: {id: name}"""
    out = {}
    data, _ = api.get("/guilds/%s/threads/active" % guild)
    for t in (data or {}).get("threads") or []:
        if str(t.get("parent_id")) == forum:
            out[str(t["id"])] = t.get("name") or ""
    data, _ = api.get("/channels/%s/threads/archived/public?limit=25" % forum)
    for t in (data or {}).get("threads") or []:
        out.setdefault(str(t["id"]), t.get("name") or "")
    return out


def _new_messages(api, tid, after):
    """messages of a thread after the id `after` (oldest first, at most 500)"""
    got = []
    cur = after or "0"
    for _ in range(5):
        data, code = api.get("/channels/%s/messages?limit=100&after=%s" % (tid, cur))
        if data is None:
            return got, code
        if not data:
            break
        data = sorted(data, key=lambda m: int(m.get("id", "0")))
        got += data
        cur = str(data[-1]["id"])
        if len(data) < 100:
            break
    return got, 200


def _make_post(api, forum, ch, title, text):
    body = {"name": (title or "WoWFA").strip()[:100],
            "message": {"content": (text or title or "WoWFA").strip()[:2000]}}
    tags = ch.get("available_tags") or []
    if (int(ch.get("flags") or 0) & REQUIRE_TAG) and tags:
        body["applied_tags"] = [str(tags[0]["id"])]
    r = api.req("POST", "/channels/%s/threads" % forum, json=body)
    code = r.status_code if r is not None else 0
    tid = ""
    if code in (200, 201):
        try:
            tid = str(r.json().get("id") or "")
        except Exception:
            pass
    return code, tid


def _attachments(m):
    lines, blocks, names = [], [], []
    for a in m.get("attachments") or []:
        name = str(a.get("filename") or "")
        low = name.lower()
        if not low.endswith((".lua", ".txt")) or int(a.get("size") or 0) > MAX_FILE:
            if name:
                names.append(name)
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
        elif low.endswith(".txt"):
            blocks.append(body[:MAX_TEXT])
    return lines, blocks, names


def collect(root, token):
    base = os.path.join(root, "data", "wowfa_reports")
    cfg_path = os.path.join(base, "config.json")
    try:
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return "off (no data/wowfa_reports/config.json)"
    forum = str(cfg.get("forum") or "").strip()
    if not forum:
        return "off (no forum in config)"
    if not token or requests is None:
        return "off (no token or no requests)"

    api = Api(token)
    ch, code = api.get("/channels/%s" % forum)
    if ch is None:
        cfg["last"] = "%s forum read HTTP %s (bot not in that server or no View Channel)" % (_now(), code)
        _save(root, cfg_path, cfg)
        return cfg["last"]
    if int(ch.get("type") or 0) != FORUM_TYPE:
        cfg["last"] = "%s channel %s is type %s, not a forum" % (_now(), forum, ch.get("type"))
        _save(root, cfg_path, cfg)
        return cfg["last"]
    guild = str(ch.get("guild_id") or "")
    g, _ = api.get("/guilds/%s" % guild)
    owner = str((g or {}).get("owner_id") or "")

    note = []
    made = cfg.setdefault("made", {})
    pages = cfg.get("pages")
    if pages is None:
        pages = cfg["pages"] = [WELCOME]
    for p in pages:
        title = str(p.get("title") or "").strip()
        if not title or title in made:
            continue
        code, tid = _make_post(api, forum, ch, title, p.get("text"))
        if tid:
            made[title] = tid
            note.append("page made")
        else:
            note.append("page HTTP %s" % code)

    threads = cfg.setdefault("threads", {})
    live = _threads(api, guild, forum)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    saved = 0
    empty = 0
    cmds = 0
    for tid, tname in sorted(live.items(), key=lambda kv: int(kv[0])):
        msgs, code = _new_messages(api, tid, threads.get(tid))
        if code != 200 and not msgs:
            note.append("post %s HTTP %s" % (tid, code))
            continue
        for m in msgs:
            mid = str(m.get("id"))
            threads[tid] = mid
            if (m.get("author") or {}).get("bot") or int(m.get("type") or 0) not in (0, 19):
                continue
            text = (m.get("content") or "").strip()
            first = text.split("\n", 1)[0].strip()
            word = first.split(" ", 1)[0].lower()
            if word in PAGE_CMD:
                if owner and str((m.get("author") or {}).get("id")) == owner:
                    title = first[len(word):].strip()
                    rest = text.split("\n", 1)[1].strip() if "\n" in text else ""
                    if title:
                        code, ntid = _make_post(api, forum, ch, title, rest or title)
                        if ntid:
                            made[title] = ntid
                            api.react(tid, mid)
                            cmds += 1
                        else:
                            note.append("!page HTTP %s" % code)
                continue
            lines, blocks, names = _attachments(m)
            if not text and not m.get("attachments"):
                empty += 1
                continue
            if not (text or lines or blocks or names):
                continue
            os.makedirs(base, exist_ok=True)
            path = os.path.join(base, "%s-%s.txt" % (today, mid))
            with open(path, "w", encoding="utf-8") as f:
                f.write("post: %s\n" % tname)
                f.write("at: %s\n\n" % (m.get("timestamp") or _now()))
                if text:
                    f.write(text[:MAX_TEXT] + "\n")
                for ln in lines:
                    if ln not in text:
                        f.write(ln + "\n")
                for n in names:
                    f.write("[file: %s]\n" % n)
                for b in blocks:
                    f.write("\n--- file ---\n" + b + "\n")
            _stage(root, path)
            api.react(tid, mid)
            saved += 1

    cfg["last"] = "%s posts %d, saved %d, commands %d%s%s" % (
        _now(), len(live), saved, cmds,
        (", %d without text (Message Content Intent off?)" % empty) if empty else "",
        (" | " + "; ".join(note)) if note else "")
    _save(root, cfg_path, cfg)
    return cfg["last"]
