"""점수 엔진 단위 테스트 (가상 지역, LLM·API 없음).

실행:  python -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import Constraints, Params, State, apply_changes, build_features, compare, evaluate, normalize_weights, rank  # noqa: E402
from engine.data import Dataset, Deal  # noqa: E402
from engine.diff import explain_pair  # noqa: E402

DEST = "가상역"


def dong(code, name, *, commute, fare=1500, walk, conv, bars):
    c = {"min": commute, "fare": fare, "transfers": 0, "mode": "지하철", "lines": []} if commute else {"error": "NO_RESULTS"}
    return {
        "dong_code": code, "sido": "가상도", "sgg": "가상시", "name": name, "lon": 127.0, "lat": 37.0,
        "station": {"name": f"{name}역", "lines": [], "dist_m": walk * 50, "walk_min": walk} if walk else None,
        "convenience": {"편의점": conv, "약국": conv // 2},
        "bars": {"count": bars},
        "commute": {DEST: c},
    }


def deals(code, rents, *, deposit=1000, house_type="오피스텔", area=25.0, kind="신규"):
    return [Deal(code, house_type, area, "전용", deposit, r, "202610", kind) for r in rents]


def make_dataset() -> Dataset:
    dongs = [
        dong("9900000001", "가동", commute=50, walk=5, conv=20, bars=30),   # 싸고 멀고 시끄러움
        dong("9900000002", "나동", commute=10, walk=3, conv=22, bars=40),   # 비싸고 가까움
        dong("9900000003", "다동", commute=25, walk=10, conv=10, bars=5),   # 중간
        dong("9900000004", "라동", commute=30, walk=20, conv=2, bars=0),    # 조용하고 불편
        dong("9900000005", "마동", commute=20, walk=8, conv=8, bars=10),    # 실거래 부족
        dong("9900000006", "바동", commute=None, walk=None, conv=5, bars=3),  # 통근 경로 없음, 역 없음
    ]
    by = {
        "9900000001": deals("9900000001", [38, 40, 40, 42, 45, 39, 41]),
        "9900000002": deals("9900000002", [75, 78, 80, 82, 85, 79, 81]),
        "9900000003": deals("9900000003", [55, 58, 60, 62, 65, 59, 61]),
        "9900000004": deals("9900000004", [50, 52, 55, 57, 60, 54, 56])
        + deals("9900000004", [20, 20, 20], house_type="단독다가구", area=20.0),
        "9900000005": deals("9900000005", [50, 52]),
        "9900000006": deals("9900000006", [48, 50, 50, 52, 55]),
    }
    return Dataset(dongs=dongs, deals_by_dong=by)


ALL_NORMAL = {k: "보통" for k in ("monthly_cost", "commute", "station_access", "convenience", "quiet")}


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.ds = make_dataset()
        self.params = Params(destination=DEST, house_types=("오피스텔",))
        self.feats = build_features(self.ds, self.params)

    # ---------------------------------------------------------------- 가중치
    def test_weights_sum_to_one(self):
        w = normalize_weights({**ALL_NORMAL, "monthly_cost": "매우 중요", "quiet": "상관없음"})
        self.assertAlmostEqual(sum(w.values()), 1.0)
        self.assertEqual(w["quiet"], 0.0)
        self.assertAlmostEqual(w["monthly_cost"], 4 / 10)

    def test_all_zero_weights_become_equal(self):
        w = normalize_weights({k: "상관없음" for k in ALL_NORMAL})
        self.assertTrue(all(abs(v - 0.2) < 1e-9 for v in w.values()))

    # ---------------------------------------------------------------- 재현성
    def test_same_input_same_output(self):
        a = rank(self.feats, ALL_NORMAL).to_dict()
        b = rank(build_features(self.ds, self.params), ALL_NORMAL).to_dict()
        self.assertEqual(a, b)

    def test_scores_are_sum_of_contributions(self):
        for e in rank(self.feats, ALL_NORMAL).ranked:
            self.assertAlmostEqual(e["score"], sum(e["contrib"].values()), places=1)

    # ---------------------------------------------------------------- 필수 조건과 고정 정규화
    def test_commute_limit_excludes_without_changing_others(self):
        base = rank(self.feats, ALL_NORMAL)
        limited = rank(self.feats, ALL_NORMAL, Constraints(max_commute_min=40))
        self.assertNotIn("가동", [e["name"] for e in limited.ranked])
        ex = {e["name"]: e for e in limited.excluded}
        self.assertEqual(ex["가동"]["violations"][0]["relax_to"], {"max_commute_min": 50})
        # 가동이 빠져도 남은 동의 정규화 값·점수는 그대로
        b = base.by_code()
        for e in limited.ranked:
            self.assertEqual(e["norm"], b[e["dong_code"]]["norm"])
            self.assertEqual(e["score"], b[e["dong_code"]]["score"])

    def test_budget_excludes_expensive_dong_and_suggests_relaxation(self):
        r = rank(self.feats, ALL_NORMAL, Constraints(max_monthly_rent=60))
        ex = {e["name"]: e for e in r.excluded}
        self.assertIn("나동", ex)
        v = ex["나동"]["violations"][0]
        self.assertEqual(v["constraint"], "budget")
        self.assertEqual(v["in_budget"], 0)
        self.assertGreaterEqual(v["relax_to"]["max_monthly_rent"], 79)  # 3번째로 싼 거래가 79

    def test_budget_uses_in_budget_deals_for_cost(self):
        base = rank(self.feats, ALL_NORMAL).by_code()
        r = rank(self.feats, ALL_NORMAL, Constraints(max_monthly_rent=58))
        # 다동: 58 이하 거래가 55, 58 두 건뿐 → 제외
        self.assertIn("다동", [e["name"] for e in r.excluded])
        # 라동: 58 이하 6건 → 통과, 월 총비용은 예산 안 거래의 중앙값이라 전체 중앙값보다 낮다
        ra = next(e for e in r.ranked if e["name"] == "라동")
        self.assertIn("예산 안 거래 6/7건", ra["flags"])
        self.assertLess(ra["raw"]["monthly_cost"], base["9900000004"]["raw"]["monthly_cost"])

    def test_near_misses_when_nothing_passes(self):
        r = rank(self.feats, ALL_NORMAL, Constraints(max_monthly_rent=30))
        self.assertLess(len(r.ranked), 3)
        self.assertTrue(r.near_misses)
        self.assertTrue(r.notes)
        self.assertEqual(r.near_misses[0]["name"], "가동")  # 가장 적게 올리면 되는 동

    def test_unverified_budget_is_flagged_not_excluded(self):
        r = rank(self.feats, ALL_NORMAL, Constraints(max_monthly_rent=60))
        ma = next(e for e in r.ranked if e["name"] == "마동")
        self.assertTrue(any("예산 확인 불가" in f for f in ma["flags"]))

    # ---------------------------------------------------------------- 데이터 부족
    def test_missing_cost_is_filled_with_median_and_flagged(self):
        r = rank(self.feats, ALL_NORMAL)
        ma = next(e for e in r.ranked if e["name"] == "마동")
        self.assertIn("monthly_cost", ma["estimated"])
        self.assertTrue(any("월 총비용 데이터 부족" in f for f in ma["flags"]))
        others = sorted(e["norm"]["monthly_cost"] for e in r.ranked if "monthly_cost" not in e["estimated"])
        self.assertGreater(ma["norm"]["monthly_cost"], others[0])   # 가장 나쁜 값보다 낫고
        self.assertLess(ma["norm"]["monthly_cost"], others[-1])     # 가장 좋은 값보다 못함

    def test_no_station_is_far_not_missing(self):
        ba = next(f for f in self.feats if f.dong["name"] == "바동")
        self.assertEqual(ba.raw["station_access"], 60.0)
        self.assertIsNone(ba.raw["commute"])

    # ---------------------------------------------------------------- 가중치 변경과 순위 변동
    def test_cost_priority_moves_cheap_dong_up_and_diff_adds_up(self):
        before = rank(self.feats, ALL_NORMAL)
        after = rank(self.feats, {**ALL_NORMAL, "monthly_cost": "매우 중요", "commute": "조금"})
        rb, ra = before.by_code(), after.by_code()
        self.assertLess(ra["9900000001"]["rank"], rb["9900000001"]["rank"])  # 가동(싸다)이 올라감
        pair = explain_pair(before, after, "9900000001", "9900000002")
        self.assertAlmostEqual(pair["gap_after"] - pair["gap_before"], sum(pair["by_factor"].values()), places=1)
        top_factor = next(iter(pair["by_factor"]))
        self.assertIn(top_factor, ("월 총비용", "통근 시간"))
        d = compare(before, after)
        self.assertIn("월 총비용", d["weight_change"])
        self.assertTrue(d["moves"])

    # ---------------------------------------------------------------- 파라미터
    def test_house_type_filter(self):
        only_offi = {f.dong["name"]: f for f in self.feats}
        both = {f.dong["name"]: f for f in build_features(
            self.ds, Params(destination=DEST, house_types=("오피스텔", "단독다가구")))}
        self.assertEqual(only_offi["라동"].detail["monthly_cost"]["samples"], 7)
        self.assertEqual(both["라동"].detail["monthly_cost"]["samples"], 10)
        self.assertLess(both["라동"].raw["monthly_cost"], only_offi["라동"].raw["monthly_cost"])

    def test_unknown_destination_raises(self):
        with self.assertRaises(ValueError):
            build_features(self.ds, Params(destination="판교역"))

    # ---------------------------------------------------------------- 대화 상태
    def test_apply_changes_validates_and_keeps_original(self):
        s0 = State(params=Params(destination=DEST, house_types=("오피스텔",)))
        s1, rep = apply_changes(s0, {
            "set_constraints": {"max_monthly_rent": 60, "max_floor": 3},
            "params": {"destination": "없는역", "house_types": ["오피스텔", "아파트"]},
            "preference_changes": [
                {"factor": "monthly_cost", "level": "매우 중요", "evidence": "월세가 제일 중요해"},
                {"factor": "neighbors", "level": "중요"},
                {"factor": "quiet", "level": "엄청"},
            ],
        }, destinations=[DEST], utterance="테스트")
        self.assertEqual(s1.levels["monthly_cost"], "매우 중요")
        self.assertEqual(s1.constraints.max_monthly_rent, 60)
        self.assertEqual(s1.params.destination, DEST)
        rejected = {r["item"] for r in rep["rejected"]}
        self.assertTrue({"max_floor", "destination", "neighbors", "quiet:엄청"} <= rejected)
        self.assertEqual(s0.levels["monthly_cost"], "보통")  # 원래 상태는 그대로
        self.assertEqual(len(s1.history), 1)

    def test_clear_constraint_and_evaluate(self):
        s = State(params=Params(destination=DEST, house_types=("오피스텔",)))
        s, _ = apply_changes(s, {"set_constraints": {"max_commute_min": 40}})
        self.assertNotIn("가동", [e["name"] for e in evaluate(self.ds, s).ranked])
        s, rep = apply_changes(s, {"clear_constraints": ["max_commute_min"]})
        self.assertIn("가동", [e["name"] for e in evaluate(self.ds, s).ranked])
        self.assertEqual(rep["applied"][0]["after"], None)


if __name__ == "__main__":
    unittest.main()
