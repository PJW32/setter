"""백엔드 단위 테스트 (가짜 LLM·가짜 데이터, 네트워크 없음).

실행:  python -m unittest discover -s tests -v
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend import llm, presenter  # noqa: E402
from backend.agent import Agent  # noqa: E402
from backend.regions import Destination  # noqa: E402
from test_engine import DEST, make_dataset  # noqa: E402

BASE = dict(llm.EMPTY_CHANGES)


class FakeData:
    def __init__(self):
        self.calls = 0

    def resolve_destination(self, q):
        if q == "없는곳":
            return None
        return Destination(key=DEST, label=DEST, query=q, place_name=DEST, place_lon=127.0, place_lat=37.0,
                           lon=127.0, lat=37.0)

    def dataset_for(self, dest, log):
        self.calls += 1
        log("region", "done", "가짜 지역")
        ds = make_dataset()
        ds.meta = {"destination": dest.to_dict(), "sources": {"테스트": "가상 데이터"}}
        return ds


class FakeLLM:
    """턴마다 준비한 변경분을 돌려주고, 설명은 지정한 문장을 돌려준다."""

    enforce_comparisons = staticmethod(llm.enforce_comparisons)

    def __init__(self, turns, explanation="상위 동을 설명합니다."):
        self.turns = list(turns)
        self.explanation = explanation
        self.facts = []

    def extract(self, snapshot, text, last_q):
        return {**BASE, **self.turns.pop(0)}, {"ms": 1}

    def explain(self, facts):
        self.facts.append(facts)
        bad = llm.unknown_numbers(self.explanation, facts)
        return (None, {"rejected_numbers": [bad]}) if bad else (self.explanation, {"ms": 1})


def run(agent, s, text):
    return list(agent.handle(s, text))


def types(evs):
    return [e["type"] for e in evs]


class LlmHelpersTest(unittest.TestCase):
    def test_enforce_comparisons_raises_more_important_factor(self):
        ch = {"preference_changes": [{"factor": "commute", "level": "중요", "evidence": "x"}],
              "comparisons": [{"more": "monthly_cost", "less": "commute", "evidence": "월세가 통근보다 중요"}]}
        fixes = llm.enforce_comparisons(ch, {k: "보통" for k in
                                             ("monthly_cost", "commute", "station_access", "convenience", "quiet")})
        levels = {p["factor"]: p["level"] for p in ch["preference_changes"]}
        self.assertEqual(levels["monthly_cost"], "매우 중요")
        self.assertTrue(fixes)

    def test_enforce_comparisons_keeps_correct_order(self):
        ch = {"preference_changes": [{"factor": "monthly_cost", "level": "매우 중요", "evidence": "x"}],
              "comparisons": [{"more": "monthly_cost", "less": "commute", "evidence": "x"}]}
        self.assertEqual(llm.enforce_comparisons(ch, {"monthly_cost": "보통", "commute": "보통"}), [])

    def test_unknown_numbers(self):
        facts = {"월총비용_만원": 61.0, "통근_분": 11, "표본": "1,234"}
        self.assertEqual(llm.unknown_numbers("월 61만 원, 통근 11분, 표본 1,234건, 1위", facts), [])
        self.assertEqual(llm.unknown_numbers("월 59만 원", facts), ["59"])


class PresenterTest(unittest.TestCase):
    def test_pareto(self):
        rows = [{"dong_code": c, "raw": {"monthly_cost": m, "commute": t}} for c, m, t in
                [("a", 40, 50), ("b", 80, 10), ("c", 60, 30), ("d", 70, 40)]]
        self.assertEqual(presenter.pareto_codes(rows), {"a", "b", "c"})  # d 는 c 에 지배됨


class AgentTest(unittest.TestCase):
    def setUp(self):
        self.data = FakeData()

    def test_asks_destination_first(self):
        agent = Agent(self.data, FakeLLM([{"intent": "update", "set_constraints": {"max_monthly_rent": 60}}]))
        s = agent.new_session()
        evs = run(agent, s, "월세 60 이하")
        self.assertNotIn("result", types(evs))
        self.assertIn("출근", evs[-2]["text"])
        self.assertEqual(s.state.constraints.max_monthly_rent, 60)

    def test_full_turns_with_diff_and_number_check(self):
        fake = FakeLLM([
            {"intent": "update", "destination": "가상역", "set_constraints": {"max_commute_min": 45},
             "unsupported": ["이웃이 친절했으면"]},
            {"intent": "update", "preference_changes": [
                {"factor": "monthly_cost", "level": "매우 중요", "evidence": "월세가 제일 중요해"}]},
        ], explanation="1위 동을 추천합니다. 월 123456만 원")  # facts 에 없는 숫자 → 템플릿으로 대체
        agent = Agent(self.data, fake)
        s = agent.new_session()

        evs1 = run(agent, s, "가상역 출근, 통근 45분 이내")
        self.assertEqual(types(evs1)[-1], "done")
        res1 = next(e for e in evs1 if e["type"] == "result")["payload"]
        self.assertNotIn("가동", [d["name"] for d in res1["ranked"]])  # 통근 50분 → 제외
        msg = next(e for e in evs1 if e["type"] == "message")
        self.assertEqual(msg["source"], "template")
        self.assertIn("이웃이 친절했으면", msg["text"])
        self.assertIsNone(res1["diff"])

        evs2 = run(agent, s, "월세가 제일 중요해")
        res2 = next(e for e in evs2 if e["type"] == "result")["payload"]
        self.assertIsNotNone(res2["diff"])
        self.assertIn("월 총비용", res2["diff"]["weight_change"])
        self.assertEqual(self.data.calls, 1)  # 같은 목적지면 다시 불러오지 않음
        self.assertIn("changes", fake.facts[-1])

    def test_what_if_does_not_commit(self):
        agent = Agent(self.data, FakeLLM([
            {"intent": "update", "destination": "가상역"},
            {"intent": "what_if", "set_constraints": {"max_commute_min": 20}},
        ]))
        s = agent.new_session()
        run(agent, s, "가상역 출근")
        evs = run(agent, s, "통근 20분 이내면?")
        self.assertTrue(next(e for e in evs if e["type"] == "result")["what_if"])
        self.assertIsNone(s.state.constraints.max_commute_min)

    def test_unknown_destination_asks_again(self):
        agent = Agent(self.data, FakeLLM([{"intent": "update", "destination": "없는곳"}]))
        s = agent.new_session()
        evs = run(agent, s, "없는곳으로 출근")
        self.assertIn("찾지 못했어요", next(e for e in evs if e["type"] == "message")["text"])


class ApiTest(unittest.TestCase):
    def test_sse_stream(self):
        from fastapi.testclient import TestClient

        from backend import main

        main.agent = Agent(FakeData(), FakeLLM([{"intent": "update", "destination": "가상역"}]))
        c = TestClient(main.app)
        sid = c.post("/api/sessions").json()["session_id"]
        r = c.post(f"/api/sessions/{sid}/messages", json={"text": "가상역 출근"})
        self.assertEqual(r.status_code, 200)
        events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
        self.assertEqual(events[-1]["type"], "done")
        self.assertIn("result", types(events))
        view = c.get(f"/api/sessions/{sid}").json()
        self.assertEqual(view["state"]["destination"]["key"], DEST)
        self.assertTrue(view["result"]["ranked"])


if __name__ == "__main__":
    unittest.main()
