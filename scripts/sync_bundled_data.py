#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
Refresh the reference data bundled in the package (tigertag/database/).

Downloads the 7 id_*.json tables and last_update.json from TigerTag-RFID-Guide, plus the
TigerTag+ catalogue, stored gzip-compressed as id_catalog.json.gz. A file is rewritten only
when its content changed, so an unchanged day leaves the repository untouched. The gzip
header time of id_catalog.json.gz records when the catalogue content last changed: the SDK
uses it to decide whether its cached copy or the bundled one is newer.

Used by .github/workflows/sync-databases.yml (daily) and publish.yml (before every build).

Usage:
    python scripts/sync_bundled_data.py [--dest tigertag/database]
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import sys
import time
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/TigerTag-Project/TigerTag-RFID-Guide/main/database"
TABLES = [
    "id_version.json", "id_material.json", "id_aspect.json", "id_type.json",
    "id_diameter.json", "id_brand.json", "id_measure_unit.json", "last_update.json",
]
CATALOG = "id_catalog.json"


def fetch(name: str) -> bytes:
    req = urllib.request.Request(f"{BASE}/{name}", headers={"User-Agent": "tigertag-sdk-python-sync"})
    try:
        import certifi, ssl  # noqa: E401
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = None
    with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
        return resp.read()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--dest", default=str(Path(__file__).resolve().parent.parent / "tigertag" / "database"))
    dest = Path(ap.parse_args().dest)
    dest.mkdir(parents=True, exist_ok=True)
    changed = []

    for name in TABLES:
        raw = fetch(name)
        json.loads(raw)                                   # refuse anything that is not JSON
        path = dest / name
        if not path.exists() or path.read_bytes() != raw:
            path.write_bytes(raw)
            changed.append(name)

    raw = fetch(CATALOG)
    if not isinstance(json.loads(raw), list):
        raise SystemExit("id_catalog.json is not a JSON list")
    gz_path = dest / (CATALOG + ".gz")
    old = gzip.decompress(gz_path.read_bytes()) if gz_path.exists() else None
    if old != raw:
        buf = io.BytesIO()
        with gzip.GzipFile(filename=CATALOG, mode="wb", fileobj=buf, compresslevel=9,
                           mtime=int(time.time())) as gz:
            gz.write(raw)
        gz_path.write_bytes(buf.getvalue())
        changed.append(gz_path.name)

    print("Updated: " + ", ".join(changed) if changed else "All bundled data is up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
