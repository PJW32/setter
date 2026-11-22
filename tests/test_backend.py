"""백엔드 단위 테스트 (가짜 LLM·가짜 데이터, 네트워크 없음).

실행:  python -m unittest discover -s tests -v
"""

import json
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend import llm, presenter  # noqa: E402
from backend.agent import Agent  # noqa: E402
from backend.regions import Destination  # noqa: E402
from engine.data import Dataset  # noqa: E402
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

    def __init__(self, turns, explanation="상위 동을 설명합니다.", answer_fn=None):
        self.turns = list(turns)
        self.explanation = explanation
        self.answer_fn = answer_fn or (lambda f: "지금 결과로 답합니다.")
        self.facts = []
        self.answer_facts = []
        self.snapshots = []

    def extract(self, snapshot, text, last_q):
        self.snapshots.append(snapshot)
        return {**BASE, **self.turns.pop(0)}, {"ms": 1}

    def explain(self, facts):
        self.facts.append(facts)
        bad = llm.unknown_numbers(self.explanation, facts)
        return (None, {"rejected_numbers": [bad]}) if bad else (self.explanation, {"ms": 1})

    def answer(self, facts):
        self.answer_facts.append(facts)
        text = self.answer_fn(facts)
        bad = llm.unknown_numbers(text, facts)
        return (None, {"rejected_numbers": [bad]}) if bad else (text, {"ms": 1})


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


class DestinationStateTest(unittest.TestCase):
    def test_same_station_new_place_rebuilds_dataset(self):
        class SameStationData(FakeData):
            def resolve_destination(self, q):
                d = super().resolve_destination(q)
                d.label = q
                d.walk_from_station_min = 15 if q == "회사" else 0
                return d

            def dataset_for(self, dest, log):
                ds = super().dataset_for(dest, log)
                for d in ds.dongs:
                    c = d["commute"][DEST]
                    if "min" in c:
                        c["min"] += dest.walk_from_station_min
                return ds

        data = SameStationData()
        agent = Agent(data, FakeLLM([
            {"intent": "update", "destination": "역"},
            {"intent": "update", "destination": "회사"},
        ]))
        s = agent.new_session()
        run(agent, s, "역으로 출근")
        before = s.result.by_code()["9900000001"]["raw"]["commute"]
        evs = run(agent, s, "회사로 변경")
        self.assertEqual(s.result.by_code()["9900000001"]["raw"]["commute"], before + 15)
        self.assertEqual(data.calls, 2)
        self.assertEqual(s.dataset.meta["destination"]["label"], "회사")
        self.assertIsNone(next(e for e in evs if e["type"] == "result")["payload"]["diff"])

    def test_other_destination_what_if_keeps_committed_dataset(self):
        class OtherDestinationData(FakeData):
            def resolve_destination(self, q):
                d = super().resolve_destination(q)
                d.key = q
                return d

            def dataset_for(self, dest, log):
                ds = super().dataset_for(dest, log)
                for d in ds.dongs:
                    d["commute"] = {dest.key: d["commute"][DEST]}
                return ds

        agent = Agent(OtherDestinationData(), FakeLLM([
            {"intent": "update", "destination": "A"},
            {"intent": "what_if", "destination": "B"},
        ]))
        s = agent.new_session()
        run(agent, s, "A로 출근")
        dataset, result, snapshot = s.dataset, s.result, s.state.snapshot()
        run(agent, s, "B로 출근하면?")
        self.assertIs(s.dataset, dataset)
        self.assertIs(s.result, result)
        self.assertEqual(s.ds_key, "A")
        self.assertEqual(s.state.snapshot(), snapshot)
        self.assertEqual(agent.what_if(s, {"set_constraints": {"max_commute_min": 30}})["payload"]["destination"]["key"], "A")

    def test_empty_dataset_completes_without_changing_state(self):
        agent = Agent(FakeData(), FakeLLM([{"intent": "update", "destination": DEST}]))
        s = agent.new_session()
        snapshot = s.state.snapshot()
        with patch.object(agent.data, "dataset_for", return_value=Dataset([], {})):
            evs = run(agent, s, "추천")
        self.assertEqual(types(evs)[-2:], ["error", "done"])
        self.assertNotIn("result", types(evs))
        self.assertEqual(s.state.snapshot(), snapshot)

    def test_destination_api_error_completes_stream(self):
        agent = Agent(FakeData(), FakeLLM([{"intent": "update", "destination": DEST}]))
        with patch.object(agent.data, "resolve_destination", side_effect=RuntimeError("private provider detail")):
            evs = run(agent, agent.new_session(), "추천")
        self.assertEqual(types(evs)[-2:], ["error", "done"])
        self.assertNotIn("private provider detail", evs[-2]["detail"])


FIRST = {"intent": "update", "destination": "가상역", "set_constraints": {"max_commute_min": 45}}


