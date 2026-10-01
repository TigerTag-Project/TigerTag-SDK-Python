"""
Tests for the TigerTag+ catalogue (tigertag/catalog.py, TigerTag.from_catalog).

The download is mocked: no network access.
"""

from __future__ import annotations

import os as _os
_os.environ["TIGERTAG_OFFLINE"] = "1"   # the suite never touches the network (tests that need it mock it)

import json
import os
import struct
import sys
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from tigertag import TigerTag, load_catalog, catalog_entry
from tigertag import catalog as cat_mod
from tigertag.tag import ID_TIGERTAG_PLUS

ELEGOO = {
    "RFID_Data": {"color_a": 255, "color_b": 0, "color_g": 0, "color_r": 0, "data1": 56, "data2": 200,
                  "data3": 250, "data4": 60, "data5": 6, "data6": 25, "data7": 45, "id_aspect1": 104,
                  "id_aspect2": None, "id_brand": 57632, "id_material": 43518, "id_type": 142,
                  "id_unit": 21, "measure": 1000},
    "barcode": "40553085", "brand": "ELEGOO", "color": "#000000FF",
    "color_info": {"colors": ["#000000FF"], "type": "mono"}, "id": 3527039449,
    "img_src": "https://example.invalid/tpu.png", "material": "TPU", "measure": "1000 g",
    "product_type": "Filament", "sku": "50.203.0631", "title": "Rapid TPU 95A - Black",
}
DUAL = {   # colour 2 given in RFID_Data
    "RFID_Data": {"color_a": 255, "color_b": 189, "color_b2": 46, "color_g": 173, "color_g2": 47,
                  "color_r": 234, "color_r2": 237, "data1": 56, "data2": 190, "data3": 240, "data4": 55,
                  "data5": 6, "data6": 25, "data7": 60, "id_aspect1": 247, "id_aspect2": 252,
                  "id_brand": 50604, "id_material": 38219, "id_type": 142, "id_unit": 21, "measure": 1000},
    "color_info": {"colors": ["#EAADBDFF", "#ED2F2EFF"], "type": "multi"}, "id": 19278539,
    "title": "PolyTerra - Dual Matte Flamingo",
}
TRI_INFO = {   # colours 2 and 3 only in color_info; null temperatures
    "RFID_Data": {"color_a": 255, "color_b": 3, "color_g": 2, "color_r": 1, "data1": 56, "data2": None,
                  "data3": None, "data4": None, "data5": None, "data6": None, "data7": None,
                  "id_aspect1": 104, "id_aspect2": 24, "id_brand": 1, "id_material": 38219,
                  "id_type": 142, "id_unit": 21, "measure": 500},
    "color_info": {"colors": ["#010203FF", "#112233", "#AABBCCFF"], "type": "multi"}, "id": 1001,
    "title": "Tri",
}
RESIN = {   # same chip layout for resin: data1–data7 keep their meaning
    "RFID_Data": {"color_a": 255, "color_b": 200, "color_g": 100, "color_r": 50, "data1": 0, "data2": 0,
                  "data3": 0, "data4": 0, "data5": 0, "data6": 25, "data7": 30, "id_aspect1": 104,
                  "id_aspect2": None, "id_brand": 1, "id_material": 1, "id_type": 173, "id_unit": 79,
                  "measure": 1},
    "id": 1002, "title": "Resin bottle",
}
NO_DATA = {"id": 1003, "title": "No chip data", "RFID_Data": None}

CATALOG_JSON = json.dumps([ELEGOO, DUAL, TRI_INFO, RESIN, NO_DATA]).encode()
HEADERS = {"etag": '"abc123"', "last_modified": "Wed, 30 Sep 2026 08:00:00 GMT"}


def _catalog():
    return cat_mod._index(CATALOG_JSON)


