"""캐시를 거치는 GET 요청.

같은 요청은 data/cache/ 에 저장된 응답을 다시 쓴다 (API 사용량 절약, 재현성).
캐시 파일 이름과 내용에는 키가 들어가지 않는다.
"""

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from config import ROOT

CACHE_DIR = ROOT / "data" / "cache"
USER_AGENT = "dongnefit-collector/0.1"


class ApiError(RuntimeError):
    pass


def _cache_path(source: str, url: str, params: dict, ext: str):
    ident = url + "?" + urllib.parse.urlencode(sorted(params.items()))
    digest = hashlib.sha1(ident.encode("utf-8")).hexdigest()
    return CACHE_DIR / source / f"{digest}.{ext}"


def _fetch(source: str, url: str, query: dict, headers: dict | None, retries: int) -> str:
    req = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(query)}", headers={"User-Agent": USER_AGENT, **(headers or {})}
    )
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:300]
            if e.code in (429, 500, 502, 503, 504):
                last_err = ApiError(f"{source} HTTP {e.code}: {body}")
                time.sleep(1.5 * (attempt + 1))
                continue
            raise ApiError(f"{source} HTTP {e.code}: {body}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_err = ApiError(f"{source} 연결 실패: {e}")
            time.sleep(1.5 * (attempt + 1))
    raise last_err  # type: ignore[misc]


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
) -> str:
    """params 는 캐시 키에 들어가고, secret_params(키)는 들어가지 않는다.
    cache_ok(text) 가 False 면 저장하지 않는다 (한도 초과 같은 일시 오류)."""
    path = _cache_path(source, url, params, ext)
    if path.exists():
        return path.read_text(encoding="utf-8")
    text = _fetch(source, url, {**params, **(secret_params or {})}, headers, retries)
    if cache_ok is None or cache_ok(text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    if pause:
        time.sleep(pause)
    return text


def get_json(source: str, url: str, params: dict, *, cache_ok=None, **kw) -> dict:
    ok = (lambda t: cache_ok(json.loads(t))) if cache_ok else None
    return json.loads(get_text(source, url, params, cache_ok=ok, ext="json", **kw))