class IntentRoutingTest(unittest.TestCase):
    """조건이 바뀌지 않는 발화는 순위를 다시 계산하지 않고, 의도에 맞게 답한다."""

    def setUp(self):
        self.data = FakeData()

    def start(self, *turns, **kw):
        fake = FakeLLM([FIRST, *turns], **kw)
        agent = Agent(self.data, fake)
        s = agent.new_session()
        run(agent, s, "가상역 출근, 통근 45분 이내")
        return agent, s, fake

    def test_first_result_message_has_top3_table(self):
        agent, s, fake = self.start()
        msg = next(e for e in s.messages if e["role"] == "assistant")
        table = msg["attachments"][0]
        self.assertEqual(table["kind"], "dongs")
        self.assertEqual([r["status"] for r in table["rows"]], ["1위", "2위", "3위"])
        self.assertTrue(fake.facts[-1]["첫_결과"])

    def test_smalltalk_short_reply_keeps_result(self):
        agent, s, fake = self.start({"intent": "smalltalk"})
        result = s.result
        evs = run(agent, s, "고마워요")
        self.assertNotIn("result", types(evs))
        self.assertNotIn("interpretation", types(evs))
        msg = next(e for e in evs if e["type"] == "message")
        self.assertIn("다행", msg["text"])
        self.assertIs(s.result, result)
        self.assertEqual(fake.answer_facts, [])  # LLM 답변도 부르지 않음

    def test_question_about_excluded_dong_answers_without_recompute(self):
        agent, s, fake = self.start({"intent": "question", "mentioned_dongs": ["가동"]})
        result = s.result
        evs = run(agent, s, "가동은 왜 순위에 없어?")
        self.assertNotIn("result", types(evs))
        self.assertIs(s.result, result)
        self.assertEqual(self.data.calls, 1)
        target = fake.answer_facts[-1]["대상_동네"][0]
        self.assertIn("조건 밖", target["상태"])
        self.assertTrue(any("통근" in w for w in target["제외_이유"]))
        rows = next(e for e in evs if e["type"] == "message")["attachments"][0]["rows"]
        self.assertTrue(rows[0]["excluded"])
        self.assertIn("answer", [e.get("step") for e in evs if e["type"] == "log"])

    def test_dong_found_from_text_even_if_llm_misses_it(self):
        agent, s, fake = self.start({"intent": "question"})
        run(agent, s, "다동이랑 라동은 어때?")
        names = [d["동"].split()[-1] for d in fake.answer_facts[-1]["대상_동네"]]
        self.assertEqual(sorted(names), ["다동", "라동"])

    def test_comparison_difference_is_computed_by_code(self):
        def answer_fn(f):
            cost = next(i for i in f["비교"][0]["항목"] if i["항목"] == "월 총비용")
            return f"월 총비용은 {cost['더_나은_쪽']}이 {cost['차이_크기']}만 원 낮아요."

        agent, s, fake = self.start({"intent": "question"}, answer_fn=answer_fn)
        r1, r2 = [e for e in s.result.ranked if e["raw"]["monthly_cost"] is not None][:2]
        fake.turns[0]["mentioned_ranks"] = [r1["rank"], r2["rank"]]
        evs = run(agent, s, "두 동네 월 총비용 차이가 얼마야?")
        f = fake.answer_facts[-1]
        cost = next(i for i in f["비교"][0]["항목"] if i["항목"] == "월 총비용")
        self.assertAlmostEqual(cost["차이_A빼기B"], round(r1["raw"]["monthly_cost"] - r2["raw"]["monthly_cost"], 1))
        msg = next(e for e in evs if e["type"] == "message")
        self.assertEqual(msg["source"], "llm")  # 코드가 넘긴 차이를 쓰면 숫자 검사를 통과
        self.assertIn("compare", msg["attachments"][0])

    def test_answer_with_made_up_number_falls_back_to_template(self):
        agent, s, fake = self.start({"intent": "question", "mentioned_dongs": ["다동"]},
                                    answer_fn=lambda f: "다동은 월 98765만 원이에요.")
        evs = run(agent, s, "다동은 어때?")
        msg = next(e for e in evs if e["type"] == "message")
        self.assertEqual(msg["source"], "template")
        self.assertIn("다동", msg["text"])

    def test_unknown_dong_is_reported_missing(self):
        agent, s, fake = self.start({"intent": "question", "mentioned_dongs": ["없는동"]})
        run(agent, s, "없는동은 어때?")
        self.assertEqual(fake.answer_facts[-1]["찾지_못한_동네"], ["없는동"])

    def test_unavailable_info_gets_how_to_check(self):
        agent, s, fake = self.start({"intent": "question", "unsupported": ["치안"]})
        evs = run(agent, s, "여기 치안은 어때?")
        att = next(e for e in evs if e["type"] == "message")["attachments"]
        guide = next(a for a in att if a["kind"] == "guides")
        self.assertIn("생활안전지도", [l["label"] for g in guide["items"] for l in g["links"]])
        self.assertTrue(fake.answer_facts[-1]["확인_방법"])

    def test_refer_back_uses_previous_targets(self):
        agent, s, fake = self.start({"intent": "question", "mentioned_dongs": ["다동"]},
                                    {"intent": "question", "unsupported": ["치안"]})
        run(agent, s, "다동은 어때?")
        run(agent, s, "그 동네 치안은 어때?")
        self.assertEqual(fake.answer_facts[-1]["대상_동네"][0]["동"].split()[-1], "다동")

    def test_extract_sees_candidates_and_recent_history(self):
        agent, s, fake = self.start({"intent": "question"})
        run(agent, s, "아까 2위는?")
        snap = fake.snapshots[-1]
        self.assertIn("다동", snap["후보_동네"])
        self.assertTrue(snap["현재_상위"][0].startswith("1위"))
        self.assertEqual(snap["최근_대화"][0]["역할"], "user")

    def test_condition_change_still_recomputes(self):
        agent, s, fake = self.start({"intent": "update", "preference_changes": [
            {"factor": "quiet", "level": "매우 중요", "evidence": "조용한 게 제일"}]})
        evs = run(agent, s, "조용한 게 제일 중요해")
        self.assertIn("result", types(evs))
        self.assertFalse(fake.facts[-1]["첫_결과"])