class TestMapping(unittest.TestCase):

    def test_example_entry_bytes(self) -> None:
        tag = TigerTag.from_catalog(3527039449, catalog=_catalog(), tag_count=2, tag_index=1,
                                    timestamp=800000000)
        b = tag.to_bytes()
        self.assertEqual(struct.unpack(">I", b[0:4])[0], ID_TIGERTAG_PLUS)
        self.assertEqual(struct.unpack(">I", b[4:8])[0], 3527039449)        # page 5 = product id
        self.assertEqual(struct.unpack(">H", b[8:10])[0], 43518)            # material
        self.assertEqual((b[10], b[11], b[12], b[13]), (104, 0, 142, 56))  # aspects (aspect2 null → 0), type, diameter
        self.assertEqual(struct.unpack(">H", b[14:16])[0], 57632)           # brand
        self.assertEqual(b[16:20], bytes([0, 0, 0, 255]))                   # colour 1 RGBA
        self.assertEqual(int.from_bytes(b[20:23], "big"), 1000)
        self.assertEqual(b[23], 21)
        self.assertEqual(struct.unpack(">HH", b[24:28]), (200, 250))        # nozzle
        self.assertEqual((b[28], b[29], b[30], b[31]), (60, 6, 25, 45))     # dry temp/time, bed
        self.assertEqual(struct.unpack(">I", b[32:36])[0], 800000000)
        self.assertEqual(b[39], 0x12)                                       # tag 1 of 2
        self.assertEqual(int.from_bytes(b[76:79], "big"), 1000)             # measure_available
        self.assertEqual(TigerTag.from_catalog(3527039449, catalog=_catalog(),
                                               tag_count=2, tag_index=2).to_bytes()[39], 0x22)
        self.assertEqual(tag.validate(), [])

    def test_multicolour_from_rfid_data(self) -> None:
        tag = TigerTag.from_catalog(19278539, catalog=_catalog())
        self.assertEqual((tag.color2_r, tag.color2_g, tag.color2_b), (237, 47, 46))
        self.assertEqual((tag.color3_r, tag.color3_g, tag.color3_b), (0, 0, 0))
        self.assertEqual(tag.id_aspect_2, 252)

    def test_multicolour_from_color_info_and_null_temps(self) -> None:
        tag = TigerTag.from_catalog(1001, catalog=_catalog())
        self.assertEqual((tag.color2_r, tag.color2_g, tag.color2_b), (0x11, 0x22, 0x33))
        self.assertEqual((tag.color3_r, tag.color3_g, tag.color3_b), (0xAA, 0xBB, 0xCC))
        self.assertEqual((tag.nozzle_temp_min, tag.dry_temp, tag.bed_temp_max), (0, 0, 0))

    def test_resin_uses_same_layout(self) -> None:
        tag = TigerTag.from_catalog(1002, catalog=_catalog())
        self.assertEqual((tag.id_type, tag.id_unit, tag.bed_temp_min, tag.bed_temp_max), (173, 79, 25, 30))
        self.assertEqual(tag.id_aspect_2, 0)

    def test_unknown_and_empty_entries(self) -> None:
        with self.assertRaises(KeyError) as ctx:
            TigerTag.from_catalog(42, catalog=_catalog())
        self.assertIn("42", str(ctx.exception))
        with self.assertRaises(ValueError):
            TigerTag.from_catalog(1003, catalog=_catalog())

    def test_entry_metadata(self) -> None:
        e = catalog_entry(3527039449, _catalog())
        self.assertEqual((e["title"], e["brand"], e["sku"], e["barcode"]),
                         ("Rapid TPU 95A - Black", "ELEGOO", "50.203.0631", "40553085"))

    def test_parse_hex_color(self) -> None:
        self.assertEqual(cat_mod.parse_hex_color("#ED2F2EFF"), (237, 47, 46, 255))
        self.assertEqual(cat_mod.parse_hex_color("102030"), (16, 32, 48, 255))
        with self.assertRaises(ValueError):
            cat_mod.parse_hex_color("#123")


