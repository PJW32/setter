"""캐시를 거치는 GET 요청.

같은 요청은 data/cache/ 에 저장된 응답을 다시 쓴다 (API 사용량 절약, 재현성).
캐시 파일 이름과 내용에는 키가 들어가지 않는다.
"""

import atexit
import hashlib
import json
import time
import urllib.parse

import threading
import uuid
from collections import defaultdict
from concurrent.futures import Future

import httpx

from config import ROOT

CACHE_DIR = ROOT / "data" / "cache"
USER_AGENT = "dongnefit-collector/0.1"


class ApiError(RuntimeError):
    pass


def _cache_path(source: str, url: str, params: dict, ext: str):
    ident = url + "?" + urllib.parse.urlencode(sorted(params.items()))
    digest = hashlib.sha1(ident.encode("utf-8")).hexdigest()
    return CACHE_DIR / source / f"{digest}.{ext}"


_clients: dict[str, httpx.Client] = {}
_clients_lock = threading.Lock()
_flights: dict[str, Future] = {}
_flights_lock = threading.Lock()
_metrics = defaultdict(lambda: defaultdict(float))
_metrics_lock = threading.Lock()


def _record(source, **values):
    with _metrics_lock:
        for key, value in values.items():
            _metrics[source][key] += value


def metrics_snapshot():
    """URL・쿼리・인증 정보 없이 공급자별 누적 수치만 반환한다."""
    with _metrics_lock:
        return {source: dict(values) for source, values in _metrics.items()}


def _client(source):
    with _clients_lock:
        if source not in _clients:
            _clients[source] = httpx.Client(
                timeout=30, follow_redirects=True,
                limits=httpx.Limits(max_connections=8, max_keepalive_connections=8, keepalive_expiry=30),
            )
        return _clients[source]


def close_clients():
    """모든 수집 작업이 끝난 뒤에만 호출한다."""
    with _clients_lock:
        clients = list(_clients.values())
        _clients.clear()
    for client in clients:
        client.close()


atexit.register(close_clients)


def _fetch(source: str, url: str, query: dict, headers: dict | None, retries: int) -> str:
    if retries < 1:
        raise ValueError("retries must be at least 1")
    request_url = f"{url}?{urllib.parse.urlencode(query)}"
    last_err = ApiError(f"{source} 요청 실패")
    for attempt in range(retries):
        started = time.monotonic()
        _record(source, attempts=1, retries=int(attempt > 0))
        try:
            response = _client(source).get(request_url, headers={"User-Agent": USER_AGENT, **(headers or {})})
            if response.is_error:
                _record(source, http_errors=1)
                last_err = ApiError(f"{source} HTTP {response.status_code}")
                if response.status_code not in (429, 500, 502, 503, 504):
                    raise last_err
            else:
                return response.content.decode("utf-8")
        except httpx.TransportError as exc:
            _record(source, transport_errors=1)
            # 예외 본문과 요청 URL에는 키가 포함될 수 있으므로 외부에 전달하지 않는다.
            last_err = ApiError(f"{source} 연결 실패 ({type(exc).__name__})")
        finally:
            _record(source, network_seconds=time.monotonic() - started)
        delay = 1.5 * (attempt + 1)
        _record(source, backoff_seconds=delay)
        time.sleep(delay)
    raise last_err


def _shared_fetch(source, url, query, headers, retries):
    # 진행 중인 완전히 동일한 인증・요청만 공유한다. 완료 응답을 메모리에 캐시하지 않는다.
    identity = json.dumps([source, url, query, headers or {}, retries], sort_keys=True, ensure_ascii=False)
    key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    with _flights_lock:
        future = _flights.get(key)
        leader = future is None
        if leader:
            future = Future()
            _flights[key] = future
    if not leader:
        _record(source, shared_waits=1)
        started = time.monotonic()
        try:
            return future.result()
        finally:
            _record(source, shared_wait_seconds=time.monotonic() - started)
    try:
        text = _fetch(source, url, query, headers, retries)
        future.set_result(text)
        return text
    except BaseException as exc:
        future.set_exception(exc)
        raise
    finally:
        with _flights_lock:
            _flights.pop(key, None)


def get_text(
    source: str,
    url: str,
    params: dict,
    *,
    secret_params: dict | None = None,
    headers: dict | None = None,
    retries: int = 3,
    pause: float = 0.0,
    cache_ok=None,
    ext: str = "txt",
    offline: bool = False,
) -> str:
    """params 는 캐시 키에 들어가고, secret_params(키)는 들어가지 않는다.
    cache_ok(text) 가 False 면 저장하지 않는다 (한도 초과 같은 일시 오류)."""
    path = _cache_path(source, url, params, ext)
    _record(source, requests=1)
    if path.exists():
        _record(source, cache_hits=1)
        return path.read_text(encoding="utf-8")
    _record(source, cache_misses=1)
    if offline:
        raise ApiError(f"{source} 오프라인 캐시에 응답이 없습니다")
    text = _shared_fetch(source, url, {**params, **(secret_params or {})}, headers, retries)
    if cache_ok is None or cache_ok(text):
        path.parent.mkdir(parents=True, exist_ok=True)
        pending = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            pending.write_text(text, encoding="utf-8")
            pending.replace(path)
        finally:
            pending.unlink(missing_ok=True)
    if pause:
        time.sleep(pause)
    return text


def get_json(source: str, url: str, params: dict, *, cache_ok=None, **kw) -> dict:
    ok = (lambda t: cache_ok(json.loads(t))) if cache_ok else None
    return json.loads(get_text(source, url, params, cache_ok=ok, ext="json", **kw))
