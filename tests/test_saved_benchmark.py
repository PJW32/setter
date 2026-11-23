import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backend import store
from scripts.benchmark_saved_search import benchmark
from test_engine import DEST, make_dataset


class SavedBenchmarkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "source.sqlite"
        p = patch.object(store, "DB_PATH", self.path)
        p.start()
        self.addCleanup(p.stop)
        store.init()
        ds = make_dataset()
        deals = [r.__dict__ for rows in ds.deals_by_dong.values() for r in rows]
        store.save_sgg("99000", "가상도", "가상시", ds.dongs, deals)
        store.save_commutes(DEST, {d["dong_code"]: d["commute"][DEST] for d in ds.dongs})

    def test_restored_results_repeat_without_network_or_source_writes(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with patch("socket.create_connection", side_effect=AssertionError("network forbidden")):
            report = benchmark(self.path, DEST, repeats=2)
        self.assertEqual(report["isolated_sqlite_restore"], "passed")
        self.assertEqual(report["result_repeatability"], "passed")
        self.assertEqual([r["candidate_count"] for r in report["runs"]], [6, 6])
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)

    def test_missing_database_or_routes_fail_instead_of_reporting_fast_success(self):
        with self.assertRaises(sqlite3.OperationalError):
            benchmark(self.path.parent / "missing.sqlite", DEST, 1)
        self.assertFalse((self.path.parent / "missing.sqlite").exists())
        with self.assertRaisesRegex(ValueError, "저장된 통근 후보"):
            benchmark(self.path, "없는역", 1)
