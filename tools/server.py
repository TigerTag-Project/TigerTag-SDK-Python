#!/usr/bin/env python3
"""
TigerTag playground dev server (Python SDK).

Implements the playground server contract shared with the JavaScript SDK
(docs/playground-api.md) — the same tools/playground.html runs against either.

Serves static files from the project root AND handles:
  GET  /api/version — {version, sdk, label, repo, install, style}: the page adapts its names / code
  POST /api/diff   — runs TigerTag.diff_api() server-side via the Python SDK
  POST /api/parse  — {uid?, payload} hex → pretty, describe, verify, raw_dict, dict, validate, tag_*
  POST /api/build  — TigerTag.create() keyword arguments (uid as hex, measure_available) →
                     {payload, validate, tag_*}

Reference tables (bundled copy + downloaded updates, checked once a day):
  GET  /api/db/info          — per table: source (bundled / downloaded / custom), timestamp;
                               last check, data dir, offline flag, catalogue info
  POST /api/db/update        — {force?, catalog?} → check now, download what changed
  GET  /api/db/table/<file>  — the table in use (e.g. id_material.json), for the page

TigerTag+ catalogue (bundled .gz, refreshed from GitHub once a day; kept in memory):
  GET  /api/catalog/info     — cached copy: downloaded?, count, fetched_at, checked_at, url
  POST /api/catalog/refresh  — force an update (ETag / Last-Modified: unchanged → no download)
  GET  /api/catalog/<id>     — TigerTag.from_catalog(id): entry, create() fields, payload hex,
                               pretty(), describe()

NFC readers (ACS ACR122U or any PC/SC reader), optional — needs pyscard:
  GET  /api/nfc/events — Server-Sent Events: readers:status, reader:connected,
                         reader:disconnected, card:detected (auto-read + SDK outputs),
                         card:removed, error — same messages as the JS playground
  POST /api/nfc/read   — {reqId?, reader?} → read:result per reader with a card + read:done
  POST /api/nfc/burn   — {reqId?, reader?, payload hex} → writes pages 0x04–0x27 (36 pages)
                         of every reader with a card (or only `reader`) → burn:result + burn:done.
                         Accepts 80 or 144 bytes; the signature pages 0x18–0x27 are always
                         written as 00 (playgrounds never write a signature). Pages 0–3 and 0x28+ never.
  POST /api/nfc/plan   — {payload hex} → the APDUs a burn would send (no reader touched)

  pip install "tigertag[nfc]"      # or: pip install pyscard
  Without pyscard the server still runs; the playground shows "No reader".
  TIGERTAG_PLAYGROUND_NO_NFC=1 starts it without touching the readers (tests).

Usage:
  python3 tools/server.py [port]   (default port: 7432)
"""

import json
import os
import queue
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from tigertag import TigerTag, TigerTagDB, __version__  # noqa: E402

SDK_INFO = {
    "version": __version__,
    "sdk":     "python",
    "label":   "Python SDK",
    "repo":    "https://github.com/TigerTag-Project/TigerTag-SDK-Python",
    "install": "pip install tigertag",
    "server":  "python3 tools/server.py",
    "style":   "snake",
}

from tigertag.catalog import catalog_entry, catalog_info, load_catalog, refresh_catalog, rfid_fields  # noqa: E402
from nfc_reader import NFC_INSTALL_HINT, ReaderMonitor, burn_image, burn_plan, carries_signature  # noqa: E402


# ── NFC event hub (Server-Sent Events) ────────────────────────────────────────

_clients: List["queue.Queue[Dict[str, Any]]"] = []
_clients_lock = threading.Lock()


def _broadcast(msg: Dict[str, Any]) -> None:
    with _clients_lock:
        for q in list(_clients):
            q.put(msg)
    reader = (msg.get("reader") or {}).get("name", "")
    if msg["type"] in ("reader:connected", "reader:disconnected", "card:removed"):
        print(f"[NFC] {msg['type']}: {reader}")
    elif msg["type"] == "card:detected":
        print(f"[NFC] Card on {reader} — UID: {msg.get('uid')}")
    elif msg["type"] == "error":
        print(f"[NFC] Error on {reader}: {msg.get('message')}", file=sys.stderr)


