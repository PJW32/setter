"""실제 API 키/네트워크 없이 인증 우회, 대화 접근, 자원 제한을 검증한다."""

import base64
import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.staticfiles import StaticFiles

from backend import main
from backend.agent import Agent
from backend.security import DeploymentGuard, SecuritySettings
from test_backend import FakeData, FakeLLM

ORIGIN = "https://preview.example"
CONFIG = SecuritySettings(enabled=True, production=True, username="reviewer",
                          password="test-password-with-24-characters", secret="test-signing-key-32-characters-long", origin=ORIGIN)


class ConfigurationTest(unittest.TestCase):
    def test_public_mode_keeps_protection_and_requires_signing_secret(self):
        env = {"APP_ENV": "production", "DEPLOY_ACCESS_MODE": "public",
               "DEPLOY_SESSION_SECRET": CONFIG.secret, "APP_ORIGIN": ORIGIN}
        with patch.dict(os.environ, env, clear=True):
            settings = SecuritySettings.load()
            self.assertTrue(settings.enabled)
            self.assertFalse(settings.require_login)
            self.assertEqual(settings.username, "")
            with patch.dict(os.environ, {"DEPLOY_SESSION_SECRET": ""}):
                with self.assertRaises(RuntimeError):
                    SecuritySettings.load()
            with patch.dict(os.environ, {"DEPLOY_ACCESS_MODE": "typo"}):
                with self.assertRaises(RuntimeError):
                    SecuritySettings.load()

    def test_production_requires_strong_credentials_and_https_origin(self):
        with patch.dict(os.environ, {"APP_ENV": "production"}, clear=True):
            with self.assertRaises(RuntimeError):
                SecuritySettings.load()
        env = {"RENDER": "true", "DEPLOY_USERNAME": CONFIG.username, "DEPLOY_PASSWORD": CONFIG.password,
               "DEPLOY_SESSION_SECRET": CONFIG.secret, "RENDER_EXTERNAL_URL": ORIGIN}
        with patch.dict(os.environ, env, clear=True):
            self.assertTrue(SecuritySettings.load().enabled)
            for name, value in (("DEPLOY_PASSWORD", "short"), ("DEPLOY_SESSION_SECRET", "short"),
                                ("DEPLOY_USERNAME", "user:name"), ("APP_ORIGIN", "http://preview.example"),
                                ("APP_ORIGIN", "https://user:pass@preview.example")):
                with self.subTest(name=name, value=value), patch.dict(os.environ, {name: value}):
                    with self.assertRaises(RuntimeError):
                        SecuritySettings.load()

    def test_local_default_is_unchanged_and_credentials_are_not_represented(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(SecuritySettings.load().enabled)
        self.assertNotIn(CONFIG.password, repr(CONFIG))
        self.assertNotIn(CONFIG.secret, repr(CONFIG))


class DeploymentSecurityTest(unittest.TestCase):
    def setUp(self):
        for name, value in (("agent", Agent(FakeData(), FakeLLM([{"intent": "update", "destination": "가상역"}]))),
                            ("SESSIONS", {}), ("_session_access", {}), ("_inflight", {})):
            p = patch.object(main, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.guard = DeploymentGuard(main.app, CONFIG)
        self.client = self.client_for(self.guard)

    def client_for(self, app, authenticated=True):
        client = TestClient(app, base_url=ORIGIN)
        if authenticated:
            client.auth = (CONFIG.username, CONFIG.password)
        self.addCleanup(client.close)
        return client

    def session(self, client=None):
        response = (client or self.client).post("/api/sessions")
        self.assertEqual(response.status_code, 200)
        return response.json()["session_id"]

    def test_public_access_has_no_login_prompt_and_keeps_browser_isolation(self):
        guard = DeploymentGuard(main.app, replace(CONFIG, require_login=False, username="", password=""))
        a = self.client_for(guard, authenticated=False)
        b = self.client_for(guard, authenticated=False)
        sid = self.session(a)
        response = a.get(f"/api/sessions/{sid}")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("www-authenticate", response.headers)
        self.assertEqual(b.get(f"/api/sessions/{sid}").status_code, 404)
        self.assertIn(CONFIG.cookie_name, a.cookies)
        self.assertEqual(a.post("/api/sessions", headers={"Origin": "https://other.example"}).status_code, 403)
        self.assertEqual(a.get("/data/store.sqlite").status_code, 404)
        self.assertEqual(a.get("/docs").status_code, 404)
        self.assertEqual(a.get("/api/meta").headers["cache-control"], "no-store")

    def test_public_access_keeps_body_job_limits_and_static_access(self):
        guard = DeploymentGuard(main.app, replace(CONFIG, require_login=False, jobs_per_day=1))
        client = self.client_for(guard, authenticated=False)
        sid = self.session(client)
        self.assertEqual(client.post(f"/api/sessions/{sid}/messages", content="x" * 17000).status_code, 413)
        self.assertEqual(client.post(f"/api/sessions/{sid}/what-if", json={"changes": {}}).status_code, 400)
        self.assertEqual(client.post(f"/api/sessions/{sid}/what-if", json={"changes": {}}).status_code, 429)
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "index.html").write_text("<h1>Public</h1>", encoding="utf-8")
            static_guard = DeploymentGuard(StaticFiles(directory=tmp, html=True), replace(CONFIG, require_login=False))
            self.assertEqual(self.client_for(static_guard, False).get("/").status_code, 200)

    def test_public_health_is_minimal_but_screen_api_and_docs_require_auth(self):
        guest = self.client_for(self.guard, authenticated=False)
        self.assertEqual(guest.get("/healthz").json(), {"ok": True})
        for path in ("/", "/api/health", "/api/meta", "/api/sessions/unknown", "/docs", "/openapi.json", "/assets/a.js"):
            with self.subTest(path=path):
                response = guest.get(path)
                self.assertEqual(response.status_code, 401)
                self.assertIn("Basic", response.headers["www-authenticate"])
                self.assertNotIn(CONFIG.password, response.text)

    def test_malformed_auth_and_spoofed_host_or_forwarded_identity_do_not_bypass(self):
        guest = self.client_for(self.guard, authenticated=False)
        for value in ("Basic !!!", "Bearer test", "Basic " + base64.b64encode(b"reviewer:wrong").decode(),
                      "Basic " + base64.b64encode(b"\xff:password").decode()):
            self.assertEqual(guest.get("/api/meta", headers={"Authorization": value}).status_code, 401)
        self.assertEqual(self.client.get("/api/meta", headers={"Host": "attacker.example"}).status_code, 400)
        for i in range(9):
            response = guest.get("/api/meta", headers={"X-Forwarded-For": f"10.0.0.{i}"})
        self.assertEqual(response.status_code, 429)

    def test_browser_ownership_applies_to_get_messages_and_what_if(self):
        sid = self.session()
        self.assertEqual(len(sid), 32)
        self.assertEqual(self.client.get(f"/api/sessions/{sid}").status_code, 200)
        other = self.client_for(self.guard)
        self.session(other)
        self.assertEqual(other.get(f"/api/sessions/{sid}").status_code, 404)
        self.assertEqual(other.post(f"/api/sessions/{sid}/messages", json={"text": "검색"}).status_code, 404)
        self.assertEqual(other.post(f"/api/sessions/{sid}/what-if", json={"changes": {}}).status_code, 404)

    def test_forged_or_expired_cookie_cannot_restore_a_session(self):
        sid = self.session()
        original = self.client.cookies.get(CONFIG.cookie_name)
        for token in (original[:-1] + ("0" if original[-1] != "0" else "1"), "bad", "x.0.bad"):
            other = self.client_for(self.guard)
            other.cookies.set(CONFIG.cookie_name, token, domain="preview.example", path="/")
            self.assertEqual(other.get(f"/api/sessions/{sid}").status_code, 404)

    def test_cookie_and_response_security_headers(self):
        response = self.client.post("/api/sessions")
        cookie = response.headers["set-cookie"]
        for part in ("__Host-saeteo-browser=", "HttpOnly", "Secure", "SameSite=Strict", "Path=/"):
            self.assertIn(part, cookie)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["referrer-policy"], "strict-origin-when-cross-origin")

    def test_cross_site_mutations_are_rejected(self):
        for headers in ({"Origin": "https://attacker.example"}, {"Sec-Fetch-Site": "cross-site"}):
            self.assertEqual(self.client.post("/api/sessions", headers=headers).status_code, 403)
        self.assertEqual(self.client.post("/api/sessions", headers={"Origin": ORIGIN}).status_code, 200)

    def test_provider_failure_text_in_region_metadata_is_not_exposed(self):
        with patch.object(main.store, "list_sggs", return_value=[{"code": "41135", "error": "private provider URL"}]):
            response = self.client.get("/api/meta")
        self.assertNotIn("private provider", response.text)
        self.assertEqual(response.json()["regions"][0]["error"], "수집 실패")

    def test_private_paths_and_docs_are_hidden_even_after_auth(self):
        for path in ("/.env", "/data/rent_snapshot.sqlite", "/data/store.sqlite", "/.git/config", "/docs", "/redoc", "/openapi.json", "/assets/main.js.map"):
            self.assertEqual(self.client.get(path).status_code, 404)

    def test_body_limit_checks_both_declared_and_streamed_sizes(self):
        for content, headers in ((b"{}", {"Content-Length": "17000"}),
                                 (b"x" * 17000, {"Content-Length": "1"}),
                                 (iter([b"x" * 9000, b"x" * 9000]), {"Transfer-Encoding": "chunked"})):
            self.assertEqual(self.client.post("/api/sessions/unknown/messages", content=content, headers=headers).status_code, 413)
        self.assertEqual(self.client.post("/api/sessions", headers={"Content-Length": "-1"}).status_code, 400)

    def test_global_limits_work_across_clients_and_cookies(self):
        guard = DeploymentGuard(main.app, replace(CONFIG, api_per_minute=2))
        a, b = self.client_for(guard), self.client_for(guard)
        self.assertEqual(a.get("/api/meta").status_code, 200)
        self.assertEqual(b.get("/api/meta").status_code, 200)
        self.assertEqual(a.get("/api/meta").status_code, 429)
        self.assertEqual(a.get("/healthz").status_code, 200)

    def test_daily_job_limit_and_stream_slots_are_released_after_errors(self):
        guard = DeploymentGuard(main.app, replace(CONFIG, jobs_per_day=1))
        client = self.client_for(guard)
        sid = self.session(client)
        self.assertEqual(client.post(f"/api/sessions/{sid}/what-if", json={"changes": {}}).status_code, 400)
        self.assertEqual(client.post(f"/api/sessions/{sid}/what-if", json={"changes": {}}).status_code, 429)
        self.assertTrue(guard.jobs.acquire(blocking=False))
        guard.jobs.release()

    def test_concurrent_sse_requests_are_bounded_and_diagnostics_are_redacted(self):
        guard = DeploymentGuard(main.app, replace(CONFIG, max_jobs=1))
        client = self.client_for(guard)
        sid = self.session(client)
        other = self.session(client)
        entered, release = threading.Event(), threading.Event()

        def handle(*args):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test timeout")
            yield {"type": "log", "status": "error", "detail": "private provider URL", "info": {"error": "secret"}}
            yield {"type": "error", "detail": "private provider URL"}
            yield {"type": "done"}

        with patch.object(main.agent, "handle", side_effect=handle), ThreadPoolExecutor(max_workers=1) as pool:
            running = pool.submit(client.post, f"/api/sessions/{sid}/messages", json={"text": "검색"})
            try:
                self.assertTrue(entered.wait(3))
                self.assertEqual(client.post(f"/api/sessions/{other}/messages", json={"text": "검색"}).status_code, 503)
            finally:
                release.set()
            response = running.result(timeout=3)
        self.assertNotIn("private provider", response.text)
        self.assertNotIn("secret", response.text)
        self.assertIn('"type": "done"', response.text)
        self.assertTrue(guard.jobs.acquire(blocking=False))
        guard.jobs.release()

    def test_expired_sessions_and_per_browser_capacity_are_bounded(self):
        first = self.session()
        for _ in range(3):
            self.session()
        self.assertEqual(len(main.SESSIONS), 3)
        self.assertEqual(self.client.get(f"/api/sessions/{first}").status_code, 404)
        last = next(iter(main._session_access))
        owner, touched = main._session_access[last]
        main._session_access[last] = (owner, touched - 3601)
        self.assertEqual(self.client.get(f"/api/sessions/{last}").status_code, 404)

    def test_static_frontend_is_also_protected(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "index.html").write_text("<h1>Preview</h1>", encoding="utf-8")
            guard = DeploymentGuard(StaticFiles(directory=tmp, html=True), CONFIG)
            self.assertEqual(self.client_for(guard, False).get("/").status_code, 401)
            self.assertEqual(self.client_for(guard).get("/").status_code, 200)


if __name__ == "__main__":
    unittest.main()
