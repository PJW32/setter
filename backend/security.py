"""단일 프로세스 심사용 배포의 접속 인증과 요청 제한. 비밀값은 환경변수로만 받는다."""

import base64
import binascii
import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from http.cookies import SimpleCookie, CookieError
from urllib.parse import unquote, urlsplit


@dataclass(frozen=True, repr=False)
class SecuritySettings:
    enabled: bool = False
    production: bool = False
    username: str = ""
    password: str = ""
    secret: str = ""
    origin: str = ""
    api_per_minute: int = 120
    jobs_per_minute: int = 12
    jobs_per_day: int = 100
    max_jobs: int = 5
    require_login: bool = True

    @classmethod
    def load(cls):
        # config.py가 먼저 로컬 .env를 로딩한다. Render에서는 환경변수가 우선한다.
        production = os.getenv("RENDER") == "true" or os.getenv("APP_ENV") == "production"
        username = os.getenv("DEPLOY_USERNAME", "")
        password = os.getenv("DEPLOY_PASSWORD", "")
        secret = os.getenv("DEPLOY_SESSION_SECRET", "")
        mode = os.getenv("DEPLOY_ACCESS_MODE", "basic")
        if mode not in ("basic", "public"):
            raise RuntimeError("DEPLOY_ACCESS_MODE는 basic 또는 public이어야 합니다")
        require_login = mode == "basic"
        enabled = production or not require_login or any((username, password, secret))
        origin = os.getenv("APP_ORIGIN") or os.getenv("RENDER_EXTERNAL_URL", "")
        if enabled:
            parsed = urlsplit(origin)
            if len(secret) < 32 or (require_login and (
                    not username or ":" in username or len(username) > 64 or len(password) < 20)):
                raise RuntimeError("배포 인증 설정 필요: DEPLOY_USERNAME, DEPLOY_PASSWORD(20자 이상), DEPLOY_SESSION_SECRET(32자 이상)")
            if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
                    or parsed.path not in ("", "/") or parsed.scheme not in ("http", "https")
                    or (production and parsed.scheme != "https")):
                raise RuntimeError("APP_ORIGIN 또는 RENDER_EXTERNAL_URL에 서비스의 정확한 HTTPS 주소가 필요합니다")
        return cls(enabled, production, username, password, secret, origin.rstrip("/"), require_login=require_login)

    @property
    def cookie_name(self):
        return "__Host-saeteo-browser" if self.origin.startswith("https://") else "saeteo-browser"


class WindowLimits:
    """외부 입력의 키 수도 제한한다. 프록시 전달 헤더를 IP로 신뢰하지 않는다."""

    def __init__(self):
        self.entries = OrderedDict()
        self.lock = threading.Lock()

    def allow(self, key, maximum, seconds=60):
        now = time.monotonic()
        with self.lock:
            if key not in self.entries:
                if len(self.entries) >= 1024:
                    self.entries.popitem(last=False)
                self.entries[key] = deque()
            values = self.entries[key]
            self.entries.move_to_end(key)
            while values and values[0] <= now - seconds:
                values.popleft()
            if len(values) >= maximum:
                return False
            values.append(now)
            return True


