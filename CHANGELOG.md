# Changelog

All notable changes to this project will be documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Changed
- `catalog_info()` now takes the same options as the JS SDK's `catalogInfo()`: `data_dir`
  (alias of `cache_dir`) and `offline` (accepted for symmetry with `load_catalog()`; the
  function only reads local files, so it never uses the network).

## [1.3.0] — 2026-09-30

### Added
- **Unified playground**: `tools/playground.html` is now one page, byte-for-byte identical in the
  JavaScript and Python SDKs. Each `tools/server.*` implements the same server contract
  (`docs/playground-api.md`): `GET /api/version` (now `{ version, sdk, label, repo, install,
  server, style }` — the page takes its SDK names, links and the `create()` code style from it),
  `POST /api/parse` / `/api/build` (snake_case `create()` fields, `measure_available`) /
  `/api/diff`, `GET /api/catalog/info` / `<id>`, `POST /api/catalog/refresh`, `GET /api/db/info`,
  `POST /api/db/update`, `GET /api/db/table/<file>`, `GET /api/nfc/events` (Server-Sent Events,
  chips already present replayed on connect), `POST /api/nfc/read` / `burn` / `plan`. The page
  talks to the readers through SSE + HTTP on both servers (`TIGERTAG_PLAYGROUND_NO_NFC=1` starts the server without readers; `/api/parse` and `card:detected` now carry `pretty`, `describe`, `verify`, `raw_dict`, `dict`, `validate`; burn results and `/api/nfc/plan` report `signature_dropped`).
  `scripts/check_playground_sync.py` fails when the two copies differ (the local checkout next to
  this one, else GitHub `main`); the test suite runs it and skips it when neither is reachable.
  From the other SDK's page: Read / Burn modes with per-mode panels, the merged Offline · Catalogue / Online · API product loader, twin tag mode, SDK Input create() / HEX / Pages, the decluttered layout with info bubbles, bytes always built by the SDK on the server (`POST /api/build`).
- `to_bytes()` and `patch()` refuse a `measure_available` above `measure` (`ValueError`);
  reading such a chip still works and `validate()` still reports it. The playground's
  Generate refuses it too.
- **Tag index / tag count** (protocol v2.2, spec section 2.11). Page 0x0D byte 3
  (payload offset +39), previously reserved, is now read and written as `tag_info`:
  the high nibble is the tag index — which of the item's TigerTags this one is, from 1
  (0 = unknown) — and the low nibble is the tag count — how many TigerTags the item
  carries (0 = unknown, 1 = single tag, 2 = twin tag, up to 15). A TigerTag identifies
  any item — a filament spool, a resin bottle…; what the item is comes from `id_type`. The hex reads like
  "index/count": `0x11` single tag, `0x12` / `0x22` twin tag 1 of 2 / 2 of 2,
  `0x02` two tags with the index unknown, `0x00` unknown (tags written before v2.2).
  - `TigerTag.tag_info` field (u8) with read-only `tag_index` and `tag_count` properties.
  - `TigerTag.create(..., tag_count=0, tag_index=0)` packs both values into `tag_info`
    (`(tag_index << 4) | tag_count`); `as_init()` writes `0x00`.
  - `tag.patch(tag_count=..., tag_index=...)` as a shortcut for `tag_info` (either one
    alone keeps the other nibble). `create()` and `patch()` raise `ValueError` for a value
    outside 0–15.
  - `validate()` warns when the tag index exceeds a known tag count, or when
    `tag_info` does not fit in one byte.
  - `to_raw_dict()` gains `"tag_info"`; `to_dict()` gains `"tag_count"` and
    `"tag_index"` (`None` when unknown); `pretty()` gains a `Tag  1 of 2` line;
    `describe()` mentions the tag position when the count is known, naming the item
    from `id_type` ("Tag 1 of 2 on this filament.", "on this item" when unknown).
- Same changes in the standalone `parse_tigertag.py`.
- Playground (`tools/playground.html`): "Tag index" / "Tag count" inputs, byte +39
  written and read back (build, `.bin` import / export), a "Tag" row in the
  Traceability card and in `pretty()`, `tag_info` in `to_raw_dict()`, `tag_count` /
  `tag_index` in `to_dict()`, and a "validate() · Python SDK" card listing the SDK's
  warnings.
