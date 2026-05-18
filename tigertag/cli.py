# TigerTag RFID Guide
# Copyright (C) 2025 TigerTag
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License.

"""CLI entry point for the TigerTag SDK."""

from __future__ import annotations

import argparse
import json
import pprint
import sys
from pathlib import Path

from tigertag.db import TigerTagDB, sync_databases, _REQUESTS_AVAILABLE, _BUNDLED_DB_PATH
from tigertag.signature import SignatureResult
from tigertag.tag import TigerTag

try:
    from tigertag import __version__
except ImportError:
    __version__ = "1.0.0"


def main() -> None:
    """
    TigerTag CLI — parse, verify, and export TigerTag RFID chip dumps.

    Usage:
        tigertag dump.bin              parse + human-readable output
        tigertag dump.bin --json       output as JSON
        tigertag dump.bin --raw        raw dataclass (no DB lookup)
        tigertag --sync-only           update databases only
        tigertag --version             show version
    """
    ap = argparse.ArgumentParser(
        prog="tigertag",
        description="TigerTag RFID material identification SDK",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  tigertag dump.bin              # parse + auto-sync DB\n"
            "  tigertag dump.bin --json       # output as JSON\n"
            "  tigertag dump.bin --raw        # raw IDs, no DB lookup\n"
            "  tigertag --sync-only           # update databases only\n"
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
    ap.add_argument(
        "--db",
        metavar="PATH",
        default=None,
        help="Database folder (default: bundled database inside the package)",
    )
    ap.add_argument("--json",      action="store_true", help="Output as JSON")
    ap.add_argument("--raw",       action="store_true", help="Print raw dataclass, no DB lookup")
    ap.add_argument("--no-sync",   action="store_true", help="Do not auto-download databases")
    ap.add_argument("--sync-only", action="store_true", help="Update databases and exit")
    ap.add_argument("--version",   action="version",    version=f"tigertag {__version__}")
    args = ap.parse_args()

    db_path = Path(args.db) if args.db else _BUNDLED_DB_PATH

    # Sync-only mode
    if args.sync_only:
        if not _REQUESTS_AVAILABLE:
            print(
                "Error: database sync requires 'requests'.\n"
                "Install it with:  pip install tigertag[sync]",
                file=sys.stderr,
            )
            sys.exit(1)
        updated = sync_databases(db_path, verbose=True)
        if updated:
            print(f"\nUpdated {len(updated)} file(s): {', '.join(updated)}")
        else:
            print("\nAll databases already up to date.")
        sys.exit(0)

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

    # Load DB (auto-sync unless --no-sync)
    db = TigerTagDB(db_path, auto_sync=not args.no_sync)

    # Signature verification
    sig_result = tag.verify(db) if tag.is_signed else SignatureResult(SignatureResult.UNSIGNED)

    # Output
    if args.json:
        d = tag.to_dict(db)
        d["signature"] = sig_result.to_dict()
        print(json.dumps(d, indent=2, default=str))
    else:
        print(tag.pretty(db, sig_result))
