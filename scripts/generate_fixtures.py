"""
generate_fixtures.py — Generate TigerTag test fixture .bin files.

Produces one .bin file per test scenario in fixtures/.
Each file can be loaded with TigerTag.from_dump() or TigerTag.from_file()
without any NFC hardware.

Run:
    python scripts/generate_fixtures.py

Fixtures generated:
    tigertag_pla_rosa3d.bin         80B   TigerTag  — PLA Rosa3D Red, full stock
    tigertag_petg_bambu_silk.bin    80B   TigerTag  — PETG Silk Bambu Lab, Blue
    tigertag_pla_bicolor.bin        80B   TigerTag  — PLA Bicolor Polymaker, Orange+Black
    tigertag_resin_generic.bin      80B   TigerTag  — Castable Resin Generic, 500ml
    tigertag_low_stock.bin          80B   TigerTag  — PLA eSun, 15% remaining
    tigertag_plus_bambu.bin         80B   TigerTag+ — PETG Bambu Lab, cloud product ID
    tigertag_init.bin               80B   TigerTag Init — blank/uninitialized chip
    tigertag_full_dump.bin         180B   TigerTag  — full chip dump, UID auto-extractable
"""

import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tigertag import TigerTag, TigerTagDB

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"

# ── TigerTag epoch ─────────────────────────────────────────────────────────────

_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)


def ts(year: int, month: int, day: int) -> int:
    """Seconds since TigerTag epoch (2000-01-01 UTC) for a given date."""
    return int((datetime(year, month, day, tzinfo=timezone.utc) - _EPOCH).total_seconds())


# ── Binary packing helpers ─────────────────────────────────────────────────────

def u8(v: int)  -> bytes: return bytes([v & 0xFF])
def u16(v: int) -> bytes: return struct.pack(">H", v & 0xFFFF)
def u24(v: int) -> bytes: v &= 0xFFFFFF; return bytes([(v>>16)&0xFF, (v>>8)&0xFF, v&0xFF])
def u32(v: int) -> bytes: return struct.pack(">I", v & 0xFFFFFFFF)
def msg(s: str) -> bytes: return s.encode("utf-8").ljust(28, b"\x00")[:28]


# ── Protocol constants (from TigerTag spec v2.1) ───────────────────────────────

ID_TIGERTAG      = 0x5BF59264
ID_TIGERTAG_PLUS = 0xBC0FCB97
ID_TIGERTAG_INIT = 0x6C41A2E1

MAKER = 0xFFFFFFFF
INIT  = 0x00000000

# Material IDs (from bundled id_material.json)
MAT_PLA    = 0x954B   # 38219 — PLA
MAT_PETG   = 0x9570   # 38256 — PETG
MAT_RESIN  = 0x20CA   # 8394  — Castable Resin
MAT_ABS    = 0x5052   # 20562 — ABS
MAT_TPU    = 0xA9FE   # 43518 — TPU

# Brand IDs (from bundled id_brand.json)
BRAND_ROSA3D    = 0x4DF9   # 19961
BRAND_BAMBU_LAB = 0x8933   # 35123
BRAND_POLYMAKER = 0xC5AC   # 50604
BRAND_ESUN      = 0xBB3A   # 47930
BRAND_PRUSAMENT = 0xB538   # 46392
BRAND_GENERIC   = 0xFFFF   # 65535

# Type IDs
TYPE_FILAMENT = 0x8E   # 142
TYPE_RESIN    = 0xAD   # 173

# Diameter IDs
DIA_175  = 0x38   # 1.75mm
DIA_285  = 0xDD   # 2.85mm
DIA_NONE = 0x00   # N/A (resin)

# Unit IDs
UNIT_G  = 0x15   # grams
UNIT_KG = 0x23   # kilograms
UNIT_ML = 0x30   # millilitres
UNIT_L  = 0x4F   # litres

# Aspect IDs (from bundled id_aspect.json)
ASP_NONE    = 0x00
ASP_BASIC   = 0x68   # 104  color_count=1
ASP_SILK    = 0x5C   # 92   color_count=1
ASP_MATT    = 0xF7   # 247  color_count=1
ASP_WOOD    = 0x7B   # 123  color_count=1
ASP_GLITTER = 0x40   # 64   color_count=1
ASP_BICOLOR = 0xFC   # 252  color_count=2
ASP_TRICOLOR = 0x18  # 24   color_count=3
ASP_RAINBOW  = 0x91  # 145  color_count=3


# ── Payload builder ────────────────────────────────────────────────────────────

