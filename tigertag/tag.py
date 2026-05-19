# TigerTag RFID Guide
# Copyright (C) 2025 TigerTag
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License.

"""TigerTag dataclass — binary parsing, serialization, and verification."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field, fields as _dc_fields, replace as _dc_replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tigertag.db import TigerTagDB
from tigertag.signature import SignatureResult, _CRYPTO_AVAILABLE, verify_signature


# ── Protocol constants ─────────────────────────────────────────────────────────

CHIP_DUMP_LEN = 180   # full chip: 45 pages × 4B (pages 0-44)
FULL_DATA_LEN = 144   # user data + signature (pages 0x04-0x27)
MIN_DATA_LEN  = 80    # user data only (pages 0x04-0x17)

_TIGERTAG_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)

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


# ── ApiDiff ────────────────────────────────────────────────────────────────────

@dataclass
class ApiDiff:
    """
    A single field difference between chip data and the TigerTag+ cloud API.

    Returned by :meth:`TigerTag.diff_api`.

    Attributes:
        field      : Field name (e.g. ``"nozzle_min"``).
        chip_value : Value currently stored on the chip.
        api_value  : Value returned by the cloud API.
    """

    field:      str
    chip_value: Any
    api_value:  Any

    def __repr__(self) -> str:
        return f"  {self.field}: chip={self.chip_value!r}  →  api={self.api_value!r}"


# ── TigerTag dataclass ─────────────────────────────────────────────────────────

@dataclass
class TigerTag:
    """
    TigerTag NTAG-compatible chip payload — CRUD interface.

    All fields are plain integers/bytes/strings. Use :class:`TigerTagDB`
    (via the ``.db`` property or pass one to :meth:`to_dict`) to resolve IDs
    to labels.

    **Create**::

        tag = TigerTag.create(id_material=38219, nozzle_temp_min=190, ...)
        tag = TigerTag.create(product_id=10, ...)   # TigerTag+
        chip.write_pages(4, tag.to_bytes())

    **Read**::

        tag = TigerTag.from_pages(chip.read_pages(4, 20), uid=chip.uid)
        tag = TigerTag.from_dump(data)
        tag = TigerTag.from_file("dump.bin")

    **Update (surgical)**::

        new_tag = tag.patch(dry_temp=55, nozzle_temp_max=240)
        chip.write_pages(4, new_tag.to_bytes())

    **Update (auto-sync from cloud API)**::

        new_tag, applied = tag.patch_from_api()
        chip.write_pages(4, new_tag.to_bytes())

    **Init** (optional formatting step — reserve the chip without programming it)::

        chip.write_pages(4, TigerTag.as_init().to_bytes())

    **Delete** (wipe back to blank NDEF)::

        chip.write_pages(4, TigerTag.erase())
    """

    # Identity
    id_tigertag : int   # u32 BE — format/version identifier (see id_version.json)
    id_product  : int   # u32 BE — 0xFFFFFFFF=Maker, 0=Init, else cloud product ID

    # Material (all IDs resolve via TigerTagDB)
    id_material : int   # u16 BE — see id_material.json
    id_aspect_1 : int   # u8    — see id_aspect.json
    id_aspect_2 : int   # u8    — see id_aspect.json
    id_type     : int   # u8    — see id_type.json (0x8E=Filament, 0xAD=Resin)
    id_diameter : int   # u8    — see id_diameter.json
    id_brand    : int   # u16 BE — see id_brand.json

    # Colors
    color1_r : int      # Color 1 Red   (page 0x08)
    color1_g : int      # Color 1 Green
    color1_b : int      # Color 1 Blue
    color1_a : int      # Color 1 Alpha
    color2_r : int      # Color 2 Red   (page 0x0D)
    color2_g : int      # Color 2 Green
    color2_b : int      # Color 2 Blue
    color3_r : int      # Color 3 Red   (page 0x0E)
    color3_g : int      # Color 3 Green
    color3_b : int      # Color 3 Blue

    # Quantity
    measure           : int  # u24 BE — quantity at manufacturing
    id_unit           : int  # u8    — see id_measure_unit.json
    measure_available : int  # u24 BE — remaining (updated by Tiger Scale)

    # Temperatures (°C)
    nozzle_temp_min : int   # u16 BE
    nozzle_temp_max : int   # u16 BE
    dry_temp        : int   # u8
    dry_time        : int   # u8 hours
    bed_temp_min    : int   # u8
    bed_temp_max    : int   # u8

    # Traceability
    timestamp      : int   # u32 BE — seconds since 2000-01-01 GMT + twin tag pairing ID
    custom_message : str   # UTF-8, max 28 bytes

    # HueForge
    td_raw : int           # u16 BE — actual TD = td_raw / 10  (0=undefined, 1-1000 valid)

    # Signature (optional, pages 0x18-0x27)
    signature_r : bytes = field(default_factory=lambda: bytes(32))
    signature_s : bytes = field(default_factory=lambda: bytes(32))

    # Chip UID (auto-extracted from full 180-byte dump, else None)
    uid : Optional[bytes] = field(default=None)

    # Lazily loaded DB
    _db : Optional[TigerTagDB] = field(default=None, repr=False, compare=False)

    # ── Derived properties ─────────────────────────────────────────────────────

    @property
    def is_maker(self) -> bool:
        """True when id_product == 0xFFFFFFFF (offline Maker tag)."""
        return self.id_product == MAKER_PRODUCT_ID

    @property
    def is_init(self) -> bool:
        """True when id_product == 0x00000000 (blank/uninitialized tag)."""
        return self.id_product == INIT_PRODUCT_ID

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

    # ── Database ───────────────────────────────────────────────────────────────

    @property
    def db(self) -> TigerTagDB:
        """Lazily loaded bundled database."""
        if self._db is None:
            self._db = TigerTagDB()
        return self._db

    def raw_api(self, timeout: int = 5) -> Optional[Dict[str, Any]]:
        """
        Fetch the raw TigerTag+ cloud product data from the API.

        Returns the unmodified API JSON as a Python dict — identical to what
        the ☁ raw_api() tab shows in the playground.

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
                print(data["filament"]["diameter"])

            # Combine with to_dict() for full offline + cloud picture:
            offline = tag.to_dict()
            cloud   = tag.raw_api()
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

        Returns a list of :class:`ApiDiff` entries for every field whose value
        on the chip differs from what the API currently reports.
        An empty list means the chip is fully in sync.

        Useful for detecting chips that need reprogramming after a manufacturer
        corrects a temperature recommendation or updates product specs.

        Args:
            api_data : Pre-fetched result of :meth:`raw_api`. Fetched
                       automatically when ``None``.
            db       : Optional :class:`TigerTagDB`.

        Returns:
            List of :class:`ApiDiff`. Empty = in sync.

        Raises:
            RuntimeError : If ``api_data`` is ``None`` and the network request fails.

        Example:
            diffs = tag.diff_api()
            if diffs:
                print(f"{len(diffs)} field(s) need updating:")
                for d in diffs:
                    print(d)
            else:
                print("Chip is in sync with the API.")

            # Reuse an already-fetched response to avoid a second request:
            cloud = tag.raw_api()
            diffs = tag.diff_api(api_data=cloud)
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

        def _check(field: str, chip_val: Any, api_val: Any) -> None:
            if api_val is None:
                return
            c = str(chip_val).strip().lower()
            a = str(api_val).strip().lower()
            if c != a:
                diffs.append(ApiDiff(field, chip_val, api_val))

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
        _check("type",     _lbl(_db.type_(self.id_type)),          (data.get("product_type") or "").lower())
        _check("material", _lbl(_db.material(self.id_material)),   (fil.get("material") or "").lower())
        _check("brand",    _lbl(_db.brand(self.id_brand)),         (data.get("brand")   or "").lower())
        _check("diameter", TigerTagDB.label(_db.diameter(self.id_diameter)) or "",
                           str(fil.get("diameter") or ""))
        _EMPTY_ASPECT = {"", "unknown", "-", "none"}

        def _check_aspect(fname: str, chip_id: int, api_val: Optional[str]) -> None:
            chip_lbl = _lbl(_db.aspect(chip_id))
            api_norm = (api_val or "").strip().lower()
            if chip_lbl in _EMPTY_ASPECT and api_norm in _EMPTY_ASPECT:
                return  # both mean "no aspect" — not a diff
            if chip_lbl != api_norm:
                diffs.append(ApiDiff(fname, chip_lbl or "none", api_val or "none"))

        _check_aspect("aspect_1", self.id_aspect_1, fil.get("aspect1"))
        _check_aspect("aspect_2", self.id_aspect_2, fil.get("aspect2"))

        # Colors
        def _parse_api_color(hex_str: str) -> Optional[Tuple[int, int, int, int]]:
            """Parse #RRGGBBAA or #RRGGBB → (r, g, b, a). Returns None on error."""
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

        # Quantity & unit
        if fil.get("grams") is not None:
            _check("measure_g", self.measure, int(fil["grams"]))
        if fil.get("measure_unit"):
            _check("measure_unit",
                   TigerTagDB.label(_db.unit(self.id_unit)) or "",
                   (fil["measure_unit"] or "").strip())

        return diffs

    # ── Surgical patch ─────────────────────────────────────────────────────────

    def patch(self, **kwargs: Any) -> "TigerTag":
        """
        Return a new :class:`TigerTag` with selected fields replaced.

        The ECDSA signature covers ``uid``, ``id_tigertag``, and ``id_product``.
        Modifying these would invalidate the signature, so they are blocked here.
        All other fields (temperatures, times, colors, etc.) can be updated safely.

        Args:
            **kwargs: Field names and their new values.

        Returns:
            A new :class:`TigerTag` instance with the requested fields updated.
            The original instance is unchanged.

        Raises:
            ValueError: If any protected or unknown field is requested.

        Example::

            updated = tag.patch(nozzle_temp_min=200, nozzle_temp_max=240)
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

        Fetches the current product data from the TigerTag+ cloud API (or uses
        *api_data* if supplied), computes the diff, and patches all numeric fields
        that differ (temperatures, drying parameters, weight).

        Fields that cannot be automatically mapped (e.g. material label, brand name)
        are reported in the returned diff list but are **not** patched — those require
        re-programming the chip with manufacturer tooling.

        Args:
            api_data : Pre-fetched API dict. If ``None``, calls :meth:`raw_api`.
            db       : Override the database used for label resolution.

        Returns:
            ``(updated_tag, applied_diffs)`` — a patched :class:`TigerTag` and the
            list of :class:`ApiDiff` entries that were applied.
            If the tag is Maker/Init or no patchable diffs are found, returns
            ``(self, [])``.

        Raises:
            RuntimeError: If the network request fails (only when *api_data* is ``None``).

        Example::

            new_tag, applied = tag.patch_from_api()
            if applied:
                print(f"Updated {len(applied)} field(s). Write new_tag.to_bytes() to chip.")
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

        # Numeric and color fields can be auto-patched without touching the signature.
        # Label-based fields (material, brand, aspect…) require chip re-programming.
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
            # Color fields — unpack hex → individual RGBA/RGB channel fields
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

    def sync_db(self, db_path: Optional[Path] = None, force: bool = False) -> List[str]:
        """
        Download or update reference databases.

        Args:
            db_path : Target folder. Defaults to the bundled database directory.
            force   : Re-download all files even if up to date.

        Returns:
            List of filenames that were downloaded/updated.

        Raises:
            ImportError : if 'requests' is not installed.
        """
        from tigertag.db import _BUNDLED_DB_PATH
        path = Path(db_path) if db_path else _BUNDLED_DB_PATH
        self._db = TigerTagDB(path, auto_sync=True)
        return self._db.sync(force=force)

    # ── Constructors ───────────────────────────────────────────────────────────

    @classmethod
    def from_pages(
        cls,
        payload: bytes,
        uid: bytes,
        db: Optional[TigerTagDB] = None,
    ) -> "TigerTag":
        """
        Parse a TigerTag from NFC SDK native output. (Primary method)

        This is the recommended constructor for production use with any NFC SDK.
        The UID and payload are provided separately, exactly as NFC SDKs expose them.

        Args:
            payload : 80 or 144 bytes — pages 0x04 to 0x27 read by the NFC SDK.
                      80 bytes  = pages 0x04-0x17 (user data, no signature)
                      144 bytes = pages 0x04-0x27 (user data + ECDSA signature)
            uid     : 7-byte chip UID as returned natively by the NFC SDK.
                      Pass raw bytes — NOT a hex string, NOT a decimal integer.
            db      : Optional pre-loaded TigerTagDB instance.

        Returns:
            TigerTag with .uid set and .verify() fully operational.

        Raises:
            ValueError : if payload size or UID length is invalid.

        Example:
            # Android (NfcA / MifareUltralight)
            uid     = tag.id                       # ByteArray → bytes
            payload = mifare.readPages(4, 39)      # 144 bytes

            # iOS (CoreNFC)
            uid     = tag.identifier               # Data → bytes
            payload = tag.readNDEF(...)            # pages 4-39

            # Flutter (flutter_nfc_kit)
            uid     = bytes.fromhex(tag.id)
            payload = await FlutterNfcKit.readBlock(4, length=144)

            # Python nfcpy / ACR122U
            uid     = tag.identifier               # bytes
            payload = tag.read(4, 36)              # 36 pages × 4 bytes

            tag = TigerTag.from_pages(payload, uid=uid)
            result = tag.verify()  # fully autonomous
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
        tag = cls._parse(payload, db=db)
        tag.uid = uid
        return tag

    @classmethod
    def from_dump(
        cls,
        data: bytes,
        db: Optional[TigerTagDB] = None,
    ) -> "TigerTag":
        """
        Parse a TigerTag from a raw binary dump.

        For production NFC SDK integration, prefer from_pages() instead.

        Args:
            data : Accepted sizes:
                   180 bytes — full chip dump (pages 0-44):
                               UID auto-extracted from system pages (pages 0-1).
                               Signature is verifiable.
                   144 bytes — partial dump (pages 0x04-0x27, no system pages):
                               UID not available → signature cannot be verified.
                               Use from_pages(data, uid=uid) instead to get
                               full verification with an externally supplied UID.
                    80 bytes — user data only (pages 0x04-0x17).
            db   : Optional pre-loaded TigerTagDB instance.

        Raises:
            ValueError : if data length is not 80, 144, or 180 bytes.
        """
        uid: Optional[bytes] = None

        if len(data) == CHIP_DUMP_LEN:
            # Extract 7-byte UID from system pages:
            # Page 0 [0:3] = UID[0..2], Page 1 [0:4] = UID[3..6]
            # Byte 3 of page 0 is BCC0 (XOR check) — excluded from UID.
            uid  = data[0:3] + data[4:8]
            data = data[16:160]  # strip system pages → 144 bytes of user data

        if len(data) not in (MIN_DATA_LEN, FULL_DATA_LEN):
            raise ValueError(
                f"Invalid dump size: {len(data)} bytes.\n"
                f"Accepted: 180B (full chip), 144B (user+sig), 80B (user only)."
            )

        tag = cls._parse(data, db=db)
        tag.uid = uid
        return tag

    @classmethod
    def from_file(
        cls,
        path: Any,
        db: Optional[TigerTagDB] = None,
    ) -> "TigerTag":
        """
        Parse a TigerTag from a .bin file.

        Args:
            path : Path to binary dump file (str or Path).
            db   : Optional pre-loaded TigerTagDB instance.

        Raises:
            FileNotFoundError : if the file does not exist.
            ValueError        : if the file length is invalid.

        Example:
            tag = TigerTag.from_file("dump.bin")
        """
        with open(path, "rb") as f:
            return cls.from_dump(f.read(), db=db)

    @classmethod
    def _parse(cls, data: bytes, db: Optional[TigerTagDB] = None) -> "TigerTag":
        """Internal parser — expects exactly 80 or 144 bytes of user memory."""
        def u8(o: int)  -> int: return data[o]
        def u16(o: int) -> int: return struct.unpack_from(">H", data, o)[0]
        def u24(o: int) -> int: return (data[o] << 16) | (data[o + 1] << 8) | data[o + 2]
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
        )
        tag._db = db
        return tag

    # ── CRUD constructors ──────────────────────────────────────────────────────

    @classmethod
    def create(
        cls,
        *,
        product_id: int = MAKER_PRODUCT_ID,
        uid: Optional[bytes] = None,
        # Material
        id_material: int = 0,
        id_aspect_1: int = 0,
        id_aspect_2: int = 0,
        id_type:     int = 0,
        id_diameter: int = 0,
        id_brand:    int = 0,
        # Colors
        color1_r: int = 0, color1_g: int = 0, color1_b: int = 0, color1_a: int = 255,
        color2_r: int = 0, color2_g: int = 0, color2_b: int = 0,
        color3_r: int = 0, color3_g: int = 0, color3_b: int = 0,
        # Quantity
        measure:   int = 0,
        id_unit:   int = 0,
        # Temperatures
        nozzle_temp_min: int = 0,
        nozzle_temp_max: int = 0,
        dry_temp:        int = 0,
        dry_time:        int = 0,
        bed_temp_min:    int = 0,
        bed_temp_max:    int = 0,
        # Traceability
        timestamp:      Optional[int] = None,
        custom_message: str = "",
        # HueForge
        td_raw: int = 0,
        db: Optional[TigerTagDB] = None,
    ) -> "TigerTag":
        """
        Create a new :class:`TigerTag` from scratch and serialize it with
        :meth:`to_bytes` to write directly to a blank NDEF chip.

        No Init step required — the chip can go from blank NDEF to a fully
        programmed TigerTag or TigerTag+ in one write.

        The protocol version (``id_tigertag``) is inferred automatically:

        * ``product_id`` omitted or ``0xFFFFFFFF`` → **TigerTag** (Maker / offline)
        * ``product_id`` is a real cloud ID               → **TigerTag+**

        Args:
            product_id      : Cloud product ID for TigerTag+, or ``MAKER_PRODUCT_ID``
                              (default) for an offline Maker tag.
            uid             : 7-byte chip UID, if known.
            id_material     : Material ID from ``id_material.json``.
            id_aspect_1     : Primary aspect ID from ``id_aspect.json``.
            id_aspect_2     : Secondary aspect ID from ``id_aspect.json``.
            id_type         : Type ID from ``id_type.json``.
            id_diameter     : Diameter ID from ``id_diameter.json``.
            id_brand        : Brand ID from ``id_brand.json``.
            color1_r/g/b/a  : Primary colour (RGBA, 0–255).
            color2_r/g/b    : Secondary colour.
            color3_r/g/b    : Tertiary colour.
            measure         : Initial quantity at manufacturing.
            id_unit         : Unit ID from ``id_measure_unit.json``.
            nozzle_temp_min : Minimum nozzle temperature (°C).
            nozzle_temp_max : Maximum nozzle temperature (°C).
            dry_temp        : Drying temperature (°C).
            dry_time        : Drying time (hours).
            bed_temp_min    : Minimum bed temperature (°C).
            bed_temp_max    : Maximum bed temperature (°C).
            timestamp       : Seconds since 2000-01-01 UTC. Defaults to *now*.
            custom_message  : Free-text traceability field (max 28 bytes UTF-8).
            td_raw          : HueForge TD × 10 (0 = undefined).
            db              : Optional pre-loaded :class:`TigerTagDB`.

        Returns:
            A new :class:`TigerTag` instance ready for :meth:`to_bytes`.

        Example::

            tag = TigerTag.create(
                product_id=10,          # TigerTag+
                id_material=38219,      # PLA
                id_brand=50604,         # Polymaker
                nozzle_temp_min=190, nozzle_temp_max=240,
                bed_temp_min=35, bed_temp_max=65,
                dry_temp=45, dry_time=6,
                measure=1000, id_unit=21,
                color1_r=137, color1_g=217, color1_b=217,
            )
            chip.write_pages(4, tag.to_bytes())
        """
        if product_id != MAKER_PRODUCT_ID and product_id != INIT_PRODUCT_ID:
            id_tigertag = ID_TIGERTAG_PLUS
        else:
            id_tigertag  = ID_TIGERTAG
            product_id   = MAKER_PRODUCT_ID

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
        Create a TigerTag **Init** payload.

        Init is a "formatting" step — it marks the chip as reserved for TigerTag
        without programming any material data yet.  Write :meth:`to_bytes` to the
        chip; any reader will recognise it as a blank TigerTag placeholder.

        This step is optional: :meth:`create` can go directly from a blank NDEF
        chip to a fully programmed TigerTag or TigerTag+.

        Args:
            uid : 7-byte chip UID, if known.

        Returns:
            A :class:`TigerTag` with ``id_tigertag = ID_TIGERTAG_INIT``,
            ``id_product = 0``, and all material fields zeroed.

        Example::

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
            id_aspect_1       = 0,
            id_aspect_2       = 0,
            id_type           = 0,
            id_diameter       = 0,
            id_brand          = 0,
            color1_r          = 0, color1_g = 0, color1_b = 0, color1_a = 255,
            color2_r          = 0, color2_g = 0, color2_b = 0,
            color3_r          = 0, color3_g = 0, color3_b = 0,
            measure           = 0,
            id_unit           = 0,
            measure_available = 0,
            nozzle_temp_min   = 0,
            nozzle_temp_max   = 0,
            dry_temp          = 0,
            dry_time          = 0,
            bed_temp_min      = 0,
            bed_temp_max      = 0,
            timestamp         = ts,
            custom_message    = "",
            td_raw            = 0,
            uid               = uid,
        )

    @classmethod
    def erase(cls) -> bytes:
        """
        Return the 80-byte payload that wipes a TigerTag chip back to blank NDEF.

        Writing these bytes to pages 0x04–0x17 destroys all TigerTag data.
        The chip becomes a plain NDEF chip with no TigerTag structure — it can
        be reprogrammed as a new TigerTag at any time with :meth:`create`.

        Returns:
            ``bytes(80)`` — 80 zero bytes, pages 0x04–0x17.

        Example::

            chip.write_pages(4, TigerTag.erase())
            # chip is now blank NDEF — no longer a TigerTag
        """
        return bytes(MIN_DATA_LEN)

    # ── Serializer ─────────────────────────────────────────────────────────────

    def to_bytes(self, include_signature: bool = False) -> bytes:
        """
        Serialize to binary (pages 0x04 onward).

        Args:
            include_signature : If True, append 64-byte ECDSA signature.

        Returns:
            80 bytes (user data) or 144 bytes (with signature).
        """
        def p16(v: int) -> bytes: return struct.pack(">H", v & 0xFFFF)
        def p24(v: int) -> bytes:
            v &= 0xFFFFFF
            return bytes([(v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF])
        def p32(v: int) -> bytes: return struct.pack(">I", v & 0xFFFFFFFF)

        msg_bytes = self.custom_message.encode("utf-8")[:28]
        msg_bytes = msg_bytes + bytes(28 - len(msg_bytes))

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
            + msg_bytes
            + p24(self.measure_available)
            + b"\x00"
        )

        assert len(data) == MIN_DATA_LEN

        if include_signature:
            data += (self.signature_r + bytes(32))[:32]
            data += (self.signature_s + bytes(32))[:32]

        return data

    def to_raw_dict(self) -> Dict[str, Any]:
        """
        Return protocol fields exactly as stored on the chip — no label resolution,
        no unit conversion, no date formatting.

        Field order mirrors the binary layout (TigerTag Open Source v2.1).
        All values are raw integers, colour channels are flat (color_r/g/b/a …),
        and the UID is a plain uppercase hex string (or None for partial dumps).

        This is the canonical "source of truth" view, equivalent to what your
        cloud inventory table stores before any SDK enrichment.
        """
        return {
            # ── Header ──────────────────────────────────────────────────────
            "id_tigertag":        self.id_tigertag,
            "id_product":         self.id_product,
            # ── Material IDs ────────────────────────────────────────────────
            "id_material":        self.id_material,
            "id_aspect1":         self.id_aspect_1,
            "id_aspect2":         self.id_aspect_2,
            "id_type":            self.id_type,
            "id_diameter":        self.id_diameter,
            "id_brand":           self.id_brand,
            # ── Color 1 (RGBA) ───────────────────────────────────────────────
            "color_r":            self.color1_r,
            "color_g":            self.color1_g,
            "color_b":            self.color1_b,
            "color_a":            self.color1_a,
            # ── Quantity ─────────────────────────────────────────────────────
            "measure":            self.measure,
            "id_unit":            self.id_unit,
            # ── Temperatures (°C) ────────────────────────────────────────────
            "nozzle_min":         self.nozzle_temp_min,
            "nozzle_max":         self.nozzle_temp_max,
            "dry_temp":           self.dry_temp,
            "dry_time":           self.dry_time,
            "bed_min":            self.bed_temp_min,
            "bed_max":            self.bed_temp_max,
            # ── Traceability ─────────────────────────────────────────────────
            "timestamp":          self.timestamp,
            # ── Color 2 & 3 (RGB) ────────────────────────────────────────────
            "color_r2":           self.color2_r,
            "color_g2":           self.color2_g,
            "color_b2":           self.color2_b,
            "color_r3":           self.color3_r,
            "color_g3":           self.color3_g,
            "color_b3":           self.color3_b,
            # ── HueForge ─────────────────────────────────────────────────────
            "td_raw":             self.td_raw,
            # ── Message & stock ──────────────────────────────────────────────
            "message":            self.custom_message,
            "measure_available":  self.measure_available,
            # ── Chip UID ─────────────────────────────────────────────────────
            "uid":                self.uid_hex,
            # ── TigerTag+ links (derived — not stored on chip) ───────────────
            "product_page_url":   self.product_page_url,
            "api_url":            self.api_url,
        }

    # ── Validation ─────────────────────────────────────────────────────────────

    def validate(self) -> List[str]:
        """
        Basic field-level sanity checks.

        Returns:
            List of warning strings. Empty list = no issues.

        Example:
            for warning in tag.validate():
                print(f"Warning: {warning}")
        """
        warnings: List[str] = []
        if self.nozzle_temp_min > self.nozzle_temp_max > 0:
            warnings.append(
                f"Nozzle temp min ({self.nozzle_temp_min}°C) > max ({self.nozzle_temp_max}°C)"
            )
        if self.bed_temp_min > self.bed_temp_max > 0:
            warnings.append(
                f"Bed temp min ({self.bed_temp_min}°C) > max ({self.bed_temp_max}°C)"
            )
        if self.td_raw != 0 and not (10 <= self.td_raw <= 1000):
            warnings.append(
                f"TD HueForge out of range: {self.td_raw} (valid: 10–1000 or 0=undefined)"
            )
        if self.measure > 0 and self.measure_available > self.measure:
            warnings.append(
                f"measure_available ({self.measure_available}) > initial measure ({self.measure})"
            )
        if len(self.custom_message.encode("utf-8")) > 28:
            warnings.append("custom_message exceeds 28 bytes")
        return warnings

    # ── Signature verification ─────────────────────────────────────────────────

    def verify(self, db: Optional[TigerTagDB] = None) -> SignatureResult:
        """
        Verify the ECDSA-P256 signature — fully autonomous.

        Signed message: SHA-256( uid_bytes + block4 + block5 )
          uid_bytes = 7 raw bytes from chip pages 0-1 (ISO 14443, raw binary)
          block4    = id_tigertag as 4-byte big-endian
          block5    = id_product  as 4-byte big-endian

        The public key is read automatically from id_version.json.

        Args:
            db : Optional pre-loaded TigerTagDB. Uses bundled DB by default.

        Returns:
            SignatureResult with .ok (bool) and .status (str).

        Requires:
            - 180-byte chip dump (for UID), or from_pages() with uid argument
            - pip install tigertag[verify]
            - id_version.json with "public_key" field

        Example:
            result = tag.verify()
            print(result)     # ✅ VALID  /  ❌ INVALID  /  ⬜ NOT SIGNED
            print(result.ok)  # True / False
        """
        if not self.is_signed:
            return SignatureResult(SignatureResult.UNSIGNED)

        if not _CRYPTO_AVAILABLE:
            return SignatureResult(SignatureResult.NO_CRYPTO)

        if not self.uid:
            return SignatureResult(
                SignatureResult.NO_UID,
                "UID required for signature verification. "
                "Use from_pages(payload, uid=uid) — the NFC SDK always exposes "
                "the UID separately. For binary dumps, use a full 180-byte dump.",
            )

        _db = db or self.db
        version_entry = _db.version(self.id_tigertag) or {}
        pem = version_entry.get("public_key", "").strip()
        if not pem:
            return SignatureResult(
                SignatureResult.NO_KEY,
                f"No public_key in id_version.json for 0x{self.id_tigertag:08X}.",
            )

        return verify_signature(
            uid         = self.uid,
            id_tigertag = self.id_tigertag,
            id_product  = self.id_product,
            signature_r = self.signature_r,
            signature_s = self.signature_s,
            public_key_pem = pem,
        )

    # ── Output ─────────────────────────────────────────────────────────────────

    def to_dict(self, db: Optional[TigerTagDB] = None) -> Dict[str, Any]:
        """
        Return a fully-resolved dict with labels, units, and semantic context.

        All numeric fields include their unit. All ID fields include their
        human-readable label. Suitable for JSON serialization, API responses,
        LLM context injection, or further processing.

        Args:
            db : Optional pre-loaded TigerTagDB. Uses bundled DB by default.

        Example:
            import json
            print(json.dumps(tag.to_dict(), indent=2))

            # Inject into an LLM prompt:
            context = json.dumps(tag.to_dict())
            prompt = f"Given this material tag: {context}\\nWhat temperature should I use?"
        """
        _db    = db or self.db
        mat    = _db.material(self.id_material) or {}
        rec    = mat.get("recommended", {})
        stock  = self.stock_percent
        unit_label = TigerTagDB.label(_db.unit(self.id_unit))

        return {
            "sdk":      "tigertag-sdk-python",
            "sdk_mode": "offline",
            "protocol": "TigerTag Open Source v2.1",
            "chip":     "NTAG213/215/216",
            "uid":      self.uid_hex,
            "version": {
                "id":    self.id_tigertag,
                "hex":   f"0x{self.id_tigertag:08X}",
                "label": TigerTagDB.label(_db.version(self.id_tigertag)),
            },
            "product": {
                "id":               self.id_product,
                "mode":             "maker" if self.is_maker else "init" if self.is_init else "cloud",
                "description":      (
                    "TigerTag Maker — all data stored on chip, no cloud dependency."
                    if self.is_maker else
                    "TigerTag Init — blank/uninitialized chip."
                    if self.is_init else
                    f"TigerTag+ — cloud product ID {self.id_product}. "
                    "Query the api_url field for the full enriched product JSON."
                ),
                "product_page_url": self.product_page_url,
                "api_url":          self.api_url,
            },
            "material": {
                "id":      self.id_material,
                "label":   TigerTagDB.label(_db.material(self.id_material)),
                "density": mat.get("density"),
                "density_unit": "g/cm³",
                "filled":  mat.get("filled"),
                "recommended_by_db": {
                    "nozzle": {
                        "min": rec.get("nozzleTempMin"),
                        "max": rec.get("nozzleTempMax"),
                        "unit": "celsius",
                    },
                    "bed": {
                        "min": rec.get("bedTempMin"),
                        "max": rec.get("bedTempMax"),
                        "unit": "celsius",
                    },
                    "dry": {
                        "temp":   rec.get("dryTemp"),
                        "time_h": rec.get("dryTime"),
                        "temp_unit": "celsius",
                        "time_unit": "hours",
                    },
                } if rec else None,
                "metadata": mat.get("metadata"),
            },
            "aspect_1": {
                "id":          self.id_aspect_1,
                "label":       TigerTagDB.label(_db.aspect(self.id_aspect_1)),
                "color_count": (_db.aspect(self.id_aspect_1) or {}).get("color_count", 1),
            },
            "aspect_2": {
                "id":          self.id_aspect_2,
                "label":       TigerTagDB.label(_db.aspect(self.id_aspect_2)),
                "color_count": (_db.aspect(self.id_aspect_2) or {}).get("color_count", 1),
                "description": (
                    "Check aspect_2 first for multi-color modes (Bicolor/Tricolor/Rainbow). "
                    "color_count defines how many of the three color fields are active."
                ),
            },
            "type":     {"id": self.id_type,     "label": TigerTagDB.label(_db.type_(self.id_type))},
            "diameter": {
                "id":    self.id_diameter,
                "label": TigerTagDB.label(_db.diameter(self.id_diameter)),
                "unit":  "mm",
            },
            "brand": {"id": self.id_brand, "label": TigerTagDB.label(_db.brand(self.id_brand))},
            "colors": {
                "primary":   {
                    "hex":  self.color1_hex,
                    "rgba": [self.color1_r, self.color1_g, self.color1_b, self.color1_a],
                    "description": "Main filament color (RGBA — alpha=255 means fully opaque).",
                },
                "secondary": {
                    "hex": self.color2_hex,
                    "rgb": [self.color2_r, self.color2_g, self.color2_b],
                    "description": "Secondary color for bi-color or gradient filaments.",
                },
                "tertiary":  {
                    "hex": self.color3_hex,
                    "rgb": [self.color3_r, self.color3_g, self.color3_b],
                    "description": "Tertiary color for tri-color filaments.",
                },
            },
            "hueforge_td": {
                "value":       self.td_value if self.td_raw != 0 else None,
                "unit":        "TD (Transmission Distance)",
                "description": (
                    "HueForge Transmission Distance — opacity parameter for image-to-model slicing. "
                    "Valid range: 0.1–100.0. null means undefined (no HueForge data on this tag)."
                ),
            },
            "measure": {
                "initial":     self.measure,
                "available":   self.measure_available,
                "percent":     stock,
                "unit":        unit_label,
                "description": (
                    f"Material quantity: {self.measure_available} {unit_label} remaining "
                    f"out of {self.measure} {unit_label} initial "
                    + (f"({stock}%)." if stock is not None else "(percentage unavailable).")
                ),
            },
            "temperatures": {
                "unit": "celsius",
                "on_chip": {
                    "description": "Settings programmed by the manufacturer on the chip.",
                    "nozzle": {"min": self.nozzle_temp_min, "max": self.nozzle_temp_max},
                    "bed":    {"min": self.bed_temp_min,    "max": self.bed_temp_max},
                    "dry":    {"temp": self.dry_temp,       "time_h": self.dry_time},
                },
            },
            "manufacturing_date":  self.manufacturing_date.isoformat(),
            "twin_tag_pairing_id": self.timestamp,
            "custom_message":      self.custom_message,
            "authentication": {
                "signed":      self.is_signed,
                "uid_present": self.uid is not None,
                "description": (
                    "Tag carries an ECDSA-P256 signature. Call tag.verify() to check authenticity."
                    if self.is_signed else
                    "Tag is not signed — authenticity cannot be verified cryptographically."
                ),
            },
        }

    def describe(self, db: Optional[TigerTagDB] = None) -> str:
        """
        Return a concise natural-language description of the tag.

        Designed for injection into LLM prompts. Contains all material data
        in plain English, without protocol jargon.

        Args:
            db : Optional pre-loaded TigerTagDB. Uses bundled DB by default.

        Returns:
            A single paragraph (no newlines) describing the tag content.

        Example:
            prompt = f"Given this material: {tag.describe()}\\nWhat nozzle temp should I use?"

            # Or to seed an agent:
            agent.add_context(tag.describe())
        """
        _db  = db or self.db
        mat  = _db.material(self.id_material) or {}
        rec  = mat.get("recommended", {})

        material  = TigerTagDB.label(_db.material(self.id_material))
        type_     = TigerTagDB.label(_db.type_(self.id_type))
        diameter  = TigerTagDB.label(_db.diameter(self.id_diameter))
        brand     = TigerTagDB.label(_db.brand(self.id_brand))
        unit      = TigerTagDB.label(_db.unit(self.id_unit))
        density   = mat.get("density")
        stock     = self.stock_percent

        # Per spec: check aspect_2 first for multi-color mode (Bicolor/Tricolor/Rainbow),
        # then fall back to aspect_1. color_count drives how many colors are active.
        asp2_entry    = _db.aspect(self.id_aspect_2)
        asp1_entry    = _db.aspect(self.id_aspect_1)
        color_count   = 1
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

        # Aspect / finish — explicit dedicated line
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

        # DB-recommended temps (if available and different from chip)
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

    def pretty(
        self,
        db: Optional[TigerTagDB] = None,
        sig_result: Optional[SignatureResult] = None,
    ) -> str:
        """
        Human-readable summary of the tag contents.

        Args:
            db         : Optional TigerTagDB (uses bundled DB by default).
            sig_result : Optional pre-computed SignatureResult.

        Example:
            print(tag.pretty())
        """
        _db   = db or self.db
        mat   = _db.material(self.id_material) or {}
        rec   = mat.get("recommended", {})
        stock = self.stock_percent
        ul    = TigerTagDB.label(_db.unit(self.id_unit))
        sig   = str(sig_result) if sig_result else ("signed ✓" if self.is_signed else "not signed")

        def rec_note(kmin: str, kmax: str, suffix: str = "°C") -> str:
            return f"  (DB: {rec[kmin]}–{rec[kmax]}{suffix})" if rec.get(kmin) is not None else ""

        return (
            f"┌─ TigerTag ────────────────────────────────────────────\n"
            f"│  Version      {TigerTagDB.label(_db.version(self.id_tigertag))} (0x{self.id_tigertag:08X})\n"
            f"│  Product      {'TigerTag Maker' if self.is_maker else 'TigerTag Init' if self.is_init else f'TigerTag+ (cloud #{self.id_product})'}\n"
            f"│  UID          {self.uid_hex or '— (partial dump)'}\n"
            + (
                f"│  Product page {self.product_page_url}\n"
                f"│  API JSON     {self.api_url}\n"
                if self.product_page_url else ""
            ) +
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
