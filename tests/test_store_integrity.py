"""별도 임시 DB에서 재수집·실패 롤백·통근 캐시 일관성을 검증한다."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend import store


class StoreIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = patch.object(store, "DB_PATH", Path(self.tmp.name) / "store.sqlite")
        p.start()
        self.addCleanup(p.stop)
        store.init()
        self.a = {"dong_code": "9900010100", "lon": 127.0, "lat": 37.5}
        self.b = {"dong_code": "9900010200", "lon": 127.1, "lat": 37.5}
        self.deal = {"dong_code": self.a["dong_code"], "house_type": "오피스텔", "area_m2": 20,
                     "area_kind": "전용", "deposit": 0, "monthly_rent": 30,
                     "deal_ym": "202610", "contract_kind": "신규"}
        store.save_sgg("99000", "가상도", "가상구", [self.a, self.b], [self.deal])
        store.save_commutes("가상역", {self.a["dong_code"]: {"min": 10}, self.b["dong_code"]: {"min": 20}})

    def test_same_coordinates_keep_cache_and_changed_coordinates_remove_it(self):
        moved = {**self.a, "lon": 127.01}
        store.save_sgg("99000", "가상도", "가상구", [moved, self.b], [self.deal])
        self.assertEqual(store.commutes("가상역", [self.a["dong_code"], self.b["dong_code"]]),
                         {self.b["dong_code"]: {"min": 20}})

    def test_removed_dong_loses_commute_and_unmatched_deals_are_not_counted(self):
        store.save_sgg("99000", "가상도", "가상구", [self.a],
                       [self.deal, {"dong_code": ""}, {"dong_code": self.b["dong_code"]}])
        self.assertEqual(store.sgg_status("99000")["deal_count"], 1)
        self.assertEqual(len(store.deals_for([self.a["dong_code"], self.b["dong_code"]])), 1)
        self.assertNotIn(self.b["dong_code"], store.commutes("가상역", [self.b["dong_code"]]))

    def test_failed_refresh_rolls_back_dongs_deals_and_commutes(self):
        broken = dict(self.deal)
        del broken["monthly_rent"]
        with self.assertRaises(KeyError):
            store.save_sgg("99000", "가상도", "가상구", [{**self.a, "lon": 128.0}], [broken])
        self.assertEqual(len(store.dongs_in(["99000"])), 2)
        self.assertEqual(store.sgg_status("99000")["deal_count"], 1)
        self.assertEqual(store.commutes("가상역", [self.a["dong_code"]]), {self.a["dong_code"]: {"min": 10}})
        self.assertEqual(len(store.deals_for([self.a["dong_code"]])), 1)

    def test_duplicate_dong_is_rejected_before_existing_data_changes(self):
        with self.assertRaises(ValueError):
            store.save_sgg("99000", "가상도", "가상구", [self.a, self.a], [])
        self.assertEqual(len(store.dongs_in(["99000"])), 2)