- Playground server (`tools/server.py`): `POST /api/parse` (payload hex → raw dict,
  tag index / count, `validate()` warnings) and `POST /api/build` (`TigerTag.create()`
  keyword arguments → payload hex), and `GET /api/version`, so the playground's header
  badge shows the installed SDK version instead of a hard-coded "v1.0".
- Playground ecosystem panel: Tiger Scale V3 photo (was the previous-generation
  scale), new TigerSpool and TigerPOD Mini cards, and repository links to
  Tiger-Scale-V3, TigerSpool-RFID and TigerPOD, plus TigerSystem-Docs and
  TigerTag-SDK-JS.
- Playground: an info bubble on "Tag index" and "Tag count" explains both values.
- Playground: "SDK Input" panel — the exact `TigerTag.create()` call, the HEX that
  Burn writes (144 bytes, pages 0x04–0x27) and the same bytes page by page.
- Playground: twin tag mode — with two or more readers holding a chip, Tag count is
  set to the number of readers, each reader gets its own payload (tag index 1…n,
  same data and Timestamp), shown as #1 / #2 in SDK Input and SDK Output, and Burn
  writes each chip with its own payload.
- Playground: "Manufacturing date" is the Timestamp of the moment you click Generate
  (read-only; it is also the twin tag ID), instead of a hand-picked date.
- Playground: NFC reader support (ACS ACR122U or any PC/SC reader), matching the JS
  playground. Header chips list connected readers ("No reader" plus the install
  command when reader support is missing); a chip placed on a reader is read
  (pages 0x04–0x27, 80-byte fallback), parsed by the SDK and loaded into the form;
  **Burn** writes the current payload to every reader with a chip after a
  confirmation (never pages 0x00–0x03 or the configuration pages 0x28+);
  **Raw Read** shows an annotated hex dump per reader. The server pushes
  events over Server-Sent Events (`GET /api/nfc/events`, same messages as the JS
  WebSocket) and takes `POST /api/nfc/read` / `POST /api/nfc/burn`. Reader access
  uses `pyscard`, an optional extra: `pip install "tigertag[nfc]"`. ACR122U APDU helpers
  live in `tools/nfc_reader.py`, with unit tests that need neither pyscard nor hardware.
- Playground: Burn never writes a signature and never leaves a stale one. It always
  writes the full 144-byte image, pages 0x04–0x27 (36 pages, `pagesWritten: 36`), with
  the signature pages 0x18–0x27 set to `00` whatever the payload — only a certified
  manufacturer can issue a valid signature (it covers the chip UID), so the playground
  only reads signatures to verify them. A signature carried by the loaded data (e.g.
  read from a signed chip) is not copied. Pages 0x00–0x03 and 0x28+ are never touched.
  The SDK Input HEX / Pages tabs and the burn confirmations show the 144-byte image;
  `POST /api/nfc/plan` returns the APDUs a burn would send (and `signatureDropped`)
  without touching a reader.
- Playground: TigerTag favicon (`assets/favicon.svg`, with `assets/apple-touch-icon.png`).

- **TigerTag+ from the official catalogue.** `TigerTag.from_catalog(product_id, *, catalog=None,
  uid=None, tag_count=0, tag_index=0, timestamp=None, db=None)` builds a complete TigerTag+ from
  the product ID alone, using the entry's `RFID_Data` (data1 diameter, data2/data3 nozzle,
  data4/data5 drying, data6/data7 bed; `null` values, incl. `id_aspect2`, → 0; colours 2/3 from
  `color_r2…`/`color_r3…` or `color_info`). New module `tigertag.catalog`: `load_catalog()`
  (downloads `id_catalog.json` from TigerTag-RFID-Guide once, about 12 MB, and caches it in the
  user cache directory; refreshed after 24 h; the cached copy is used offline),
  `refresh_catalog()` (forced update, `ETag` / `Last-Modified` so an unchanged file is not
  downloaded again), `catalog_info()` (count, fetched / checked time, source URL) and
  `catalog_entry()` (title, brand, SKU, barcode, image). The catalogue is not bundled.
  Same API in the standalone `parse_tigertag.py`.