def _sdk_outputs(tag: TigerTag) -> Dict[str, Any]:
    """SDK outputs of a parsed tag (same keys as the JS server)."""
    db = _get_db()
    sig = tag.verify(db)
    return {
        "pretty":    tag.pretty(db, sig),
        "describe":  tag.describe(db),
        "verify":    sig.to_dict(),
        "raw_dict":  tag.to_raw_dict(),
        "dict":      tag.to_dict(db),
        "validate":  tag.validate(),
        "tag_info":  tag.tag_info,
        "tag_count": tag.tag_count or None,
        "tag_index": tag.tag_index or None,
    }


def _describe_tag(uid: bytes, payload: bytes) -> Dict[str, Any]:
    """SDK outputs attached to card:detected (same keys as the JS server)."""
    return _sdk_outputs(TigerTag.from_pages(uid, payload))


MONITOR = ReaderMonitor(_broadcast, _describe_tag)

# ── Reference tables (bundled + downloaded, checked once a day) ───────────────

_ref_db = None
_ref_lock = threading.Lock()


def _get_db() -> TigerTagDB:
    """The reference tables: newest of downloaded / bundled; automatic daily check."""
    global _ref_db
    with _ref_lock:
        if _ref_db is None:
            _ref_db = TigerTagDB()
        return _ref_db

# ── TigerTag+ catalogue (kept in memory after the first load) ─────────────────

_catalog = None
_catalog_lock = threading.Lock()


def _get_catalog(force: bool = False):
    global _catalog
    with _catalog_lock:
        if force:
            _catalog = refresh_catalog()
        elif _catalog is None:
            _catalog = load_catalog()
        return _catalog


def _catalog_status() -> Dict[str, Any]:
    info = catalog_info()
    info["in_memory"] = _catalog is not None
    return info


class PlaygroundHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PROJECT_ROOT), **kwargs)

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        if self.path == "/api/version":
            self._json(200, SDK_INFO)
        elif self.path == "/api/nfc/events":
            self._handle_events()
        elif self.path == "/api/db/info":
            self._json(200, _get_db().info())
        elif self.path.startswith("/api/db/table/"):
            self._handle_db_table(self.path[len("/api/db/table/"):])
        elif self.path == "/api/catalog/info":
            self._json(200, _catalog_status())
        elif self.path.startswith("/api/catalog/"):
            self._handle_catalog_product(self.path[len("/api/catalog/"):])
        else:
            super().do_GET()

    def do_POST(self) -> None:
        if self.path == "/api/diff":
            self._handle_diff()
        elif self.path == "/api/parse":
            self._handle_parse()
        elif self.path == "/api/build":
            self._handle_build()
        elif self.path == "/api/nfc/read":
            self._handle_nfc_read()
        elif self.path == "/api/nfc/burn":
            self._handle_nfc_burn()
        elif self.path == "/api/nfc/plan":
            self._handle_nfc_plan()
        elif self.path == "/api/db/update":
            self._handle_db_update()
        elif self.path == "/api/catalog/refresh":
            self._handle_catalog_refresh()
        else:
            self.send_error(404)

    def _handle_diff(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            body: dict = json.loads(self.rfile.read(length))

            uid_hex     = (body.get("uid") or "").strip()
            payload_hex = (body.get("payload") or "").strip()

            uid     = bytes.fromhex(uid_hex)     if uid_hex     else None
            payload = bytes.fromhex(payload_hex) if payload_hex else None

            if payload is None:
                raise ValueError("'payload' field is required")

            tag = TigerTag.from_pages(uid, payload)

            api_data  = None
            api_error = None
            try:
                api_data = tag.raw_api()
            except Exception as exc:
                api_error = str(exc)

            diffs = []
            if api_data:
                for d in tag.diff_api(api_data=api_data):
                    diffs.append({
                        "field":      d.field,
                        "chip_value": d.chip_value,
                        "api_value":  d.api_value,
                    })

            result = {
                "api_data": api_data,
                "diffs":    diffs,
                "in_sync":  api_data is not None and len(diffs) == 0,
                "error":    api_error,
            }
            self._json(200, result)

        except Exception as exc:
            self._json(400, {"error": str(exc)})

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def _handle_parse(self) -> None:
        try:
            body        = self._body()
            uid_hex     = (body.get("uid") or "").strip()
            payload_hex = (body.get("payload") or "").strip()
            if not payload_hex:
                raise ValueError("'payload' field is required (hex, 80 or 144 bytes)")
            payload = bytes.fromhex(payload_hex)
            # from_pages() needs the 7-byte UID; partial dumps without one go through from_dump()
            tag = (TigerTag.from_pages(bytes.fromhex(uid_hex), payload) if uid_hex
                   else TigerTag.from_dump(payload))
            self._json(200, _sdk_outputs(tag))
        except Exception as exc:
            self._json(400, {"error": str(exc)})

    def _handle_build(self) -> None:
        try:
            kwargs = self._body()
            uid_hex = (kwargs.pop("uid", None) or "").strip()
            if uid_hex:
                kwargs["uid"] = bytes.fromhex(uid_hex)
            available = kwargs.pop("measure_available", None)
            tag = TigerTag.create(**kwargs)
            if available is not None:
                tag = tag.patch(measure_available=int(available))
            self._json(200, {
                "payload":   tag.to_bytes().hex(),
                "validate":  tag.validate(),
                "tag_info":  tag.tag_info,
                "tag_count": tag.tag_count or None,
                "tag_index": tag.tag_index or None,
            })
        except Exception as exc:
            self._json(400, {"error": str(exc)})

    # ── NFC ───────────────────────────────────────────────────────────────────

    def _handle_events(self) -> None:
        q: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self._cors()
        self.end_headers()
        with _clients_lock:
            _clients.append(q)
        try:
            self._sse(MONITOR.status())
            for msg in list(MONITOR.last_cards.values()):   # chips already on the readers
                self._sse(msg)
            while True:
                try:
                    self._sse(q.get(timeout=15))
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # browser tab closed
        finally:
            with _clients_lock:
                if q in _clients:
                    _clients.remove(q)

    def _sse(self, msg: Dict[str, Any]) -> None:
        self.wfile.write(b"data: " + json.dumps(msg).encode() + b"\n\n")
        self.wfile.flush()

    def _targets(self, body: Dict[str, Any]) -> List[str]:
        wanted = body.get("reader")
        names = MONITOR.readers_with_card()
        return [n for n in names if n == wanted] if wanted else names

    def _handle_nfc_read(self) -> None:
        """read:request equivalent — returns the messages the JS server would send."""
        try:
            body = self._body()
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        req_id = body.get("reqId")
        messages: List[Dict[str, Any]] = []
        for name in self._targets(body):
            ref = {"id": name, "name": name}
            uid = MONITOR.readers.get(name, {}).get("uid")
            try:
                uid_b, payload = MONITOR.read(name)
                messages.append({"type": "read:result", "reqId": req_id, "reader": ref,
                                 "uid": uid_b.hex().upper(), "payload": payload.hex(),
                                 "bytes": len(payload), "ok": True})
            except Exception as exc:
                messages.append({"type": "read:result", "reqId": req_id, "reader": ref,
                                 "uid": uid, "ok": False, "error": str(exc)})
        messages.append({"type": "read:done", "reqId": req_id})
        self._json(200, {"messages": messages})

    def _handle_nfc_burn(self) -> None:
        """burn:write equivalent — pages 0x04–0x27, one APDU per page; signature pages always 00."""
        try:
            body = self._body()
            payload = bytes.fromhex((body.get("payload") or "").strip())
            burn_image(payload)  # 80 or 144 bytes, else ValueError
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        req_id = body.get("reqId")
        messages: List[Dict[str, Any]] = []
        for name in self._targets(body):
            ref = {"id": name, "name": name}
            uid = MONITOR.readers.get(name, {}).get("uid")
            try:
                pages = MONITOR.burn(name, payload)
                messages.append({"type": "burn:result", "reqId": req_id, "reader": ref,
                                 "uid": uid, "ok": True, "pagesWritten": pages,
                                 "signature_dropped": carries_signature(payload)})
                print(f"[NFC] Burn OK on {name} — UID: {uid} — {pages} pages written")
                MONITOR._on_card(name)   # read the chip back: card:detected with what is now on it
            except Exception as exc:
                messages.append({"type": "burn:result", "reqId": req_id, "reader": ref,
                                 "uid": uid, "ok": False, "error": str(exc)})
                print(f"[NFC] Burn error on {name}: {exc}", file=sys.stderr)
        messages.append({"type": "burn:done", "reqId": req_id})
        self._json(200, {"messages": messages})

    def _handle_nfc_plan(self) -> None:
        """Dry run of a burn: the APDU list, without touching any reader."""
        try:
            payload = bytes.fromhex((self._body().get("payload") or "").strip())
            burn_image(payload)
            plan = burn_plan(payload)
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        self._json(200, {
            "signature_dropped": carries_signature(payload),
            "pages":  len(plan),
            "apdus":  [bytes(a).hex(" ").upper() for a in plan],
        })

    # ── Reference tables ──────────────────────────────────────────────────────

    def _handle_db_table(self, name: str) -> None:
        db = _get_db()
        tables = db.info()["tables"]
        if name not in tables:
            self._json(404, {"error": f"Unknown table {name!r}. Known: {', '.join(tables)}"})
            return
        try:
            body = Path(tables[name]["path"]).read_bytes()
        except OSError as exc:
            self._json(500, {"error": str(exc)})
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-TigerTag-Source", tables[name]["source"])
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _handle_db_update(self) -> None:
        global _catalog
        try:
            body = self._body()
        except ValueError:
            body = {}
        db = _get_db()
        try:
            changed = db.update(force=bool(body.get("force")), catalog=bool(body.get("catalog")))
        except RuntimeError as exc:
            self._json(503, {"error": str(exc), "info": db.info()})
            return
        if body.get("catalog"):
            with _catalog_lock:
                _catalog = None                    # reload the refreshed copy on next use
        self._json(200, {"changed": changed, "info": db.info()})

    # ── Catalogue ─────────────────────────────────────────────────────────────

    def _handle_catalog_refresh(self) -> None:
        try:
            _get_catalog(force=True)
        except RuntimeError as exc:
            self._json(503, {"error": str(exc), "info": _catalog_status()})
            return
        self._json(200, _catalog_status())

    def _handle_catalog_product(self, raw_id: str) -> None:
        try:
            product_id = int(raw_id.split("?")[0])
        except ValueError:
            self._json(400, {"error": f"Product ID must be a number (got {raw_id!r})."})
            return
        try:
            catalog = _get_catalog()
            entry = catalog_entry(product_id, catalog)
            fields = rfid_fields(entry)
            tag = TigerTag.from_catalog(product_id, catalog=catalog)
        except KeyError as exc:
            self._json(404, {"error": exc.args[0] if exc.args else str(exc)})
            return
        except RuntimeError as exc:
            self._json(503, {"error": str(exc)})
            return
        except ValueError as exc:
            self._json(422, {"error": str(exc)})
            return
        meta = {k: entry.get(k) for k in ("id", "title", "brand", "sku", "barcode", "img_src",
                                          "material", "measure", "product_type", "color", "color_info")}
        self._json(200, {
            "entry":     meta,
            "rfid_data": entry.get("RFID_Data"),
            "fields":    fields,
            "raw_dict":  tag.to_raw_dict(),
            "payload":   tag.to_bytes().hex(),
            "pretty":   tag.pretty(),
            "describe": tag.describe(),
            "catalog":  _catalog_status(),
        })

    def _json(self, code: int, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, fmt: str, *args) -> None:  # silence request log
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 7432
    httpd = ThreadingHTTPServer(("", port), PlaygroundHandler)
    httpd.daemon_threads = True
    print(f"TigerTag playground → http://localhost:{port}/tools/playground.html")
    no_nfc = os.environ.get("TIGERTAG_PLAYGROUND_NO_NFC", "").lower() in ("1", "true", "yes")
    if MONITOR.available and not no_nfc:
        print("[NFC] pyscard loaded — listening for ACR122U / PC/SC readers…")
        MONITOR.start()
    else:
        print(f"[NFC] Not available — run: {NFC_INSTALL_HINT}")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