class _NetworkCase(unittest.TestCase):
    """Online mode, an empty cache and no bundled copy; downloads are mocked per test."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        patches = [mock.patch.dict(os.environ, {"TIGERTAG_OFFLINE": ""}),
                   mock.patch.object(cat_mod, "BUNDLED_CATALOG", self.dir / "no-bundle.json.gz")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self) -> None:
        self.tmp.cleanup()


class TestCache(_NetworkCase):

    def test_download_then_cache(self) -> None:
        with mock.patch.object(cat_mod, "_download", return_value=(CATALOG_JSON, HEADERS)) as dl:
            c1 = load_catalog(cache_dir=self.dir)
            c2 = load_catalog(cache_dir=self.dir)          # fresh cache: no second download
        self.assertEqual(dl.call_count, 1)
        self.assertIn(3527039449, c1)
        self.assertEqual(c1.keys(), c2.keys())
        self.assertTrue((self.dir / "id_catalog.json").exists())

    def test_stale_cache_refreshes_and_force(self) -> None:
        (self.dir / "id_catalog.json").write_bytes(json.dumps([ELEGOO]).encode())
        old = time.time() - 10 * 24 * 3600
        os.utime(self.dir / "id_catalog.json", (old, old))
        with mock.patch.object(cat_mod, "_download", return_value=(CATALOG_JSON, HEADERS)) as dl:
            c = load_catalog(cache_dir=self.dir)
            self.assertEqual(len(c), 5)
            load_catalog(cache_dir=self.dir, force=True)
        self.assertEqual(dl.call_count, 2)

    def test_offline_uses_cache_and_errors_without(self) -> None:
        offline = mock.patch.object(cat_mod, "_download", side_effect=urllib.error.URLError("offline"))
        with offline:
            with self.assertRaises(RuntimeError) as ctx:
                load_catalog(cache_dir=self.dir)
        self.assertIn("no local copy", str(ctx.exception))
        (self.dir / "id_catalog.json").write_bytes(CATALOG_JSON)
        with offline:
            c = load_catalog(cache_dir=self.dir, force=True)   # stale or forced: still served
        self.assertIn(1001, c)

    def test_bad_download_keeps_cache(self) -> None:
        (self.dir / "id_catalog.json").write_bytes(CATALOG_JSON)
        with mock.patch.object(cat_mod, "_download", return_value=(b"<html>error</html>", HEADERS)):
            c = load_catalog(cache_dir=self.dir, force=True)
        self.assertEqual(len(c), 5)
        self.assertEqual((self.dir / "id_catalog.json").read_bytes(), CATALOG_JSON)


class TestRefreshAndInfo(_NetworkCase):

    def test_info_before_and_after_download(self) -> None:
        from tigertag import catalog_info
        self.assertEqual(catalog_info(self.dir)["downloaded"], False)
        with mock.patch.object(cat_mod, "_download", return_value=(CATALOG_JSON, HEADERS)):
            load_catalog(cache_dir=self.dir, url="https://example.invalid/cat.json")
        info = catalog_info(self.dir)
        self.assertTrue(info["downloaded"])
        self.assertEqual(info["count"], 5)
        self.assertEqual(info["url"], "https://example.invalid/cat.json")
        self.assertEqual(info["etag"], '"abc123"')
        self.assertTrue(info["fetched_at"].endswith("+00:00"))

    def test_info_accepts_data_dir_and_offline(self) -> None:
        from tigertag import catalog_info
        with mock.patch.object(cat_mod, "_download", return_value=(CATALOG_JSON, HEADERS)):
            load_catalog(cache_dir=self.dir, url="https://example.invalid/cat.json")
        with mock.patch.object(cat_mod, "_download", side_effect=AssertionError("network")):
            for info in (catalog_info(data_dir=self.dir, offline=True),
                         catalog_info(self.dir, offline=False)):
                self.assertEqual(info, catalog_info(self.dir))
                self.assertEqual(info["count"], 5)

    def test_refresh_sends_validators_and_handles_304(self) -> None:
        from tigertag import refresh_catalog, catalog_info
        url = "https://example.invalid/cat.json"
        with mock.patch.object(cat_mod, "_download", return_value=(CATALOG_JSON, HEADERS)):
            load_catalog(cache_dir=self.dir, url=url)
        fetched = catalog_info(self.dir)["fetched_at"]
        with mock.patch.object(cat_mod, "_download", return_value=None) as dl:   # 304
            c = refresh_catalog(cache_dir=self.dir, url=url)
        self.assertEqual(len(c), 5)
        _, kwargs = dl.call_args
        self.assertEqual(kwargs["etag"], '"abc123"')
        self.assertEqual(kwargs["last_modified"], HEADERS["last_modified"])
        info = catalog_info(self.dir)
        self.assertEqual(info["fetched_at"], fetched)          # not re-downloaded
        self.assertIsNotNone(info["checked_at"])

    def test_refresh_downloads_new_content(self) -> None:
        from tigertag import refresh_catalog, catalog_info
        with mock.patch.object(cat_mod, "_download", return_value=(json.dumps([ELEGOO]).encode(), HEADERS)):
            load_catalog(cache_dir=self.dir)
        self.assertEqual(catalog_info(self.dir)["count"], 1)
        with mock.patch.object(cat_mod, "_download", return_value=(CATALOG_JSON, {"etag": '"new"', "last_modified": None})):
            c = refresh_catalog(cache_dir=self.dir)              # fresh cache, refresh forces
        self.assertEqual(len(c), 5)
        self.assertEqual(catalog_info(self.dir)["count"], 5)
        self.assertEqual(catalog_info(self.dir)["etag"], '"new"')

    def test_validators_not_sent_for_another_url(self) -> None:
        with mock.patch.object(cat_mod, "_download", return_value=(CATALOG_JSON, HEADERS)):
            load_catalog(cache_dir=self.dir, url="https://a.invalid/x.json")
        with mock.patch.object(cat_mod, "_download", return_value=(CATALOG_JSON, HEADERS)) as dl:
            load_catalog(cache_dir=self.dir, url="https://b.invalid/y.json", force=True)
        self.assertIsNone(dl.call_args.kwargs["etag"])


class TestStandaloneParity(unittest.TestCase):

    def test_standalone_from_catalog(self) -> None:
        import importlib.util
        path = Path(__file__).resolve().parent.parent / "parse_tigertag.py"
        spec = importlib.util.spec_from_file_location("parse_tigertag_catalog", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        catalog = module._index(CATALOG_JSON)
        for pid in (3527039449, 19278539, 1001, 1002):
            with self.subTest(pid=pid):
                a = module.TigerTag.from_catalog(pid, catalog=catalog, tag_count=2, tag_index=1, timestamp=1)
                b = TigerTag.from_catalog(pid, catalog=_catalog(), tag_count=2, tag_index=1, timestamp=1)
                self.assertEqual(a.to_bytes(), b.to_bytes())


if __name__ == "__main__":
    unittest.main()
