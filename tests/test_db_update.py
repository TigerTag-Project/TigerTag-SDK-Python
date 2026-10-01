"""
Tests for reference-data precedence, automatic / manual updates and offline mode
(tigertag/db.py). All network access is mocked through ``tigertag.db._open_url``.
"""

from __future__ import annotations

import os as _os
_os.environ["TIGERTAG_OFFLINE"] = "1"   # the suite never touches the network (tests that need it mock it)

import io
import json
import os
import tempfile
import time
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from tigertag import db as db_mod
from tigertag.db import TigerTagDB, _API_BASE, _DATASETS, _GITHUB_RAW_BASE

KEYS = list(_DATASETS)                         # last_update keys
OLD, NEW = 1_000, 2_000


def _table(label: str):
    return [{"id": 1, "label": label}]


def _write_set(folder: Path, label: str, ts: int, keys=KEYS) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for key in keys:
        (folder / _DATASETS[key][1]).write_text(json.dumps(_table(f"{label}-{key}")))
    (folder / "last_update.json").write_text(json.dumps({k: ts for k in keys}))


class FakeRemote:
    """Answers the TigerTag API (or only the GitHub mirror when api_down)."""

    def __init__(self, ts: dict, api_down: bool = False, down: bool = False) -> None:
        self.ts, self.api_down, self.down, self.calls = ts, api_down, down, []

    def __call__(self, url: str, timeout: float) -> bytes:
        self.calls.append(url)
        if self.down or (self.api_down and url.startswith(_API_BASE)):
            raise urllib.error.URLError("unreachable")
        if url.endswith("/all/last_update") or url.endswith("/last_update.json"):
            return json.dumps(self.ts).encode()
        for key, (endpoint, filename) in _DATASETS.items():
            if url in (f"{_API_BASE}/{endpoint}", f"{_GITHUB_RAW_BASE}/{filename}"):
                return json.dumps(_table(f"remote-{key}")).encode()
        raise AssertionError(f"unexpected URL {url}")


