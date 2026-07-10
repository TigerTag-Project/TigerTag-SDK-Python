# Changelog

All notable changes to this project will be documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [1.2.1] — 2026-07-10

### Fixed
- `1.2.0` required `setuptools>=77` at build time in order to use PEP 639 license
  fields. setuptools 77 requires Python >= 3.9, so installing from source (`pip install .`,
  `pip install git+...`, `--no-binary`) failed on Python 3.8, which this package still
  supports. Installing the published wheel was unaffected.
- The licence is now declared as `license = {text = "Apache-2.0"}` with the matching
  trove classifier, which produces `License: Apache-2.0` in the metadata and builds on
  every supported Python.

No functional change. The licence is Apache-2.0, as in 1.2.0.

## [1.2.0] — 2026-07-10

### Changed
- **License changed from GPLv3 to Apache-2.0.** The TigerTag protocol
  specification is now published as an open standard: CC-BY-4.0 for the
  specification, CC0-1.0 for the reference database, Apache-2.0 for code, with an
  irrevocable, worldwide, royalty-free right to implement it in any product, open
  source or proprietary. Apache-2.0 carries an express patent grant.
  See <https://github.com/TigerTag-Project/TigerTag-RFID-Guide/blob/main/LICENSING.md>.
- Package metadata now declares `License-Expression: Apache-2.0` (PEP 639) instead
  of embedding the full licence text into the `License` field.

### Fixed
- `__version__` was stuck at `1.1.0` while the distribution was published as
  `1.1.1`. Both now agree.

> Versions published to PyPI up to and including `1.1.1` remain under GPLv3.
> This change applies from `1.2.0` onward.

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
- `from_pages(uid, 144_bytes)` is correctly documented as verifiable — the previous README table incorrectly stated 144 bytes was "not verifiable"
- Aspect "none" vs "none" is no longer reported as a diff in `diff_api()`

## [1.0.0] — 2026-05-18

### Added
- `TigerTag.from_pages(uid, payload)` — primary constructor for NFC SDK integration
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
