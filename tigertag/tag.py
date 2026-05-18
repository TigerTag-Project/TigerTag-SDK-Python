# TigerTag RFID Guide
# Copyright (C) 2025 TigerTag
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License.

"""TigerTag dataclass — binary parsing, serialization, and verification."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from tigertag.db import TigerTagDB
from tigertag.signature import SignatureResult, _CRYPTO_AVAILABLE, verify_signature


# ── Protocol constants ─────────────────────────────────────────────────────────

CHIP_DUMP_LEN = 180   # full chip: 45 pages × 4B (pages 0-44)
FULL_DATA_LEN = 144   # user data + signature (pages 0x04-0x27)
MIN_DATA_LEN  = 80    # user data only (pages 0x04-0x17)

_TIGERTAG_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)

MAKER_PRODUCT_ID = 0xFFFFFFFF  # offline Maker tag
INIT_PRODUCT_ID  = 0x00000000  # blank / uninitialized tag


# ── TigerTag dataclass ─────────────────────────────────────────────────────────

@dataclass
class TigerTag:
    """
    Parsed TigerTag NTAG-compatible chip payload.

    All fields are plain integers/bytes/strings. Use a TigerTagDB instance
    (via the .db property or pass one to to_dict()) to resolve IDs to labels.

    Constructors:
        TigerTag.from_pages(payload, uid) — NFC SDK integration (recommended)
        TigerTag.from_dump(data)          — raw binary dump (180/144/80 bytes)
        TigerTag.from_file(path)          — convenience wrapper for .bin files

    Example:
        tag = TigerTag.from_file("dump.bin")
        print(tag.pretty())
        print(tag.verify())
        import json; print(json.dumps(tag.to_dict(), indent=2))
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

    # ── Database ───────────────────────────────────────────────────────────────

    @property
    def db(self) -> TigerTagDB:
        """Lazily loaded bundled database."""
        if self._db is None:
            self._db = TigerTagDB()
        return self._db

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
                "Provide a full 180-byte chip dump or use from_pages() with uid=.",
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
                "id":          self.id_product,
                "mode":        "maker" if self.is_maker else "init" if self.is_init else "cloud",
                "description": (
                    "TigerTag Maker — all data stored on chip, no cloud dependency."
                    if self.is_maker else
                    "TigerTag Init — blank/uninitialized chip."
                    if self.is_init else
                    f"TigerTag+ — cloud product ID {self.id_product}. "
                    "Query GET /product/get?uid=...&product_id=... for enriched data."
                ),
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

        # Aspect / color — respect color_count from aspect DB
        finish_parts = [l for l in (aspect1_label, aspect2_label) if l not in ("Unknown", "-", "None")]
        finish_str = " + ".join(finish_parts) if finish_parts else None

        color_parts = [f"primary {self.color1_hex}"]
        if color_count >= 2:
            color_parts.append(f"secondary {self.color2_hex}")
        if color_count >= 3:
            color_parts.append(f"tertiary {self.color3_hex}")

        parts.append(
            "Color: " + ", ".join(color_parts)
            + (f" ({finish_str})" if finish_str else "")
            + "."
        )

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