class _Base(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.bundled, self.data = root / "bundled", root / "data"
        _write_set(self.bundled, "bundled", OLD)
        patches = [
            mock.patch.object(db_mod, "BUNDLED_DB_PATH", self.bundled),
            mock.patch.dict(os.environ, {"TIGERTAG_OFFLINE": ""}),
            mock.patch.object(db_mod, "_CHECKED_THIS_PROCESS", set()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def label(self, db: TigerTagDB) -> str:
        return db.material(1)["label"]


class TestPrecedence(_Base):

    def test_custom_folder_exclusive(self) -> None:
        custom = Path(self.tmp.name) / "mine"
        _write_set(custom, "custom", 5)
        opener = mock.Mock(side_effect=AssertionError("no network for a custom folder"))
        with mock.patch.object(db_mod, "_open_url", opener):
            db = TigerTagDB(custom, data_dir=self.data)
        self.assertEqual(self.label(db), "custom-filament_materials")
        self.assertEqual(db.info()["tables"]["id_material.json"]["source"], "custom")
        opener.assert_not_called()

    def test_custom_folder_missing_files_is_an_error(self) -> None:
        custom = Path(self.tmp.name) / "partial"
        _write_set(custom, "custom", 5, keys=KEYS[:3])
        with mock.patch.object(db_mod, "_open_url", mock.Mock()) as opener:
            with self.assertRaises(FileNotFoundError) as ctx:
                TigerTagDB(custom, data_dir=self.data)
        self.assertIn("id_material.json", str(ctx.exception))
        opener.assert_not_called()

    def test_newest_of_downloaded_and_bundled(self) -> None:
        _write_set(self.data, "cache", NEW, keys=["filament_materials"])
        _write_set(self.data, "stale", OLD - 1, keys=["brands"])
        (self.data / "last_update.json").write_text(json.dumps({"filament_materials": NEW, "brands": OLD - 1}))
        db = TigerTagDB(data_dir=self.data, auto_update=False)
        info = db.info()["tables"]
        self.assertEqual(info["id_material.json"]["source"], "downloaded")
        self.assertEqual(self.label(db), "cache-filament_materials")
        self.assertEqual(info["id_brand.json"]["source"], "bundled")     # fresher bundled copy wins
        self.assertEqual(db.brand(1)["label"], "bundled-brands")
        self.assertEqual(info["id_type.json"]["source"], "bundled")


class TestAutoUpdate(_Base):

    def test_downloads_only_changed_tables(self) -> None:
        remote = FakeRemote({k: (NEW if k == "filament_materials" else OLD) for k in KEYS})
        with mock.patch.object(db_mod, "_open_url", remote):
            db = TigerTagDB(data_dir=self.data)
        self.assertEqual(len(remote.calls), 2)                            # last_update + 1 table
        self.assertEqual(self.label(db), "remote-filament_materials")
        self.assertTrue((self.data / "id_material.json").exists())
        self.assertFalse((self.data / "id_brand.json").exists())
        self.assertEqual(db.info()["last_changed"], ["id_material.json"])

    def test_once_per_process_and_per_day(self) -> None:
        remote = FakeRemote({k: OLD for k in KEYS})
        with mock.patch.object(db_mod, "_open_url", remote):
            TigerTagDB(data_dir=self.data)
            TigerTagDB(data_dir=self.data)                                 # same process
        self.assertEqual(len(remote.calls), 1)
        db_mod._CHECKED_THIS_PROCESS.clear()                               # "new process"
        with mock.patch.object(db_mod, "_open_url", remote):
            TigerTagDB(data_dir=self.data)                                 # checked < 1 day ago
        self.assertEqual(len(remote.calls), 1)
        state = json.loads((self.data / "db_state.json").read_text())
        state["last_check"] = time.time() - 2 * 24 * 3600
        (self.data / "db_state.json").write_text(json.dumps(state))
        db_mod._CHECKED_THIS_PROCESS.clear()
        with mock.patch.object(db_mod, "_open_url", remote):
            TigerTagDB(data_dir=self.data)                                 # older than a day
        self.assertEqual(len(remote.calls), 2)

    def test_github_fallback(self) -> None:
        remote = FakeRemote({k: NEW for k in KEYS}, api_down=True)
        with mock.patch.object(db_mod, "_open_url", remote):
            db = TigerTagDB(data_dir=self.data)
        self.assertEqual(self.label(db), "remote-filament_materials")
        self.assertTrue(any(u.startswith(_GITHUB_RAW_BASE) for u in remote.calls))
        self.assertEqual(db.info()["last_source"], "github")

    def test_failure_is_tolerated(self) -> None:
        remote = FakeRemote({}, down=True)
        with mock.patch.object(db_mod, "_open_url", remote):
            db = TigerTagDB(data_dir=self.data)                            # must not raise
        self.assertEqual(self.label(db), "bundled-filament_materials")
        self.assertIn("unreachable", db.info()["last_error"])

    def test_auto_update_false_and_auto_sync_false(self) -> None:
        opener = mock.Mock()
        with mock.patch.object(db_mod, "_open_url", opener):
            TigerTagDB(data_dir=self.data, auto_update=False)
            TigerTagDB(data_dir=self.data, auto_sync=False)
        opener.assert_not_called()


class TestOffline(_Base):

    def test_env_and_flag_mean_no_network(self) -> None:
        opener = mock.Mock(side_effect=AssertionError("network in offline mode"))
        with mock.patch.object(db_mod, "_open_url", opener):
            db = TigerTagDB(data_dir=self.data, offline=True)
            self.assertEqual(self.label(db), "bundled-filament_materials")
            with self.assertRaises(RuntimeError):
                db.update()
            with mock.patch.dict(os.environ, {"TIGERTAG_OFFLINE": "1"}):
                db2 = TigerTagDB(data_dir=self.data)
                self.assertTrue(db2.info()["offline"])
                with self.assertRaises(RuntimeError):
                    db2.update(force=True)
        opener.assert_not_called()

    def test_catalog_offline_uses_bundled_gz(self) -> None:
        from tigertag import catalog as cat_mod
        from tigertag import TigerTag
        dl = mock.Mock(side_effect=AssertionError("catalogue download in offline mode"))
        with mock.patch.object(cat_mod, "_download", dl), \
             mock.patch.dict(os.environ, {"TIGERTAG_OFFLINE": "1"}):
            catalog = cat_mod.load_catalog(cache_dir=self.data)
            tag = TigerTag.from_catalog(3527039449, offline=True)
        dl.assert_not_called()
        self.assertIn(3527039449, catalog)
        self.assertEqual((tag.nozzle_temp_min, tag.nozzle_temp_max), (200, 250))
        self.assertEqual(cat_mod.catalog_info(self.data)["source"], "bundled")


class TestManualUpdate(_Base):

    def test_update_and_force(self) -> None:
        remote = FakeRemote({k: OLD for k in KEYS})
        with mock.patch.object(db_mod, "_open_url", remote):
            db = TigerTagDB(data_dir=self.data, auto_update=False)
            self.assertEqual(db.update(), [])                              # nothing newer
            self.assertEqual(len(remote.calls), 1)
            changed = db.update(force=True)
        self.assertEqual(sorted(changed), sorted(fn for _, fn in _DATASETS.values()))
        self.assertEqual(db.info()["tables"]["id_type.json"]["source"], "bundled")  # same ts → tie
        remote.ts = {k: NEW for k in KEYS}
        with mock.patch.object(db_mod, "_open_url", remote):
            self.assertEqual(len(db.update()), 7)
        self.assertEqual(db.info()["tables"]["id_type.json"]["source"], "downloaded")

    def test_update_custom_folder(self) -> None:
        custom = Path(self.tmp.name) / "mine"
        _write_set(custom, "custom", OLD)
        remote = FakeRemote({k: (NEW if k == "aspects" else OLD) for k in KEYS})
        with mock.patch.object(db_mod, "_open_url", remote):
            db = TigerTagDB(custom, data_dir=self.data)
            self.assertEqual(db.update(), ["id_aspect.json"])
        self.assertEqual(db.aspect(1)["label"], "remote-aspects")
        self.assertFalse((self.data / "id_aspect.json").exists())          # custom folder updated

    def test_info(self) -> None:
        db = TigerTagDB(data_dir=self.data, auto_update=False)
        info = db.info()
        self.assertEqual(info["data_dir"], str(self.data))
        self.assertFalse(info["offline"])
        self.assertEqual(set(info["tables"]), {fn for _, fn in _DATASETS.values()})
        t = info["tables"]["id_version.json"]
        self.assertEqual((t["source"], t["timestamp"]), ("bundled", OLD))
        self.assertIn("catalog", info)

    def test_sync_databases_compat(self) -> None:
        target = Path(self.tmp.name) / "legacy"
        remote = FakeRemote({k: OLD for k in KEYS})
        with mock.patch.object(db_mod, "_open_url", remote):
            updated = db_mod.sync_databases(target, verbose=False)
        self.assertIn("last_update.json", updated)
        self.assertEqual(len(updated), 8)


class TestCli(_Base):

    def test_cli_update(self) -> None:
        from tigertag import cli
        remote = FakeRemote({k: (NEW if k == "brands" else OLD) for k in KEYS})
        out = io.StringIO()
        with mock.patch.object(db_mod, "_open_url", remote), redirect_stdout(out), \
             mock.patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit) as ctx:
            cli.main(["update", "--data-dir", str(self.data)])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("id_brand.json", out.getvalue())
        self.assertTrue((self.data / "id_brand.json").exists())

    def test_cli_update_offline_refused(self) -> None:
        from tigertag import cli
        with mock.patch.dict(os.environ, {"TIGERTAG_OFFLINE": "1"}), \
             mock.patch.object(db_mod, "_open_url", mock.Mock()) as opener, \
             redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            with mock.patch("sys.stderr", io.StringIO()):
                cli.main(["update", "--data-dir", str(self.data)])
        self.assertEqual(ctx.exception.code, 1)
        opener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
