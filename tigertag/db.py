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

"""TigerTag reference database loader and sync utilities."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False


# ── Network constants ──────────────────────────────────────────────────────────

_API_BASE        = "https://api.tigertag.io/api:tigertag"
_GITHUB_RAW_BASE = "https://raw.githubusercontent.com/TigerTag-Project/TigerTag-RFID-Guide/main/database"
_HTTP_TIMEOUT    = 30

# Maps last_update key → (API endpoint, local filename)
_DATASETS: Dict[str, tuple] = {
    "versions":           ("version/get/all",           "id_version.json"),
    "types":              ("type/get/all",              "id_type.json"),
    "brands":             ("brand/get/all",             "id_brand.json"),
    "filament_diameters": ("diameter/filament/get/all", "id_diameter.json"),
    "filament_materials": ("material/get/all",          "id_material.json"),
    "aspects":            ("aspect/get/all",            "id_aspect.json"),
    "measure_units":      ("measure_unit/get/all",      "id_measure_unit.json"),
}

# Bundled database path — always present after pip install
_BUNDLED_DB_PATH = Path(__file__).parent / "database"


# ── Sync ───────────────────────────────────────────────────────────────────────

def sync_databases(
    db_path: Path,
    force: bool = False,
    verbose: bool = True,
) -> List[str]:
    """
    Download or update TigerTag reference JSON databases.

    Tries the live TigerTag API first; falls back to the GitHub mirror if
    the API is unreachable. Only downloads files whose timestamp has changed.

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
            "Install it with:  pip install tigertag[sync]"
        )

    db_path = Path(db_path)
    db_path.mkdir(parents=True, exist_ok=True)
    last_update_path = db_path / "last_update.json"

    def _get(url: str):
        r = _requests.get(url, timeout=_HTTP_TIMEOUT)
        r.raise_for_status()
        return r.json(), r.text

    def _log(msg: str) -> None:
        if verbose:
            print(msg)

    # Pick source: API first, GitHub fallback
    dataset_url_fn = None
    try:
        remote_data, remote_text = _get(f"{_API_BASE}/all/last_update")
        source = "api"

        def dataset_url_fn(endpoint: str, filename: str) -> str:
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

        def dataset_url_fn(endpoint: str, filename: str) -> str:
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
        r = _requests.get(dataset_url_fn(endpoint, filename), timeout=_HTTP_TIMEOUT)
        r.raise_for_status()
        local_file.write_text(
            json.dumps(r.json(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        updated.append(filename)

    if updated or local_data != remote_data:
        last_update_path.write_text(remote_text, encoding="utf-8")
        if "last_update.json" not in updated:
            updated.append("last_update.json")

    return updated


# ── Database loader ────────────────────────────────────────────────────────────

class TigerTagDB:
    """
    Loads and exposes TigerTag JSON reference databases.

    Ships with bundled JSON files so the SDK works offline immediately
    after ``pip install tigertag``. Optionally syncs updates from the
    TigerTag API or GitHub mirror.

    All ID lookups return the full JSON entry dict (or None if not found).
    The JSON files are the single source of truth — no hardcoded ID mappings.

    Args:
        db_path   : Folder containing the JSON files.
                    Defaults to the bundled database inside the package.
        auto_sync : Download missing/stale files automatically
                    (requires ``pip install tigertag[sync]``).
        verbose   : Print sync progress.

    Example:
        db = TigerTagDB()
        mat = db.material(38219)
        print(mat["label"])    # "PLA"
        print(mat["density"])  # 1.24
    """

    REQUIRED_FILES: List[tuple] = list(_DATASETS.values())

    def __init__(
        self,
        db_path: Optional[Path] = None,
        auto_sync: bool = False,
        verbose: bool = True,
    ) -> None:
        self._path      = Path(db_path) if db_path else _BUNDLED_DB_PATH
        self._auto_sync = auto_sync
        self._verbose   = verbose
        self._ensure_db()
        self._versions  = self._load("id_version.json")
        self._materials = self._load("id_material.json")
        self._aspects   = self._load("id_aspect.json")
        self._types     = self._load("id_type.json")
        self._diameters = self._load("id_diameter.json")
        self._brands    = self._load("id_brand.json")
        self._units     = self._load("id_measure_unit.json")

    def _ensure_db(self) -> None:
        """Check for missing files; auto-sync or emit clear error."""
        missing = [fn for _, fn in self.REQUIRED_FILES if not (self._path / fn).exists()]
        if not missing:
            return

        if self._auto_sync and _REQUESTS_AVAILABLE:
            if self._verbose:
                print(f"[info] Missing {len(missing)} database file(s) — downloading now...")
            try:
                sync_databases(self._path, verbose=self._verbose)
                return
            except Exception as exc:
                print(f"[warn] Auto-sync failed: {exc}", file=sys.stderr)

        missing_still = [fn for _, fn in self.REQUIRED_FILES if not (self._path / fn).exists()]
        if not missing_still:
            return

        # Fallback to bundled database if user provided a custom path
        if self._path != _BUNDLED_DB_PATH and _BUNDLED_DB_PATH.exists():
            self._path = _BUNDLED_DB_PATH
            return

        lines = ["", "TigerTag database files not found.", f"  Expected: {self._path.resolve()}", "", "  Missing:"]
        for fn in missing_still:
            lines.append(f"    - {fn}")
        lines.append("")
        if not _REQUESTS_AVAILABLE:
            lines.append("  'requests' is not installed — cannot auto-download.")
            lines.append("  Install it:  pip install tigertag[sync]")
        else:
            lines.append("  To download:  tigertag --sync-only")
        lines.append("")
        print("\n".join(lines), file=sys.stderr)
        sys.exit(1)

    def _load(self, filename: str) -> List[Dict]:
        fp = self._path / filename
        if not fp.exists():
            return []
        with open(fp, encoding="utf-8") as f:
            return json.load(f)

    def _reload_all(self) -> None:
        self._versions  = self._load("id_version.json")
        self._materials = self._load("id_material.json")
        self._aspects   = self._load("id_aspect.json")
        self._types     = self._load("id_type.json")
        self._diameters = self._load("id_diameter.json")
        self._brands    = self._load("id_brand.json")
        self._units     = self._load("id_measure_unit.json")

    @staticmethod
    def _find(table: List[Dict], id_value: int) -> Optional[Dict]:
        return next((e for e in table if e.get("id") == id_value), None)

    def sync(self, force: bool = False) -> List[str]:
        """
        Manually trigger a database update.

        Args:
            force : Re-download all files even if up to date.

        Returns:
            List of filenames that were downloaded/updated.

        Raises:
            ImportError : if 'requests' is not installed.
        """
        updated = sync_databases(self._path, force=force, verbose=self._verbose)
        self._reload_all()
        return updated

    # ── Lookups (return full JSON entry or None) ───────────────────────────────

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
        """Safe label string from any DB entry dict."""
        if entry is None:
            return "Unknown"
        return entry.get("label") or entry.get("name") or "Unknown"