def build(
    id_tigertag: int,
    id_product: int,
    id_material: int,
    id_aspect_1: int,
    id_aspect_2: int,
    id_type: int,
    id_diameter: int,
    id_brand: int,
    color1: tuple,          # (R, G, B, A)
    measure: int,
    id_unit: int,
    nozzle_min: int,
    nozzle_max: int,
    dry_temp: int,
    dry_time: int,
    bed_min: int,
    bed_max: int,
    timestamp: int,
    color2: tuple = (0, 0, 0),
    color3: tuple = (0, 0, 0),
    td_raw: int = 0,
    custom: str = "",
    measure_available: int = None,
) -> bytes:
    if measure_available is None:
        measure_available = measure
    return (
        u32(id_tigertag)
        + u32(id_product)
        + u16(id_material)
        + u8(id_aspect_1)
        + u8(id_aspect_2)
        + u8(id_type)
        + u8(id_diameter)
        + u16(id_brand)
        + bytes([color1[0], color1[1], color1[2], color1[3]])
        + u24(measure)
        + u8(id_unit)
        + u16(nozzle_min)
        + u16(nozzle_max)
        + u8(dry_temp)
        + u8(dry_time)
        + u8(bed_min)
        + u8(bed_max)
        + u32(timestamp)
        + bytes([color2[0], color2[1], color2[2], 0x00])
        + bytes([color3[0], color3[1], color3[2], 0x00])
        + u16(td_raw)
        + b"\x00\x00"
        + msg(custom)
        + u24(measure_available)
        + b"\x00"
    )


def wrap_full_dump(payload_80: bytes, uid_hex: str) -> bytes:
    """Wrap an 80-byte payload into a 180-byte full chip dump.

    Layout: 16B system pages + 80B user data + 64B signature (zeros) + 20B config
    The UID is embedded in the system pages so from_dump() can extract it.
    """
    uid = bytes.fromhex(uid_hex)
    system = uid[0:3] + b"\xBB" + uid[3:7] + bytes(8)   # pages 0-3 (16 bytes)
    signature = bytes(64)                                 # unsigned — all zeros
    cfg = bytes(20)                                       # config pages
    return system + payload_80 + signature + cfg          # 16 + 80 + 64 + 20 = 180


# ── Fixture definitions ────────────────────────────────────────────────────────

FIXTURES = [
    {
        "filename": "tigertag_pla_rosa3d.bin",
        "description": "TigerTag — PLA Rosa3D Red, 1000g, full stock, unsigned",
        "uid": "04A1B2C3D4E5F6",
        "payload": build(
            ID_TIGERTAG, MAKER,
            MAT_PLA, ASP_BASIC, ASP_NONE,
            TYPE_FILAMENT, DIA_175,
            BRAND_ROSA3D,
            (0xFF, 0x00, 0x00, 0xFF),
            measure=1000, id_unit=UNIT_G,
            nozzle_min=195, nozzle_max=230,
            dry_temp=50, dry_time=5,
            bed_min=50, bed_max=60,
            timestamp=ts(2024, 3, 26),
            td_raw=230,
            custom="Starter Red",
        ),
    },
    {
        "filename": "tigertag_petg_bambu_silk.bin",
        "description": "TigerTag — PETG Silk Bambu Lab, Blue, 1000g",
        "uid": "04B2C3D4E5F607",
        "payload": build(
            ID_TIGERTAG, MAKER,
            MAT_PETG, ASP_SILK, ASP_NONE,
            TYPE_FILAMENT, DIA_175,
            BRAND_BAMBU_LAB,
            (0x1A, 0x6B, 0xFF, 0xFF),
            measure=1000, id_unit=UNIT_G,
            nozzle_min=220, nozzle_max=250,
            dry_temp=65, dry_time=8,
            bed_min=70, bed_max=85,
            timestamp=ts(2024, 6, 12),
            td_raw=0,
            custom="Bambu PETG-S Blue",
        ),
    },
    {
        "filename": "tigertag_pla_bicolor.bin",
        "description": "TigerTag — PLA Bicolor Polymaker, Orange+Black (2 colors)",
        "uid": "04C3D4E5F60718",
        "payload": build(
            ID_TIGERTAG, MAKER,
            MAT_PLA, ASP_BASIC, ASP_BICOLOR,   # asp2=Bicolor → color_count=2
            TYPE_FILAMENT, DIA_175,
            BRAND_POLYMAKER,
            (0xFF, 0x80, 0x00, 0xFF),           # color1 = Orange
            measure=1000, id_unit=UNIT_G,
            nozzle_min=190, nozzle_max=220,
            dry_temp=45, dry_time=6,
            bed_min=25, bed_max=60,
            timestamp=ts(2024, 9, 1),
            color2=(0x1A, 0x1A, 0x1A),          # color2 = Near-Black
            td_raw=195,
            custom="PolyTwin Orange-Black",
        ),
    },
    {
        "filename": "tigertag_resin_generic.bin",
        "description": "TigerTag — Castable Resin Generic, 500ml",
        "uid": "04D4E5F6071829",
        "payload": build(
            ID_TIGERTAG, MAKER,
            MAT_RESIN, ASP_NONE, ASP_NONE,
            TYPE_RESIN, DIA_NONE,
            BRAND_GENERIC,
            (0xCC, 0xCC, 0xFF, 0xCC),           # translucent lilac
            measure=500, id_unit=UNIT_ML,
            nozzle_min=0, nozzle_max=0,
            dry_temp=0, dry_time=0,
            bed_min=25, bed_max=35,
            timestamp=ts(2024, 1, 15),
            td_raw=0,
            custom="Castable Resin 500ml",
        ),
    },
    {
        "filename": "tigertag_low_stock.bin",
        "description": "TigerTag — PLA eSun Green, 150g remaining (15% of 1000g)",
        "uid": "04E5F60718293A",
        "payload": build(
            ID_TIGERTAG, MAKER,
            MAT_PLA, ASP_MATT, ASP_NONE,
            TYPE_FILAMENT, DIA_175,
            BRAND_ESUN,
            (0x22, 0xAA, 0x44, 0xFF),
            measure=1000, id_unit=UNIT_G,
            nozzle_min=200, nozzle_max=230,
            dry_temp=50, dry_time=4,
            bed_min=50, bed_max=60,
            timestamp=ts(2023, 11, 20),
            td_raw=165,
            custom="eSun PLA+ Green",
            measure_available=150,              # 15% left
        ),
    },
    {
        "filename": "tigertag_plus_bambu.bin",
        "description": "TigerTag+ — PETG Bambu Lab, cloud product ID 0x00001234",
        "uid": "04F60718293A4B",
        "payload": build(
            ID_TIGERTAG_PLUS, 0x00001234,       # TigerTag+ with cloud product ID
            MAT_PETG, ASP_BASIC, ASP_NONE,
            TYPE_FILAMENT, DIA_175,
            BRAND_BAMBU_LAB,
            (0xFF, 0xFF, 0xFF, 0xFF),
            measure=1000, id_unit=UNIT_G,
            nozzle_min=230, nozzle_max=260,
            dry_temp=65, dry_time=8,
            bed_min=70, bed_max=90,
            timestamp=ts(2024, 10, 5),
            td_raw=0,
            custom="Bambu PETG HF White",
        ),
    },
    {
        "filename": "tigertag_init.bin",
        "description": "TigerTag Init — blank/uninitialized chip (all fields zero)",
        "uid": "04071829" + "3A4B5C",
        "payload": build(
            ID_TIGERTAG_INIT, INIT,
            0x0000, ASP_NONE, ASP_NONE,
            0x00, 0x00,
            0x0000,
            (0x00, 0x00, 0x00, 0x00),
            measure=0, id_unit=UNIT_G,
            nozzle_min=0, nozzle_max=0,
            dry_temp=0, dry_time=0,
            bed_min=0, bed_max=0,
            timestamp=0,
        ),
    },
    {
        "filename": "tigertag_full_dump.bin",
        "description": "TigerTag — PLA Prusament Galaxy Black, 180B full dump (UID embedded)",
        "uid": "04AA" + "BBCCDDEEFF",
        "size": 180,
        "payload": None,                        # built below (needs wrap_full_dump)
    },
]