- Playground: in the TigerTag+ tab, a Product ID field with **Load from catalogue** fills the
  whole form, shows the catalogue title, brand, SKU, barcode and photo, switches to Burn and
  builds the preview (twin tag with two readers); **Update catalogue** forces a download and
  the status line shows "Catalogue: N products · updated …" ("not downloaded yet" before the
  first load). Server: `GET /api/catalog/<id>`, `GET /api/catalog/info`,
  `POST /api/catalog/refresh`.

- **Reference data always available offline, kept fresh, refreshable, disableable.**
  The package now bundles the TigerTag+ catalogue (`database/id_catalog.json.gz`, about
  1 MB) next to the 7 reference tables; both are refreshed daily by the sync workflow and
  before every release build (`scripts/sync_bundled_data.py`). `TigerTagDB` gains
  `data_dir=`, `offline=`, `auto_update=`, `max_age=`, `update(force=False, catalog=False)`,
  `info()` and `catalog()`; per table it uses your own folder exclusively when `db_path` is
  given, else the newest of the downloaded copy (user cache directory, `TIGERTAG_DATA_DIR`)
  and the bundled copy by `last_update.json` timestamps. `load_catalog()` /
  `TigerTag.from_catalog()` share the data directory and the offline switch and fall back to
  the bundled catalogue. CLI: `tigertag update [--force] [--catalog] [--data-dir PATH]` and
  `--offline` / `--data-dir` for parsing. Playground: "Update reference tables" with a status
  line, server endpoints `GET /api/db/info`, `POST /api/db/update`, `GET /api/db/table/<file>`
  (the page loads the tables in use from the server).
- Playground: in the TigerTag+ tab, one Product ID field with two sources — **Offline ·
  Catalogue** (bundled / cached official catalogue, no internet) and **Online · API** (live
  data from api.tigertag.io, mapped onto the form by label) — and one **Load** button; the
  chosen source is remembered. Unknown IDs suggest the other source.
- Playground: decluttered — on screen only short labels, values, buttons and status words
  ("Tables · up to date", "Catalogue · 14 164 · 1 oct."); every explanation (TigerTag+ and
  Init descriptions, data-source hints, catalogue and table details, tag index / count hint,
  Read / Burn banners, HEX / Pages captions, demo-preset notes) moved into info bubbles, kept
  inside the sidebar or the viewport.
- Playground: Read mode shows only the SDK Output panel and Burn mode only the SDK Input
  panel (the other one is not rendered at all, not even its rail); switching mode opens the
  mode's panel.

### Changed
- **Behaviour change: the SDK now checks for new reference data once a day.** The first
  `TigerTagDB` of a process makes at most one small request per day (`last_update`, 5 s
  timeout, never raises) and downloads only the tables that changed. Turn it off with
  `offline=True`, `TIGERTAG_OFFLINE=1` (zero network anywhere) or `auto_update=False`.
  Updates use the standard library: `requests` is no longer needed. `sync()`,
  `sync_databases()`, `tag.sync_db()` and `tigertag --sync-only` keep working; `sync_db()`
  and `--sync-only` now update the data directory instead of the installed package. A custom
  `db_path` no longer falls back silently to the bundled copy: missing tables raise
  `FileNotFoundError`.
- No emoji anywhere in the SDK's text output or the playground. `SignatureResult`
  labels are plain words (`VALID`, `INVALID`, `NOT SIGNED`, `NO CRYPTO — …`,
  `NO PUBLIC KEY — …`, `NO UID — …`); `pretty()`, `describe()` and the CLI use words
  ("signed", "Warning:", "Error:"); the playground uses inline SVG icons (read, burn,
  raw read, import / export, generate, check / warning / error, cloud, …) and plain
  words where text cannot hold an icon (confirmation dialogs, toasts' copy, clipboard).
- Protocol version is now **TigerTag Open Source v2.2**. Fully backward compatible:
  chips written before v2.2 carry `0x00` at +39 and read as unknown. The byte is not
  covered by the ECDSA signature (UID + pages 4–5), so setting it never invalidates a
  signed chip.

### Fixed
- `raw_api()` uses certifi's CA bundle when installed (it comes with `tigertag[sync]`),
  so the TigerTag+ API no longer fails with `CERTIFICATE_VERIFY_FAILED` on the python.org
  macOS installer, which has no CA certificates until "Install Certificates.command" runs.

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
