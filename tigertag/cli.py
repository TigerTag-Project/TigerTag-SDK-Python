# SPDX-License-Identifier: Apache-2.0
#
# TigerTag SDK
# Copyright (c) 2025-2026 TigerTag Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Implementing the TigerTag protocol requires no licence and no payment.
# https://github.com/TigerTag-Project/TigerTag-RFID-Guide/blob/main/LICENSING.md

"""CLI entry point for the TigerTag SDK."""

from __future__ import annotations

import argparse
import json
import pprint
import sys
from pathlib import Path

from typing import List, Optional

from tigertag.db import TigerTagDB
from tigertag.signature import SignatureResult
from tigertag.tag import TigerTag

try:
    from tigertag import __version__
except ImportError:
    __version__ = "1.3.0"


def _update(argv: List[str]) -> int:
    """``tigertag update [--force] [--catalog] [--data-dir PATH] [--db PATH]``."""
    ap = argparse.ArgumentParser(
        prog="tigertag update",
        description="Check for new TigerTag reference data now and download what changed.",
    )
    ap.add_argument("--force", action="store_true", help="Re-download every table")
    ap.add_argument("--catalog", action="store_true", help="Also update the TigerTag+ catalogue")
    ap.add_argument("--data-dir", metavar="PATH", help="Data directory (default: user cache dir)")
    ap.add_argument("--db", metavar="PATH", help="Update your own database folder instead")
    args = ap.parse_args(argv)
    try:
        db = TigerTagDB(Path(args.db) if args.db else None, auto_update=False, verbose=True,
                        data_dir=Path(args.data_dir) if args.data_dir else None)
        changed = db.update(force=args.force, catalog=args.catalog)
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Updated {len(changed)} file(s): {', '.join(changed)}" if changed
          else "Reference data is up to date.")
    info = db.info()
    print(f"Data directory: {info['data_dir'] if not info['custom'] else info['db_path']}")
    for name, t in info["tables"].items():
        print(f"  {name:<22} {t['source']:<10} {t['updated_at'] or '-'}")
    cat = info["catalog"]
    if cat.get("source"):
        print(f"  {'id_catalog.json':<22} {cat['source']:<10} {cat.get('fetched_at') or '-'}"
              f"  ({cat.get('count')} products)")
    return 0


def main(argv: Optional[List[str]] = None) -> None:
    """
    TigerTag CLI — parse, verify, and export TigerTag RFID chip dumps.

    Usage:
        tigertag dump.bin              parse + human-readable output
        tigertag dump.bin --json       output as JSON
        tigertag dump.bin --raw        raw dataclass (no DB lookup)
        tigertag dump.bin --offline    no network access at all
        tigertag update [--force]      check for new reference data now
        tigertag --version             show version
    """
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] == "update":
        sys.exit(_update(argv[1:]))

    ap = argparse.ArgumentParser(
        prog="tigertag",
        description="TigerTag RFID material identification SDK",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  tigertag dump.bin              # parse (reference data checked once a day)\n"
            "  tigertag dump.bin --json       # output as JSON\n"
            "  tigertag dump.bin --raw        # raw IDs, no DB lookup\n"
            "  tigertag dump.bin --offline    # no network access at all\n"
            "  tigertag update [--force]      # check for new reference data now\n"
            "  tigertag update --catalog      # ... and the TigerTag+ catalogue\n"
            "\n"
            "dump formats:\n"
            "  180 bytes  full chip dump (pages 0-44): UID extracted, signature verifiable\n"
            "  144 bytes  user data + signature (pages 0x04-0x27)\n"
            "   80 bytes  user data only (pages 0x04-0x17)\n"
            "\n"
            "spec: https://github.com/TigerTag-Project/TigerTag-RFID-Guide"
        ),
    )
    ap.add_argument("dump", nargs="?", help="Binary .bin file to parse")
    ap.add_argument("--db", metavar="PATH", default=None,
                    help="Your own database folder, used exclusively (default: bundled + downloaded)")
    ap.add_argument("--data-dir", metavar="PATH", default=None,
                    help="Where downloaded reference data is kept (default: user cache dir)")
    ap.add_argument("--json",      action="store_true", help="Output as JSON")
    ap.add_argument("--raw",       action="store_true", help="Print raw dataclass, no DB lookup")
    ap.add_argument("--offline",   action="store_true", help="No network access at all")
    ap.add_argument("--no-sync",   action="store_true", help="Skip the automatic daily check")
    ap.add_argument("--sync-only", action="store_true", help="Same as: tigertag update")
    ap.add_argument("--version",   action="version",    version=f"tigertag {__version__}")
    args = ap.parse_args(argv)

    if args.sync_only:
        sys.exit(_update((["--db", args.db] if args.db else [])
                         + (["--data-dir", args.data_dir] if args.data_dir else [])))

    if not args.dump:
        ap.print_help()
        sys.exit(0)

    # Parse
    try:
        with open(args.dump, "rb") as f:
            raw_data = f.read()
    except FileNotFoundError:
        print(f"Error: file not found: {args.dump}", file=sys.stderr)
        sys.exit(1)

    try:
        tag = TigerTag.from_dump(raw_data)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Warnings
    for w in tag.validate():
        print(f"Warning: {w}", file=sys.stderr)

    # Raw mode (no DB)
    if args.raw:
        pprint.pprint(tag)
        sys.exit(0)

    try:
        db = TigerTagDB(Path(args.db) if args.db else None,
                        data_dir=Path(args.data_dir) if args.data_dir else None,
                        offline=args.offline or None, auto_update=not args.no_sync)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Signature verification
    sig_result = tag.verify(db) if tag.is_signed else SignatureResult(SignatureResult.UNSIGNED)

    # Output
    if args.json:
        d = tag.to_dict(db)
        d["signature"] = sig_result.to_dict()
        print(json.dumps(d, indent=2, default=str))
    else:
        print(tag.pretty(db, sig_result))
