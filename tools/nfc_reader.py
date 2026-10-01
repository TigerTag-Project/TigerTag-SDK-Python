# SPDX-License-Identifier: Apache-2.0
#
# TigerTag SDK
# Copyright (c) 2025-2026 TigerTag Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
ACR122U / PC/SC reader support for the TigerTag playground server.

Two layers:

* Pure helpers (no dependency, unit-tested): APDU builders for NTAG21x through the
  ACR122U pseudo-APDUs, response checking, page chunking, and ``read_payload`` /
  ``write_payload`` / ``read_uid`` that drive any ``transmit(apdu) -> (data, sw1, sw2)``
  callable.
* :class:`ReaderMonitor` — a background thread built on ``pyscard`` (optional,
  ``pip install "tigertag[nfc]"``) that watches readers and cards and emits the same
  events as the JS playground server (``reader:connected``, ``card:detected``…).

Memory safety: the builders only address pages 0x04–0x27 (user data + signature),
never the UID / lock / capability pages 0x00–0x03 nor the configuration pages 0x28+.

A burn never writes a signature: ``write_payload`` always writes the full 144-byte
image, pages 0x04–0x27, with the signature pages 0x18–0x27 set to ``00`` whatever the
payload. Only a certified manufacturer can issue a valid signature (it covers the chip
UID, so a signature copied from another chip is invalid anyway); the playground only
reads signatures to verify them. Zeroing also erases any stale signature.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

# ── Protocol constants ─────────────────────────────────────────────────────────

FIRST_PAGE      = 0x04   # first TigerTag page (user memory)
LAST_PAGE       = 0x27   # last signature page
LAST_DATA_PAGE  = 0x17   # last data page (measure_available)
FIRST_SIG_PAGE  = 0x18   # first signature page
PAGE_SIZE       = 4
READ_CHUNK      = 16     # the ACR122U READ BINARY returns 4 pages at once
FULL_READ_LEN   = 144    # pages 0x04–0x27 (data + signature)
DATA_LEN        = 80     # pages 0x04–0x17 (data only)
UID_LEN         = 7

NFC_INSTALL_HINT = 'pip install "tigertag[nfc]"  (or: pip install pyscard)'

Transmit = Callable[[List[int]], Tuple[Sequence[int], int, int]]


class ApduError(Exception):
    """An APDU returned a status word other than 90 00."""

    def __init__(self, apdu: Sequence[int], sw1: int, sw2: int) -> None:
        self.sw1, self.sw2 = sw1, sw2
        super().__init__(
            f"APDU {bytes(apdu[:5]).hex(' ').upper()} failed: SW={sw1:02X} {sw2:02X}"
            + (" (tag not in field, or page out of range for this chip)" if (sw1, sw2) == (0x63, 0x00) else "")
        )


# ── Pure helpers ───────────────────────────────────────────────────────────────

def _check_page(page: int) -> None:
    if not isinstance(page, int) or not FIRST_PAGE <= page <= LAST_PAGE:
        raise ValueError(
            f"Page {page!r} is outside the TigerTag area 0x04–0x27. "
            "Pages 0x00–0x03 (UID, lock bytes, capability container) and 0x28+ "
            "(chip configuration) are never addressed."
        )


def apdu_get_uid() -> List[int]:
    """GET DATA (UID): ``FF CA 00 00 00``."""
    return [0xFF, 0xCA, 0x00, 0x00, 0x00]


def apdu_read(page: int) -> List[int]:
    """READ BINARY of 16 bytes (4 pages) from ``page``: ``FF B0 00 <page> 10``."""
    _check_page(page)
    return [0xFF, 0xB0, 0x00, page, READ_CHUNK]


def apdu_write(page: int, data: bytes) -> List[int]:
    """UPDATE BINARY of one 4-byte page: ``FF D6 00 <page> 04 <4 bytes>``."""
    _check_page(page)
    data = bytes(data)
    if len(data) != PAGE_SIZE:
        raise ValueError(f"A page write takes exactly 4 bytes (got {len(data)}).")
    return [0xFF, 0xD6, 0x00, page, PAGE_SIZE, *data]


def check_response(apdu: Sequence[int], data: Sequence[int], sw1: int, sw2: int) -> bytes:
    """Return the response data with the 90 00 status stripped, or raise :class:`ApduError`."""
    if (sw1, sw2) != (0x90, 0x00):
        raise ApduError(apdu, sw1, sw2)
    return bytes(data)


