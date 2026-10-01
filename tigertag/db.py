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
TigerTag reference data: loading, offline use, automatic and manual updates.

Where each table (``id_*.json``) comes from, in order:

1. **Your own folder** — ``TigerTagDB(db_path=...)``. Used exclusively: no fallback to
   the bundled copy and no network access, unless you call :meth:`TigerTagDB.update`,
   which then updates that folder.
2. **Downloaded copy** in the data directory — :func:`default_data_dir` (the user cache
   directory, ``TIGERTAG_DATA_DIR`` or ``data_dir=``), filled by updates.
3. **Bundled copy** inside the package — always present, refreshed at every release.

Between 2 and 3 the newest wins, per table, by the timestamps of ``last_update.json``.

Automatic update: the first :class:`TigerTagDB` of a process checks for new data at most
once per ``max_age`` (default one day). That is one small request (``last_update``,
TigerTag API with the GitHub mirror as fallback, 5 s timeout); only the tables whose
timestamp changed are downloaded. It never raises: on failure the local data is used.

Offline: ``offline=True`` or ``TIGERTAG_OFFLINE=1`` means zero network access anywhere.
``auto_update=False`` only disables the automatic check.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

try:  # kept for compatibility: updates no longer need requests (stdlib urllib)
    import requests as _requests  # noqa: F401
    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False


# ── Constants ──────────────────────────────────────────────────────────────────

_API_BASE        = "https://api.tigertag.io/api:tigertag"
_GITHUB_RAW_BASE = "https://raw.githubusercontent.com/TigerTag-Project/TigerTag-RFID-Guide/main/database"
_HTTP_TIMEOUT    = 30            # explicit update()
CHECK_TIMEOUT    = 5             # automatic check: short, never blocks long
DEFAULT_MAX_AGE  = 24 * 3600     # automatic check at most once a day

# Maps last_update key → (API endpoint, local filename)
_DATASETS: Dict[str, Tuple[str, str]] = {
    "versions":           ("version/get/all",           "id_version.json"),
    "types":              ("type/get/all",              "id_type.json"),
    "brands":             ("brand/get/all",             "id_brand.json"),
    "filament_diameters": ("diameter/filament/get/all", "id_diameter.json"),
    "filament_materials": ("material/get/all",          "id_material.json"),
    "aspects":            ("aspect/get/all",            "id_aspect.json"),
    "measure_units":      ("measure_unit/get/all",      "id_measure_unit.json"),
}
LAST_UPDATE_FILE = "last_update.json"
STATE_FILE       = "db_state.json"        # last automatic / manual check, in the data dir

# Bundled database — always present after pip install
BUNDLED_DB_PATH  = Path(__file__).parent / "database"
_BUNDLED_DB_PATH = BUNDLED_DB_PATH        # former private name, kept for compatibility

_CHECKED_THIS_PROCESS: set = set()        # data dirs already checked by this process


# ── Environment ────────────────────────────────────────────────────────────────

def is_offline(flag: Optional[bool] = None) -> bool:
    """True when ``flag`` is set or ``TIGERTAG_OFFLINE`` is 1 / true / yes / on."""
    env = os.environ.get("TIGERTAG_OFFLINE", "").strip().lower() in ("1", "true", "yes", "on")
    return bool(flag) or env


def default_data_dir() -> Path:
    """
    Where downloaded reference data and the catalogue are kept.

    ``TIGERTAG_DATA_DIR``, else ``TIGERTAG_CACHE_DIR``, else the user cache directory:
    macOS ``~/Library/Caches/tigertag``, Windows ``%LOCALAPPDATA%\\tigertag\\Cache``,
    elsewhere ``$XDG_CACHE_HOME/tigertag`` (default ``~/.cache/tigertag``).
    """
    for var in ("TIGERTAG_DATA_DIR", "TIGERTAG_CACHE_DIR"):
        if os.environ.get(var):
            return Path(os.environ[var])
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "tigertag"
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "tigertag" / "Cache"
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "tigertag"


# ── Network (stdlib) ───────────────────────────────────────────────────────────

def _open_url(url: str, timeout: float) -> bytes:
    """GET ``url`` (certifi CA bundle when installed). The only network call of this module."""
    from tigertag.tag import _https_context  # lazy: tag.py imports this module
    req = urllib.request.Request(url, headers={"User-Agent": "tigertag-sdk-python"})
    with urllib.request.urlopen(req, timeout=timeout, context=_https_context()) as resp:
        return resp.read()


