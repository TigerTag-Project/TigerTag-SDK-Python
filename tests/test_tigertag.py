"""
TigerTag SDK test suite — stdlib unittest only, no external test runners required.

Run with:
    python -m unittest discover tests/
    python -m pytest tests/ -v
"""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path


def _make_payload(
    id_tigertag:     int   = 0x01000001,
    id_product:      int   = 0xFFFFFFFF,  # Maker
    id_material:     int   = 38219,       # PLA
    id_aspect_1:     int   = 1,
    id_aspect_2:     int   = 0,
    id_type:         int   = 0x8E,        # Filament
    id_diameter:     int   = 0x38,        # 1.75mm
    id_brand:        int   = 1,
    color1_r:        int   = 255,
    color1_g:        int   = 0,
    color1_b:        int   = 0,
    color1_a:        int   = 255,
    measure:         int   = 1000,
    id_unit:         int   = 1,
    nozzle_min:      int   = 190,
    nozzle_max:      int   = 220,
    dry_temp:        int   = 65,
    dry_time:        int   = 8,
    bed_min:         int   = 60,
    bed_max:         int   = 70,
    timestamp:       int   = 700000000,
    color2_r:        int   = 0,
    color2_g:        int   = 255,
    color2_b:        int   = 0,
    color3_r:        int   = 0,
    color3_g:        int   = 0,
    color3_b:        int   = 255,
    td_raw:          int   = 0,
    custom_message:  bytes = b"",
    measure_avail:   int   = 800,
    include_sig:     bool  = False,
) -> bytes:
    """Build a minimal valid 80- or 144-byte TigerTag payload."""
    def p16(v): return struct.pack(">H", v & 0xFFFF)
    def p24(v): v &= 0xFFFFFF; return bytes([(v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF])
    def p32(v): return struct.pack(">I", v & 0xFFFFFFFF)

    msg = custom_message[:28].ljust(28, b"\x00")

    data = (
        p32(id_tigertag)
        + p32(id_product)
        + p16(id_material)
        + bytes([id_aspect_1, id_aspect_2])
        + bytes([id_type, id_diameter])
        + p16(id_brand)
        + bytes([color1_r, color1_g, color1_b, color1_a])
        + p24(measure)
        + bytes([id_unit])
        + p16(nozzle_min)
        + p16(nozzle_max)
        + bytes([dry_temp, dry_time, bed_min, bed_max])
        + p32(timestamp)
        + bytes([color2_r, color2_g, color2_b])
        + b"\x00"
        + bytes([color3_r, color3_g, color3_b])
        + b"\x00"
        + p16(td_raw)
        + b"\x00\x00"
        + msg
        + p24(measure_avail)
        + b"\x00"
    )

    assert len(data) == 80

    if include_sig:
        data += bytes(64)

    return data


def _make_full_dump(payload: bytes) -> bytes:
    """Wrap a 144-byte payload in 180-byte full chip dump with a fake UID.

    NTAG memory layout:
        Page 0 [0:4]  = UID[0..2], BCC0
        Page 1 [4:8]  = UID[3..6]
        Pages 2-3     = BCC1, internal, lock, CC (zeros)
        Pages 4-39    = payload (144 bytes)
        Pages 40-44   = config (20 bytes)
    """
    page0  = bytes([0x04, 0xA1, 0xB2, 0xBB])   # UID[0..2] + BCC0
    page1  = bytes([0xC3, 0xD4, 0xE5, 0xF6])   # UID[3..6]
    pages23 = bytes(8)                           # pages 2-3 (8 bytes)
    system  = page0 + page1 + pages23            # 16 bytes total
    cfg     = bytes(20)                          # pages 40-44 (20 bytes)
    return system + payload + cfg                # 16 + 144 + 20 = 180 bytes


# ══════════════════════════════════════════════════════════════════════════════
# from_pages / from_dump / from_file
# ══════════════════════════════════════════════════════════════════════════════

class TestConstructors(unittest.TestCase):

    def _uid(self) -> bytes:
        return bytes([0x04, 0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF])

    def test_from_pages_80b(self) -> None:
        from tigertag import TigerTag
        payload = _make_payload()
        tag = TigerTag.from_pages(payload, uid=self._uid())
        self.assertEqual(tag.id_material, 38219)
        self.assertEqual(tag.uid, self._uid())

    def test_from_pages_144b(self) -> None:
        from tigertag import TigerTag
        payload = _make_payload(include_sig=True)
        tag = TigerTag.from_pages(payload, uid=self._uid())
        self.assertEqual(len(payload), 144)
        self.assertFalse(tag.is_signed)   # all-zero sig counts as unsigned

    def test_from_pages_invalid_size(self) -> None:
        from tigertag import TigerTag
        with self.assertRaises(ValueError):
            TigerTag.from_pages(bytes(50), uid=self._uid())

    def test_from_pages_invalid_uid(self) -> None:
        from tigertag import TigerTag
        with self.assertRaises(ValueError):
            TigerTag.from_pages(_make_payload(), uid=bytes(3))

    def test_from_dump_80b(self) -> None:
        from tigertag import TigerTag
        tag = TigerTag.from_dump(_make_payload())
        self.assertIsNone(tag.uid)
        self.assertFalse(tag.is_signed)

    def test_from_dump_144b(self) -> None:
        from tigertag import TigerTag
        tag = TigerTag.from_dump(_make_payload(include_sig=True))
        self.assertIsNone(tag.uid)

    def test_from_dump_180b_extracts_uid(self) -> None:
        from tigertag import TigerTag
        dump = _make_full_dump(_make_payload(include_sig=True))
        self.assertEqual(len(dump), 180)
        tag = TigerTag.from_dump(dump)
        # UID = dump[0:3] + dump[4:8]
        self.assertEqual(tag.uid, bytes([0x04, 0xA1, 0xB2, 0xC3, 0xD4, 0xE5, 0xF6]))

    def test_from_dump_invalid_size(self) -> None:
        from tigertag import TigerTag
        with self.assertRaises(ValueError):
            TigerTag.from_dump(bytes(100))

    def test_from_file(self) -> None:
        from tigertag import TigerTag
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(_make_payload())
            path = f.name
        tag = TigerTag.from_file(path)
        self.assertEqual(tag.id_material, 38219)
        Path(path).unlink()


# ══════════════════════════════════════════════════════════════════════════════
# validate()
# ══════════════════════════════════════════════════════════════════════════════

class TestValidate(unittest.TestCase):

    def test_valid_tag_no_warnings(self) -> None:
        from tigertag import TigerTag
        tag = TigerTag.from_dump(_make_payload())
        self.assertEqual(tag.validate(), [])

    def test_nozzle_min_gt_max(self) -> None:
        from tigertag import TigerTag
        tag = TigerTag.from_dump(_make_payload(nozzle_min=250, nozzle_max=200))
        warnings = tag.validate()
        self.assertTrue(any("Nozzle" in w for w in warnings))

    def test_bed_min_gt_max(self) -> None:
        from tigertag import TigerTag
        tag = TigerTag.from_dump(_make_payload(bed_min=80, bed_max=60))
        warnings = tag.validate()
        self.assertTrue(any("Bed" in w for w in warnings))

    def test_measure_available_exceeds_initial(self) -> None:
        from tigertag import TigerTag
        tag = TigerTag.from_dump(_make_payload(measure=500, measure_avail=600))
        warnings = tag.validate()
        self.assertTrue(any("measure_available" in w for w in warnings))

    def test_td_out_of_range(self) -> None:
        from tigertag import TigerTag
        tag = TigerTag.from_dump(_make_payload(td_raw=5))
        warnings = tag.validate()
        self.assertTrue(any("TD" in w for w in warnings))

    def test_td_zero_is_valid(self) -> None:
        from tigertag import TigerTag
        tag = TigerTag.from_dump(_make_payload(td_raw=0))
        self.assertEqual(tag.validate(), [])


# ══════════════════════════════════════════════════════════════════════════════
# to_bytes() round-trip
# ══════════════════════════════════════════════════════════════════════════════

class TestRoundTrip(unittest.TestCase):

    def test_serialize_parse_roundtrip(self) -> None:
        from tigertag import TigerTag
        original = TigerTag.from_dump(_make_payload(
            id_material=38219, nozzle_min=190, nozzle_max=220, measure=1000,
        ))
        serialized = original.to_bytes()
        self.assertEqual(len(serialized), 80)
        restored = TigerTag.from_dump(serialized)
        self.assertEqual(original.id_material,     restored.id_material)
        self.assertEqual(original.nozzle_temp_min, restored.nozzle_temp_min)
        self.assertEqual(original.nozzle_temp_max, restored.nozzle_temp_max)
        self.assertEqual(original.measure,         restored.measure)
        self.assertEqual(original.id_tigertag,     restored.id_tigertag)

    def test_serialize_with_signature(self) -> None:
        from tigertag import TigerTag
        tag = TigerTag.from_dump(_make_payload())
        data = tag.to_bytes(include_signature=True)
        self.assertEqual(len(data), 144)


# ══════════════════════════════════════════════════════════════════════════════
# to_dict()
# ══════════════════════════════════════════════════════════════════════════════

class TestToDict(unittest.TestCase):

    def test_required_keys_present(self) -> None:
        from tigertag import TigerTag
        tag = TigerTag.from_dump(_make_payload())
        d = tag.to_dict()
        for key in ("sdk", "protocol", "chip", "uid", "version", "product",
                    "material", "brand", "colors", "temperatures", "measure",
                    "authentication", "custom_message", "manufacturing_date"):
            self.assertIn(key, d, f"Missing key: {key}")
        self.assertIn("signed", d["authentication"])

    def test_sdk_mode_is_offline(self) -> None:
        from tigertag import TigerTag
        tag = TigerTag.from_dump(_make_payload())
        self.assertEqual(tag.to_dict()["sdk_mode"], "offline")

    def test_maker_product_mode(self) -> None:
        from tigertag import TigerTag
        tag = TigerTag.from_dump(_make_payload(id_product=0xFFFFFFFF))
        self.assertEqual(tag.to_dict()["product"]["mode"], "maker")

    def test_init_product_mode(self) -> None:
        from tigertag import TigerTag
        tag = TigerTag.from_dump(_make_payload(id_product=0x00000000))
        self.assertEqual(tag.to_dict()["product"]["mode"], "init")


# ══════════════════════════════════════════════════════════════════════════════
# SignatureResult
# ══════════════════════════════════════════════════════════════════════════════

class TestSignatureResult(unittest.TestCase):

    def test_valid_ok_true(self) -> None:
        from tigertag import SignatureResult
        r = SignatureResult(SignatureResult.VALID)
        self.assertTrue(r.ok)

    def test_invalid_ok_false(self) -> None:
        from tigertag import SignatureResult
        r = SignatureResult(SignatureResult.INVALID)
        self.assertFalse(r.ok)

    def test_unsigned_ok_false(self) -> None:
        from tigertag import SignatureResult
        r = SignatureResult(SignatureResult.UNSIGNED)
        self.assertFalse(r.ok)

    def test_no_crypto_ok_false(self) -> None:
        from tigertag import SignatureResult
        r = SignatureResult(SignatureResult.NO_CRYPTO)
        self.assertFalse(r.ok)

    def test_no_key_ok_false(self) -> None:
        from tigertag import SignatureResult
        r = SignatureResult(SignatureResult.NO_KEY)
        self.assertFalse(r.ok)

    def test_no_uid_ok_false(self) -> None:
        from tigertag import SignatureResult
        r = SignatureResult(SignatureResult.NO_UID)
        self.assertFalse(r.ok)

    def test_to_dict_structure(self) -> None:
        from tigertag import SignatureResult
        r = SignatureResult(SignatureResult.UNSIGNED, "test detail")
        d = r.to_dict()
        self.assertIn("status", d)
        self.assertIn("ok", d)
        self.assertIn("detail", d)
        self.assertEqual(d["status"], SignatureResult.UNSIGNED)


# ══════════════════════════════════════════════════════════════════════════════
# verify()
# ══════════════════════════════════════════════════════════════════════════════

class TestVerify(unittest.TestCase):

    def test_unsigned_tag_returns_unsigned(self) -> None:
        from tigertag import TigerTag, SignatureResult
        tag = TigerTag.from_dump(_make_payload())
        result = tag.verify()
        self.assertEqual(result.status, SignatureResult.UNSIGNED)
        self.assertFalse(result.ok)

    def test_no_uid_returns_no_uid(self) -> None:
        from tigertag import TigerTag, SignatureResult
        from tigertag.signature import _CRYPTO_AVAILABLE
        payload = _make_payload(include_sig=False)
        # Craft a signed payload with non-zero signature bytes
        sig_payload = payload + bytes([0xAB] * 32 + [0xCD] * 32)
        tag = TigerTag.from_dump(sig_payload)
        tag.uid = None  # no UID
        result = tag.verify()
        if _CRYPTO_AVAILABLE:
            self.assertEqual(result.status, SignatureResult.NO_UID)
        else:
            self.assertEqual(result.status, SignatureResult.NO_CRYPTO)


# ══════════════════════════════════════════════════════════════════════════════
# TigerTagDB
# ══════════════════════════════════════════════════════════════════════════════

class TestTigerTagDB(unittest.TestCase):

    def test_loads_bundled_db_without_network(self) -> None:
        from tigertag import TigerTagDB
        db = TigerTagDB(auto_sync=False)
        # Bundled db should have at least the PLA material
        mat = db.material(38219)
        if mat is not None:  # only assert if bundled DB has this ID
            self.assertEqual(mat.get("label"), "PLA")

    def test_unknown_id_returns_none(self) -> None:
        from tigertag import TigerTagDB
        db = TigerTagDB(auto_sync=False)
        self.assertIsNone(db.material(0xDEADBEEF))

    def test_label_on_none_returns_unknown(self) -> None:
        from tigertag import TigerTagDB
        self.assertEqual(TigerTagDB.label(None), "Unknown")

    def test_label_on_entry(self) -> None:
        from tigertag import TigerTagDB
        self.assertEqual(TigerTagDB.label({"label": "PLA"}), "PLA")

    def test_bundled_db_has_files(self) -> None:
        from tigertag.db import _BUNDLED_DB_PATH
        for _, filename in [
            ("", "id_version.json"), ("", "id_material.json"),
            ("", "id_aspect.json"),  ("", "id_type.json"),
            ("", "id_diameter.json"),("", "id_brand.json"),
            ("", "id_measure_unit.json"),
        ]:
            self.assertTrue(
                (_BUNDLED_DB_PATH / filename).exists(),
                f"Missing bundled file: {filename}",
            )


# ══════════════════════════════════════════════════════════════════════════════
# ECDSA full round-trip (requires cryptography)
# ══════════════════════════════════════════════════════════════════════════════

class TestECDSARoundTrip(unittest.TestCase):

    def test_sign_and_verify(self) -> None:
        """Generate a real ECDSA-P256 key pair, sign, then verify through TigerTag.verify()."""
        try:
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
        except ImportError:
            self.skipTest("cryptography not installed")

        from tigertag import TigerTag, TigerTagDB, SignatureResult

        uid         = bytes([0x04, 0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF])
        id_tigertag = 0x01000001
        id_product  = 0xFFFFFFFF

        # Generate ephemeral key pair
        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key  = private_key.public_key()
        pem         = public_key.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

        # Sign: SHA-256(uid + block4 + block5)
        block4  = id_tigertag.to_bytes(4, "big")
        block5  = id_product.to_bytes(4, "big")
        message = uid + block4 + block5

        der = private_key.sign(message, ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        sig_r = r.to_bytes(32, "big")
        sig_s = s.to_bytes(32, "big")

        # Build payload with real signature
        payload = _make_payload(
            id_tigertag=id_tigertag,
            id_product=id_product,
            include_sig=False,
        )
        signed_payload = payload + sig_r + sig_s
        self.assertEqual(len(signed_payload), 144)

        tag = TigerTag.from_pages(signed_payload, uid=uid)
        self.assertTrue(tag.is_signed)

        # Inject public key into a temporary DB backed by real bundled files
        from tigertag.db import _BUNDLED_DB_PATH, _DATASETS
        import json as _json

        db = TigerTagDB(auto_sync=False)
        # Patch version lookup with the test public key
        db._versions = [{"id": id_tigertag, "label": "test", "public_key": pem}]

        result = tag.verify(db)
        self.assertEqual(result.status, SignatureResult.VALID)
        self.assertTrue(result.ok)


if __name__ == "__main__":
    unittest.main()
