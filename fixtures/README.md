# TigerTag Test Fixtures

Pre-generated `.bin` files for testing the SDK without NFC hardware.
Regenerate at any time with:

```bash
python scripts/generate_fixtures.py
```

---

## Fixtures

| File | Size | Protocol | Scenario |
|------|------|----------|----------|
| `tigertag_pla_rosa3d.bin` | 80B | TigerTag | PLA Rosa3D Red, 1000g, full stock |
| `tigertag_petg_bambu_silk.bin` | 80B | TigerTag | PETG Silk Bambu Lab, Blue, 1000g |
| `tigertag_pla_bicolor.bin` | 80B | TigerTag | PLA Bicolor Polymaker, Orange+Black — tests `color_count=2` |
| `tigertag_resin_generic.bin` | 80B | TigerTag | Castable Resin Generic, 500ml |
| `tigertag_low_stock.bin` | 80B | TigerTag | PLA eSun Green, 150g remaining (15% of 1000g) |
| `tigertag_plus_bambu.bin` | 80B | TigerTag+ | PETG Bambu Lab, cloud product ID `0x00001234` |
| `tigertag_init.bin` | 80B | TigerTag Init | Blank/uninitialized chip — all fields zero |
| `tigertag_full_dump.bin` | 180B | TigerTag | Full chip dump — UID auto-extracted from system pages |

---

## Format

| Size | Content | UID available | Signature verifiable |
|------|---------|---------------|----------------------|
| 80B | User data only | No (pass via `from_pages`) | No |
| 144B | User data + ECDSA signature | No | No |
| 180B | Full chip dump (system pages + user data + signature + config) | Yes (auto-extracted) | Yes |

---

## Usage

```python
from tigertag import TigerTag

# Load any fixture — no hardware needed
tag = TigerTag.from_file("fixtures/tigertag_pla_rosa3d.bin")
print(tag.pretty())          # human-readable summary
print(tag.describe())        # natural language for LLM injection
print(tag.to_dict())         # full structured data

# 180-byte full dump — UID is auto-extracted
tag = TigerTag.from_file("fixtures/tigertag_full_dump.bin")
print(tag.uid_hex)           # "04AABBCCDDEEFF"
print(tag.verify())          # ⬜ NOT SIGNED (unsigned fixture)

# TigerTag+ — has a cloud product ID
tag = TigerTag.from_file("fixtures/tigertag_plus_bambu.bin")
d = tag.to_dict()
print(d["product"]["mode"])          # "cloud"
print(hex(tag.id_product))           # 0x1234

# TigerTag Init — blank chip
tag = TigerTag.from_file("fixtures/tigertag_init.bin")
print(tag.is_init)           # True

# Bicolor — two active colors
tag = TigerTag.from_file("fixtures/tigertag_pla_bicolor.bin")
d = tag.to_dict()
print(d["aspect_2"]["color_count"])  # 2
print(tag.color1_hex)                # "#FF8000" (Orange)
print(tag.color2_hex)                # "#1A1A1A" (Near-Black)

# Low stock
tag = TigerTag.from_file("fixtures/tigertag_low_stock.bin")
print(tag.stock_percent)     # 15.0
```

---

## CLI

```bash
tigertag fixtures/tigertag_pla_rosa3d.bin
tigertag fixtures/tigertag_full_dump.bin --json
tigertag fixtures/tigertag_plus_bambu.bin --json
```
