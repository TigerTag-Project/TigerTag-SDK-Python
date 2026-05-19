# Changelog

All notable changes to this project will be documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [1.1.0] — 2026-05-19

### Added
- `TigerTag.create()` — build a new tag from scratch with all fields
- `TigerTag.as_init(uid)` — create a blank TigerTag Init chip ready for programming
- `TigerTag.erase()` — return 80 zero bytes to wipe a chip back to blank NDEF
- `tag.patch(**kwargs)` — immutable surgical field update, signature-safe (protected fields: id_tigertag, id_product, uid, signature_r/s)
- `tag.patch_from_api()` — auto-apply cloud API values to chip fields; returns patched tag + applied diffs
- `tag.diff_api()` — compare all chip fields vs TigerTag+ cloud API; covers nozzle, bed, drying, type, material, brand, diameter, aspects, colors, quantity, unit
- `tag.raw_api()` — fetch live TigerTag+ cloud product data (requires requests)
- `ApiDiff` namedtuple — (field, chip_value, api_value) — exported from main package
- `ID_TIGERTAG`, `ID_TIGERTAG_PLUS`, `ID_TIGERTAG_INIT`, `MAKER_PRODUCT_ID`, `INIT_PRODUCT_ID` — exported constants
- Playground (`tools/playground.html`) — interactive 3-column browser UI for parsing, previewing and diff-checking tags
- Dev server (`tools/server.py`) — serves playground and exposes `POST /api/diff` REST endpoint backed by the Python SDK

### Fixed
- `from_pages(144_bytes, uid=uid)` is correctly documented as verifiable — the previous README table incorrectly stated 144 bytes was "not verifiable"
- Aspect "none" vs "none" is no longer reported as a diff in `diff_api()`

## [1.0.0] — 2026-05-18

### Added
- `TigerTag.from_pages(payload, uid)` — primary constructor for NFC SDK integration
- `TigerTag.from_dump(data)` — constructor for binary dumps (180B auto-extracts UID)
- `TigerTag.from_file(path)` — convenience constructor from .bin file
- `TigerTag.verify()` — autonomous ECDSA-P256 signature verification
- `TigerTag.to_dict()` — fully resolved dict (all IDs replaced by labels + metadata)
- `TigerTag.pretty()` — human-readable summary
- `TigerTag.validate()` — field-level sanity checks
- `TigerTagDB` — loads bundled reference JSONs, auto-updates from API or GitHub
- `sync_databases()` — standalone database sync with API + GitHub fallback
- CLI: `tigertag dump.bin` and `python -m tigertag dump.bin`
- Bundled reference databases (offline use, no network required on first run)
- Compatible with NTAG213, NTAG215, NTAG216 and ISO 14443 compatible chips
- Standalone `parse_tigertag.py` for single-file copy-paste usage
- Material identification support: filament, resin (extensible to any material type)
