"""
Playground: the shared page stays identical to the JavaScript SDK's copy, and tools/server.py
implements the server contract (docs/playground-api.md). The server runs without readers.
"""

import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestPlaygroundSync(unittest.TestCase):
    def test_identical_to_the_js_copy(self):
        sync = _load("check_playground_sync", ROOT / "scripts" / "check_playground_sync.py")
        r = sync.check()
        if r["status"] == "unreachable":
            self.skipTest("sibling playground.html not reachable")
        self.assertEqual(r["status"], "identical", r)


class TestPlaygroundServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls._env = mock.patch.dict(os.environ, {"TIGERTAG_OFFLINE": "1", "TIGERTAG_DATA_DIR": cls._tmp.name,
                                                "TIGERTAG_PLAYGROUND_NO_NFC": "1"})
        cls._env.start()
        sys.path.insert(0, str(ROOT / "tools"))
        cls.server_mod = _load("tigertag_playground_server", ROOT / "tools" / "server.py")
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), cls.server_mod.PlaygroundHandler)
        cls.httpd.daemon_threads = True
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls._env.stop()
        cls._tmp.cleanup()

    def get(self, url):
        try:
            with urllib.request.urlopen(self.base + url, timeout=10) as r:
                return r.status, json.loads(r.read()), r.headers
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}"), e.headers

    def post(self, url, body):
        req = urllib.request.Request(self.base + url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_version_names_the_sdk(self):
        code, v, _ = self.get("/api/version")
        self.assertEqual(code, 200)
        self.assertEqual((v["sdk"], v["label"], v["style"]), ("python", "Python SDK", "snake"))
        self.assertEqual(v["install"], "pip install tigertag")

    def test_build_then_parse(self):
        code, built = self.post("/api/build", {
            "id_material": 38219, "id_aspect_1": 104, "id_type": 142, "id_brand": 57632, "measure": 1000,
            "id_unit": 21, "color1_r": 1, "color1_g": 2, "color1_b": 3, "color1_a": 255,
            "tag_count": 2, "tag_index": 1, "timestamp": 5, "measure_available": 800,
        })
        self.assertEqual(code, 200, built)
        self.assertRegex(built["payload"], r"^[0-9a-f]{160}$")
        self.assertEqual((built["tag_info"], built["tag_count"], built["tag_index"]), (0x12, 2, 1))
        code, parsed = self.post("/api/parse", {"uid": "04aabbccddeeff", "payload": built["payload"]})
        self.assertEqual(code, 200, parsed)
        for k in ("pretty", "describe", "verify", "raw_dict", "dict", "validate", "tag_info", "tag_count", "tag_index"):
            self.assertIn(k, parsed)
        self.assertEqual(parsed["raw_dict"]["measure_available"], 800)

    def test_plan_and_burn_shapes(self):
        code, plan = self.post("/api/nfc/plan", {"payload": "ab" * 80 + "cd" * 64})
        self.assertEqual(code, 200)
        self.assertEqual(plan["pages"], 36)
        self.assertTrue(plan["signature_dropped"])
        self.assertEqual(plan["apdus"][0], "FF D6 00 04 04 AB AB AB AB")
        self.assertEqual(plan["apdus"][35], "FF D6 00 27 04 00 00 00 00")
        self.assertEqual(self.post("/api/nfc/burn", {"payload": "ab"})[0], 400)
        code, out = self.post("/api/nfc/burn", {"reqId": 7, "payload": "00" * 80})
        self.assertEqual(out["messages"], [{"type": "burn:done", "reqId": 7}])

    def test_db_table_and_info(self):
        code, table, headers = self.get("/api/db/table/id_material.json")
        self.assertEqual(code, 200)
        self.assertIsInstance(table, list)
        self.assertIn(headers.get("X-TigerTag-Source"), ("bundled", "downloaded"))
        code, info, _ = self.get("/api/db/info")
        self.assertIn("id_material.json", info["tables"])

    def test_catalog_product_offline(self):
        code, out, _ = self.get("/api/catalog/3527039449")
        self.assertEqual(code, 200, out)
        self.assertEqual(out["entry"]["title"], "Rapid TPU 95A - Black")
        for k in ("rfid_data", "fields", "raw_dict", "payload", "pretty", "describe", "catalog"):
            self.assertIn(k, out)
        self.assertEqual(self.get("/api/catalog/123")[0], 404)


if __name__ == "__main__":
    unittest.main()
