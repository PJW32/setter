"""사전 수집 CLI의 오프라인 조회, 캐시 재사용, 부분 실패와 재개 동작을 검증한다."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend import store
from backend.regions import DataService
from engine.data import Dataset
from scripts import prewarm_data as cli
from test_backend import FakeData
from test_engine import DEST, deals, dong


class PrewarmTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.report = self.root / "report.json"

    def service(self):
        d = dong("9900000001", "가동", commute=10, fare=0, walk=2, conv=10, bars=1)
        service = Mock(radius_km=10)
        service.resolve_destination.side_effect = FakeData().resolve_destination
        service.dataset_for.return_value = Dataset([d], {d["dong_code"]: deals(d["dong_code"], [20] * 5)})
        return service

    def test_no_arguments_or_status_never_starts_collection(self):
        with patch.object(cli, "DataService") as create, patch("builtins.print"):
            self.assertEqual(cli.main([]), 0)
            with patch.object(store, "DB_PATH", self.root / "missing.sqlite"):
                self.assertEqual(cli.main(["--status"]), 0)
            create.assert_not_called()
        self.assertFalse((self.root / "missing.sqlite").exists())

    def test_missing_keys_prevent_partial_dataset_creation(self):
        with patch.object(cli, "get_key", return_value=None), patch.object(cli, "DataService") as create, patch("builtins.print"):
            self.assertEqual(cli.main(["판교역", "--include-kakao"]), 2)
            create.assert_not_called()

    def test_full_collection_requires_explicit_kakao_scope_confirmation(self):
        with patch.object(cli, "DataService") as create, patch("builtins.print"):
            self.assertEqual(cli.main(["판교역"]), 2)
            create.assert_not_called()

    def test_destinations_are_deduplicated_and_reported(self):
        service = self.service()
        self.assertEqual(cli.prewarm([DEST, DEST], service, self.report, emit=lambda _: None), 0)
        report = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertEqual(len(report["results"]), 1)
        self.assertEqual(report["results"][0]["status"], "done")
        service.dataset_for.assert_called_once()

    def test_failure_does_not_stop_next_destination_or_expose_exception(self):
        service = self.service()
        destination = FakeData().resolve_destination(DEST)
        service.resolve_destination.side_effect = [RuntimeError("secret-provider-url"), destination]
        self.assertEqual(cli.prewarm(["없는곳", DEST], service, self.report, emit=lambda _: None), 1)
        text = self.report.read_text(encoding="utf-8")
        results = json.loads(text)["results"]
        self.assertEqual([r["status"] for r in results], ["failed", "done"])
        self.assertNotIn("secret-provider-url", text)

    def test_missing_routes_or_fares_are_partial_not_success(self):
        for route in ({"error": "NO_RESULTS"}, {"min": 10, "fare": None}):
            service = self.service()
            service.dataset_for.return_value.dongs[0]["commute"][DEST] = route
            self.assertEqual(cli.prewarm([DEST], service, self.report, emit=lambda _: None), 1)
            row = json.loads(self.report.read_text(encoding="utf-8"))["results"][0]
            self.assertEqual(row["status"], "partial")
            self.assertGreater(row["missing_fares"], 0)

    def test_collection_error_or_empty_dataset_is_not_success(self):
        for empty in (False, True):
            service = self.service()
            ds = Dataset([], {}) if empty else service.dataset_for.return_value

            def dataset_for(dest, log):
                log("collect", "error", "일부 지역 실패")
                return ds

            service.dataset_for.side_effect = dataset_for
            self.assertEqual(cli.prewarm([DEST], service, self.report, emit=lambda _: None), 1)
            row = json.loads(self.report.read_text(encoding="utf-8"))["results"][0]
            self.assertEqual(row["status"], "failed" if empty else "partial")

    def test_interrupt_records_progress_and_stops(self):
        service = self.service()
        service.dataset_for.side_effect = KeyboardInterrupt()
        self.assertEqual(cli.prewarm([DEST, "다른역"], service, self.report, emit=lambda _: None), 130)
        results = json.loads(self.report.read_text(encoding="utf-8"))["results"]
        self.assertEqual([r["status"] for r in results], ["interrupted"])

    def test_existing_database_is_reused_without_region_or_transit_collection(self):
        with patch.object(store, "DB_PATH", self.root / "store.sqlite"):
            store.init()
            code = "9900000001"
            d = dong(code, "가동", commute=10, fare=0, walk=2, conv=10, bars=1)
            rows = [{**r.__dict__, "sgg_code": "99000"} for r in deals(code, [20] * 5)]
            store.save_sgg("99000", "가상도", "가상시", [d], rows)
            store.save_commutes(DEST, {code: {"min": 10, "fare": 0}})
            service = DataService()
            destination = FakeData().resolve_destination(DEST)
            candidates = {"99000": {"sido": "가상도", "name": "가상시", "seed": (127, 37)}}
            with patch.object(service, "resolve_destination", return_value=destination), \
                    patch("backend.regions.candidate_sggs", return_value=candidates), \
                    patch("backend.regions.region.discover") as discover, \
                    patch("backend.regions.molit.fetch_raw") as rent, \
                    patch("backend.regions.kakao.transit") as transit:
                for _ in range(2):
                    self.assertEqual(cli.prewarm([DEST], service, self.report, emit=lambda _: None), 0)
                discover.assert_not_called()
                rent.assert_not_called()
                transit.assert_not_called()
            snapshot = cli.saved_status()
            self.assertEqual(snapshot["regions"][0]["deal_count"], 5)
            self.assertEqual(snapshot["commutes_by_destination"][0]["stored_rows"], 1)


if __name__ == "__main__":
    unittest.main()