class GuidesAndUnitsTest(unittest.TestCase):
    """확인 방법 범위, 숫자 단위, 화면 연동."""

    def setUp(self):
        self.data = FakeData()

    def start(self, *turns, **kw):
        fake = FakeLLM([FIRST, *turns], **kw)
        agent = Agent(self.data, fake)
        s = agent.new_session()
        run(agent, s, "가상역 출근, 통근 45분 이내")
        return agent, s, fake

    def test_listing_keywords_get_listing_guide(self):
        from backend import guides
        for text in ("지금 이매동에 나와 있는 방 보여줘", "방 보여줘", "원룸 보여줘"):
            self.assertEqual(guides.match([text])[0]["topic"], "실제 매물·현재 시세", text)

    def test_outside_topic_gets_map_search_guide(self):
        agent, s, fake = self.start({"intent": "question", "mentioned_dongs": ["다동"], "outside_topics": ["맛집"]})
        evs = run(agent, s, "다동에 맛집 많아?")
        guide = next(a for a in next(e for e in evs if e["type"] == "message")["attachments"] if a["kind"] == "guides")
        item = guide["items"][0]
        self.assertEqual(item["topic"], "맛집")
        self.assertIn("map.kakao.com", item["links"][0]["url"])
        self.assertIn("다동 맛집", item["links"][0]["label"])  # 질문한 동네 이름으로 검색

    def test_known_topic_does_not_get_duplicate_default_guide(self):
        from backend import guides
        got = guides.match(["치안은 어때?"], outside=["치안"])
        self.assertEqual([g["topic"] for g in got], ["치안·밤길"])

    def test_counts_and_minutes_are_integers(self):
        agent, s, fake = self.start({"intent": "question", "mentioned_dongs": ["다동", "라동"]})
        evs = run(agent, s, "다동이랑 라동 비교해줘")
        att = next(e for e in evs if e["type"] == "message")["attachments"][0]
        for row in att["rows"]:
            for k in ("commute", "station_walk", "bars"):
                self.assertIsInstance(row[k], int, k)
        items = {i["label"]: i for i in att["compare"]["items"]}
        self.assertIsInstance(items["통근 시간"]["diff"], int)
        self.assertIsInstance(items["주변 주점"]["a"], int)
        self.assertIsInstance(items["월 총비용"]["a"], float)  # 금액은 소수 첫째 자리
        facts = fake.answer_facts[-1]["대상_동네"][0]
        self.assertIsInstance(facts["통근_분"], int)

    def test_compare_attachment_has_factor_points_for_chart(self):
        agent, s, fake = self.start({"intent": "question", "mentioned_dongs": ["다동", "라동"]})
        evs = run(agent, s, "다동이랑 라동 비교해줘")
        cmp = next(e for e in evs if e["type"] == "message")["attachments"][0]["compare"]
        self.assertEqual([f["key"] for f in cmp["factors"]],
                         ["monthly_cost", "commute", "station_access", "convenience", "quiet"])
        rows = {r["name"]: r for r in s.result.ranked}
        self.assertAlmostEqual(sum(f["a"] for f in cmp["factors"]), rows["다동"]["score"], places=0)

    def test_focus_moves_right_panel(self):
        agent, s, fake = self.start(
            {"intent": "question", "mentioned_dongs": ["다동"]},
            {"intent": "question", "mentioned_dongs": ["다동", "라동"]},
            {"intent": "question", "mentioned_dongs": ["라동"]},
            {"intent": "question"},
        )
        focus = lambda evs: next(e for e in evs if e["type"] == "message")["focus"]  # noqa: E731
        f1 = focus(run(agent, s, "다동은 어때?"))
        self.assertEqual(f1["tab"], "map")
        f2 = focus(run(agent, s, "다동이랑 라동 비교해줘"))
        self.assertEqual(f2["tab"], "compare")
        self.assertEqual(len(f2["dong_codes"]), 2)
        f3 = focus(run(agent, s, "라동은 통근이 얼마나 걸려?"))
        self.assertEqual(f3["tab"], "tradeoff")
        self.assertIsNone(focus(run(agent, s, "조건 어떻게 돼?")))  # 대상이 없으면 화면은 그대로


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