class DeploymentGuard:
    """정적 화면도 인증한다. SSE를 버퍼링하지 않고 응답 종료까지 실행 슬롯을 유지한다."""

    BODY_LIMIT = 16 * 1024
    COOKIE_AGE = 12 * 3600

    def __init__(self, app, settings):
        self.app, self.settings = app, settings
        self.limits = WindowLimits()
        self.jobs = threading.BoundedSemaphore(settings.max_jobs)

    def authenticated(self, header):
        try:
            scheme, value = header.split(" ", 1)
            if scheme.lower() != "basic" or len(value) > 4096:
                return False
            user, password = base64.b64decode(value, validate=True).decode("utf-8").split(":", 1)
            user_ok = secrets.compare_digest(user.encode(), self.settings.username.encode())
            password_ok = secrets.compare_digest(password.encode(), self.settings.password.encode())
            return user_ok & password_ok
        except (ValueError, UnicodeError, binascii.Error):
            return False

    def owner_cookie(self, header):
        token = ""
        try:
            cookies = SimpleCookie()
            cookies.load(header)
            if self.settings.cookie_name in cookies:
                token = cookies[self.settings.cookie_name].value
            owner, expires, signature = token.split(".")
            expected = hmac.new(self.settings.secret.encode(), f"{owner}.{expires}".encode(), hashlib.sha256).hexdigest()
            now = time.time()
            if (len(owner) == 48 and all(c in "0123456789abcdef" for c in owner)
                    and now < int(expires) <= now + self.COOKIE_AGE
                    and secrets.compare_digest(signature, expected)):
                return owner, None
        except (CookieError, ValueError):
            pass
        owner = secrets.token_hex(24)
        message = f"{owner}.{int(time.time()) + self.COOKIE_AGE}"
        signature = hmac.new(self.settings.secret.encode(), message.encode(), hashlib.sha256).hexdigest()
        cookie = SimpleCookie()
        cookie[self.settings.cookie_name] = f"{message}.{signature}"
        item = cookie[self.settings.cookie_name]
        item["path"], item["httponly"], item["samesite"] = "/", True, "Strict"
        item["max-age"] = self.COOKIE_AGE
        if self.settings.origin.startswith("https://"):
            item["secure"] = True
        return owner, item.OutputString()

    async def __call__(self, scope, receive, send):
        from starlette.datastructures import Headers
        from starlette.responses import JSONResponse

        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        cfg = self.settings
        if not cfg.enabled:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        path, method = unquote(scope["path"]).lower(), scope["method"]
        cookie = None

        async def protected_send(message):
            if message["type"] == "http.response.start":
                additions = {
                    b"cache-control": b"no-store", b"x-content-type-options": b"nosniff",
                    # OSM 타일은 웹 요청의 Referer가 필요하다. 외부에는 origin만 보낸다.
                    b"x-frame-options": b"DENY", b"referrer-policy": b"strict-origin-when-cross-origin",
                    b"content-security-policy": b"frame-ancestors 'none'; base-uri 'self'; object-src 'none'",
                }
                if cfg.production:
                    additions[b"strict-transport-security"] = b"max-age=31536000"
                message = dict(message)
                message["headers"] = [(k, v) for k, v in message.get("headers", []) if k.lower() not in additions]
                message["headers"] += list(additions.items())
                if cookie:
                    message["headers"].append((b"set-cookie", cookie.encode("ascii")))
            await send(message)

        async def reject(status, detail, extra=None):
            await JSONResponse({"detail": detail}, status_code=status, headers=extra)(scope, receive, protected_send)

        # Render 상태 확인에는 비밀값・DB 상태를 제공하지 않는다.
        if scope["path"] == "/healthz" and method in ("GET", "HEAD"):
            await JSONResponse({"ok": True})(scope, receive, protected_send)
            return
        if headers.get("host", "").lower() != urlsplit(cfg.origin).netloc.lower():
            await reject(400, "허용되지 않은 호스트입니다")
            return
        if cfg.require_login and not self.authenticated(headers.get("authorization", "")):
            peer = (scope.get("client") or ("unknown",))[0]
            if not self.limits.allow(("login", peer), 12):
                await reject(429, "접속 시도가 많습니다. 잠시 후 다시 시도해 주세요", {"Retry-After": "60"})
            else:
                await reject(401, "접속 인증이 필요합니다", {"WWW-Authenticate": 'Basic realm="Saeteo preview", charset="UTF-8"'})
            return
        if (path in ("/docs", "/redoc", "/openapi.json") or path.startswith("/docs/")
                or any(part.startswith(".") for part in path.split("/") if part)
                or path.startswith(("/data/", "/backend/", "/collectors/", "/scripts/"))
                or path.endswith((".sqlite", ".sqlite3", ".db", ".map"))):
            await reject(404, "찾을 수 없습니다")
            return
        if method not in ("GET", "HEAD", "OPTIONS"):
            if (headers.get("origin") not in (None, cfg.origin)
                    or headers.get("sec-fetch-site") == "cross-site"):
                await reject(403, "다른 사이트에서 보낸 요청은 허용되지 않습니다")
                return
        owner, cookie = self.owner_cookie(headers.get("cookie", ""))
        scope.setdefault("state", {}).update(deployment_protected=True, browser_owner=owner)
        if path.startswith("/api/") and not self.limits.allow("api", cfg.api_per_minute):
            await reject(429, "요청이 많습니다. 잠시 후 다시 시도해 주세요", {"Retry-After": "60"})
            return
        if method not in ("GET", "HEAD", "OPTIONS"):
            try:
                size = int(headers.get("content-length", "0"))
                if size < 0:
                    raise ValueError
            except ValueError:
                await reject(400, "잘못된 요청 크기입니다")
                return
            if size > self.BODY_LIMIT:
                await reject(413, "요청 본문이 너무 큽니다")
                return
            chunks, total = [], 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                total += len(chunk)
                if total > self.BODY_LIMIT:
                    await reject(413, "요청 본문이 너무 큽니다")
                    return
                chunks.append(chunk)
                if not message.get("more_body", False):
                    break
            consumed = False
            original_receive = receive

            async def buffered_receive():
                nonlocal consumed
                if not consumed:
                    consumed = True
                    return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
                return await original_receive()

            receive = buffered_receive
        expensive = method == "POST" and path.startswith("/api/sessions/") and path.endswith(("/messages", "/what-if"))
        if expensive:
            if not self.limits.allow("jobs", cfg.jobs_per_minute):
                await reject(429, "추천 요청이 많습니다. 잠시 후 다시 시도해 주세요", {"Retry-After": "60"})
                return
            if not self.limits.allow("jobs-day", cfg.jobs_per_day, seconds=86400):
                await reject(429, "오늘의 시연 요청 한도에 도달했습니다", {"Retry-After": "86400"})
                return
            if not self.jobs.acquire(blocking=False):
                await reject(503, "다른 추천 요청을 처리 중입니다. 잠시 후 다시 시도해 주세요", {"Retry-After": "10"})
                return
        try:
            await self.app(scope, receive, protected_send)
        finally:
            if expensive:
                self.jobs.release()
