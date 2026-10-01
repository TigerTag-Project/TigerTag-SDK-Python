"""
Tests for the playground's ACR122U helpers (tools/nfc_reader.py).

Only the pure parts are covered: APDU building, response checking, page chunking and
the read / write sequences driven through a fake transmit function. No pyscard and
no hardware required.
"""

from __future__ import annotations

import os as _os
_os.environ["TIGERTAG_OFFLINE"] = "1"   # the suite never touches the network (tests that need it mock it)

import sys
import unittest
from pathlib import Path
from typing import List, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import nfc_reader as nr  # noqa: E402


class FakeTag:
    """In-memory NTAG215: 135 pages, answers the ACR122U pseudo-APDUs."""

    def __init__(self, uid: bytes, pages: int = 135) -> None:
        self.uid = uid
        self.mem = bytearray(pages * 4)
        self.log: List[List[int]] = []

    def transmit(self, apdu: Sequence[int]) -> Tuple[List[int], int, int]:
        apdu = list(apdu)
        self.log.append(apdu)
        if apdu[:2] == [0xFF, 0xCA]:
            return list(self.uid), 0x90, 0x00
        page = apdu[3]
        if apdu[:2] == [0xFF, 0xB0]:
            if (page + 4) * 4 > len(self.mem):
                return [], 0x63, 0x00
            return list(self.mem[page * 4:page * 4 + 16]), 0x90, 0x00
        if apdu[:2] == [0xFF, 0xD6]:
            self.mem[page * 4:page * 4 + 4] = bytes(apdu[5:9])
            return [], 0x90, 0x00
        return [], 0x6A, 0x81


class TestApduBuilders(unittest.TestCase):

    def test_get_uid(self) -> None:
        self.assertEqual(nr.apdu_get_uid(), [0xFF, 0xCA, 0x00, 0x00, 0x00])

    def test_read(self) -> None:
        self.assertEqual(nr.apdu_read(4), [0xFF, 0xB0, 0x00, 0x04, 0x10])
        self.assertEqual(nr.apdu_read(0x24), [0xFF, 0xB0, 0x00, 0x24, 0x10])

    def test_write(self) -> None:
        self.assertEqual(
            nr.apdu_write(0x0D, b"\x01\x02\x03\x12"),
            [0xFF, 0xD6, 0x00, 0x0D, 0x04, 0x01, 0x02, 0x03, 0x12],
        )

    def test_write_rejects_bad_length(self) -> None:
        with self.assertRaises(ValueError):
            nr.apdu_write(4, b"\x00\x00\x00")

    def test_pages_outside_tigertag_area_rejected(self) -> None:
        for page in (0, 1, 2, 3, 0x28, 0x29, 0x82):
            with self.subTest(page=page):
                with self.assertRaises(ValueError):
                    nr.apdu_write(page, b"\x00" * 4)
                with self.assertRaises(ValueError):
                    nr.apdu_read(page)


class TestResponses(unittest.TestCase):

    def test_ok_strips_status(self) -> None:
        self.assertEqual(nr.check_response([0xFF], [1, 2, 3], 0x90, 0x00), b"\x01\x02\x03")

    def test_error_raises(self) -> None:
        with self.assertRaises(nr.ApduError) as ctx:
            nr.check_response(nr.apdu_read(4), [], 0x63, 0x00)
        self.assertEqual((ctx.exception.sw1, ctx.exception.sw2), (0x63, 0x00))
        self.assertIn("63 00", str(ctx.exception))


class TestPageChunks(unittest.TestCase):

    def test_80_bytes_to_pages_4_to_39_signature_zeroed(self) -> None:
        payload = bytes(range(80))
        chunks = nr.page_chunks(payload)
        self.assertEqual(len(chunks), 36)
        self.assertEqual(chunks[0], (4, bytes([0, 1, 2, 3])))
        self.assertEqual(chunks[19], (0x17, bytes([76, 77, 78, 79])))
        self.assertEqual(chunks[9], (0x0D, bytes([36, 37, 38, 39])))  # color2 + tag_info
        self.assertEqual([p for p, _ in chunks[20:]], list(range(0x18, 0x28)))
        self.assertTrue(all(d == bytes(4) for _, d in chunks[20:]))

    def test_signature_in_payload_is_dropped(self) -> None:
        payload = bytes(range(144))                   # non-zero "signature" bytes 80-143
        chunks = nr.page_chunks(payload)
        self.assertEqual(b"".join(d for _, d in chunks), payload[:80] + bytes(64))
        self.assertEqual(chunks[-1][0], 0x27)
        self.assertTrue(nr.carries_signature(payload))
        self.assertFalse(nr.carries_signature(bytes(range(80)) + bytes(64)))
        self.assertFalse(nr.carries_signature(bytes(range(80))))

    def test_burn_plan_apdus(self) -> None:
        plan = nr.burn_plan(bytes(80))
        self.assertEqual(len(plan), 36)
        self.assertEqual(plan[20], [0xFF, 0xD6, 0x00, 0x18, 0x04, 0, 0, 0, 0])
        self.assertEqual(plan[-1], [0xFF, 0xD6, 0x00, 0x27, 0x04, 0, 0, 0, 0])
        self.assertTrue(all(4 <= a[3] <= 0x27 for a in plan))

    def test_bad_lengths_rejected(self) -> None:
        for n in (0, 79, 81, 143, 145):
            with self.subTest(n=n):
                with self.assertRaises(ValueError):
                    nr.page_chunks(bytes(n))


