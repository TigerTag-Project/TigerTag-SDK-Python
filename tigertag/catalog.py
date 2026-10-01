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
Official TigerTag+ product catalogue — load it and turn a product ID into chip fields.

The catalogue (``id_catalog.json`` in TigerTag-RFID-Guide, about 12 MB, 14 000+
products) ships with the package as ``database/id_catalog.json.gz`` (about 1 MB),
refreshed at every release, so it works offline. :func:`load_catalog` uses the
newest local copy (bundled, or downloaded into the shared data directory) while it
is younger than ``max_age`` (one day), and downloads a fresh one otherwise. Offline
(``offline=True`` or ``TIGERTAG_OFFLINE=1``) it never touches the network.

The catalogue changes every day. :func:`refresh_catalog` forces a check; it sends
the cached copy's ``ETag`` / ``Last-Modified`` so an unchanged file is not
downloaded again. :func:`catalog_info` tells when the cached copy was fetched,
how many products it holds and where it came from.

Each entry carries the chip data in ``RFID_Data``, with the generic names of the
export format. Their meaning comes from the chip layout and is the same for every
product type (filament, resin…)::

    data1 → id_diameter        data4 → dry_temp (°C)     data6 → bed_temp_min (°C)
    data2 → nozzle_temp_min    data5 → dry_time (h)      data7 → bed_temp_max (°C)
    data3 → nozzle_temp_max

