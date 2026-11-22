"""예산 경계값・비교군 일치・교통비 미확인 회귀 테스트 (외부 호출 없음)."""

import json
import unittest

from backend import presenter
from engine import Constraints, Params, build_features, rank
from engine.data import Dataset
from test_engine import ALL_NORMAL, DEST, deals, dong


class CostRegressionTest(unittest.TestCase):
    def dataset(self, rows, fare=0):
        d = dong("a", "가동", commute=10, fare=fare, walk=2, conv=10, bars=1)
        return Dataset([d], {"a": rows})

    def evaluate(self, ds, constraints):
        features = build_features(ds, Params(destination=DEST, house_types=("오피스텔",)))
        return rank(features, ALL_NORMAL, constraints)

    def test_zero_deposit_transactions_pass_zero_cap(self):
        ds = self.dataset(deals("a", [20] * 5, deposit=0))
        result = self.evaluate(ds, Constraints(max_deposit=0, max_monthly_rent=30))
        self.assertEqual(len(result.ranked), 1)
        self.assertEqual(result.ranked[0]["raw"]["monthly_cost"], 20)
        json.dumps(presenter.result_payload(result, {}, None, []), allow_nan=False)

    def test_positive_deposits_excluded_with_finite_relaxation(self):
        ds = self.dataset(deals("a", [20] * 5, deposit=1000))
        result = self.evaluate(ds, Constraints(max_deposit=0, max_monthly_rent=30))
        self.assertEqual(len(result.excluded), 1)
        violation = result.excluded[0]["violations"][0]
        self.assertEqual(violation["relax_to"]["max_deposit"], 1000)
        json.dumps(result.to_dict(), allow_nan=False)
        json.dumps(presenter.result_payload(result, {}, None, []), allow_nan=False)

    def test_two_zero_deposits_are_not_enough_and_relaxation_is_feasible(self):
        rows = deals("a", [20] * 2, deposit=0) + deals("a", [20] * 3, deposit=500)
        ds = self.dataset(rows)
        result = self.evaluate(ds, Constraints(max_deposit=0, max_monthly_rent=30))
        violation = result.excluded[0]["violations"][0]
        self.assertEqual(violation["in_budget"], 2)
        relaxed = self.evaluate(ds, Constraints(**violation["relax_to"]))
        self.assertEqual(len(relaxed.ranked), 1)
        json.dumps(result.to_dict(), allow_nan=False)

    def test_budget_detail_and_llm_facts_use_the_same_transactions(self):
        ds = self.dataset(deals("a", [20] * 3, deposit=0) + deals("a", [100] * 8, deposit=1000))
        features = build_features(ds, Params(destination=DEST))
        result = rank(features, ALL_NORMAL, Constraints(max_monthly_rent=30))
        card = presenter.dong_card(result.ranked[0])
        self.assertEqual(card["cost"]["monthly_total"], 20)
        self.assertEqual(card["cost"]["median_rent"], 20)
        self.assertEqual(card["cost"]["median_deposit"], 0)
        self.assertEqual(card["cost"]["samples"], 3)
        self.assertEqual(features[0].detail["monthly_cost"]["median_rent"], 100)
        self.assertEqual(features[0].detail["monthly_cost"]["samples"], 11)
        self.assertEqual(presenter.dong_facts(result.ranked[0])["월세_중앙값_만원"], 20)

    def test_missing_fare_does_not_become_zero_or_verified_total(self):
        ds = self.dataset(deals("a", [20] * 5, deposit=0), fare=None)
        for constraints in (Constraints(max_monthly_cost=25),
                            Constraints(max_monthly_rent=30, max_monthly_cost=25)):
            with self.subTest(constraints=constraints):
                result = self.evaluate(ds, constraints)
                entry = result.ranked[0]
                self.assertIsNone(entry["raw"]["monthly_cost"])
                self.assertIn("monthly_cost", entry["estimated"])
                self.assertIn("교통비 확인 불가", entry["flags"])
                self.assertIn("월 총비용 한도 확인 불가", entry["flags"])
                self.assertIsNone(presenter.dong_card(entry)["cost"]["fare_month"])

    def test_known_zero_fare_is_valid(self):
        ds = self.dataset(deals("a", [20] * 5, deposit=0), fare=0)
        entry = self.evaluate(ds, Constraints(max_monthly_cost=25)).ranked[0]
        self.assertEqual(entry["raw"]["monthly_cost"], 20)
        self.assertNotIn("교통비 확인 불가", entry["flags"])

    def test_relaxation_changes_only_required_budget_limits(self):
        cases = [
            (1000, 20, {"max_deposit": 0, "max_monthly_rent": 30}, {"max_deposit": 1000}),
            (500, 40, {"max_deposit": 1000, "max_monthly_rent": 30}, {"max_monthly_rent": 40}),
            (1000, 40, {"max_deposit": 0, "max_monthly_rent": 30},
             {"max_deposit": 1000, "max_monthly_rent": 40}),
        ]
        for deposit, rent, original, expected in cases:
            with self.subTest(deposit=deposit, rent=rent):
                ds = self.dataset(deals("a", [rent] * 5, deposit=deposit))
                result = self.evaluate(ds, Constraints(**original))
                relax = result.excluded[0]["violations"][0]["relax_to"]
                self.assertEqual(relax, expected)
                self.assertEqual(len(self.evaluate(ds, Constraints(**{**original, **relax})).ranked), 1)

    def test_joint_relaxation_uses_real_transaction_pairs(self):
        rows = (deals("a", [20] * 2, deposit=1000)
                + deals("a", [100] * 3, deposit=0))
        ds = self.dataset(rows)
        original = {"max_deposit": 0, "max_monthly_rent": 30}
        result = self.evaluate(ds, Constraints(**original))
        relax = result.excluded[0]["violations"][0]["relax_to"]
        self.assertEqual(len(self.evaluate(ds, Constraints(**{**original, **relax})).ranked), 1)
        json.dumps(result.to_dict(), allow_nan=False)

    def test_template_formats_missing_cost_and_commute_without_none(self):
        ds = self.dataset(deals("a", [20] * 5, deposit=0), fare=None)
        ds.dongs[0]["commute"][DEST] = {"error": "NO_RESULTS"}
        result = self.evaluate(ds, Constraints(max_monthly_cost=25))
        facts = presenter.facts(result, destination={"label": DEST}, report=None, diff=None,
                                trade=[], unsupported=[], follow_up=None, question=None)
        text = presenter.template_explanation(facts)
        self.assertNotIn("None", text)
        self.assertIn("월 총비용 확인 불가", text)
        self.assertIn("통근 확인 불가", text)

    def test_template_preserves_numeric_zero(self):
        facts = {"상위": [{"순위": 1, "동": "가동", "월총비용_만원": 0,
                          "통근_분": 0, "강점": []}],
                 "목적지": DEST, "후보_동_수": 1, "통과_동_수": 1}
        text = presenter.template_explanation(facts)
        self.assertIn("월 총비용 0만 원", text)
        self.assertIn("통근 0분", text)


if __name__ == "__main__":
    unittest.main()
