"""실제 네트워크 없이 수집기의 요청 동일성・재시도・동시 처리를 검증한다."""

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import httpx
from collectors import http


class CollectorHttpTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = patch.object(http, "CACHE_DIR", Path(tmp.name))
        p.start()
        self.addCleanup(p.stop)

    def test_client_is_reused_and_connections_are_bounded(self):
        with patch.object(http, "_clients", {}), patch.object(httpx, "Client") as factory:
            self.assertIs(http._client("molit"), http._client("molit"))
            factory.assert_called_once()
            self.assertEqual(factory.call_args.kwargs["limits"].max_connections, 8)

    def test_parameters_and_utf8_are_preserved(self):
        def respond(request):
            self.assertEqual(request.url.params["query"], "판교역")
            self.assertEqual(request.url.params["serviceKey"], "a+b/=")
            self.assertEqual(request.headers["Authorization"], "KakaoAK key")
            return httpx.Response(200, content="응답".encode())
        with httpx.Client(transport=httpx.MockTransport(respond)) as client, patch.object(http, "_client", return_value=client):
            self.assertEqual(http._fetch("test", "https://example.test", {"query": "판교역", "serviceKey": "a+b/="},
                                         {"Authorization": "KakaoAK key"}, 3), "응답")

    def test_transient_error_retries_but_permanent_error_does_not(self):
        for status, expected in ((503, 2), (403, 1)):
            calls = []

            def respond(request):
                calls.append(request)
                return httpx.Response(status if len(calls) == 1 else 200, content=b"ok")

            with httpx.Client(transport=httpx.MockTransport(respond)) as client, \
                    patch.object(http, "_client", return_value=client), patch.object(http.time, "sleep"):
                if status == 403:
                    with self.assertRaises(http.ApiError):
                        http._fetch("test", "https://example.test", {}, None, 3)
                else:
                    self.assertEqual(http._fetch("test", "https://example.test", {}, None, 3), "ok")
            self.assertEqual(len(calls), expected)

    def test_offline_cache_miss_never_calls_network(self):
        with patch.object(http, "_fetch") as fetch:
            with self.assertRaises(http.ApiError):
                http.get_text("test", "https://example.test", {}, offline=True)
            fetch.assert_not_called()

    def test_cache_and_metrics_do_not_contain_secrets(self):
        with patch.object(http, "_fetch", return_value="hello") as fetch:
            for _ in range(2):
                self.assertEqual(http.get_text("test", "https://example.test", {}, secret_params={"key": "private-secret"}), "hello")
            fetch.assert_called_once()
        self.assertNotIn("private-secret", str(http.metrics_snapshot()))
        for path in http.CACHE_DIR.iterdir():
            for file in path.iterdir():
                self.assertNotIn("private-secret", file.name + file.read_text())

    def test_inflight_duplicates_share_one_fetch_and_are_not_retained(self):
        entered, release, joined = threading.Event(), threading.Event(), threading.Event()

        def fetch(*_):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("test timeout")
            return "result"

        original_record = http._record

        def record(source, **values):
            original_record(source, **values)
            if "shared_waits" in values:
                joined.set()

        with patch.object(http, "_fetch", side_effect=fetch) as mock, patch.object(http, "_record", side_effect=record), \
                ThreadPoolExecutor(max_workers=2) as pool:
            args = ("test", "https://example.test", {"a": 1}, {"Authorization": "key"}, 3)
            first = pool.submit(http._shared_fetch, *args)
            try:
                self.assertTrue(entered.wait(2))
                second = pool.submit(http._shared_fetch, *args)
                self.assertTrue(joined.wait(2))
            finally:
                release.set()
            self.assertEqual(first.result(), second.result())
            mock.assert_called_once()
            http._shared_fetch(*args)
            self.assertEqual(mock.call_count, 2)

    def test_failed_shared_fetch_can_be_retried_and_secrets_are_not_exposed(self):
        def fail(request):
            raise httpx.ConnectError("secret-provider-url", request=request)
        with httpx.Client(transport=httpx.MockTransport(fail)) as client, \
                patch.object(http, "_client", return_value=client), patch.object(http.time, "sleep"):
            with self.assertRaises(http.ApiError) as caught:
                http._shared_fetch("test", "https://example.test", {"key": "private-secret"}, None, 1)
        self.assertNotIn("secret", str(caught.exception))
        self.assertFalse(http._flights)
        with patch.object(http, "_fetch", return_value="recovered"):
            self.assertEqual(http._shared_fetch("test", "https://example.test", {}, None, 1), "recovered")

    def test_unapproved_response_is_not_cached(self):
        with patch.object(http, "_fetch", return_value="error") as fetch:
            for _ in range(2):
                http.get_text("test", "https://example.test", {}, cache_ok=lambda text: False)
            self.assertEqual(fetch.call_count, 2)

    def test_different_credentials_do_not_share_inflight_requests(self):
        barrier = threading.Barrier(2)

        def fetch(source, url, query, headers, retries):
            barrier.wait(timeout=3)
            return headers["Authorization"]

        with patch.object(http, "_fetch", side_effect=fetch) as mock, ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(http._shared_fetch, "test", "https://example.test", {}, {"Authorization": "A"}, 3)
            second = pool.submit(http._shared_fetch, "test", "https://example.test", {}, {"Authorization": "B"}, 3)
            self.assertEqual((first.result(), second.result()), ("A", "B"))
            self.assertEqual(mock.call_count, 2)
