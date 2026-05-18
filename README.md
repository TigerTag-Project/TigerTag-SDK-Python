# TigerTag Python SDK

![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![License](https://img.shields.io/badge/license-GPLv3-green)
![Protocol](https://img.shields.io/badge/protocol-TigerTag%20v2.1-orange)

**Offline Python SDK for TigerTag RFID material identification.**

> TigerTag is an open-source RFID protocol for identifying manufacturing materials.
> Currently: filament, resin. Designed to extend to any physical material
> (sheet goods, wood, PMMA, metals, composites…).
> All material data is stored directly on the NTAG chip — 100% offline.

---

## Scope

| TigerTag type    | This SDK (Offline)       | Future Online SDK        |
|------------------|--------------------------|--------------------------|
| TigerTag (Maker) | ✅ full support           | ✅ full support           |
| TigerTag Init    | ✅ full support           | ✅ full support           |
| TigerTag+        | ✅ full support (offline) | ✅ chip + cloud (API)     |

TigerTag+ tags carry a cloud product ID alongside all standard material data.
This SDK reads all chip data identically — no functional difference in offline mode.

---

## Install

```bash
pip install tigertag                    # core only (stdlib, works offline)
pip install tigertag[sync]              # + requests  (database updates)
pip install tigertag[verify]            # + cryptography (ECDSA verification)
pip install tigertag[full]              # everything
```

---

## Quick start

```python
from tigertag import TigerTag

tag = TigerTag.from_pages(payload, uid=uid)   # from NFC SDK
print(tag.pretty())                            # human-readable summary
print(tag.verify())                            # ECDSA result
print(tag.to_dict())                           # dict for JSON / API
```

That's it. No configuration. No network. Works immediately after `pip install`.

---

## API reference

### Constructors

| Method | Input | Use when |
|--------|-------|----------|
| `TigerTag.from_pages(payload, uid)` | 80 or 144 bytes + 7-byte UID | NFC SDK integration (**recommended**) |
| `TigerTag.from_dump(data)` | 80 / 144 / 180 bytes | Binary dumps, ACR122U raw read |
| `TigerTag.from_file(path)` | path to `.bin` file | Testing, offline processing |

**`from_pages`** is the primary constructor for production use. Pass the raw bytes
from your NFC SDK — the UID separately (exactly as the SDK provides it) enables
full signature verification.

**`from_dump` with 180 bytes** automatically extracts the 7-byte UID from system pages.

### Key methods

```python
tag.pretty(db=None, sig_result=None) -> str      # human-readable
tag.to_dict(db=None)                 -> dict     # JSON-serializable
tag.to_bytes(include_signature=False)-> bytes    # re-serialize
tag.validate()                       -> list[str]# sanity check warnings
tag.verify(db=None)                  -> SignatureResult
tag.sync_db(db_path=None, force=False)-> list[str]  # update databases
```

### Key properties

```python
tag.is_maker          # True if id_product == 0xFFFFFFFF
tag.is_init           # True if id_product == 0x00000000
tag.is_signed         # True if signature pages are non-zero
tag.uid_hex           # "04AABBCCDDEE11" or None
tag.color1_hex        # "#FF3232"
tag.td_value          # 12.5  (HueForge Transmission Distance)
tag.manufacturing_date# datetime (UTC)
tag.stock_percent     # 75.0  or None
```

### SignatureResult

```python
result = tag.verify()
result.ok      # True only for VALID
result.status  # "valid" | "invalid" | "unsigned" | "no_crypto" | "no_key" | "no_uid"
str(result)    # "✅ VALID" | "❌ INVALID" | "⬜ NOT SIGNED" | …
result.to_dict()  # {"status": ..., "ok": ..., "detail": ...}
```

### TigerTagDB

```python
from tigertag import TigerTagDB

db = TigerTagDB()                          # uses bundled database (offline)
db = TigerTagDB(auto_sync=True)            # checks for updates on init
db = TigerTagDB("/path/to/db")             # custom database path

db.material(38219)    # {"id": 38219, "label": "PLA", "density": 1.24, ...}
db.brand(1)           # {"id": 1, "label": "Generic", ...}
db.version(0x01000001)# {"id": ..., "label": ..., "public_key": "-----BEGIN..."}
TigerTagDB.label(entry) -> str             # safe label extraction
```

---

## NFC SDK integration

`from_pages()` accepts exactly what NFC SDKs provide:

```python
# Android (NfcA / MifareUltralight)
uid     = tag.id                          # ByteArray → bytes
payload = mifare.readPages(4, 39)         # 144 bytes

# iOS (CoreNFC)
uid     = tag.identifier                  # Data → bytes
payload = tag.readNDEF(...)               # pages 4-39

# Flutter (flutter_nfc_kit)
uid     = bytes.fromhex(tag.id)
payload = await FlutterNfcKit.readBlock(4, length=144)

# Python nfcpy / ACR122U
uid     = tag.identifier                  # bytes
payload = tag.read(4, 36)                 # 36 pages × 4 bytes

tag = TigerTag.from_pages(payload, uid=uid)
result = tag.verify()  # fully autonomous
```

### ACR122U — exemple complet (nfcpy)

```bash
pip install nfcpy tigertag[verify]
```

```python
import nfc
from tigertag import TigerTag

def on_connect(tag):
    uid     = tag.identifier   # 7 bytes — fourni directement par nfcpy
    payload = tag.read(4, 36)  # 36 pages × 4 bytes = 144 bytes (pages 0x04–0x27)

    tt = TigerTag.from_pages(payload, uid=uid)

    print(tt.pretty())         # résumé lisible
    print(tt.verify())         # ✅ VALID / ⬜ NOT SIGNED / ❌ INVALID
    return True

with nfc.ContactlessFrontend("usb") as clf:
    print("En attente d'un tag TigerTag…")
    clf.connect(rdwr={"on-connect": on_connect})
```

> **Note :** nfcpy nécessite d'avoir accès au périphérique USB. Sur Linux, ajouter l'utilisateur au groupe `plugdev` ou lancer en root. Sur macOS/Windows, les drivers ACR122U doivent être installés.

See [`examples/integrate_nfc_sdk.py`](examples/integrate_nfc_sdk.py) for all platforms.

---

## Accepted dump formats

| Size | Content | UID | Signature |
|------|---------|-----|-----------|
| 180 bytes | Full chip dump (pages 0-44) | Auto-extracted | Verifiable |
| 144 bytes | User data + signature (pages 0x04-0x27) | Not available | Not verifiable |
| 80 bytes | User data only (pages 0x04-0x17) | Not available | N/A |

---

## Auto-update behavior

The SDK ships with bundled reference databases — it works fully offline after
`pip install tigertag`. Updates are opt-in:

1. **Bundled** (default) — always usable, never empty, no network required
2. **`TigerTagDB(auto_sync=True)`** — checks timestamps on init, downloads only changed files
3. **`tag.sync_db(force=True)`** — forces full re-download
4. **Network failure** — caught silently, bundled databases are used as fallback
5. **`tigertag --sync-only`** — CLI sync, updates bundled database in place

Sources: TigerTag API → GitHub mirror (automatic fallback).

---

## CLI

```bash
tigertag dump.bin              # parse + human-readable output
tigertag dump.bin --json       # output as JSON
tigertag dump.bin --raw        # raw dataclass, no DB lookup
tigertag --sync-only           # update databases and exit
tigertag --version             # show SDK version
python -m tigertag dump.bin    # same, via module runner
```

---

## Standalone single-file usage

For projects where you can't add a dependency, copy `parse_tigertag.py`
directly into your project:

```python
from parse_tigertag import TigerTag

tag = TigerTag.from_dump(open("dump.bin", "rb").read())
tag.sync_db()        # auto-download databases (requires requests)
print(tag.pretty())
```

The standalone file is a copy of the full package logic and works independently
without the `tigertag/` package.

---

## Binary layout (NTAG chip pages 0x04–0x27)

```
Page    Offset  Size  Field
──────  ──────  ────  ──────────────────────
0x04    +0      4B    ID TigerTag   (u32 BE)
0x05    +4      4B    ID Product    (u32 BE)
0x06    +8      2B    ID Material   (u16 BE)
0x06    +10     1B    ID Aspect 1   (u8)
0x06    +11     1B    ID Aspect 2   (u8)
0x07    +12     1B    ID Type       (u8)
0x07    +13     1B    ID Diameter   (u8)
0x07    +14     2B    ID Brand      (u16 BE)
0x08    +16     4B    Color 1 RGBA  (bytes)
0x09    +20     3B    Measure       (u24 BE)
0x09    +23     1B    ID Unit       (u8)
0x0A    +24     2B    Nozzle Min    (u16 BE, °C)
0x0A    +26     2B    Nozzle Max    (u16 BE, °C)
0x0B    +28     1B    Dry Temp      (u8, °C)
0x0B    +29     1B    Dry Time      (u8, hours)
0x0B    +30     1B    Bed Min       (u8, °C)
0x0B    +31     1B    Bed Max       (u8, °C)
0x0C    +32     4B    Timestamp     (u32 BE, sec since 2000-01-01)
0x0D    +36     3B    Color 2 RGB   (bytes)
0x0E    +40     3B    Color 3 RGB   (bytes)
0x0F    +44     2B    HueForge TD   (u16 BE, value/10)
0x10    +48     28B   Custom msg    (UTF-8)
0x17    +76     3B    Avail. qty    (u24 BE)
0x18    +80     32B   Sig R         (ECDSA, optional)
0x20    +112    32B   Sig S         (ECDSA, optional)
```

---

## TigerTag ecosystem

Official tools built on the same protocol:

| Tool | Platform | Description |
|------|----------|-------------|
| [TigerTag Studio Manager](https://github.com/TigerTag-Project/TigerTag-Studio-Manager) | Windows / macOS / Linux | Desktop inventory manager, ACR122U integration |
| [Tiger Scale](https://github.com/TigerTag-Project/Tiger_Scale) | ESP32 DIY | Smart scale — reads tag, weighs spool, updates `measure_available` in real time |
| [TigerTag RFID Connect (iOS)](https://apps.apple.com/fr/app/tigertag-rfid-connect/id6745437963) | iOS | Official mobile app |
| [TigerTag RFID Connect (Android)](https://play.google.com/store/apps/details?id=com.tigertag.connect) | Android | Official mobile app |

Community integrations: [OpenRFID](https://github.com/suchmememanyskill/OpenRFID), [Home Assistant](https://github.com/Kenny3231/TigerTag), [Snapmaker U1 firmware](https://github.com/paxx12-snapmaker-u1/SnapmakerU1-Extended-Firmware).

---

## License

**Open source:** GNU General Public License v3.0 — see [LICENSE.md](LICENSE.md)

**Commercial OEM licensing:** contact licensing@tigertag.io

Protocol spec: [github.com/TigerTag-Project/TigerTag-RFID-Guide](https://github.com/TigerTag-Project/TigerTag-RFID-Guide)
