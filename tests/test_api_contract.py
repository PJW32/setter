"""HTTP 검증과 세션 동시 요청 테스트. 가짜 데이터로 실행하며 외부 API는 호출하지 않는다."""

import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import main
from backend.agent import Agent
from test_backend import FakeData, FakeLLM


class ApiContractTest(unittest.TestCase):
    def setUp(self):
        self.agent = Agent(FakeData(), FakeLLM([{"intent": "update", "destination": "가상역"}]))
        for name, value in (("agent", self.agent), ("SESSIONS", {}), ("_inflight", {})):
            p = patch.object(main, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)
        self.sid = self.client.post("/api/sessions").json()["session_id"]

    def post(self, path, body):
        return self.client.post(f"/api/sessions/{self.sid}/{path}", json=body)

    def test_message_shape_and_length_validation(self):
        for body in ({}, {"text": None}, {"text": 123}, {"text": "x" * 4001}):
            with self.subTest(body_type=type(body.get("text")).__name__):
                self.assertEqual(self.post("messages", body).status_code, 422)
        for text in ("", " \n\t "):
            self.assertEqual(self.post("messages", {"text": text}).status_code, 400)
        self.assertEqual(main.SESSIONS[self.sid].messages, [])

    def test_evicted_session_cannot_start_after_lookup(self):
        session = main.SESSIONS.pop(self.sid)
        with self.assertRaises(HTTPException) as caught:
            main._reserve(self.sid, session)
        self.assertEqual(caught.exception.status_code, 404)
        self.assertNotIn(self.sid, main._inflight)

    def test_malformed_what_if_is_422_instead_of_server_error(self):
        changes = [
            {"set_constraints": []},
            {"set_constraints": {"max_monthly_rent": True}},
            {"set_constraints": {"max_monthly_rent": "NaN"}},
            {"clear_constraints": 3},
            {"preference_changes": [1]},
            {"params": {"house_types": 3}},
            {"params": {"new_contracts_only": "false"}},
            {"params": {"unexpected": 1}},
        ]
        for change in changes:
            with self.subTest(change=change):
                self.assertEqual(self.post("what-if", {"changes": change}).status_code, 422)

    def test_unknown_session_and_missing_result_have_distinct_errors(self):
        self.assertEqual(self.client.get("/api/sessions/missing").status_code, 404)
        self.assertEqual(self.client.post("/api/sessions/missing/messages", json={"text": "추천"}).status_code, 404)
        self.assertEqual(self.post("what-if", {"changes": {}}).status_code, 400)
        self.assertEqual(main._inflight, {})

    def test_valid_what_if_keeps_committed_state(self):
        self.assertEqual(self.post("messages", {"text": "가상역 출근"}).status_code, 200)
        before = self.client.get(f"/api/sessions/{self.sid}").json()
        response = self.post("what-if", {"changes": {"set_constraints": {"max_commute_min": 30}}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["payload"]["constraints"]["max_commute_min"], 30)
        self.assertEqual(self.client.get(f"/api/sessions/{self.sid}").json(), before)

    def test_same_session_is_busy_but_other_sessions_are_independent(self):
        entered, release = threading.Event(), threading.Event()
        sid = self.sid

        def handle(session, text):
            if session.id == sid:
                entered.set()
                if not release.wait(5):
                    raise RuntimeError("test timed out")
            yield {"type": "done", "t": 0}

        with patch.object(self.agent, "handle", side_effect=handle), ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.post, "messages", {"text": "첫 요청"})
            try:
                self.assertTrue(entered.wait(3))
                self.assertEqual(self.post("messages", {"text": "중복"}).status_code, 409)
                self.assertEqual(self.post("what-if", {"changes": {}}).status_code, 409)
                other = self.client.post("/api/sessions").json()["session_id"]
                response = self.client.post(f"/api/sessions/{other}/messages", json={"text": "독립 요청"})
                self.assertEqual(response.status_code, 200)
            finally:
                release.set()
            self.assertEqual(future.result(timeout=3).status_code, 200)
            self.assertEqual(self.post("messages", {"text": "다음 요청"}).status_code, 200)
        self.assertEqual(main._inflight, {})

    def test_null_condition_does_not_clear_or_reject_existing_limit(self):
        self.post("messages", {"text": "가상역 출근"})
        session = main.SESSIONS[self.sid]
        session.state.constraints.max_monthly_rent = 60
        response = self.post("what-if", {"changes": {
            "set_constraints": {"max_monthly_rent": None}, "params": {"destination": None},
        }})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["payload"]["constraints"]["max_monthly_rent"], 60)
        self.assertEqual(response.json()["report"]["rejected"], [])
        self.assertEqual(session.state.constraints.max_monthly_rent, 60)

    def test_failure_stream_releases_session_for_retry(self):
        with patch.object(self.agent.llm, "extract", side_effect=RuntimeError("provider unavailable")):
            response = self.post("messages", {"text": "추천"})
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        self.assertEqual([e["type"] for e in events][-2:], ["error", "done"])
        self.assertEqual(main._inflight, {})
        self.assertEqual(self.post("messages", {"text": "다시 추천"}).status_code, 200)

    def test_late_cleanup_cannot_unlock_a_new_request(self):
        first = main._reserve(self.sid)
        main._release(self.sid, first)
        second = main._reserve(self.sid)
        main._release(self.sid, first)
        with self.assertRaises(HTTPException) as caught:
            main._reserve(self.sid)
        self.assertEqual(caught.exception.status_code, 409)
        main._release(self.sid, second)


if __name__ == "__main__":
    unittest.main()
