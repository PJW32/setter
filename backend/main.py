"""FastAPI 서버.

실행:  python -m uvicorn backend.main:app --reload --port 8000
"""

import json
import secrets
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from config import ROOT, key_status
from engine.factors import FACTORS, LEVELS

from . import presenter, store
from .agent import Agent, Session
from .regions import DataService
from .schemas import MessageIn, WhatIfIn
from .security import DeploymentGuard, SecuritySettings

SECURITY = SecuritySettings.load()
app = FastAPI(title="첫동네 API", version="0.1", docs_url=None if SECURITY.enabled else "/docs",
              redoc_url=None if SECURITY.enabled else "/redoc", openapi_url=None if SECURITY.enabled else "/openapi.json")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"], allow_headers=["*"],
)
app.add_middleware(DeploymentGuard, settings=SECURITY)

agent = Agent(DataService())
SESSIONS: dict[str, Session] = {}
_sessions_lock = threading.Lock()
_inflight: dict[str, object] = {}
_session_access: dict[str, tuple[str, float]] = {}


def _prune_sessions():
    """호출자는 _sessions_lock을 보유한다. 작업 중 세션은 삭제하지 않는다."""
    now = time.time()
    for sid, (_, touched) in list(_session_access.items()):
        if sid not in SESSIONS or (now - touched > 3600 and sid not in _inflight):
            _session_access.pop(sid, None)
            SESSIONS.pop(sid, None)


def _reserve(sid: str, expected: Session | None = None) -> object:
    with _sessions_lock:
        if expected is not None and SESSIONS.get(sid) is not expected:
            raise HTTPException(404, "세션이 없습니다")
        if sid in _inflight:
            raise HTTPException(409, "이 대화의 이전 요청을 처리 중입니다. 완료 후 다시 시도해 주세요.")
        token = object()
        _inflight[sid] = token
        return token


def _release(sid: str, token: object) -> None:
    with _sessions_lock:
        # 스트림 종료와 백그라운드 정리가 겹쳐도 다음 요청의 예약을 지우지 않는다.
        if _inflight.get(sid) is token:
            del _inflight[sid]


def _session(sid: str, request: Request) -> Session:
    with _sessions_lock:
        if getattr(request.state, "deployment_protected", False):
            _prune_sessions()
            access = _session_access.get(sid)
            if not access or access[0] != request.state.browser_owner:
                raise HTTPException(404, "세션이 없습니다")
            _session_access[sid] = (access[0], time.time())
        s = SESSIONS.get(sid)
        if not s:
            raise HTTPException(404, "세션이 없습니다")
        return s


def _session_view(s: Session) -> dict:
    payload = None
    if s.result is not None and s.dataset is not None:
        payload = presenter.result_payload(s.result, s.dataset.meta, None, presenter.tradeoffs(s.result))
    return {
        "session_id": s.id,
        "state": {**s.state.snapshot(), "destination": s.dest.to_dict() if s.dest else None},
        "messages": s.messages,
        "result": payload,
    }


@app.get("/api/health")
def health():
    return {"ok": True, "keys": key_status(), "store": store.stats()}


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}


@app.get("/api/meta")
def meta(request: Request):
    regions = store.list_sggs()
    if getattr(request.state, "deployment_protected", False):
        regions = [{**r, "error": "수집 실패" if r.get("error") else None} for r in regions]
    return {
        "factors": [{"key": f.key, "label": f.label, "better": f.better, "unit": f.unit, "description": f.description}
                    for f in FACTORS.values()],
        "levels": list(LEVELS),
        "regions": regions,
    }


@app.post("/api/sessions")
def create_session(request: Request):
    s = agent.new_session()
    s.id = secrets.token_hex(16)
    with _sessions_lock:
        if getattr(request.state, "deployment_protected", False):
            _prune_sessions()
            owner = request.state.browser_owner
            owned = [sid for sid, access in _session_access.items() if access[0] == owner]
            if len(owned) >= 3:
                idle = [sid for sid in owned if sid not in _inflight]
                if not idle:
                    raise HTTPException(429, "기존 대화 처리가 끝난 후 다시 시도해 주세요")
                oldest = min(idle, key=lambda sid: _session_access[sid][1])
                SESSIONS.pop(oldest, None)
                _session_access.pop(oldest, None)
            if len(SESSIONS) >= 16:
                raise HTTPException(503, "사용 중인 대화가 많습니다. 잠시 후 다시 시도해 주세요")
            _session_access[s.id] = (owner, time.time())
        SESSIONS[s.id] = s
    return _session_view(s)


@app.get("/api/sessions/{sid}")
def get_session(sid: str, request: Request):
    return _session_view(_session(sid, request))


@app.post("/api/sessions/{sid}/messages")
def post_message(sid: str, body: MessageIn, request: Request):
    """이벤트 스트림(text/event-stream)으로 진행 상황과 결과를 보낸다."""
    s = _session(sid, request)
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "빈 메시지")
    if getattr(request.state, "deployment_protected", False) and len(s.messages) >= 200:
        raise HTTPException(429, "새 대화를 시작해 주세요")
    token = _reserve(sid, s)

    def stream():
        try:
            for ev in agent.handle(s, text):
                if getattr(request.state, "deployment_protected", False):
                    # 공급자 진단 본문은 응답에 보내지 않는다. AI 추출·추천 계산은 그대로 둔다.
                    ev = {k: v for k, v in ev.items() if k != "info"}
                    if ev["type"] == "error" or (ev["type"] == "log" and ev.get("status") == "error"):
                        ev = {**ev, "detail": "처리 중 오류가 발생했어요. 잠시 후 다시 시도해 주세요."}
                yield f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
        finally:
            _release(sid, token)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                             background=BackgroundTask(_release, sid, token))


@app.post("/api/sessions/{sid}/what-if")
def what_if(sid: str, body: WhatIfIn, request: Request):
    s = _session(sid, request)
    token = _reserve(sid, s)
    try:
        changes = body.changes.model_dump(exclude_unset=True, exclude_none=True)
        if "set_constraints" in changes:
            changes["set_constraints"] = {k: v for k, v in changes["set_constraints"].items() if v is not None}
        return agent.what_if(s, changes)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    finally:
        _release(sid, token)


# 빌드된 프론트엔드가 있으면 같은 서버에서 제공
_dist = Path(ROOT) / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
