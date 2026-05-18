"""
basic_parse.py — Minimal TigerTag parse example.

Uses real IDs from the official spec (section 4 — Rosa3D Red PLA example).
Works offline, no NFC hardware needed.

Run:
    python examples/basic_parse.py
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tigertag import TigerTag


def _make_rosa3d_red_pla() -> bytes:
    """
    Build the Rosa3D Red PLA payload from the official spec (section 4).

    Real values — not simulated:
      ID TigerTag : 0x5BF59264  (TigerTag)
      Material    : 0x954B = 38219  (PLA)
      Aspect 1    : 0x68 = 104  (Basic)
      Type        : 0x8E = 142  (Filament)
      Diameter    : 0x38 = 56   (1.75mm)
      Brand       : 0x4DF9 = 19961  (Rosa3D)  [spec shows 0x4E19 — typo]
      Unit        : 0x15 = 21   (grams)
      TD          : 0x00E6 = 230  (HueForge TD = 23.0)
    """
    def p16(v): return struct.pack(">H", v & 0xFFFF)
    def p24(v): v &= 0xFFFFFF; return bytes([(v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF])
    def p32(v): return struct.pack(">I", v & 0xFFFFFFFF)

    custom = "Starter Red".encode("utf-8").ljust(28, b"\x00")

    return (
        p32(0x5BF59264)   # id_tigertag  — TigerTag
        + p32(0xFFFFFFFF) # id_product   — Maker (all data on chip)
        + p16(0x954B)     # id_material  — PLA (38219)
        + bytes([0x68])   # id_aspect_1  — Basic (104)
        + bytes([0x00])   # id_aspect_2  — None
        + bytes([0x8E])   # id_type      — Filament (142)
        + bytes([0x38])   # id_diameter  — 1.75mm (56)
        + p16(0x4DF9)     # id_brand     — Rosa3D (19961)  — note: spec has typo 0x4E19
        + bytes([0xFF, 0x00, 0x00, 0xFF])  # Color 1 RGBA — Red, fully opaque
        + p24(1000)       # measure      — 1000g initial
        + bytes([0x15])   # id_unit      — grams (21)
        + p16(195)        # nozzle min   — 195°C
        + p16(230)        # nozzle max   — 230°C
        + bytes([50])     # dry_temp     — 50°C
        + bytes([5])      # dry_time     — 5 hours
        + bytes([50])     # bed_min      — 50°C
        + bytes([60])     # bed_max      — 60°C
        + p32(0x2D94CC80) # timestamp    — 764726400 s since 2000-01-01 (= 2024-03-26 UTC)
        + bytes([0, 0, 0]) # Color 2 RGB — none
        + b"\x00"
        + bytes([0, 0, 0]) # Color 3 RGB — none
        + b"\x00"
        + p16(230)        # td_raw       — HueForge TD = 23.0 (230 / 10)
        + b"\x00\x00"
        + custom
        + p24(1000)       # measure_available — full spool
        + b"\x00"
    )


def main() -> None:
    uid     = bytes.fromhex("04A1B2C3D4E5F6")  # illustrative 7-byte UID
    payload = _make_rosa3d_red_pla()

    tag = TigerTag.from_pages(payload, uid=uid)

    # Human-readable
    print(tag.pretty())
    print()

    # LLM-ready natural language description
    print("=== describe() — for LLM injection ===")
    print(tag.describe())
    print()

    # Key resolved fields
    d = tag.to_dict()
    print(f"Material : {d['material']['label']}  (density: {d['material']['density']} g/cm³)")
    print(f"Brand    : {d['brand']['label']}")
    print(f"Diameter : {d['diameter']['label']} {d['diameter']['unit']}")
    print(f"Nozzle   : {d['temperatures']['on_chip']['nozzle']['min']}–"
          f"{d['temperatures']['on_chip']['nozzle']['max']} °C")
    print(f"HueForge : TD {tag.td_value}")
    print(f"Stock    : {d['measure']['description']}")
    print(f"Signed   : {d['authentication']['signed']}")


if __name__ == "__main__":
    main()
