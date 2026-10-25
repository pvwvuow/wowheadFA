#!/usr/bin/env python3
"""mask_keys.py - register ::add-mask:: for every API key before any
other step runs.

GitHub auto-masks SINGLE-line secrets in logs, but a MULTILINE secret
(like GEMINI_API_KEY with one key per line) is NOT masked line by line -
only the exact full raw value is. So every individual key is echoed here
through the ::add-mask:: workflow command (GitHub redacts the value and
all later occurrences). The keys themselves are never printed anywhere
else; only key POSITIONS (#1, #2...) ever appear in reports.
"""
import os
import re
import sys

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


def main():
    n = 0
    for var in VARS:
        for k in split_keys(os.environ.get(var) or ""):
            print(f"::add-mask::{k}", flush=True)
            n += 1
    print(f"masks registered: {n}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
