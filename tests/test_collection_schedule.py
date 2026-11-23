"""실제 공급자 호출 없이 시군구 스케줄과 추천 입력의 일관성을 검증한다."""
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from backend import regions
from engine import State, Params, evaluate
from engine.data import Dataset
from test_backend import FakeData
from test_engine import DEST, make_dataset


class CollectionScheduleTest(unittest.TestCase):
    def setUp(self):
        with patch.object(regions.store, "init"):
            self.service = regions.DataService()
        self.dest = FakeData().resolve_destination(DEST)
        self.candidates = {str(i): {"sido": "가상도", "name": str(i), "seed": (127, 37)} for i in range(4)}

    def test_two_districts_overlap_and_global_pool_is_bounded(self):
        ready, release = threading.Event(), threading.Event()
        lock = threading.Lock()
        active, peak, seen = 0, 0, []

        def collect(code, *args):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                seen.append(code)
                if active == 2:
                    ready.set()
            try:
                if not release.wait(3):
                    raise RuntimeError("overlap test timed out")
            finally:
                with lock:
                    active -= 1

        with patch.object(regions, "candidate_sggs", return_value=self.candidates), \
                patch.object(regions.store, "sgg_status", return_value=None), \
                patch.object(regions, "ensure_sgg", side_effect=collect), \
                patch.object(regions, "build_dataset", return_value=Dataset([], {})), \
                ThreadPoolExecutor(max_workers=2) as callers:
            a = callers.submit(self.service.dataset_for, self.dest)
            b = callers.submit(self.service.dataset_for, self.dest)
            try:
                self.assertTrue(ready.wait(2), "districts were processed serially")
                with lock:
                    self.assertEqual(active, 2)
            finally:
                release.set()
            a.result(timeout=3)
            b.result(timeout=3)
        self.assertEqual(peak, 2)
        self.assertCountEqual(seen, list(self.candidates) * 2)

    def test_cached_districts_are_not_submitted_and_timing_has_no_secrets(self):
        logs = []
        with patch.object(regions, "candidate_sggs", return_value=self.candidates), \
                patch.object(regions.store, "sgg_status", return_value={"status": "done"}), \
                patch.object(regions, "ensure_sgg") as collect, \
                patch.object(regions, "build_dataset", return_value=Dataset([], {})) as build:
            self.service.dataset_for(self.dest, lambda *a, **kw: logs.append((a, kw)))
        collect.assert_not_called()
        self.assertEqual(build.call_args.args[1], list(self.candidates))
        timings = [kw for _, kw in logs if "ms" in kw]
        self.assertEqual(len(timings), 3)
        self.assertTrue(all(isinstance(kw["ms"], int) and kw["ms"] >= 0 for kw in timings))
        collect_log = next((args, kw) for args, kw in logs if args[:2] == ("collect", "done"))
        self.assertIn(f"전체 경과 {collect_log[1]['ms'] / 1000:.1f}초", collect_log[0][2])
        dataset_log = next((args, kw) for args, kw in logs if args[:2] == ("dataset", "done"))
        self.assertIn(f"전체 경과 {dataset_log[1]['total_ms'] / 1000:.1f}초", dataset_log[0][2])

    def test_unexpected_failure_drains_other_work_before_returning(self):
        completed = []

        def collect(code, *args):
            if code == "0":
                raise RuntimeError("failure")
            completed.append(code)

        with patch.object(regions, "candidate_sggs", return_value=self.candidates), \
                patch.object(regions.store, "sgg_status", return_value=None), \
                patch.object(regions, "ensure_sgg", side_effect=collect), \
                patch.object(regions, "build_dataset") as build:
            with self.assertRaises(RuntimeError):
                self.service.dataset_for(self.dest)
        self.assertCountEqual(completed, ["1", "2", "3"])
        build.assert_not_called()

    def test_insertion_order_does_not_change_dataset_or_ranking(self):
        source = make_dataset()
        rows = [{**deal.__dict__} for group in source.deals_by_dong.values() for deal in group]
        commutes = {d["dong_code"]: d["commute"][DEST] for d in source.dongs}
        outputs = []
        for dongs in (source.dongs, list(reversed(source.dongs))):
            with patch.object(regions.store, "dongs_in", return_value=dongs), \
                    patch.object(regions.store, "deals_for", return_value=rows), \
                    patch.object(regions, "ensure_commutes", return_value=commutes):
                ds = regions.build_dataset(self.dest, ["99000"], 10)
            outputs.append(ds)
        self.assertEqual(outputs[0], outputs[1])
        state = State(params=Params(destination=DEST))
        self.assertEqual(evaluate(outputs[0], state), evaluate(outputs[1], state))


if __name__ == "__main__":
    unittest.main()