class TestSequences(unittest.TestCase):

    UID = bytes.fromhex("04A1B2C3D4E5F6")

    def test_read_uid(self) -> None:
        tag = FakeTag(self.UID)
        self.assertEqual(nr.read_uid(tag.transmit), self.UID)

    def test_read_payload_144(self) -> None:
        tag = FakeTag(self.UID)
        tag.mem[16:16 + 144] = bytes(range(144))
        self.assertEqual(nr.read_payload(tag.transmit), bytes(range(144)))
        self.assertEqual([a[3] for a in tag.log], list(range(4, 40, 4)))

    def test_read_payload_falls_back_to_80(self) -> None:
        tag = FakeTag(self.UID, pages=30)   # too small for pages 4-39
        tag.mem[16:96] = bytes(range(80))
        self.assertEqual(nr.read_payload(tag.transmit), bytes(range(80)))

    def _stale_tag(self) -> "FakeTag":
        tag = FakeTag(self.UID)
        tag.mem[0:16] = b"\xAA" * 16          # UID / lock / CC pages 0-3
        tag.mem[96:160] = b"\x55" * 64        # stale signature, pages 0x18-0x27
        tag.mem[160:] = b"\xCC" * (len(tag.mem) - 160)   # pages 0x28+ (config)
        return tag

    def test_unsigned_burn_clears_stale_signature(self) -> None:
        for payload in (bytes(range(1, 81)), bytes(range(1, 81)) + bytes(64)):
            with self.subTest(length=len(payload)):
                tag = self._stale_tag()
                self.assertEqual(nr.write_payload(tag.transmit, payload), 36)
                self.assertEqual(bytes(tag.mem[16:96]), payload[:80])
                self.assertEqual(bytes(tag.mem[96:160]), bytes(64))              # zeroed
                self.assertEqual(bytes(tag.mem[0:16]), b"\xAA" * 16)             # untouched
                self.assertEqual(set(tag.mem[160:]), {0xCC})                     # untouched
                self.assertTrue(all(a[:2] == [0xFF, 0xD6] and 4 <= a[3] <= 0x27 for a in tag.log))

    def test_signed_payload_never_writes_its_signature(self) -> None:
        tag = self._stale_tag()
        payload = bytes(range(1, 81)) + bytes(range(100, 164))   # e.g. read from a signed chip
        self.assertEqual(nr.write_payload(tag.transmit, payload), 36)
        self.assertEqual(bytes(tag.mem[16:96]), payload[:80])
        self.assertEqual(bytes(tag.mem[96:160]), bytes(64))       # pages 0x18-0x27 zeroed
        self.assertEqual(bytes(tag.mem[0:16]), b"\xAA" * 16)      # pages 0-3 untouched
        self.assertEqual(set(tag.mem[160:]), {0xCC})              # pages 0x28+ untouched
        self.assertEqual(nr.read_payload(tag.transmit), payload[:80] + bytes(64))

    def test_tag_info_written_and_parsed(self) -> None:
        from tigertag import TigerTag
        built = TigerTag.create(id_material=38219, tag_count=2, tag_index=2)
        tag = FakeTag(self.UID)
        nr.write_payload(tag.transmit, built.to_bytes())
        parsed = TigerTag.from_pages(nr.read_uid(tag.transmit), nr.read_payload(tag.transmit))
        self.assertEqual((parsed.tag_count, parsed.tag_index), (2, 2))
        first = TigerTag.create(id_material=38219, tag_count=2, tag_index=1)
        nr.write_payload(tag.transmit, first.to_bytes())
        self.assertEqual(tag.mem[0x0D * 4 + 3], 0x12)   # page 0x0D byte 3
        parsed = TigerTag.from_pages(nr.read_uid(tag.transmit), nr.read_payload(tag.transmit))
        self.assertEqual((parsed.tag_index, parsed.tag_count), (1, 2))

    def test_write_error_propagates(self) -> None:
        def failing(apdu):
            return [], 0x63, 0x00
        with self.assertRaises(nr.ApduError):
            nr.write_payload(failing, bytes(80))


if __name__ == "__main__":
    unittest.main()
