import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import prewarm_rent as cli
from collectors import molit


class RentSnapshotTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "rent.sqlite"
        for name, value in (("RENT_MONTHS", 1), ("RENT_END_YM", "202610")):
            p = patch.object(cli.S, name, value)
            p.start()
            self.addCleanup(p.stop)

    def rows(self, house_type, code, ym, *, offline):
        return [{"sggCd": code, "umdNm": "가동", "dealYear": ym[:4], "dealMonth": ym[4:],
                 "deposit": "1,000", "monthlyRent": "20", "excluUseAr": "25", "totalFloorAr": "25"}]

    def test_build_preserves_records_and_second_run_makes_no_fetches(self):
        fetch = Mock(side_effect=self.rows)
        for _ in range(2):
            self.assertEqual(cli.build_snapshot(["41135"], self.path, offline=True, fetch=fetch, emit=lambda _: None), 0)
        self.assertEqual(fetch.call_count, 3)
        with closing(sqlite3.connect(self.path)) as conn:
            rows = conn.execute("SELECT data FROM rental").fetchall()
            self.assertEqual(len(rows), 3)
            self.assertEqual(json.loads(rows[0][0])["deposit"], 1000)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM collection").fetchone()[0], 3)

    def test_failure_is_not_marked_complete_and_can_resume(self):
        fetch = Mock(side_effect=[RuntimeError("secret"), self.rows("a", "41135", "202610", offline=True), []])
        self.assertEqual(cli.build_snapshot(["41135"], self.path, True, fetch, lambda _: None), 1)
        resumed = Mock(side_effect=self.rows)
        self.assertEqual(cli.build_snapshot(["41135"], self.path, True, resumed, lambda _: None), 0)
        resumed.assert_called_once()

    def test_wrong_region_does_not_commit(self):
        fetch = Mock(return_value=self.rows("a", "99999", "202610", offline=True))
        self.assertEqual(cli.build_snapshot(["41135"], self.path, True, fetch, lambda _: None), 1)
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM rental").fetchone()[0], 0)

    def test_backend_reads_completed_snapshot_and_detects_incomplete_data(self):
        cli.build_snapshot(["41135"], self.path, True, self.rows, lambda _: None)
        with patch.object(molit, "RENT_SNAPSHOT_PATH", self.path):
            records = molit.prepared_records("오피스텔", "41135", "202610")
            self.assertEqual(records, [molit.normalize("오피스텔", self.rows("오피스텔", "41135", "202610", offline=True)[0])])
            self.assertIsNone(molit.prepared_records("오피스텔", "99999", "202610"))
            with closing(sqlite3.connect(self.path)) as conn, conn:
                conn.execute("DELETE FROM rental")
            self.assertIsNone(molit.prepared_records("오피스텔", "41135", "202610"))

    def test_region_collector_uses_snapshot_without_rental_api(self):
        from backend import regions
        cli.build_snapshot(["41135"], self.path, True, self.rows, lambda _: None)
        with patch.object(molit, "RENT_SNAPSHOT_PATH", self.path), \
                patch.object(regions.store, "sgg_status", side_effect=[None, {"status": "done"}]), \
                patch.object(regions.store, "save_sgg") as save, \
                patch.object(regions.region, "discover", return_value={}), \
                patch.object(regions, "get_key", return_value="configured"), \
                patch.object(molit, "fetch_raw") as fetch:
            result = regions.ensure_sgg("41135", "가상도", "가상시", (127, 37))
            self.assertEqual(result["status"], "done")
            self.assertEqual(len(save.call_args.args[4]), 3)
            fetch.assert_not_called()