def burn_image(payload: bytes) -> bytes:
    """
    Return the 144-byte image a burn writes to pages 0x04–0x27.

    Bytes 0–79 (pages 0x04–0x17) are kept; bytes 80–143 (signature pages 0x18–0x27)
    are always zero, even when a 144-byte payload carries a signature (e.g. read back
    from a signed chip) — see :func:`carries_signature`.

    Raises:
        ValueError: If the payload is neither 80 nor 144 bytes.
    """
    payload = bytes(payload)
    if len(payload) not in (DATA_LEN, FULL_READ_LEN):
        raise ValueError(
            f"Burn payload must be {DATA_LEN} bytes (data) or {FULL_READ_LEN} bytes "
            f"(data + signature, which is dropped), got {len(payload)}."
        )
    return payload[:DATA_LEN] + bytes(FULL_READ_LEN - DATA_LEN)


def carries_signature(payload: bytes) -> bool:
    """True when a 144-byte payload has a non-zero signature — which a burn drops."""
    return any(bytes(payload)[DATA_LEN:FULL_READ_LEN])


def page_chunks(payload: bytes, first_page: int = FIRST_PAGE) -> List[Tuple[int, bytes]]:
    """
    Split a burn payload into ``(page, 4 bytes)`` pairs for pages 0x04–0x27 (36 pages).

    See :func:`burn_image`: pages 0x18–0x27 are always zero, so no signature is ever
    written and a stale one from a previous tag is always erased.
    """
    image = burn_image(payload)
    chunks = [(first_page + i // PAGE_SIZE, image[i:i + PAGE_SIZE]) for i in range(0, FULL_READ_LEN, PAGE_SIZE)]
    assert chunks[-1][0] == LAST_PAGE
    return chunks


def burn_plan(payload: bytes) -> List[List[int]]:
    """The exact APDU sequence a burn sends: one UPDATE BINARY per page, 0x04–0x27."""
    return [apdu_write(page, data) for page, data in page_chunks(payload)]


def read_uid(transmit: Transmit) -> bytes:
    """Read the chip UID (7 bytes for NTAG21x)."""
    apdu = apdu_get_uid()
    return check_response(apdu, *transmit(apdu))


def read_pages(transmit: Transmit, length: int, first_page: int = FIRST_PAGE) -> bytes:
    """Read ``length`` bytes (a multiple of 16) starting at ``first_page``."""
    if length % READ_CHUNK:
        raise ValueError(f"length must be a multiple of {READ_CHUNK} (got {length}).")
    out = bytearray()
    for page in range(first_page, first_page + length // PAGE_SIZE, READ_CHUNK // PAGE_SIZE):
        apdu = apdu_read(page)
        chunk = check_response(apdu, *transmit(apdu))
        if len(chunk) < READ_CHUNK:
            raise ApduError(apdu, 0x6C, len(chunk))
        out += chunk[:READ_CHUNK]
    return bytes(out)


def read_payload(transmit: Transmit) -> bytes:
    """Read pages 0x04–0x27 (144 bytes); fall back to 0x04–0x17 (80 bytes) like the JS server."""
    try:
        return read_pages(transmit, FULL_READ_LEN)
    except ApduError:
        return read_pages(transmit, DATA_LEN)


def write_payload(transmit: Transmit, payload: bytes) -> int:
    """Write pages 0x04–0x27 one page per APDU (see :func:`burn_image`). Returns pages written."""
    written = 0
    for apdu in burn_plan(payload):
        check_response(apdu, *transmit(apdu))
        written += 1
    return written


# ── pyscard reader monitor (optional) ──────────────────────────────────────────

try:  # optional dependency, exactly like nfc-pcsc for the JS playground
    from smartcard.System import readers as _pcsc_readers
    from smartcard.Exceptions import CardConnectionException, NoCardException
    from smartcard.scard import (
        SCARD_S_SUCCESS, SCARD_SCOPE_USER, SCARD_STATE_PRESENT, SCARD_STATE_UNAWARE,
        SCardEstablishContext, SCardGetStatusChange, SCardListReaders, SCardReleaseContext,
    )
    PYSCARD_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on the environment
    PYSCARD_AVAILABLE = False


def _reader_ref(name: str) -> Dict[str, str]:
    return {"id": name, "name": name}


class ReaderMonitor:
    """
    Watch PC/SC readers and cards in a background thread and emit playground events.

    ``emit`` receives dicts shaped like the JS WebSocket messages. ``describe_tag``
    turns ``(uid, payload)`` into the SDK outputs added to ``card:detected``.
    Cards are opened in PC/SC *shared* mode so another application can use the
    same reader.
    """

    POLL_MS = 400

    def __init__(self, emit: Callable[[Dict[str, Any]], None],
                 describe_tag: Callable[[bytes, bytes], Dict[str, Any]]) -> None:
        self._emit = emit
        self._describe = describe_tag
        self._lock = threading.RLock()          # serialises every APDU exchange
        self.readers: Dict[str, Dict[str, Any]] = {}
        # Last card:detected per reader, replayed to a page that connects while chips are on the readers
        self.last_cards: Dict[str, Dict[str, Any]] = {}
        self.error: Optional[str] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def available(self) -> bool:
        return PYSCARD_AVAILABLE

    def status(self) -> Dict[str, Any]:
        return {
            "type": "readers:status",
            "readers": [dict(r) for r in self.readers.values()],
            "nfc": PYSCARD_AVAILABLE,
            "hint": None if PYSCARD_AVAILABLE else NFC_INSTALL_HINT,
            "error": self.error,
        }

    def start(self) -> None:
        if not PYSCARD_AVAILABLE or self._thread:
            return
        self._thread = threading.Thread(target=self._run, name="pcsc-monitor", daemon=True)
        self._thread.start()

    # ── card I/O ──────────────────────────────────────────────────────────────

    def _with_card(self, name: str, fn: Callable[[Transmit], Any]) -> Any:
        reader = next((r for r in _pcsc_readers() if str(r) == name), None)
        if reader is None:
            raise RuntimeError(f"Reader not found: {name}")
        with self._lock:
            conn = reader.createConnection()
            conn.connect()  # shared mode by default
            try:
                return fn(lambda apdu: conn.transmit(list(apdu)))
            finally:
                try:
                    conn.disconnect()
                except CardConnectionException:
                    pass

    def read(self, name: str) -> Tuple[bytes, bytes]:
        """Return ``(uid, payload)`` from the card on ``name``."""
        return self._with_card(name, lambda tx: (read_uid(tx), read_payload(tx)))

    def burn(self, name: str, payload: bytes) -> int:
        """Write pages 0x04–0x27 of the card on ``name`` (signature pages always 00)."""
        burn_image(payload)  # validate before touching the chip
        return self._with_card(name, lambda tx: write_payload(tx, payload))

    def readers_with_card(self) -> List[str]:
        return [n for n, r in self.readers.items() if r.get("hasCard")]

    # ── monitoring loop ───────────────────────────────────────────────────────

    def _on_card(self, name: str) -> None:
        info = self.readers[name]
        info["hasCard"] = True
        try:
            uid, payload = self.read(name)
            info["uid"] = uid.hex().upper()
            msg = {
                "type": "card:detected",
                "reader": _reader_ref(name),
                "uid": uid.hex().upper(),
                "payload": payload.hex(),
            }
            msg.update(self._describe(uid, payload))
            self.last_cards[name] = msg
            self._emit(msg)
        except (ApduError, NoCardException, CardConnectionException, ValueError, RuntimeError) as exc:
            self._emit({"type": "error", "reader": _reader_ref(name), "message": str(exc)})

    def _on_card_off(self, name: str) -> None:
        info = self.readers.get(name)
        if info:
            info["hasCard"] = False
            info["uid"] = None
        self.last_cards.pop(name, None)
        self._emit({"type": "card:removed", "reader": _reader_ref(name)})

    def _run(self) -> None:
        hctx = None
        states: Dict[str, int] = {}
        while True:
            try:
                if hctx is None:
                    hr, hctx = SCardEstablishContext(SCARD_SCOPE_USER)
                    if hr != SCARD_S_SUCCESS:
                        hctx = None
                        raise RuntimeError(f"PC/SC service unavailable (0x{hr & 0xFFFFFFFF:08X})")
                hr, names = SCardListReaders(hctx, [])
                names = list(names) if hr == SCARD_S_SUCCESS else []
                self.error = None

                for name in names:
                    if name not in self.readers:
                        self.readers[name] = {"id": name, "name": name, "connected": True,
                                              "hasCard": False, "uid": None}
                        states[name] = SCARD_STATE_UNAWARE
                        self._emit({"type": "reader:connected", "reader": dict(self.readers[name])})
                for name in [n for n in self.readers if n not in names]:
                    self.readers.pop(name, None)
                    self.last_cards.pop(name, None)
                    states.pop(name, None)
                    self._emit({"type": "reader:disconnected", "reader": _reader_ref(name)})

                if not names:
                    time.sleep(self.POLL_MS / 1000)
                    continue

                hr, new = SCardGetStatusChange(hctx, self.POLL_MS, [(n, states[n]) for n in names])
                if hr != SCARD_S_SUCCESS:
                    continue  # timeout or reader list changed
                for name, event_state, _atr in new:
                    was = bool(states.get(name, 0) & SCARD_STATE_PRESENT)
                    now = bool(event_state & SCARD_STATE_PRESENT)
                    states[name] = event_state & ~0x2  # drop SCARD_STATE_CHANGED
                    if now and not was:
                        self._on_card(name)
                    elif was and not now:
                        self._on_card_off(name)
            except Exception as exc:  # keep the monitor alive whatever PC/SC does
                self.error = str(exc)
                if hctx is not None:
                    try:
                        SCardReleaseContext(hctx)
                    except Exception:
                        pass
                    hctx = None
                time.sleep(2)
