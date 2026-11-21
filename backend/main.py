"""FastAPI 서버.

실행:  python -m uvicorn backend.main:app --reload --port 8000
"""

import json
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import ROOT, key_status
from engine.factors import FACTORS, LEVELS

from . import presenter, store
from .agent import Agent, Session
from .regions import DataService

app = FastAPI(title="첫동네 API", version="0.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"], allow_headers=["*"],
)

agent = Agent(DataService())
SESSIONS: dict[str, Session] = {}
_sessions_lock = threading.Lock()


class MessageIn(BaseModel):
    text: str


class WhatIfIn(BaseModel):
    changes: dict


def _session(sid: str) -> Session:
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


@app.get("/api/meta")
def meta():
    return {
        "factors": [{"key": f.key, "label": f.label, "better": f.better, "unit": f.unit, "description": f.description}
                    for f in FACTORS.values()],
        "levels": list(LEVELS),
        "regions": store.list_sggs(),
    }


@app.post("/api/sessions")
def create_session():
    s = agent.new_session()
    with _sessions_lock:
        SESSIONS[s.id] = s
    return _session_view(s)


@app.get("/api/sessions/{sid}")
def get_session(sid: str):
    return _session_view(_session(sid))


@app.post("/api/sessions/{sid}/messages")
def post_message(sid: str, body: MessageIn):
    """이벤트 스트림(text/event-stream)으로 진행 상황과 결과를 보낸다."""
    s = _session(sid)
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "빈 메시지")

    def stream():
        for ev in agent.handle(s, text):
            yield f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/sessions/{sid}/what-if")
def what_if(sid: str, body: WhatIfIn):
    try:
        return agent.what_if(_session(sid), body.changes)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


# 빌드된 프론트엔드가 있으면 같은 서버에서 제공
_dist = Path(ROOT) / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