``null`` values are written as 0: ``id_aspect2: null`` (no second aspect) becomes
0x00 "(none)", as in the protocol examples and the TigerTag+ Burning Factory; a null
temperature is 0 (undefined). Colours 2 and 3 come from ``color_r2/g2/b2`` and ``color_r3/g3/b3``,
or from ``color_info.colors[1]`` / ``[2]`` (``#RRGGBB[AA]``) when those are absent.
"""

from __future__ import annotations

import gzip
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from tigertag.db import BUNDLED_DB_PATH, default_data_dir, is_offline

# ── Constants ──────────────────────────────────────────────────────────────────

DEFAULT_CATALOG_URL = (
    "https://raw.githubusercontent.com/TigerTag-Project/TigerTag-RFID-Guide/"
    "refs/heads/main/database/id_catalog.json"
)
CATALOG_FILENAME = "id_catalog.json"
META_FILENAME    = "id_catalog.meta.json"   # url, fetched_at, checked_at, count, etag, last_modified
DEFAULT_MAX_AGE  = 24 * 3600     # refresh the cached copy once a day
DEFAULT_TIMEOUT  = 60            # seconds — the file is about 12 MB
BUNDLED_CATALOG  = BUNDLED_DB_PATH / "id_catalog.json.gz"   # fallback, refreshed at every release
ASPECT_NONE      = 0             # no second aspect: 0x00 "(none)", as in the spec examples

Catalog = Dict[int, Dict[str, Any]]


# ── Data directory, offline switch, bundled copy ───────────────────────────────

def default_cache_dir() -> Path:
    """Where the downloaded catalogue is kept — the shared data dir (see :func:`default_data_dir`)."""
    return default_data_dir()


def _gzip_mtime(path: Path) -> Optional[float]:
    """Time recorded in a gzip header (when the bundled catalogue content last changed)."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
        if head[:2] != b"\x1f\x8b":
            return None
        return float(int.from_bytes(head[4:8], "little")) or path.stat().st_mtime
    except OSError:
        return None


def read_catalog_file(path: Path) -> Catalog:
    """Read ``id_catalog.json`` or ``id_catalog.json.gz`` into ``{product_id: entry}``."""
    raw = Path(path).read_bytes()
    if str(path).endswith(".gz"):
        raw = gzip.decompress(raw)
    return _index(raw)


def _epoch(iso: Optional[str]) -> Optional[float]:
    try:
        return datetime.fromisoformat(iso).timestamp() if iso else None
    except ValueError:
        return None


def _local_copies(cache: Path) -> Dict[str, Tuple[Path, float]]:
    """Available local copies → ``{"downloaded"|"bundled": (path, content date)}``."""
    found: Dict[str, Tuple[Path, float]] = {}
    path = cache / CATALOG_FILENAME
    if path.exists():
        found["downloaded"] = (path, _epoch(_read_meta(cache).get("fetched_at")) or path.stat().st_mtime)
    gz = BUNDLED_CATALOG
    if gz.exists():
        found["bundled"] = (gz, _gzip_mtime(gz) or 0.0)
    return found


def _newest(copies: Dict[str, Tuple[Path, float]]) -> Optional[str]:
    if not copies:
        return None
    # On a tie the downloaded copy wins (it may carry an ETag for conditional requests)
    return max(copies, key=lambda k: (copies[k][1], k == "downloaded"))


# ── Download / cache ───────────────────────────────────────────────────────────

def _download(
    url: str,
    timeout: int,
    etag: Optional[str] = None,
    last_modified: Optional[str] = None,
) -> Optional[Tuple[bytes, Dict[str, Optional[str]]]]:
    """
    Fetch ``url`` over HTTPS (certifi CA bundle when installed).

    Sends ``If-None-Match`` / ``If-Modified-Since`` when known. Returns ``None``
    when the server answers 304 Not Modified, else ``(body, {"etag", "last_modified"})``.
    """
    from tigertag.tag import _https_context  # lazy: tag.py imports this module lazily too
    headers = {"User-Agent": "tigertag-sdk-python"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_https_context()) as resp:
            return resp.read(), {"etag": resp.headers.get("ETag"),
                                 "last_modified": resp.headers.get("Last-Modified")}
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return None
        raise


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_meta(cache: Path) -> Dict[str, Any]:
    try:
        return json.loads((cache / META_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_meta(cache: Path, meta: Dict[str, Any]) -> None:
    try:
        (cache / META_FILENAME).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    except OSError:
        pass


def _index(raw: bytes) -> Catalog:
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, list):
        raise ValueError("Catalogue JSON must be a list of products.")
    return {int(e["id"]): e for e in data if isinstance(e, dict) and isinstance(e.get("id"), int)}


def load_catalog(
    url: str = DEFAULT_CATALOG_URL,
    cache_dir: Optional[Path] = None,
    max_age: Optional[float] = DEFAULT_MAX_AGE,
    force: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
    offline: Optional[bool] = None,
) -> Catalog:
    """
    Load the official TigerTag+ catalogue as ``{product_id: entry}``.

    Uses the newest local copy — downloaded (in ``cache_dir``) or bundled with the
    package — while it is younger than ``max_age``; otherwise downloads it (a
    conditional request: an unchanged file is not downloaded again). Any download
    failure falls back to the newest local copy.

    Args:
        url       : Catalogue URL (defaults to the TigerTag-RFID-Guide ``main`` branch).
        cache_dir : Where the downloaded JSON is kept (default: the shared data dir).
        max_age   : Seconds before a local copy is considered stale; ``None`` = never.
        force     : Check for a new version even when the local copy is fresh.
        timeout   : Download timeout in seconds.
        offline   : No network access (also ``TIGERTAG_OFFLINE=1``): the newest local copy.

    Returns:
        Dict mapping each product ID to its catalogue entry (``title``, ``brand``,
        ``sku``, ``barcode``, ``img_src``, ``RFID_Data``…).

    Raises:
        RuntimeError: No local copy at all and the download failed (or offline).
    """
    cache = Path(cache_dir) if cache_dir else default_cache_dir()
    path = cache / CATALOG_FILENAME
    copies = _local_copies(cache)
    best = _newest(copies)

    if is_offline(offline):
        if best is None:
            raise RuntimeError(
                "Offline mode is on and no TigerTag+ catalogue is available locally "
                f"(no {path}, no bundled copy). Turn offline mode off to download it."
            )
        return read_catalog_file(copies[best][0])

    if best is not None and not force:
        if best == "downloaded":
            age = time.time() - path.stat().st_mtime          # restarted on every 304
        else:
            age = time.time() - copies["bundled"][1]
        if max_age is None or age < max_age:
            return read_catalog_file(copies[best][0])

    meta = _read_meta(cache) if path.exists() else {}
    use_validators = meta.get("url") == url and best == "downloaded"
    try:
        result = _download(url, timeout,
                           etag=meta.get("etag") if use_validators else None,
                           last_modified=meta.get("last_modified") if use_validators else None)
        if result is None:                         # 304: the cached copy is current
            catalog = _index(path.read_bytes())
            meta.update(checked_at=_now_iso(), count=len(catalog))
            _write_meta(cache, meta)
            try:
                os.utime(path)                     # restart the max_age clock
            except OSError:
                pass
            return catalog
        raw, headers = result
        catalog = _index(raw)                      # validate before replacing the cache
    except (urllib.error.URLError, OSError, ValueError) as exc:
        if best is not None:
            return read_catalog_file(copies[best][0])   # offline: newest local copy
        raise RuntimeError(
            f"Cannot download the TigerTag+ catalogue ({exc}) and no local copy exists "
            f"in {cache}. Connect to the internet and retry, or download {url} and pass "
            f"its folder as cache_dir."
        ) from exc
    try:
        cache.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(raw)
        tmp.replace(path)
        now = _now_iso()
        _write_meta(cache, {"url": url, "fetched_at": now, "checked_at": now,
                            "count": len(catalog), "size": len(raw), **headers})
    except OSError:
        pass  # a read-only cache must not prevent using the catalogue
    return catalog


def refresh_catalog(
    url: str = DEFAULT_CATALOG_URL,
    cache_dir: Optional[Path] = None,
    timeout: int = DEFAULT_TIMEOUT,
    offline: Optional[bool] = None,
) -> Catalog:
    """
    Force a catalogue update (same as ``load_catalog(force=True)``).

    The cached copy's ``ETag`` / ``Last-Modified`` are sent, so an unchanged file
    is not downloaded again (HTTP 304). On failure the newest local copy is returned.

    Raises:
        RuntimeError: Offline mode is on.
    """
    if is_offline(offline):
        raise RuntimeError(
            "Offline mode is on (offline=True or TIGERTAG_OFFLINE=1): the catalogue cannot "
            "be refreshed. Turn offline mode off to update it."
        )
    return load_catalog(url=url, cache_dir=cache_dir, force=True, timeout=timeout)


_BUNDLED_COUNT: Dict[float, int] = {}


def catalog_info(cache_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    Describe the local catalogue copies without downloading anything.

    Returns:
        ``source`` ("downloaded" or "bundled": the copy :func:`load_catalog` uses
        offline), ``downloaded`` (a downloaded copy exists), ``path``, ``url``,
        ``fetched_at`` (when the copy in use was produced or downloaded), ``checked_at``,
        ``count``, ``size``, ``etag``, ``last_modified``, and ``bundled`` (the
        package's copy: ``path``, ``date``).
    """
    cache = Path(cache_dir) if cache_dir else default_cache_dir()
    path = cache / CATALOG_FILENAME
    copies = _local_copies(cache)
    best = _newest(copies)
    info: Dict[str, Any] = {"downloaded": path.exists(), "path": str(path), "source": best}
    if "bundled" in copies:
        gz, date = copies["bundled"]
        info["bundled"] = {"path": str(gz), "date": datetime.fromtimestamp(date, tz=timezone.utc)
                           .replace(microsecond=0).isoformat()}
    if best == "downloaded":
        meta = _read_meta(cache)
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat()
        info.update({
            "url":           meta.get("url"),
            "fetched_at":    meta.get("fetched_at") or mtime,
            "checked_at":    meta.get("checked_at") or mtime,
            "count":         meta.get("count"),
            "size":          meta.get("size") or path.stat().st_size,
            "etag":          meta.get("etag"),
            "last_modified": meta.get("last_modified"),
        })
        if info["count"] is None:          # cache written by hand: count it once
            try:
                info["count"] = len(_index(path.read_bytes()))
            except ValueError:
                pass
    elif best == "bundled":
        gz, date = copies["bundled"]
        if date not in _BUNDLED_COUNT:
            try:
                _BUNDLED_COUNT[date] = len(read_catalog_file(gz))
            except (OSError, ValueError):
                _BUNDLED_COUNT[date] = 0
        info.update({
            "url": None, "fetched_at": info["bundled"]["date"], "checked_at": None,
            "count": _BUNDLED_COUNT[date], "size": gz.stat().st_size,
            "etag": None, "last_modified": None,
        })
    return info


# ── Entry → chip fields ────────────────────────────────────────────────────────

def catalog_entry(product_id: int, catalog: Optional[Catalog] = None) -> Dict[str, Any]:
    """
    Return the catalogue entry for ``product_id`` (title, brand, sku, barcode,
    img_src, RFID_Data…). Loads the catalogue when ``catalog`` is omitted.

    Raises:
        KeyError: The product ID is not in the catalogue.
    """
    catalog = load_catalog() if catalog is None else catalog
    try:
        return catalog[int(product_id)]
    except KeyError:
        raise KeyError(
            f"TigerTag+ product ID {product_id} is not in the official catalogue "
            f"({len(catalog)} products). Check the ID on https://tigertag.io or refresh "
            f"the catalogue with load_catalog(force=True)."
        ) from None


def parse_hex_color(value: str) -> Tuple[int, int, int, int]:
    """``"#RRGGBB"`` or ``"#RRGGBBAA"`` → ``(r, g, b, a)``; alpha defaults to 255."""
    h = value.strip().lstrip("#")
    if len(h) not in (6, 8):
        raise ValueError(f"Not a #RRGGBB[AA] colour: {value!r}")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    a = int(h[6:8], 16) if len(h) == 8 else 255
    return r, g, b, a


def rfid_fields(entry: Dict[str, Any]) -> Dict[str, int]:
    """
    Map a catalogue entry to :meth:`TigerTag.create` keyword arguments
    (``product_id`` included). See the module docstring for the data1–data7 mapping.

    Raises:
        ValueError: The entry has no ``RFID_Data``.
    """
    d = entry.get("RFID_Data")
    if not isinstance(d, dict):
        raise ValueError(
            f"Catalogue entry {entry.get('id')} ({entry.get('title', '?')}) has no RFID_Data: "
            "it cannot be written to a chip."
        )

    def n(key: str, default: int = 0) -> int:
        v = d.get(key)
        return int(v) if v is not None else default

    fields: Dict[str, int] = {
        "product_id":      int(entry["id"]),
        "id_material":     n("id_material"),
        "id_aspect_1":     n("id_aspect1"),
        "id_aspect_2":     n("id_aspect2", ASPECT_NONE),
        "id_type":         n("id_type"),
        "id_diameter":     n("data1"),
        "id_brand":        n("id_brand"),
        "color1_r":        n("color_r"),
        "color1_g":        n("color_g"),
        "color1_b":        n("color_b"),
        "color1_a":        n("color_a", 255),
        "measure":         n("measure"),
        "id_unit":         n("id_unit"),
        "nozzle_temp_min": n("data2"),
        "nozzle_temp_max": n("data3"),
        "dry_temp":        n("data4"),
        "dry_time":        n("data5"),
        "bed_temp_min":    n("data6"),
        "bed_temp_max":    n("data7"),
    }
    colors = ((entry.get("color_info") or {}).get("colors")) or []
    for slot in (2, 3):
        keys = (f"color_r{slot}", f"color_g{slot}", f"color_b{slot}")
        if all(d.get(k) is not None for k in keys):
            rgb = tuple(int(d[k]) for k in keys)
        elif len(colors) >= slot:
            rgb = parse_hex_color(colors[slot - 1])[:3]
        else:
            rgb = (0, 0, 0)
        fields[f"color{slot}_r"], fields[f"color{slot}_g"], fields[f"color{slot}_b"] = rgb
    return fields
