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

"""
parse_tigertag.py — TigerTag Python SDK  (v1.1)
================================================
Single-file, self-contained SDK for reading, writing, and syncing TigerTag RFID chips.

Spec    : https://github.com/TigerTag-Project/TigerTag-RFID-Guide
SDK repo: https://github.com/TigerTag-Project/tigertag-sdk-python

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SCOPE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  All material data (temperatures, material, brand, colors…) is stored directly
  on the chip. No API call is required to read a tag.

  TigerTag+ chips carry a cloud product ID (id_product ≠ 0xFFFFFFFF).
  This SDK reads all chip fields identically for every tag type.
  Use diff_api() / patch_from_api() to compare chip data against the
  TigerTag+ cloud API and apply manufacturer updates.

  ┌─────────────────────────────────────────────────────────────────────┐
  │  TigerTag type    │  Read         │  Write        │  Cloud sync     │
  ├───────────────────┼───────────────┼───────────────┼─────────────────┤
  │  TigerTag (Maker) │  ✅ full      │  ✅ create()  │  —              │
  │  TigerTag Init    │  ✅ full      │  ✅ as_init() │  —              │
  │  TigerTag+        │  ✅ full      │  ✅ create()  │  ✅ diff_api()  │
  └───────────────────┴───────────────┴───────────────┴─────────────────┘

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
QUICK START
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # Parse a tag from binary dump
  from parse_tigertag import TigerTag

  tag = TigerTag.from_dump(open("dump.bin", "rb").read())
  tag.sync_db()                    # download/update reference databases (optional)
  print(tag.pretty())              # human-readable output
  print(tag.to_dict())             # dict for JSON / API
  print(tag.verify())              # ECDSA signature verification

  # Create a new tag from scratch
  tag = TigerTag.create(id_material=38219, nozzle_temp_min=190, nozzle_temp_max=230)
  chip.write_pages(4, tag.to_bytes())

  # Surgical update (immutable — returns a new TigerTag)
  updated = tag.patch(dry_temp=55, nozzle_temp_max=240)

  # TigerTag+ cloud sync
  diffs = tag.diff_api()
  new_tag, applied = tag.patch_from_api()

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DEPENDENCIES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  REQUIRED — core parsing (Python stdlib, no install needed):
    struct, json, os, sys, pathlib, dataclasses, datetime, typing

  OPTIONAL for database sync (auto-download reference JSON files):
    pip install requests
    → Without this, databases must be present locally before use.

  OPTIONAL for ECDSA signature verification:
    pip install cryptography
    → Without this, verify() returns SignatureResult.NO_CRYPTO.

  Install everything at once:
    pip install requests cryptography

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BINARY LAYOUT — pages 0x04-0x27 (144 bytes)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Page      Offset  Size  Field                   Type
  ────────  ──────  ────  ──────────────────────  ────────
  0x04      +0      4B    ID TigerTag             u32 BE
  0x05      +4      4B    ID Product              u32 BE
  0x06      +8      2B    ID Material             u16 BE
  0x06      +10     1B    ID Aspect 1             u8
  0x06      +11     1B    ID Aspect 2             u8
  0x07      +12     1B    ID Type                 u8
  0x07      +13     1B    ID Diameter             u8
  0x07      +14     2B    ID Brand                u16 BE
  0x08      +16     4B    Color 1 (RGBA)          bytes
  0x09      +20     3B    Measure                 u24 BE
  0x09      +23     1B    ID Unit                 u8
  0x0A      +24     2B    Nozzle Temp Min         u16 BE  °C
  0x0A      +26     2B    Nozzle Temp Max         u16 BE  °C
  0x0B      +28     1B    Dry Temp                u8      °C
  0x0B      +29     1B    Dry Time                u8      hours
  0x0B      +30     1B    Bed Temp Min            u8      °C
  0x0B      +31     1B    Bed Temp Max            u8      °C
  0x0C      +32     4B    Twin Tag ID+Timestamp   u32 BE  sec since 2000-01-01 GMT
  0x0D      +36     3B    Color 2 (RGB)           bytes
  0x0D      +39     1B    Reserved                u8      = 0x00
  0x0E      +40     3B    Color 3 (RGB)           bytes
  0x0E      +43     1B    Reserved                u8      = 0x00
  0x0F      +44     2B    TD HueForge             u16 BE  value / 10
  0x0F      +46     2B    Reserved                u16     = 0x0000
  0x10-0x16 +48     28B   Custom Message          UTF-8
  0x17      +76     3B    Measure Available       u24 BE
  0x17      +79     1B    Reserved                u8      = 0x00
  0x18-0x1F +80     32B   Signature R (ECDSA)     bytes   optional
  0x20-0x27 +112    32B   Signature S (ECDSA)     bytes   optional

  Capacity : 80B user data + 64B signature = 144B = full user memory

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SIGNATURE ALGORITHM
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Algorithm : ECDSA SECP256R1 (P-256)
  Hash      : SHA-256
  Message   : SHA-256( UID_bytes + block4 + block5 )

  Where:
    UID_bytes = 7 raw bytes from chip pages 0-1 (NOT hex string, NOT decimal)
                page0[0:3] + page1[0:4]
    block4    = page 0x04 bytes 0-3  (ID TigerTag, u32 BE)
    block5    = page 0x05 bytes 4-7  (ID Product,  u32 BE)

  The public key is stored in id_version.json ("public_key" field).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ACCEPTED DUMP FORMATS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  180 bytes — full chip dump (pages 0-44): UID auto-extracted → signature verifiable
  144 bytes — user data + signature  (pages 0x04-0x27): signature NOT verifiable (no UID)
   80 bytes — user data only         (pages 0x04-0x17)
"""

from __future__ import annotations

# ──────────────────────────────────────────────────────────────────────────────
# Standard library (no install required)
# ──────────────────────────────────────────────────────────────────────────────
import json
import os
import struct
import sys
from dataclasses import dataclass, field, fields as _dc_fields, replace as _dc_replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ──────────────────────────────────────────────────────────────────────────────
# Optional: requests  (pip install requests)
# Required for auto-downloading reference JSON databases
# ──────────────────────────────────────────────────────────────────────────────
try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False

# ──────────────────────────────────────────────────────────────────────────────
# Optional: cryptography  (pip install cryptography)
# Required for ECDSA signature verification
# ──────────────────────────────────────────────────────────────────────────────
try:
    from cryptography.hazmat.primitives.asymmetric import ec as _ec
    from cryptography.hazmat.primitives import hashes as _hashes
    from cryptography.hazmat.primitives.serialization import load_pem_public_key as _load_pem_public_key
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature as _encode_dss_signature
    from cryptography.exceptions import InvalidSignature as _InvalidSignature
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

# Database sources
_API_BASE        = "https://api.tigertag.io/api:tigertag"
_GITHUB_RAW_BASE = "https://raw.githubusercontent.com/TigerTag-Project/TigerTag-RFID-Guide/main/database"
_HTTP_TIMEOUT    = 30

# Database files: last_update key → (API endpoint, local filename)
_DATASETS: Dict[str, tuple] = {
    "versions":           ("version/get/all",           "id_version.json"),
    "types":              ("type/get/all",              "id_type.json"),
    "brands":             ("brand/get/all",             "id_brand.json"),
    "filament_diameters": ("diameter/filament/get/all", "id_diameter.json"),
    "filament_materials": ("material/get/all",          "id_material.json"),
    "aspects":            ("aspect/get/all",            "id_aspect.json"),
    "measure_units":      ("measure_unit/get/all",      "id_measure_unit.json"),
}

# NTAG-compatible memory layout
CHIP_DUMP_LEN = 180   # full chip: 45 pages × 4B (pages 0-44)
FULL_DATA_LEN = 144   # user data + signature (pages 0x04-0x27)
MIN_DATA_LEN  = 80    # user data only        (pages 0x04-0x17)

# Epoch for TigerTag timestamps (seconds since this date)
_TIGERTAG_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)

# Product ID sentinel values
MAKER_PRODUCT_ID = 0xFFFFFFFF  # offline Maker tag
INIT_PRODUCT_ID  = 0x00000000  # blank / uninitialized tag

# Protocol version identifiers (id_tigertag field)
ID_TIGERTAG      = 0x5BF59264  # TigerTag v1.0 (Maker / offline)
ID_TIGERTAG_PLUS = 0xBC0FCB97  # TigerTag+ v1.0 (cloud product)
ID_TIGERTAG_INIT = 0x6C41A2E1  # TigerTag Init (reserved, not yet programmed)

_PRODUCT_PAGE_BASE = "https://tigertag.io/pages/product-infos"
_API_PRODUCT_BASE  = "https://api.tigertag.io/api:tigertag/product/get"

# Fields covered by the ECDSA signature — must never be modified after signing.
_PROTECTED_FIELDS: frozenset = frozenset({
    "id_tigertag", "id_product", "uid", "signature_r", "signature_s", "_db",
})


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE SYNC
# ══════════════════════════════════════════════════════════════════════════════