def _remote_last_update(timeout: float) -> Tuple[Dict[str, int], str]:
    """``last_update`` from the TigerTag API, else the GitHub mirror → ``(data, source)``."""
    errors = []
    for source, url in (("api", f"{_API_BASE}/all/last_update"),
                        ("github", f"{_GITHUB_RAW_BASE}/{LAST_UPDATE_FILE}")):
        try:
            data = json.loads(_open_url(url, timeout))
            if isinstance(data, dict):
                return data, source
            errors.append(f"{source}: unexpected payload")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            errors.append(f"{source}: {exc}")
    raise RuntimeError(
        "TigerTag reference data cannot be checked: both the TigerTag API and the GitHub "
        "mirror are unreachable (" + "; ".join(errors) + "). Check your internet connection."
    )


def _table_url(source: str, endpoint: str, filename: str) -> str:
    return f"{_API_BASE}/{endpoint}" if source == "api" else f"{_GITHUB_RAW_BASE}/{filename}"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _iso(epoch: Optional[float]) -> Optional[str]:
    if not epoch:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).replace(microsecond=0).isoformat()


def _download_tables(
    target: Path,
    local_ts: Dict[str, Optional[int]],
    force: bool,
    timeout: float,
    require_files: bool,
    log: Callable[[str], None] = lambda _m: None,
) -> Tuple[List[str], str]:
    """
    Download into ``target`` every table whose remote timestamp is newer than ``local_ts``
    (all of them with ``force``), then merge their timestamps into ``target/last_update.json``.
    ``require_files``: also download a table missing from ``target``.
    """
    remote, source = _remote_last_update(timeout)
    log(f"[info] source: {source}")
    target.mkdir(parents=True, exist_ok=True)
    lu_path = target / LAST_UPDATE_FILE
    merged = _read_json(lu_path)
    merged = merged if isinstance(merged, dict) else {}
    changed: List[str] = []
    for key, (endpoint, filename) in _DATASETS.items():
        remote_ts = remote.get(key)
        if remote_ts is None:
            continue
        local = local_ts.get(key)
        missing = require_files and not (target / filename).exists()
        if not force and not missing and local is not None and remote_ts <= local:
            log(f"[ok]   {filename}: up to date")
            continue
        data = json.loads(_open_url(_table_url(source, endpoint, filename), timeout))
        if not isinstance(data, list):
            raise ValueError(f"{filename}: expected a JSON list from {source}")
        (target / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        merged[key] = remote_ts
        changed.append(filename)
        log(f"[sync] {filename}: {local} → {remote_ts}")
    if changed:
        lu_path.write_text(json.dumps(merged), encoding="utf-8")
    return changed, source


# ── Compatibility: standalone sync ─────────────────────────────────────────────

def sync_databases(db_path: Path, force: bool = False, verbose: bool = True) -> List[str]:
    """
    Download or update the reference tables in ``db_path`` (kept for compatibility —
    prefer :meth:`TigerTagDB.update`).

    Tries the TigerTag API, then the GitHub mirror. Only tables whose timestamp changed
    (or that are missing) are downloaded.

    Returns:
        Filenames written, ``last_update.json`` included when anything changed.

    Raises:
        RuntimeError: Both sources are unreachable, or offline mode is on.
    """
    if is_offline():
        raise RuntimeError("Offline mode (TIGERTAG_OFFLINE) is on: no database sync.")
    db_path = Path(db_path)
    lu = _read_json(db_path / LAST_UPDATE_FILE)
    lu = lu if isinstance(lu, dict) else {}
    changed, _ = _download_tables(db_path, lu, force, _HTTP_TIMEOUT, require_files=True,
                                  log=print if verbose else (lambda _m: None))
    if changed:
        changed.append(LAST_UPDATE_FILE)
    return changed


# ── Database loader ────────────────────────────────────────────────────────────

class TigerTagDB:
    """
    The TigerTag reference tables (materials, brands, aspects…), always available offline.

    Args:
        db_path     : Your own folder with the ``id_*.json`` files, used exclusively
                      (no bundled fallback, no network unless :meth:`update` is called).
        auto_sync   : Former switch, kept for compatibility: ``False`` = ``auto_update=False``.
        verbose     : Print update progress and failures.
        data_dir    : Where downloaded data is kept (default :func:`default_data_dir`).
        offline     : No network access at all (also ``TIGERTAG_OFFLINE=1``).
        auto_update : Check for new data automatically (at most once per ``max_age``).
        max_age     : Seconds between automatic checks (default one day).

    Raises:
        FileNotFoundError: ``db_path`` lacks one of the required tables.

    Example:
        db = TigerTagDB()
        print(db.material(38219)["label"])   # "PLA"
        db.update()                          # check now
        print(db.info()["tables"]["id_material.json"]["source"])   # bundled / downloaded
    """

    REQUIRED_FILES: List[tuple] = list(_DATASETS.values())

    def __init__(
        self,
        db_path: Optional[Path] = None,
        auto_sync: Optional[bool] = None,
        verbose: bool = False,
        *,
        data_dir: Optional[Path] = None,
        offline: Optional[bool] = None,
        auto_update: bool = True,
        max_age: float = DEFAULT_MAX_AGE,
    ) -> None:
        self._custom      = Path(db_path) if db_path is not None else None
        self._data_dir    = Path(data_dir) if data_dir is not None else default_data_dir()
        self._offline     = is_offline(offline)
        self._auto_update = bool(auto_sync) if auto_sync is not None else auto_update
        self._max_age     = max_age
        self._verbose     = verbose
        self._last_error: Optional[str] = None

        if self._custom is not None:
            missing = [fn for _, fn in self.REQUIRED_FILES if not (self._custom / fn).exists()]
            if missing and auto_sync and not self._offline:
                sync_databases(self._custom, verbose=verbose)       # former auto_sync behaviour
                missing = [fn for _, fn in self.REQUIRED_FILES if not (self._custom / fn).exists()]
            if missing:
                raise FileNotFoundError(
                    f"TigerTag database folder {self._custom} is missing: {', '.join(missing)}. "
                    "A custom db_path is used exclusively (no fallback to the bundled copy). "
                    "Copy the files there, call TigerTagDB(db_path).update() / "
                    "sync_databases(db_path), or omit db_path to use the bundled and "
                    "downloaded data."
                )
        self._resolve()
        self._maybe_auto_update()
        self._reload_all()

    # ── Resolution ─────────────────────────────────────────────────────────────

    def _resolve(self) -> None:
        """Pick, per table, the file to load and remember its source and timestamp."""
        self._paths: Dict[str, Path] = {}
        self._sources: Dict[str, str] = {}
        self._ts: Dict[str, Optional[int]] = {}
        if self._custom is not None:
            lu = _read_json(self._custom / LAST_UPDATE_FILE) or {}
            for key, (_, fn) in _DATASETS.items():
                self._paths[key], self._sources[key], self._ts[key] = self._custom / fn, "custom", lu.get(key)
            return
        bundled = _read_json(BUNDLED_DB_PATH / LAST_UPDATE_FILE) or {}
        cached = _read_json(self._data_dir / LAST_UPDATE_FILE) or {}
        for key, (_, fn) in _DATASETS.items():
            b_ts, c_ts = bundled.get(key), cached.get(key)
            c_file = self._data_dir / fn
            if c_file.exists() and c_ts is not None and (b_ts is None or c_ts > b_ts):
                self._paths[key], self._sources[key], self._ts[key] = c_file, "downloaded", c_ts
            else:
                self._paths[key], self._sources[key], self._ts[key] = BUNDLED_DB_PATH / fn, "bundled", b_ts

    def _state(self) -> Dict[str, Any]:
        state = _read_json(self._data_dir / STATE_FILE)
        return state if isinstance(state, dict) else {}

    def _save_state(self, **values: Any) -> None:
        state = self._state()
        state.update(values)
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            (self._data_dir / STATE_FILE).write_text(json.dumps(state, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _log(self, msg: str) -> None:
        if self._verbose:
            print(msg, file=sys.stderr)

    def _maybe_auto_update(self) -> None:
        """First TigerTagDB of the process: check at most once per max_age. Never raises."""
        if self._custom is not None or self._offline or not self._auto_update:
            return
        key = str(self._data_dir.resolve())
        if key in _CHECKED_THIS_PROCESS:
            return
        _CHECKED_THIS_PROCESS.add(key)
        if time.time() - float(self._state().get("last_check") or 0) < self._max_age:
            return
        try:
            self._check(force=False, timeout=CHECK_TIMEOUT)
        except Exception as exc:  # the automatic check must never break the caller
            self._last_error = str(exc)
            self._save_state(last_check=time.time(), last_error=str(exc))
            self._log(f"[warn] TigerTag reference data check failed, using local data: {exc}")

    def _check(self, force: bool, timeout: float) -> List[str]:
        target = self._custom if self._custom is not None else self._data_dir
        changed, source = _download_tables(target, dict(self._ts), force, timeout,
                                           require_files=self._custom is not None, log=self._log)
        self._save_state(last_check=time.time(), last_source=source, last_changed=changed, last_error=None)
        self._resolve()
        self._reload_all()
        return changed

    # ── Public API ─────────────────────────────────────────────────────────────

    def update(self, force: bool = False, catalog: bool = False) -> List[str]:
        """
        Check for new reference data now (``force=True`` re-downloads every table).

        Updates the data directory, or your ``db_path`` folder when one is used.
        With ``catalog=True`` the TigerTag+ catalogue is refreshed too.

        Returns:
            Filenames that changed (``id_catalog.json`` included when the catalogue did).

        Raises:
            RuntimeError: Offline mode is on, or the update sources are unreachable.
        """
        if self._offline:
            raise RuntimeError(
                "Offline mode is on (offline=True or TIGERTAG_OFFLINE=1): update() makes no "
                "network call. Turn offline mode off to update the reference data."
            )
        changed = self._check(force=force, timeout=_HTTP_TIMEOUT)
        if catalog:
            from tigertag.catalog import catalog_info
            folder = self._custom if self._custom is not None else self._data_dir
            before = catalog_info(folder).get("fetched_at")
            self.catalog(refresh=True)
            after = catalog_info(folder)
            if after.get("source") == "downloaded" and after.get("fetched_at") != before:
                changed.append("id_catalog.json")
        return changed

    def sync(self, force: bool = False) -> List[str]:
        """Former name of :meth:`update`, kept for compatibility."""
        return self.update(force=force)

    def catalog(self, refresh: bool = False) -> Dict[int, Dict[str, Any]]:
        """
        The TigerTag+ catalogue with this database's settings (folder, offline, max_age).

        With a custom ``db_path`` it is read from that folder only (``id_catalog.json`` or
        ``id_catalog.json.gz``); otherwise see :func:`tigertag.catalog.load_catalog`.
        """
        from tigertag.catalog import load_catalog, read_catalog_file, refresh_catalog
        if self._custom is not None:
            if refresh:
                if self._offline:
                    raise RuntimeError("Offline mode is on: the catalogue cannot be refreshed.")
                return refresh_catalog(cache_dir=self._custom)
            for name in ("id_catalog.json", "id_catalog.json.gz"):
                if (self._custom / name).exists():
                    return read_catalog_file(self._custom / name)
            raise FileNotFoundError(
                f"No id_catalog.json or id_catalog.json.gz in {self._custom}: the TigerTag+ "
                "catalogue is needed for from_catalog(). Copy it there or call "
                "update(catalog=True)."
            )
        return load_catalog(cache_dir=self._data_dir, offline=self._offline,
                            max_age=self._max_age, force=refresh)

    def info(self) -> Dict[str, Any]:
        """Where every table comes from, its timestamp, the last check, and the catalogue."""
        from tigertag.catalog import catalog_info
        state = self._state()
        tables = {}
        for key, (_, fn) in _DATASETS.items():
            ts = self._ts.get(key)
            tables[fn] = {
                "source":     self._sources[key],
                "path":       str(self._paths[key]),
                "timestamp":  ts,
                "updated_at": _iso(ts / 1000) if ts else None,
            }
        folder = self._custom if self._custom is not None else self._data_dir
        return {
            "custom":       self._custom is not None,
            "db_path":      str(self._custom) if self._custom is not None else None,
            "data_dir":     str(self._data_dir),
            "offline":      self._offline,
            "auto_update":  self._auto_update,
            "max_age":      self._max_age,
            "last_check":   _iso(state.get("last_check")),
            "last_source":  state.get("last_source"),
            "last_changed": state.get("last_changed"),
            "last_error":   state.get("last_error"),
            "tables":       tables,
            "catalog":      catalog_info(folder),
        }

    # ── Loading ────────────────────────────────────────────────────────────────

    def _load(self, filename: str) -> List[Dict]:
        key = next(k for k, (_, fn) in _DATASETS.items() if fn == filename)
        data = _read_json(self._paths[key])
        if data is None and self._sources[key] == "downloaded":     # damaged cache → bundled
            data = _read_json(BUNDLED_DB_PATH / filename)
        return data if isinstance(data, list) else []

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
