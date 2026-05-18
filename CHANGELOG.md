# Changelog

All notable changes to this project will be documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

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