def sync_databases(
    db_path: Path,
    force: bool = False,
    verbose: bool = True,
) -> List[str]:
    """
    Download or update TigerTag reference JSON databases.

    Tries the live TigerTag API first; falls back to the GitHub mirror if the
    API is unreachable. Only downloads files whose timestamp has changed.

    Args:
        db_path : Folder where JSON files are stored (created if missing).
        force   : Re-download all files even if already up to date.
        verbose : Print progress to stdout.

    Returns:
        List of filenames that were downloaded/updated.

    Raises:
        RuntimeError : if both API and GitHub mirror are unreachable.
        ImportError  : if 'requests' is not installed.

    Example:
        sync_databases(Path("./database"))
    """
    if not _REQUESTS_AVAILABLE:
        raise ImportError(
            "Database sync requires 'requests'.\n"
            "Install it with:  pip install requests"
        )

    db_path = Path(db_path)
    db_path.mkdir(parents=True, exist_ok=True)
    last_update_path = db_path / "last_update.json"

    def _get(url: str):
        r = _requests.get(url, timeout=_HTTP_TIMEOUT)
        r.raise_for_status()
        return r.json(), r.text

    def _log(msg: str):
        if verbose:
            print(msg)

    # Pick source: API first, GitHub fallback
    try:
        remote_data, remote_text = _get(f"{_API_BASE}/all/last_update")
        source = "api"
        def _dataset_url(endpoint: str, filename: str) -> str:
            return f"{_API_BASE}/{endpoint}"
    except Exception as exc:
        _log(f"[warn] TigerTag API unreachable ({exc}), falling back to GitHub mirror")
        try:
            remote_data, remote_text = _get(f"{_GITHUB_RAW_BASE}/last_update.json")
        except Exception as exc2:
            raise RuntimeError(
                f"Both API and GitHub mirror are unreachable.\n"
                f"API error:    {exc}\n"
                f"GitHub error: {exc2}\n"
                f"Check your internet connection."
            ) from exc2
        source = "github"
        def _dataset_url(endpoint: str, filename: str) -> str:
            return f"{_GITHUB_RAW_BASE}/{filename}"

    _log(f"[info] source: {source}")

    # Load local timestamps
    local_data: Dict = {}
    if last_update_path.exists():
        try:
            local_data = json.loads(last_update_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    updated: List[str] = []

    for key, (endpoint, filename) in _DATASETS.items():
        remote_ts = remote_data.get(key)
        local_ts  = local_data.get(key)
        local_file = db_path / filename

        if remote_ts is None:
            _log(f"[skip] {key}: not in last_update payload")
            continue

        if not force and remote_ts == local_ts and local_file.exists():
            _log(f"[ok]   {filename}: up to date")
            continue

        _log(f"[sync] {filename}: {local_ts} → {remote_ts}")
        r = _requests.get(_dataset_url(endpoint, filename), timeout=_HTTP_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        local_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        updated.append(filename)

    if updated or local_data != remote_data:
        last_update_path.write_text(remote_text, encoding="utf-8")
        if "last_update.json" not in updated:
            updated.append("last_update.json")

    return updated


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE LOADER
# ══════════════════════════════════════════════════════════════════════════════

class TigerTagDB:
    """
    Loads and exposes TigerTag JSON reference databases.

    All ID lookups return the full JSON entry dict (or None if not found).
    The JSON files are the single source of truth — no hardcoded ID mappings.

    Args:
        db_path     : Folder containing the JSON files.
        auto_sync   : Download missing/stale files automatically (requires requests).
        verbose     : Print sync progress.

    Example:
        db = TigerTagDB(Path("./database"), auto_sync=True)
        mat = db.material(38219)
        print(mat["label"])   # "PLA"
        print(mat["density"]) # 1.24
    """

    REQUIRED_FILES = list(_DATASETS.values())  # list of (endpoint, filename) tuples

    def __init__(
        self,
        db_path: Path = None,
        auto_sync: bool = True,
        verbose: bool = True,
    ):
        self._path = Path(db_path) if db_path else Path(__file__).parent / "database"
        self._auto_sync = auto_sync
        self._verbose = verbose
        self._ensure_db()
        self._versions   = self._load("id_version.json")
        self._materials  = self._load("id_material.json")
        self._aspects    = self._load("id_aspect.json")
        self._types      = self._load("id_type.json")
        self._diameters  = self._load("id_diameter.json")
        self._brands     = self._load("id_brand.json")
        self._units      = self._load("id_measure_unit.json")

    def _ensure_db(self) -> None:
        """Check for missing files; auto-sync or print clear error."""
        missing = [fn for _, fn in self.REQUIRED_FILES if not (self._path / fn).exists()]
        if not missing:
            return

        if self._auto_sync and _REQUESTS_AVAILABLE:
            print(f"[info] Missing {len(missing)} database file(s) — downloading now...")
            try:
                sync_databases(self._path, verbose=self._verbose)
                return
            except Exception as exc:
                print(f"[warn] Auto-sync failed: {exc}", file=sys.stderr)

        # Still missing after sync attempt (or auto_sync=False / no requests)
        missing_still = [fn for _, fn in self.REQUIRED_FILES if not (self._path / fn).exists()]
        if not missing_still:
            return

        print("", file=sys.stderr)
        print("❌  TigerTag database files not found.", file=sys.stderr)
        print(f"    Expected folder: {self._path.resolve()}", file=sys.stderr)
        print("", file=sys.stderr)
        print("    Missing files:", file=sys.stderr)
        for fn in missing_still:
            print(f"      • {fn}", file=sys.stderr)
        print("", file=sys.stderr)
        if not _REQUESTS_AVAILABLE:
            print("    ⚠️  'requests' is not installed — cannot auto-download.", file=sys.stderr)
            print("    Install it first:  pip install requests", file=sys.stderr)
            print("", file=sys.stderr)
        print("    ➜  Run:  python parse_tigertag.py --sync-only", file=sys.stderr)
        print("", file=sys.stderr)
        sys.exit(1)

    def _load(self, filename: str) -> List[Dict]:
        fp = self._path / filename
        if not fp.exists():
            return []
        with open(fp, encoding="utf-8") as f:
            return json.load(f)

    def _find(self, table: List[Dict], id_value: int) -> Optional[Dict]:
        return next((e for e in table if e.get("id") == id_value), None)

    def sync(self, force: bool = False) -> List[str]:
        """Manually trigger a database update. Returns list of updated files."""
        updated = sync_databases(self._path, force=force, verbose=self._verbose)
        # Reload updated files
        self._versions   = self._load("id_version.json")
        self._materials  = self._load("id_material.json")
        self._aspects    = self._load("id_aspect.json")
        self._types      = self._load("id_type.json")
        self._diameters  = self._load("id_diameter.json")
        self._brands     = self._load("id_brand.json")
        self._units      = self._load("id_measure_unit.json")
        return updated

    # ── Lookups (return full JSON entry or None) ──────────────────────────────

    def version(self, id_value: int) -> Optional[Dict]:
        """id_version.json — includes public_key for signature verification."""
        return self._find(self._versions, id_value)

    def material(self, id_value: int) -> Optional[Dict]:
        """id_material.json — includes density, recommended temps, bambuID…"""
        return self._find(self._materials, id_value)

    def aspect(self, id_value: int) -> Optional[Dict]:
        """id_aspect.json — includes color_count."""
        return self._find(self._aspects, id_value)

    def type_(self, id_value: int) -> Optional[Dict]:
        """id_type.json."""
        return self._find(self._types, id_value)

    def diameter(self, id_value: int) -> Optional[Dict]:
        """id_diameter.json."""
        return self._find(self._diameters, id_value)

    def brand(self, id_value: int) -> Optional[Dict]:
        """id_brand.json."""
        return self._find(self._brands, id_value)

    def unit(self, id_value: int) -> Optional[Dict]:
        """id_measure_unit.json."""
        return self._find(self._units, id_value)

    @staticmethod
    def label(entry: Optional[Dict]) -> str:
        """Safe label from any DB entry dict."""
        if entry is None:
            return "Unknown"
        return entry.get("label") or entry.get("name") or "Unknown"


# ══════════════════════════════════════════════════════════════════════════════
# API DIFF
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ApiDiff:
    """
    A single field difference between chip data and the TigerTag+ cloud API.

    Returned by TigerTag.diff_api().

    Attributes:
        field      : Field name (e.g. "nozzle_min").
        chip_value : Value currently stored on the chip.
        api_value  : Value returned by the cloud API.

    Example:
        from parse_tigertag import ApiDiff, TigerTag

        diffs = tag.diff_api()
        for d in diffs:
            print(f"{d.field}: chip={d.chip_value!r}  →  api={d.api_value!r}")
    """

    field:      str
    chip_value: Any
    api_value:  Any

    def __repr__(self) -> str:
        return f"  {self.field}: chip={self.chip_value!r}  →  api={self.api_value!r}"


# ══════════════════════════════════════════════════════════════════════════════
# SIGNATURE RESULT
# ══════════════════════════════════════════════════════════════════════════════

class SignatureResult:
    """
    Result of an ECDSA signature verification.

    Attributes:
        status  : One of the class constants (VALID, INVALID, UNSIGNED, …)
        ok      : True only when status == VALID
        detail  : Human-readable explanation for failures

    Example:
        result = tag.verify()
        if result.ok:
            print("Authentic TigerTag")
        else:
            print(f"Problem: {result}")
    """

    VALID     = "valid"     # ✅ signature present and cryptographically correct
    INVALID   = "invalid"   # ❌ signature present but verification failed
    UNSIGNED  = "unsigned"  # ⬜ no signature (all zeros in pages 0x18-0x27)
    NO_CRYPTO = "no_crypto" # ⚠️  'cryptography' package not installed
    NO_KEY    = "no_key"    # ⚠️  public key missing from id_version.json
    NO_UID    = "no_uid"    # ⚠️  UID unavailable (partial dump, not 180 bytes)

    _ICONS = {
        VALID:     "✅ VALID",
        INVALID:   "❌ INVALID",
        UNSIGNED:  "⬜ NOT SIGNED",
        NO_CRYPTO: "⚠️  cryptography not installed — run: pip install cryptography",
        NO_KEY:    "⚠️  public key not found in id_version.json",
        NO_UID:    "⚠️  UID unavailable — provide a full 180-byte chip dump",
    }

    def __init__(self, status: str, detail: str = ""):
        self.status = status
        self.detail = detail
        self.ok     = (status == self.VALID)

    def __str__(self) -> str:
        base = self._ICONS.get(self.status, f"? {self.status}")
        return f"{base}  {self.detail}".rstrip()

    def __repr__(self) -> str:
        return f"SignatureResult(status={self.status!r}, ok={self.ok})"

    def to_dict(self) -> Dict:
        return {"status": self.status, "ok": self.ok, "detail": self.detail}


# ══════════════════════════════════════════════════════════════════════════════
# TIGERTAG — MAIN CLASS
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class TigerTag:
    """
    TigerTag chip payload — full CRUD interface.

    All fields are plain integers/bytes/strings. Use a TigerTagDB instance
    (via .db property or pass one to to_dict()) to get human-readable labels.

    Create:
        tag = TigerTag.create(id_material=38219, nozzle_temp_min=190, ...)
        chip.write_pages(4, tag.to_bytes())

    Read:
        tag = TigerTag.from_pages(uid, payload)
        tag = TigerTag.from_dump(data)
        tag = TigerTag.from_file("dump.bin")

    Update (surgical, immutable):
        new_tag = tag.patch(dry_temp=55, nozzle_temp_max=240)

    Update (auto-sync from cloud API — TigerTag+ only):
        new_tag, applied = tag.patch_from_api()

    Init (mark chip as reserved without full programming):
        chip.write_pages(4, TigerTag.as_init().to_bytes())

    Delete (wipe back to blank):
        chip.write_pages(4, TigerTag.erase())
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    id_tigertag : int    # u32 BE — format/version identifier (see id_version.json)
    id_product  : int    # u32 BE — 0xFFFFFFFF=Maker, 0=Init, else cloud product ID

    # ── Material (all IDs resolve via TigerTagDB) ──────────────────────────────
    id_material : int    # u16 BE — see id_material.json
    id_aspect_1 : int    # u8    — see id_aspect.json
    id_aspect_2 : int    # u8    — see id_aspect.json
    id_type     : int    # u8    — see id_type.json (0x8E=Filament, 0xAD=Resin)
    id_diameter : int    # u8    — see id_diameter.json (0x38=1.75mm, 0xDD=2.85mm)
    id_brand    : int    # u16 BE — see id_brand.json

    # ── Colors ─────────────────────────────────────────────────────────────────
    color1_r : int       # Color 1 Red   (page 0x08)
    color1_g : int       # Color 1 Green
    color1_b : int       # Color 1 Blue
    color1_a : int       # Color 1 Alpha
    color2_r : int       # Color 2 Red   (page 0x0D)
    color2_g : int       # Color 2 Green
    color2_b : int       # Color 2 Blue
    color3_r : int       # Color 3 Red   (page 0x0E)
    color3_g : int       # Color 3 Green
    color3_b : int       # Color 3 Blue

    # ── Quantity ───────────────────────────────────────────────────────────────
    measure           : int  # u24 BE — quantity at manufacturing
    id_unit           : int  # u8    — see id_measure_unit.json
    measure_available : int  # u24 BE — remaining (updated by Tiger Scale)

    # ── Temperatures (°C) ─────────────────────────────────────────────────────
    nozzle_temp_min : int  # u16 BE — minimum nozzle temperature
    nozzle_temp_max : int  # u16 BE — maximum nozzle temperature
    dry_temp        : int  # u8
    dry_time        : int  # u8 hours
    bed_temp_min    : int  # u8
    bed_temp_max    : int  # u8

    # ── Traceability ──────────────────────────────────────────────────────────
    timestamp      : int   # u32 BE — seconds since 2000-01-01 GMT + twin tag pairing ID
    custom_message : str   # UTF-8, max 28 bytes (emoji allowed)

    # ── HueForge ──────────────────────────────────────────────────────────────
    td_raw : int           # u16 BE — actual TD = td_raw / 10  (0=undefined, 1-1000 valid)

    # ── Signature (optional, pages 0x18-0x27) ─────────────────────────────────
    signature_r : bytes = field(default_factory=lambda: bytes(32))
    signature_s : bytes = field(default_factory=lambda: bytes(32))

    # ── Chip UID (auto-extracted from full 180-byte dump, else None) ───────────
    uid : Optional[bytes] = field(default=None)

    # ── Internal: lazily loaded DB ────────────────────────────────────────────
    _db : Optional[TigerTagDB] = field(default=None, repr=False, compare=False)

    # ── Derived properties ────────────────────────────────────────────────────

    @property
    def is_maker(self) -> bool:
        """True when id_product == 0xFFFFFFFF (offline Maker tag)."""
        return self.id_product == MAKER_PRODUCT_ID

    @property
    def is_init(self) -> bool:
        """True when id_product == 0x00000000 (blank/uninitialized tag)."""
        return self.id_product == INIT_PRODUCT_ID

    @property
    def is_plus(self) -> bool:
        """True when the tag has a cloud product ID (TigerTag+)."""
        return not self.is_maker and not self.is_init

    @property
    def is_signed(self) -> bool:
        """True when the tag carries an ECDSA signature (pages 0x18-0x27 non-zero)."""
        return self.signature_r != bytes(32) or self.signature_s != bytes(32)

    @property
    def uid_hex(self) -> Optional[str]:
        """UID as uppercase hex string (e.g. '04AABBCCDDEE11'), or None."""
        return self.uid.hex().upper() if self.uid else None

    @property
    def td_value(self) -> float:
        """HueForge TD as float. 0.0=undefined, valid range 0.1–100.0."""
        return self.td_raw / 10.0

    @property
    def manufacturing_date(self) -> datetime:
        """Manufacturing timestamp as UTC datetime."""
        return datetime.fromtimestamp(
            _TIGERTAG_EPOCH.timestamp() + self.timestamp,
            tz=timezone.utc,
        )

    @property
    def color1_hex(self) -> str:
        """Primary color as #RRGGBB hex string."""
        return f"#{self.color1_r:02X}{self.color1_g:02X}{self.color1_b:02X}"

    @property
    def color2_hex(self) -> str:
        """Secondary color as #RRGGBB hex string."""
        return f"#{self.color2_r:02X}{self.color2_g:02X}{self.color2_b:02X}"

    @property
    def color3_hex(self) -> str:
        """Tertiary color as #RRGGBB hex string."""
        return f"#{self.color3_r:02X}{self.color3_g:02X}{self.color3_b:02X}"

    @property
    def stock_percent(self) -> Optional[float]:
        """Remaining material as a percentage, or None if measure is zero."""
        if self.measure == 0:
            return None
        return round((self.measure_available / self.measure) * 100, 1)

    @property
    def product_page_url(self) -> Optional[str]:
        """Public product page URL (TigerTag+ only, None otherwise)."""
        if self.is_maker or self.is_init:
            return None
        return f"{_PRODUCT_PAGE_BASE}/{self.id_product}"

    @property
    def api_url(self) -> Optional[str]:
        """Direct API URL returning the full enriched product JSON (TigerTag+ only)."""
        if self.is_maker or self.is_init:
            return None
        uid_part = f"uid={int(self.uid_hex, 16)}&" if self.uid_hex else ""
        return f"{_API_PRODUCT_BASE}?{uid_part}product_id={self.id_product}"

    # ── Database ──────────────────────────────────────────────────────────────

    @property
    def db(self) -> TigerTagDB:
        """Lazily loaded database (auto-downloads if needed)."""
        if self._db is None:
            self._db = TigerTagDB()
        return self._db

    def sync_db(self, db_path: Path = None, force: bool = False) -> List[str]:
        """Download or update reference databases. Returns list of updated files."""
        path = Path(db_path) if db_path else Path(__file__).parent / "database"
        self._db = TigerTagDB(path, auto_sync=True)
        return self._db.sync(force=force)

    # ── Cloud API (TigerTag+ only) ────────────────────────────────────────────

    def raw_api(self, timeout: int = 5) -> Optional[Dict[str, Any]]:
        """
        Fetch the raw TigerTag+ cloud product data from the API.

        Returns the unmodified API JSON as a Python dict.
        Only meaningful for TigerTag+ chips (returns None for Maker/Init tags).
        Uses stdlib urllib — no extra dependency required.

        Args:
            timeout : Request timeout in seconds (default: 5).

        Returns:
            Raw API response dict, or None if not a TigerTag+ chip.

        Raises:
            RuntimeError : If the network request fails.

        Example:
            data = tag.raw_api()
            if data:
                print(data["title"])
        """
        if self.is_maker or self.is_init:
            return None

        import json as _json
        import urllib.error
        import urllib.request

        try:
            with urllib.request.urlopen(self.api_url, timeout=timeout) as resp:
                return _json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"TigerTag+ API request failed ({exc}). "
                f"Verify network access or browse: {self.product_page_url}"
            ) from exc

    def diff_api(
        self,
        api_data: Optional[Dict[str, Any]] = None,
        db: Optional[TigerTagDB] = None,
    ) -> List[ApiDiff]:
        """
        Compare chip data against the TigerTag+ cloud API.

        Returns a list of ApiDiff entries for every field whose value on the chip
        differs from what the API currently reports. Empty list = fully in sync.

        Args:
            api_data : Pre-fetched result of raw_api(). Fetched automatically when None.
            db       : Optional TigerTagDB.

        Returns:
            List of ApiDiff. Empty = in sync.

        Raises:
            RuntimeError : If api_data is None and the network request fails.

        Example:
            diffs = tag.diff_api()
            for d in diffs:
                print(d)
        """
        if self.is_maker or self.is_init:
            return []

        _db  = db or self.db
        data = api_data if api_data is not None else self.raw_api()
        if not data:
            return []

        diffs: List[ApiDiff] = []

        def _lbl(entry: Any) -> str:
            return (TigerTagDB.label(entry) or "").strip().lower()

        def _check(fname: str, chip_val: Any, api_val: Any) -> None:
            if api_val is None:
                return
            if str(chip_val).strip().lower() != str(api_val).strip().lower():
                diffs.append(ApiDiff(fname, chip_val, api_val))

        fil    = data.get("filament") or {}
        nozzle = data.get("nozzle")   or {}
        bed    = data.get("bed")      or {}
        dryer  = data.get("dryer")    or {}

        # Temperatures
        _check("nozzle_min", self.nozzle_temp_min, nozzle.get("temp_min"))
        _check("nozzle_max", self.nozzle_temp_max, nozzle.get("temp_max"))
        _check("bed_min",    self.bed_temp_min,    bed.get("temp_min"))
        _check("bed_max",    self.bed_temp_max,    bed.get("temp_max"))
        _check("dry_temp",   self.dry_temp,        dryer.get("temp"))
        _check("dry_time",   self.dry_time,        dryer.get("time"))

        # Material identification
        _check("type",     _lbl(_db.type_(self.id_type)),        (data.get("product_type") or "").lower())
        _check("material", _lbl(_db.material(self.id_material)), (fil.get("material") or "").lower())
        _check("brand",    _lbl(_db.brand(self.id_brand)),       (data.get("brand") or "").lower())
        _check("diameter", TigerTagDB.label(_db.diameter(self.id_diameter)) or "",
                           str(fil.get("diameter") or ""))

        _EMPTY_ASPECT = {"", "unknown", "-", "none"}

        def _check_aspect(fname: str, chip_id: int, api_val: Optional[str]) -> None:
            chip_lbl = _lbl(_db.aspect(chip_id))
            api_norm = (api_val or "").strip().lower()
            if chip_lbl in _EMPTY_ASPECT and api_norm in _EMPTY_ASPECT:
                return
            if chip_lbl != api_norm:
                diffs.append(ApiDiff(fname, chip_lbl or "none", api_val or "none"))

        _check_aspect("aspect_1", self.id_aspect_1, fil.get("aspect1"))
        _check_aspect("aspect_2", self.id_aspect_2, fil.get("aspect2"))

        # Colors
        def _parse_api_color(hex_str: str) -> Optional[Tuple[int, int, int, int]]:
            h = (hex_str or "").lstrip("#")
            try:
                if len(h) == 8:
                    return int(h[0:2],16), int(h[2:4],16), int(h[4:6],16), int(h[6:8],16)
                if len(h) == 6:
                    return int(h[0:2],16), int(h[2:4],16), int(h[4:6],16), 255
            except ValueError:
                pass
            return None

        api_colors: List[str] = []
        color_info = fil.get("color_info") or {}
        if color_info.get("colors"):
            api_colors = [c for c in color_info["colors"] if c]
        elif fil.get("color"):
            api_colors = [fil["color"]]

        if api_colors:
            c = _parse_api_color(api_colors[0])
            if c:
                chip_hex = f"#{self.color1_r:02X}{self.color1_g:02X}{self.color1_b:02X}{self.color1_a:02X}"
                api_hex  = f"#{c[0]:02X}{c[1]:02X}{c[2]:02X}{c[3]:02X}"
                if chip_hex.lower() != api_hex.lower():
                    diffs.append(ApiDiff("color_1", chip_hex, api_hex))

        if len(api_colors) > 1:
            c = _parse_api_color(api_colors[1])
            if c:
                chip_hex = f"#{self.color2_r:02X}{self.color2_g:02X}{self.color2_b:02X}"
                api_hex  = f"#{c[0]:02X}{c[1]:02X}{c[2]:02X}"
                if chip_hex.lower() != api_hex.lower():
                    diffs.append(ApiDiff("color_2", chip_hex, api_hex))

        if len(api_colors) > 2:
            c = _parse_api_color(api_colors[2])
            if c:
                chip_hex = f"#{self.color3_r:02X}{self.color3_g:02X}{self.color3_b:02X}"
                api_hex  = f"#{c[0]:02X}{c[1]:02X}{c[2]:02X}"
                if chip_hex.lower() != api_hex.lower():
                    diffs.append(ApiDiff("color_3", chip_hex, api_hex))

        if fil.get("grams") is not None:
            _check("measure_g", self.measure, int(fil["grams"]))
        if fil.get("measure_unit"):
            _check("measure_unit",
                   TigerTagDB.label(_db.unit(self.id_unit)) or "",
                   (fil["measure_unit"] or "").strip())

        return diffs

    def patch(self, **kwargs: Any) -> "TigerTag":
        """
        Return a new TigerTag with selected fields replaced (immutable).

        Protected fields (id_tigertag, id_product, uid, signature_r, signature_s)
        are covered by the ECDSA signature and cannot be modified.

        Args:
            **kwargs: Field names and their new values.

        Returns:
            A new TigerTag instance with the requested fields updated.
            The original instance is unchanged.

        Raises:
            ValueError: If any protected or unknown field is requested.

        Example:
            updated = tag.patch(nozzle_temp_min=200, dry_temp=55)
        """
        protected = set(kwargs.keys()) & _PROTECTED_FIELDS
        if protected:
            raise ValueError(
                f"Cannot modify protected field(s): {', '.join(sorted(protected))}. "
                "These fields are covered by the ECDSA signature and must never change."
            )
        valid = {f.name for f in _dc_fields(self)} - _PROTECTED_FIELDS
        unknown = set(kwargs.keys()) - valid
        if unknown:
            raise ValueError(
                f"Unknown field(s): {', '.join(sorted(unknown))}. "
                f"Valid patchable fields: {', '.join(sorted(valid))}"
            )
        return _dc_replace(self, **kwargs)

    def patch_from_api(
        self,
        api_data: Optional[Dict[str, Any]] = None,
        db: Optional[TigerTagDB] = None,
    ) -> Tuple["TigerTag", List[ApiDiff]]:
        """
        Apply API-sourced field updates surgically, without touching the signature.

        Fetches current product data from the TigerTag+ cloud API (or uses
        api_data if supplied), computes the diff, and patches all numeric fields
        that differ (temperatures, drying parameters, weight).

        Args:
            api_data : Pre-fetched API dict. If None, calls raw_api().
            db       : Override the database used for label resolution.

        Returns:
            (updated_tag, applied_diffs) — a patched TigerTag and the list of
            ApiDiff entries that were applied. Returns (self, []) for Maker/Init.

        Raises:
            RuntimeError: If the network request fails (only when api_data is None).

        Example:
            new_tag, applied = tag.patch_from_api()
            if applied:
                print(f"Updated {len(applied)} field(s).")
                chip.write_pages(4, new_tag.to_bytes())
        """
        if self.is_maker or self.is_init:
            return self, []

        _db  = db or self.db
        data = api_data if api_data is not None else self.raw_api()
        if not data:
            return self, []

        diffs = self.diff_api(api_data=data, db=_db)
        if not diffs:
            return self, []

        _FIELD_MAP: Dict[str, str] = {
            "nozzle_min": "nozzle_temp_min",
            "nozzle_max": "nozzle_temp_max",
            "bed_min":    "bed_temp_min",
            "bed_max":    "bed_temp_max",
            "dry_temp":   "dry_temp",
            "dry_time":   "dry_time",
            "measure_g":  "measure",
        }

        def _hex_to_rgba(hex_str: str) -> Optional[Tuple[int, int, int, int]]:
            h = hex_str.lstrip("#")
            try:
                if len(h) == 8:
                    return int(h[0:2],16), int(h[2:4],16), int(h[4:6],16), int(h[6:8],16)
                if len(h) == 6:
                    return int(h[0:2],16), int(h[2:4],16), int(h[4:6],16), 255
            except ValueError:
                pass
            return None

        updates: Dict[str, Any] = {}
        applied: List[ApiDiff]  = []
        for diff in diffs:
            if diff.field in ("color_1", "color_2", "color_3"):
                rgba = _hex_to_rgba(str(diff.api_value))
                if rgba:
                    r, g, b, a = rgba
                    if diff.field == "color_1":
                        updates.update(color1_r=r, color1_g=g, color1_b=b, color1_a=a)
                    elif diff.field == "color_2":
                        updates.update(color2_r=r, color2_g=g, color2_b=b)
                    else:
                        updates.update(color3_r=r, color3_g=g, color3_b=b)
                    applied.append(diff)
                continue

            tag_field = _FIELD_MAP.get(diff.field)
            if tag_field:
                updates[tag_field] = int(diff.api_value)
                applied.append(diff)

        if not updates:
            return self, []

        return self.patch(**updates), applied

    # ── Constructors ──────────────────────────────────────────────────────────

    @classmethod
    def from_pages(cls, uid: bytes, payload: bytes, db: TigerTagDB = None) -> "TigerTag":
        """
        Parse a TigerTag from NFC SDK native output.  ← PRIMARY METHOD

        This is the recommended constructor for production use with any NFC SDK.
        The UID and payload are provided separately, exactly as NFC SDKs expose them.

        Args:
            payload : 80 or 144 bytes — pages 0x04 to 0x27 read by the NFC SDK.
                      80 bytes  = pages 0x04-0x17 (user data, no signature)
                      144 bytes = pages 0x04-0x27 (user data + ECDSA signature)
            uid     : 7-byte chip UID as returned natively by the NFC SDK.
                      Raw bytes only — NOT a hex string, NOT a decimal integer.
            db      : Optional pre-loaded TigerTagDB instance.

        Returns:
            TigerTag with .uid set and .verify() fully operational.

        Example:
            tag = TigerTag.from_pages(uid, payload)
            result = tag.verify()  # ✅ fully autonomous
        """
        if len(payload) not in (MIN_DATA_LEN, FULL_DATA_LEN):
            raise ValueError(
                f"Invalid payload size: {len(payload)} bytes. "
                f"Expected 80B (pages 0x04-0x17) or 144B (pages 0x04-0x27)."
            )
        if not uid or len(uid) != 7:
            raise ValueError(
                f"Invalid UID: expected 7 bytes, got {len(uid) if uid else 0}. "
                f"Pass the raw bytes returned by your NFC SDK."
            )
        tag = cls.from_dump(payload, db=db)
        tag.uid = uid
        return tag

    @classmethod
    def from_dump(cls, data: bytes, db: TigerTagDB = None) -> "TigerTag":
        """
        Parse a TigerTag from a raw binary dump.

        Use this for full chip dumps (files, ACR122U raw read, testing).
        For production NFC SDK integration, prefer from_pages() instead.

        Args:
            data : Accepted sizes:
                   180 bytes — full chip dump (pages 0-44):
                               UID auto-extracted from system pages.
                   144 bytes — user data + signature (pages 0x04-0x27):
                               UID not available, signature cannot be verified.
                    80 bytes — user data only (pages 0x04-0x17).
            db   : Optional pre-loaded TigerTagDB instance.

        Raises:
            ValueError : if data length is not 80, 144, or 180 bytes.
        """
        uid: Optional[bytes] = None

        if len(data) == CHIP_DUMP_LEN:
            # Extract 7-byte UID from system pages:
            #   Page 0 [0:3] = UID[0..2], Page 1 [0:4] = UID[3..6]
            #   Byte 3 of page 0 is BCC0 (XOR check) — excluded from UID.
            uid  = data[0:3] + data[4:8]
            data = data[16:160]  # strip system pages → 144 bytes of user data

        if len(data) not in (MIN_DATA_LEN, FULL_DATA_LEN):
            raise ValueError(
                f"Invalid dump size: {len(data)} bytes.\n"
                f"Accepted: 180B (full chip), 144B (user+sig), 80B (user only)."
            )

        def u8 (o: int) -> int: return data[o]
        def u16(o: int) -> int: return struct.unpack_from(">H", data, o)[0]
        def u24(o: int) -> int: return (data[o]<<16)|(data[o+1]<<8)|data[o+2]
        def u32(o: int) -> int: return struct.unpack_from(">I", data, o)[0]

        msg   = data[48:76].rstrip(b"\x00").decode("utf-8", errors="replace")
        sig_r = data[80:112]  if len(data) >= FULL_DATA_LEN else bytes(32)
        sig_s = data[112:144] if len(data) >= FULL_DATA_LEN else bytes(32)

        tag = cls(
            id_tigertag       = u32(0),
            id_product        = u32(4),
            id_material       = u16(8),
            id_aspect_1       = u8(10),
            id_aspect_2       = u8(11),
            id_type           = u8(12),
            id_diameter       = u8(13),
            id_brand          = u16(14),
            color1_r          = u8(16),
            color1_g          = u8(17),
            color1_b          = u8(18),
            color1_a          = u8(19),
            measure           = u24(20),
            id_unit           = u8(23),
            nozzle_temp_min   = u16(24),
            nozzle_temp_max   = u16(26),
            dry_temp          = u8(28),
            dry_time          = u8(29),
            bed_temp_min      = u8(30),
            bed_temp_max      = u8(31),
            timestamp         = u32(32),
            color2_r          = u8(36),
            color2_g          = u8(37),
            color2_b          = u8(38),
            color3_r          = u8(40),
            color3_g          = u8(41),
            color3_b          = u8(42),
            td_raw            = u16(44),
            custom_message    = msg,
            measure_available = u24(76),
            signature_r       = sig_r,
            signature_s       = sig_s,
            uid               = uid,
        )
        tag._db = db
        return tag

    @classmethod
    def from_file(cls, path, db: TigerTagDB = None) -> "TigerTag":
        """
        Parse a TigerTag from a .bin file.

        Args:
            path : Path to binary dump file (str or Path)
            db   : Optional pre-loaded TigerTagDB

        Example:
            tag = TigerTag.from_file("dump.bin")
        """
        with open(path, "rb") as f:
            return cls.from_dump(f.read(), db=db)

    # ── CRUD constructors ─────────────────────────────────────────────────────

    @classmethod
    def create(
        cls,
        *,
        product_id: int = MAKER_PRODUCT_ID,
        uid: Optional[bytes] = None,
        id_material: int = 0,
        id_aspect_1: int = 0,
        id_aspect_2: int = 0,
        id_type:     int = 0,
        id_diameter: int = 0,
        id_brand:    int = 0,
        color1_r: int = 0, color1_g: int = 0, color1_b: int = 0, color1_a: int = 255,
        color2_r: int = 0, color2_g: int = 0, color2_b: int = 0,
        color3_r: int = 0, color3_g: int = 0, color3_b: int = 0,
        measure:         int = 0,
        id_unit:         int = 0,
        nozzle_temp_min: int = 0,
        nozzle_temp_max: int = 0,
        dry_temp:        int = 0,
        dry_time:        int = 0,
        bed_temp_min:    int = 0,
        bed_temp_max:    int = 0,
        timestamp:      Optional[int] = None,
        custom_message: str = "",
        td_raw: int = 0,
        db: Optional[TigerTagDB] = None,
    ) -> "TigerTag":
        """
        Create a new TigerTag from scratch, ready to write to a chip.

        The protocol version (id_tigertag) is inferred automatically:
        - product_id omitted or 0xFFFFFFFF → TigerTag (Maker / offline)
        - product_id is a real cloud ID    → TigerTag+

        Args:
            product_id      : Cloud product ID for TigerTag+, or MAKER_PRODUCT_ID
                              (default) for an offline Maker tag.
            uid             : 7-byte chip UID, if known.
            id_material     : Material ID from id_material.json.
            id_aspect_1     : Primary aspect ID from id_aspect.json.
            id_aspect_2     : Secondary aspect ID from id_aspect.json.
            id_type         : Type ID from id_type.json.
            id_diameter     : Diameter ID from id_diameter.json.
            id_brand        : Brand ID from id_brand.json.
            color1_r/g/b/a  : Primary colour (RGBA, 0-255).
            color2_r/g/b    : Secondary colour.
            color3_r/g/b    : Tertiary colour.
            measure         : Initial quantity at manufacturing.
            id_unit         : Unit ID from id_measure_unit.json.
            nozzle_temp_min : Minimum nozzle temperature (°C).
            nozzle_temp_max : Maximum nozzle temperature (°C).
            dry_temp        : Drying temperature (°C).
            dry_time        : Drying time (hours).
            bed_temp_min    : Minimum bed temperature (°C).
            bed_temp_max    : Maximum bed temperature (°C).
            timestamp       : Seconds since 2000-01-01 UTC. Defaults to now.
            custom_message  : Free-text traceability field (max 28 bytes UTF-8).
            td_raw          : HueForge TD × 10 (0 = undefined).
            db              : Optional pre-loaded TigerTagDB.

        Returns:
            A new TigerTag instance ready for to_bytes().

        Example:
            tag = TigerTag.create(
                id_material=38219,       # PLA
                id_brand=19961,          # Rosa3D
                nozzle_temp_min=195, nozzle_temp_max=230,
                color1_r=255, color1_g=0, color1_b=0, color1_a=255,
                measure=1000, id_unit=21,
            )
            chip.write_pages(4, tag.to_bytes())
        """
        if product_id != MAKER_PRODUCT_ID and product_id != INIT_PRODUCT_ID:
            id_tigertag = ID_TIGERTAG_PLUS
        else:
            id_tigertag = ID_TIGERTAG
            product_id  = MAKER_PRODUCT_ID

        if timestamp is None:
            timestamp = max(0, int(
                datetime.now(tz=timezone.utc).timestamp()
                - _TIGERTAG_EPOCH.timestamp()
            ))

        tag = cls(
            id_tigertag       = id_tigertag,
            id_product        = product_id,
            id_material       = id_material,
            id_aspect_1       = id_aspect_1,
            id_aspect_2       = id_aspect_2,
            id_type           = id_type,
            id_diameter       = id_diameter,
            id_brand          = id_brand,
            color1_r          = color1_r,
            color1_g          = color1_g,
            color1_b          = color1_b,
            color1_a          = color1_a,
            color2_r          = color2_r,
            color2_g          = color2_g,
            color2_b          = color2_b,
            color3_r          = color3_r,
            color3_g          = color3_g,
            color3_b          = color3_b,
            measure           = measure,
            id_unit           = id_unit,
            measure_available = measure,
            nozzle_temp_min   = nozzle_temp_min,
            nozzle_temp_max   = nozzle_temp_max,
            dry_temp          = dry_temp,
            dry_time          = dry_time,
            bed_temp_min      = bed_temp_min,
            bed_temp_max      = bed_temp_max,
            timestamp         = timestamp,
            custom_message    = custom_message,
            td_raw            = td_raw,
            uid               = uid,
            _db               = db,
        )
        return tag

    @classmethod
    def as_init(cls, uid: Optional[bytes] = None) -> "TigerTag":
        """
        Create a TigerTag Init payload.

        Init marks the chip as reserved for TigerTag without programming any
        material data yet. Write to_bytes() to the chip; any reader will
        recognise it as a blank TigerTag placeholder.

        This step is optional: create() can go directly from a blank chip to a
        fully programmed TigerTag or TigerTag+.

        Args:
            uid : 7-byte chip UID, if known.

        Returns:
            A TigerTag with id_tigertag = ID_TIGERTAG_INIT, id_product = 0,
            and all material fields zeroed.

        Example:
            init_tag = TigerTag.as_init(uid=chip.uid)
            chip.write_pages(4, init_tag.to_bytes())
        """
        ts = max(0, int(
            datetime.now(tz=timezone.utc).timestamp()
            - _TIGERTAG_EPOCH.timestamp()
        ))
        return cls(
            id_tigertag       = ID_TIGERTAG_INIT,
            id_product        = INIT_PRODUCT_ID,
            id_material       = 0,
            id_aspect_1       = 0, id_aspect_2 = 0,
            id_type           = 0, id_diameter = 0, id_brand = 0,
            color1_r          = 0, color1_g = 0, color1_b = 0, color1_a = 255,
            color2_r          = 0, color2_g = 0, color2_b = 0,
            color3_r          = 0, color3_g = 0, color3_b = 0,
            measure           = 0, id_unit = 0, measure_available = 0,
            nozzle_temp_min   = 0, nozzle_temp_max = 0,
            dry_temp          = 0, dry_time = 0,
            bed_temp_min      = 0, bed_temp_max = 0,
            timestamp         = ts,
            custom_message    = "",
            td_raw            = 0,
            uid               = uid,
        )

    @classmethod
    def erase(cls) -> bytes:
        """
        Return the 80-byte payload that wipes a TigerTag chip back to blank.

        Writing these bytes to pages 0x04-0x17 destroys all TigerTag data.
        The chip becomes a plain chip with no TigerTag structure — it can be
        reprogrammed as a new TigerTag at any time with create().

        Returns:
            bytes(80) — 80 zero bytes, pages 0x04-0x17.

        Example:
            chip.write_pages(4, TigerTag.erase())
        """
        return bytes(MIN_DATA_LEN)

    # ── Serializer ────────────────────────────────────────────────────────────

    def to_bytes(self, include_signature: bool = False) -> bytes:
        """
        Serialize back to binary (pages 0x04 onward).
        Returns 80 bytes (user data) or 144 bytes (with signature).
        """
        def p16(v): return struct.pack(">H", v & 0xFFFF)
        def p24(v): v &= 0xFFFFFF; return bytes([(v>>16)&0xFF,(v>>8)&0xFF,v&0xFF])
        def p32(v): return struct.pack(">I", v & 0xFFFFFFFF)

        msg = self.custom_message.encode("utf-8")[:28]
        msg += bytes(28 - len(msg))

        data = (
            p32(self.id_tigertag)
            + p32(self.id_product)
            + p16(self.id_material)
            + bytes([self.id_aspect_1, self.id_aspect_2])
            + bytes([self.id_type, self.id_diameter])
            + p16(self.id_brand)
            + bytes([self.color1_r, self.color1_g, self.color1_b, self.color1_a])
            + p24(self.measure)
            + bytes([self.id_unit])
            + p16(self.nozzle_temp_min)
            + p16(self.nozzle_temp_max)
            + bytes([self.dry_temp, self.dry_time, self.bed_temp_min, self.bed_temp_max])
            + p32(self.timestamp)
            + bytes([self.color2_r, self.color2_g, self.color2_b])
            + b"\x00"
            + bytes([self.color3_r, self.color3_g, self.color3_b])
            + b"\x00"
            + p16(self.td_raw)
            + b"\x00\x00"
            + msg
            + p24(self.measure_available)
            + b"\x00"
        )

        assert len(data) == MIN_DATA_LEN

        if include_signature:
            data += (self.signature_r + bytes(32))[:32]
            data += (self.signature_s + bytes(32))[:32]

        return data

    # ── Validation ────────────────────────────────────────────────────────────

    def validate(self) -> List[str]:
        """
        Basic field-level sanity checks.
        Returns list of warning strings. Empty = no issues.

        Example:
            warnings = tag.validate()
            for w in warnings:
                print(f"⚠  {w}")
        """
        warnings = []
        if self.nozzle_temp_min > self.nozzle_temp_max > 0:
            warnings.append(f"Nozzle temp min ({self.nozzle_temp_min}°C) > max ({self.nozzle_temp_max}°C)")
        if self.bed_temp_min > self.bed_temp_max > 0:
            warnings.append(f"Bed temp min ({self.bed_temp_min}°C) > max ({self.bed_temp_max}°C)")
        if self.td_raw != 0 and not (10 <= self.td_raw <= 1000):
            warnings.append(f"TD HueForge out of range: {self.td_raw} (valid: 10–1000 or 0=undefined)")
        if self.measure > 0 and self.measure_available > self.measure:
            warnings.append(f"measure_available ({self.measure_available}) > initial measure ({self.measure})")
        if len(self.custom_message.encode("utf-8")) > 28:
            warnings.append("custom_message exceeds 28 bytes")
        return warnings

    # ── Signature verification ────────────────────────────────────────────────

    def verify(self, db: TigerTagDB = None) -> SignatureResult:
        """
        Verify the ECDSA-P256 signature — fully autonomous.

        The signed message is: SHA-256( uid_bytes + block4 + block5 )
          uid_bytes = 7 raw bytes from chip pages 0-1
          block4    = id_tigertag as 4-byte big-endian (page 0x04)
          block5    = id_product  as 4-byte big-endian (page 0x05)

        Returns:
            SignatureResult with .ok (bool) and .status (str)

        Requires:
            - 180-byte chip dump or from_pages() with uid (for UID)
            - pip install cryptography
            - id_version.json with "public_key" field

        Example:
            result = tag.verify()
            print(result)        # ✅ VALID  /  ❌ INVALID  /  ⬜ NOT SIGNED
            print(result.ok)     # True / False
        """
        if not self.is_signed:
            return SignatureResult(SignatureResult.UNSIGNED)

        if not _CRYPTO_AVAILABLE:
            return SignatureResult(SignatureResult.NO_CRYPTO)

        if not self.uid:
            return SignatureResult(
                SignatureResult.NO_UID,
                "Provide a full 180-byte chip dump or use from_pages(uid, payload).",
            )

        _db = db or self.db
        version_entry = _db.version(self.id_tigertag) or {}
        pem = version_entry.get("public_key", "").strip()
        if not pem:
            return SignatureResult(
                SignatureResult.NO_KEY,
                f"No public_key in id_version.json for 0x{self.id_tigertag:08X}.",
            )

        try:
            block4  = self.id_tigertag.to_bytes(4, "big")
            block5  = self.id_product.to_bytes(4, "big")
            message = self.uid + block4 + block5

            r   = int.from_bytes(self.signature_r, "big")
            s   = int.from_bytes(self.signature_s, "big")
            der = _encode_dss_signature(r, s)

            pub = _load_pem_public_key(pem.encode())
            pub.verify(der, message, _ec.ECDSA(_hashes.SHA256()))

            return SignatureResult(SignatureResult.VALID)

        except _InvalidSignature:
            return SignatureResult(
                SignatureResult.INVALID,
                "Signature does not match — tag may be cloned or tampered.",
            )
        except Exception as exc:
            return SignatureResult(SignatureResult.INVALID, f"Verification error: {exc}")

    # ── Output ────────────────────────────────────────────────────────────────

    def to_raw_dict(self) -> Dict[str, Any]:
        """
        Return protocol fields exactly as stored on the chip — no label resolution,
        no unit conversion, no date formatting. Raw integers only.

        This is the canonical "source of truth" view.
        """
        return {
            "id_tigertag":       self.id_tigertag,
            "id_product":        self.id_product,
            "id_material":       self.id_material,
            "id_aspect1":        self.id_aspect_1,
            "id_aspect2":        self.id_aspect_2,
            "id_type":           self.id_type,
            "id_diameter":       self.id_diameter,
            "id_brand":          self.id_brand,
            "color_r":           self.color1_r,
            "color_g":           self.color1_g,
            "color_b":           self.color1_b,
            "color_a":           self.color1_a,
            "measure":           self.measure,
            "id_unit":           self.id_unit,
            "nozzle_min":        self.nozzle_temp_min,
            "nozzle_max":        self.nozzle_temp_max,
            "dry_temp":          self.dry_temp,
            "dry_time":          self.dry_time,
            "bed_min":           self.bed_temp_min,
            "bed_max":           self.bed_temp_max,
            "timestamp":         self.timestamp,
            "color_r2":          self.color2_r,
            "color_g2":          self.color2_g,
            "color_b2":          self.color2_b,
            "color_r3":          self.color3_r,
            "color_g3":          self.color3_g,
            "color_b3":          self.color3_b,
            "td_raw":            self.td_raw,
            "message":           self.custom_message,
            "measure_available": self.measure_available,
            "uid":               self.uid_hex,
            "product_page_url":  self.product_page_url,
            "api_url":           self.api_url,
        }

    def to_dict(self, db: TigerTagDB = None) -> Dict:
        """
        Return a fully-resolved dict (all IDs replaced by their labels + metadata).
        Suitable for JSON serialization, API responses, or further processing.

        Example:
            import json
            print(json.dumps(tag.to_dict(), indent=2))
        """
        _db   = db or self.db
        mat   = _db.material(self.id_material) or {}
        rec   = mat.get("recommended", {})
        stock = self.stock_percent

        return {
            "sdk":        "tigertag-sdk-python",
            "sdk_mode":   "offline",
            "protocol":   "TigerTag Open Source v2.1",
            "uid":        self.uid_hex,
            "version": {
                "id":    self.id_tigertag,
                "hex":   f"0x{self.id_tigertag:08X}",
                "label": TigerTagDB.label(_db.version(self.id_tigertag)),
            },
            "product": {
                "id":   self.id_product,
                "mode": "maker" if self.is_maker else "init" if self.is_init else "cloud",
            },
            "material": {
                "id":      self.id_material,
                "label":   TigerTagDB.label(_db.material(self.id_material)),
                "density": mat.get("density"),
                "filled":  mat.get("filled"),
                "recommended": {
                    "nozzle": {"min": rec.get("nozzleTempMin"), "max": rec.get("nozzleTempMax")},
                    "bed":    {"min": rec.get("bedTempMin"),    "max": rec.get("bedTempMax")},
                    "dry":    {"temp": rec.get("dryTemp"),      "time_h": rec.get("dryTime")},
                } if rec else None,
                "metadata": mat.get("metadata"),
            },
            "aspect_1": {"id": self.id_aspect_1, "label": TigerTagDB.label(_db.aspect(self.id_aspect_1))},
            "aspect_2": {"id": self.id_aspect_2, "label": TigerTagDB.label(_db.aspect(self.id_aspect_2))},
            "type":     {"id": self.id_type,     "label": TigerTagDB.label(_db.type_(self.id_type))},
            "diameter": {"id": self.id_diameter, "label": TigerTagDB.label(_db.diameter(self.id_diameter))},
            "brand":    {"id": self.id_brand,    "label": TigerTagDB.label(_db.brand(self.id_brand))},
            "colors": {
                "primary":   {"hex": self.color1_hex, "rgba": [self.color1_r, self.color1_g, self.color1_b, self.color1_a]},
                "secondary": {"hex": self.color2_hex, "rgb":  [self.color2_r, self.color2_g, self.color2_b]},
                "tertiary":  {"hex": self.color3_hex, "rgb":  [self.color3_r, self.color3_g, self.color3_b]},
            },
            "hueforge_td": self.td_value if self.td_raw != 0 else None,
            "unit": {"id": self.id_unit, "label": TigerTagDB.label(_db.unit(self.id_unit))},
            "measure": {
                "initial":   self.measure,
                "available": self.measure_available,
                "percent":   stock,
            },
            "temperatures": {
                "nozzle": {"min": self.nozzle_temp_min, "max": self.nozzle_temp_max},
                "bed":    {"min": self.bed_temp_min,    "max": self.bed_temp_max},
                "dry":    {"temp": self.dry_temp,       "time_h": self.dry_time},
            },
            "timestamp":           self.timestamp,
            "manufacturing_date":  self.manufacturing_date.isoformat(),
            "twin_tag_pairing_id": self.timestamp,
            "custom_message":      self.custom_message,
            "signed":              self.is_signed,
        }

    def describe(self, db: TigerTagDB = None) -> str:
        """
        Return a concise natural-language description of the tag.

        Designed for injection into LLM prompts. Contains all material data
        in plain English, without protocol jargon.

        Args:
            db : Optional pre-loaded TigerTagDB. Uses self.db by default.

        Returns:
            A single paragraph (no newlines) describing the tag content.

        Example:
            prompt = f"Given this material: {tag.describe()}\\nWhat nozzle temp should I use?"
        """
        _db  = db or self.db
        mat  = _db.material(self.id_material) or {}
        rec  = mat.get("recommended", {})

        material = TigerTagDB.label(_db.material(self.id_material))
        type_    = TigerTagDB.label(_db.type_(self.id_type))
        diameter = TigerTagDB.label(_db.diameter(self.id_diameter))
        brand    = TigerTagDB.label(_db.brand(self.id_brand))
        unit     = TigerTagDB.label(_db.unit(self.id_unit))
        density  = mat.get("density")
        stock    = self.stock_percent

        # Check aspect_2 first for multi-color mode (Bicolor/Tricolor/Rainbow),
        # then fall back to aspect_1. color_count drives how many colors are active.
        asp2_entry  = _db.aspect(self.id_aspect_2)
        asp1_entry  = _db.aspect(self.id_aspect_1)
        color_count = 1
        if asp2_entry and asp2_entry.get("color_count", 1) > 1:
            color_count = asp2_entry["color_count"]
        elif asp1_entry and asp1_entry.get("color_count", 1) > 1:
            color_count = asp1_entry["color_count"]

        aspect1_label = TigerTagDB.label(asp1_entry)
        aspect2_label = TigerTagDB.label(asp2_entry)

        parts: List[str] = []

        # Identity
        parts.append(
            f"TigerTag RFID chip read successfully."
            f" Material: {material} {type_}"
            + (f" ({diameter}mm diameter)" if diameter not in ("Unknown", "-") else "")
            + (f", density {density} g/cm³" if density else "")
            + (f", by {brand}" if brand not in ("Unknown", "-") else "")
            + "."
        )

        # Aspect / finish
        finish_parts = [l for l in (aspect1_label, aspect2_label) if l not in ("Unknown", "-", "None")]
        if finish_parts:
            parts.append(f"Finish: {' + '.join(finish_parts)}.")

        # Color — respect color_count from aspect DB
        color_parts = [f"primary {self.color1_hex}"]
        if color_count >= 2:
            color_parts.append(f"secondary {self.color2_hex}")
        if color_count >= 3:
            color_parts.append(f"tertiary {self.color3_hex}")
        parts.append("Color: " + ", ".join(color_parts) + ".")

        # Temperatures from chip
        parts.append(
            f"Print settings (on chip): nozzle {self.nozzle_temp_min}–{self.nozzle_temp_max}°C,"
            f" bed {self.bed_temp_min}–{self.bed_temp_max}°C,"
            f" drying {self.dry_temp}°C for {self.dry_time}h."
        )

        # DB-recommended temps (if available)
        if rec.get("nozzleTempMin") is not None:
            parts.append(
                f"Database recommended settings: nozzle {rec['nozzleTempMin']}–{rec['nozzleTempMax']}°C,"
                f" bed {rec.get('bedTempMin', '?')}–{rec.get('bedTempMax', '?')}°C,"
                f" drying {rec.get('dryTemp', '?')}°C for {rec.get('dryTime', '?')}h."
            )

        # Quantity
        if self.measure > 0:
            parts.append(
                f"Quantity: {self.measure_available} {unit} remaining"
                f" out of {self.measure} {unit} initial"
                + (f" ({stock}%)." if stock is not None else ".")
            )

        # HueForge
        if self.td_raw != 0:
            parts.append(f"HueForge TD: {self.td_value:.1f}.")

        # Traceability
        parts.append(f"Manufactured: {self.manufacturing_date.strftime('%Y-%m-%d')}.")
        if self.custom_message:
            parts.append(f"Custom message on chip: \"{self.custom_message}\".")
        if self.uid_hex:
            parts.append(f"Chip UID: {self.uid_hex}.")

        # TigerTag+ links
        if self.product_page_url:
            parts.append(
                f"Product page: {self.product_page_url} — "
                f"API JSON: {self.api_url}"
            )

        # Authentication
        if self.is_signed:
            parts.append(
                "Tag carries an ECDSA-P256 signature — call tag.verify() to confirm authenticity."
            )
        else:
            parts.append("Tag is not ECDSA-signed.")

        return " ".join(parts)

    def pretty(self, db: TigerTagDB = None, sig_result: SignatureResult = None) -> str:
        """
        Human-readable summary of the tag.

        Args:
            db         : Optional TigerTagDB (uses self.db by default)
            sig_result : Optional pre-computed SignatureResult

        Example:
            print(tag.pretty())
        """
        _db   = db or self.db
        mat   = _db.material(self.id_material) or {}
        rec   = mat.get("recommended", {})
        stock = self.stock_percent
        ul    = TigerTagDB.label(_db.unit(self.id_unit))
        sig   = str(sig_result) if sig_result else ("signed ✓" if self.is_signed else "not signed")

        def rec_note(kmin, kmax, suffix="°C"):
            return f"  (DB: {rec[kmin]}–{rec[kmax]}{suffix})" if rec.get(kmin) is not None else ""

        return (
            f"┌─ TigerTag ────────────────────────────────────────────\n"
            f"│  Version      {TigerTagDB.label(_db.version(self.id_tigertag))} (0x{self.id_tigertag:08X})\n"
            f"│  Product      {'Maker (offline)' if self.is_maker else ('Init' if self.is_init else f'TigerTag+ #{self.id_product}')}\n"
            f"│  UID          {self.uid_hex or '— (partial dump)'}\n"
            f"├─ Material ────────────────────────────────────────────\n"
            f"│  Material     {TigerTagDB.label(_db.material(self.id_material))}  (id={self.id_material})\n"
            f"│  Density      {mat.get('density', '—')} g/cm³\n"
            f"│  Type         {TigerTagDB.label(_db.type_(self.id_type))}\n"
            f"│  Diameter     {TigerTagDB.label(_db.diameter(self.id_diameter))}\n"
            f"│  Brand        {TigerTagDB.label(_db.brand(self.id_brand))}\n"
            f"│  Aspect 1     {TigerTagDB.label(_db.aspect(self.id_aspect_1))}\n"
            f"│  Aspect 2     {TigerTagDB.label(_db.aspect(self.id_aspect_2))}\n"
            f"├─ Colors ──────────────────────────────────────────────\n"
            f"│  Color 1      {self.color1_hex}  α={self.color1_a}\n"
            f"│  Color 2      {self.color2_hex}\n"
            f"│  Color 3      {self.color3_hex}\n"
            f"│  HueForge TD  {self.td_value:.1f}" + (" (undefined)\n" if self.td_raw == 0 else "\n") +
            f"├─ Temperatures ────────────────────────────────────────\n"
            f"│  Nozzle       {self.nozzle_temp_min}°C → {self.nozzle_temp_max}°C{rec_note('nozzleTempMin','nozzleTempMax')}\n"
            f"│  Bed          {self.bed_temp_min}°C → {self.bed_temp_max}°C{rec_note('bedTempMin','bedTempMax')}\n"
            f"│  Drying       {self.dry_temp}°C / {self.dry_time}h{rec_note('dryTemp','dryTime',' h')}\n"
            f"├─ Quantity ────────────────────────────────────────────\n"
            f"│  Unit         {ul}\n"
            f"│  Initial      {self.measure} {ul}\n"
            f"│  Available    {self.measure_available} {ul}" + (f"  ({stock}% remaining)\n" if stock is not None else "\n") +
            f"├─ Traceability ────────────────────────────────────────\n"
            f"│  Manufactured {self.manufacturing_date.strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"│  Twin tag ID  {self.timestamp}\n"
            f"│  Message      {self.custom_message!r}\n"
            f"├─ Signature ───────────────────────────────────────────\n"
            f"│  ECDSA        {sig}\n"
            f"└───────────────────────────────────────────────────────"
        )


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="TigerTag standalone SDK — parse, verify, export, sync",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python parse_tigertag.py dump.bin              # parse + pretty print\n"
            "  python parse_tigertag.py dump.bin --json       # output as JSON\n"
            "  python parse_tigertag.py dump.bin --raw        # raw IDs, no DB lookup\n"
            "  python parse_tigertag.py --sync-only           # update databases only\n"
            "\n"
            "dump formats:\n"
            "  180 bytes  full chip dump (pages 0-44): UID extracted, signature verifiable\n"
            "  144 bytes  user data + signature (pages 0x04-0x27)\n"
            "   80 bytes  user data only (pages 0x04-0x17)\n"
            "\n"
            "spec: https://github.com/TigerTag-Project/TigerTag-RFID-Guide"
        ),
    )
    ap.add_argument("dump",        nargs="?",      help="Binary .bin file to parse")
    ap.add_argument("--db",        metavar="PATH", default=None,
                    help="Database folder (default: ./database next to this script)")
    ap.add_argument("--json",      action="store_true", help="Output as JSON")
    ap.add_argument("--raw",       action="store_true", help="Print raw dataclass, no DB lookup")
    ap.add_argument("--no-sync",   action="store_true", help="Do not auto-download databases")
    ap.add_argument("--sync-only", action="store_true", help="Update databases and exit")
    ap.add_argument("--version",   action="version",    version="parse_tigertag.py v1.1")
    args = ap.parse_args()

    db_path = Path(args.db) if args.db else Path(__file__).parent / "database"

    # Sync-only mode
    if args.sync_only:
        if not _REQUESTS_AVAILABLE:
            print("❌  'requests' is not installed. Run:  pip install requests", file=sys.stderr)
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
    with open(args.dump, "rb") as f:
        raw_data = f.read()

    tag = TigerTag.from_dump(raw_data)

    # Warnings
    warnings = tag.validate()
    if warnings:
        for w in warnings:
            print(f"⚠  {w}")
        print()

    # Raw mode (no DB)
    if args.raw:
        import pprint
        pprint.pprint(tag.to_raw_dict())
        sys.exit(0)

    # Load DB (auto-sync unless --no-sync)
    db = TigerTagDB(db_path, auto_sync=not args.no_sync)

    # Signature verification (fully autonomous)
    sig_result = tag.verify(db) if tag.is_signed else SignatureResult(SignatureResult.UNSIGNED)

    # Output
    if args.json:
        d = tag.to_dict(db)
        d["signature"] = sig_result.to_dict()
        print(json.dumps(d, indent=2, default=str))
    else:
        print(tag.pretty(db, sig_result))