# Build the full dump separately
_full_dump_payload = build(
    ID_TIGERTAG, MAKER,
    MAT_PLA, ASP_GLITTER, ASP_NONE,
    TYPE_FILAMENT, DIA_175,
    BRAND_PRUSAMENT,
    (0x18, 0x18, 0x28, 0xFF),                  # dark galaxy blue-black
    measure=1000, id_unit=UNIT_G,
    nozzle_min=210, nozzle_max=230,
    dry_temp=50, dry_time=4,
    bed_min=60, bed_max=70,
    timestamp=ts(2024, 7, 4),
    td_raw=110,
    custom="Galaxy Black",
)
FIXTURES[-1]["payload"] = wrap_full_dump(_full_dump_payload, FIXTURES[-1]["uid"].replace(" ", ""))


# ── Generate ───────────────────────────────────────────────────────────────────

def main() -> None:
    FIXTURES_DIR.mkdir(exist_ok=True)
    db = TigerTagDB()

    print(f"Generating {len(FIXTURES)} fixture(s) → {FIXTURES_DIR}/\n")

    for spec in FIXTURES:
        path = FIXTURES_DIR / spec["filename"]
        payload = spec["payload"]
        uid_hex = spec["uid"].replace(" ", "")
        size = len(payload)

        path.write_bytes(payload)

        # Parse back to verify
        try:
            if size == 180:
                tag = TigerTag.from_dump(payload, db=db)
            else:
                tag = TigerTag.from_pages(bytes.fromhex(uid_hex), payload, db=db)
            sig = tag.verify()
            d   = tag.to_dict(db=db)
            material = d["material"]["label"]
            brand    = TigerTagDB.label(db.brand(tag.id_brand))
            status   = str(sig)
            ok       = "✓"
        except Exception as exc:
            material = brand = "—"
            status = f"ERROR: {exc}"
            ok = "✗"

        print(f"  {ok}  {spec['filename']:<35}  {size:3}B  {material:<16} {brand:<14}  {status}")
        if ok == "✗":
            sys.exit(1)

    print(f"\nDone. Load any fixture with:")
    print(f"  from tigertag import TigerTag")
    print(f"  tag = TigerTag.from_file('fixtures/tigertag_pla_rosa3d.bin')")
    print(f"  print(tag.pretty())")


if __name__ == "__main__":
    main()
