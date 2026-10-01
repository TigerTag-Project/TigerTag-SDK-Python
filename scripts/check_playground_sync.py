#!/usr/bin/env python3
"""
tools/playground.html must be byte-for-byte identical in the Python and JavaScript SDKs
(docs/playground-api.md). Compares this copy with the sibling repository's copy: the local
checkout next to this one when present (or TIGERTAG_SIBLING_REPO), otherwise the other
repository's main branch on GitHub.

    python3 scripts/check_playground_sync.py   → exit 0 identical, 1 different, 2 sibling unreachable
"""

import os
import sys
import urllib.request
from pathlib import Path
from typing import Dict, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
LOCAL = ROOT / "tools" / "playground.html"
SIBLING_DIRS = ("TigerTag-SDK-JS", "tigertag-sdk-js")
SIBLING_RAW = "https://raw.githubusercontent.com/TigerTag-Project/TigerTag-SDK-JS/main/tools/playground.html"


def sibling_copy() -> Optional[Tuple[str, bytes]]:
    env = os.environ.get("TIGERTAG_SIBLING_REPO")
    dirs = [Path(env)] if env else [ROOT.parent / d for d in SIBLING_DIRS]
    for d in dirs:
        f = d / "tools" / "playground.html"
        if f.is_file():
            return str(f), f.read_bytes()
    if os.environ.get("TIGERTAG_OFFLINE", "").lower() in ("1", "true", "yes", "on"):
        return None  # no network call
    try:
        with urllib.request.urlopen(SIBLING_RAW, timeout=10) as resp:
            return SIBLING_RAW, resp.read()
    except Exception:
        return None


def check() -> Dict[str, object]:
    mine = LOCAL.read_bytes()
    other = sibling_copy()
    if other is None:
        return {"status": "unreachable"}
    source, data = other
    if mine == data:
        return {"status": "identical", "source": source}
    n = next((i for i, (a, b) in enumerate(zip(mine, data)) if a != b), min(len(mine), len(data)))
    return {"status": "different", "source": source, "line": mine[:n].count(b"\n") + 1}


def main() -> int:
    r = check()
    if r["status"] == "identical":
        print(f"OK — tools/playground.html identical to {r['source']}")
        return 0
    if r["status"] == "unreachable":
        print("SKIP — sibling playground.html not reachable (no local checkout, offline)")
        return 2
    print(f"FAILED — tools/playground.html differs from {r['source']} (first difference at line {r['line']}).\n"
          "Copy the unified page to both repositories (see docs/playground-api.md).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
