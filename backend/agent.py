"""대화 한 턴의 흐름. 이벤트를 하나씩 내보낸다 (화면의 작업 로그·해석 카드·결과·설명).

발화 → [LLM] 변경분 추출 → [코드] 비교 순서 검증 → 목적지 해석 → 상태 갱신(검증)
     → 후보 지역 확보(없으면 수집) → [엔진] 순위 → 순위 변동 분해 → 상충 감지
     → [LLM] 설명 (숫자 검사, 실패 시 템플릿)

이벤트 종류: log / interpretation / result / message / error / done
"""

import copy
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field

from engine import State, apply_changes, compare, evaluate
from engine.features import Params
from engine.score import Result

from . import llm as llm_module
from . import presenter
from .regions import DataService, Destination


@dataclass
class Session:
    id: str
    state: State
    dest: Destination | None = None
    result: Result | None = None
    dataset: object = None
    ds_key: str | None = None
    last_question: str | None = None
    messages: list[dict] = field(default_factory=list)
    created: float = field(default_factory=time.time)


def _ev(type_: str, **kw) -> dict:
    return {"type": type_, "t": round(time.time(), 3), **kw}


def _log(step: str, status: str, detail: str, **kw) -> dict:
    return _ev("log", step=step, status=status, detail=detail, **kw)


class Agent:
    def __init__(self, data: DataService, llm=llm_module):
        self.data = data
        self.llm = llm

    def new_session(self) -> Session:
        return Session(id=uuid.uuid4().hex[:12], state=State(params=Params(destination="")))

    # ------------------------------------------------------------------ 한 턴
    def handle(self, s: Session, text: str):
        try:
            yield from self._handle(s, text)
        except Exception:  # 외부 조회·계산 예외도 SSE 완료 이벤트로 종료한다.
            yield _ev("error", detail="요청 처리 중 오류가 발생했어요. 잠시 후 다시 시도해 주세요.")
            yield _ev("done")

    def _handle(self, s: Session, text: str):
        s.messages.append({"role": "user", "text": text})

        # 1. 조건 해석
        yield _log("extract", "running", "발화에서 조건 추출 (Gemini)")
        snapshot = {**s.state.snapshot(), "destination": s.dest.label if s.dest else None}
        changes, info = self.llm.extract(snapshot, text, s.last_question)
        if info.get("error") and not any(changes.get(k) for k in ("destination", "preference_changes", "set_constraints")):
            yield _log("extract", "error", "조건 해석 실패", info=info)
            msg = "말씀을 잘 이해하지 못했어요. 출근지, 예산, 중요하게 생각하는 점을 한 번 더 말씀해 주세요."
            yield from self._say(s, msg, "template")
            yield _ev("done")
            return
        fixes = self.llm.enforce_comparisons(changes, s.state.levels)
        n_pref, n_con = len(changes["preference_changes"]), len([v for v in changes["set_constraints"].values() if v is not None])
        yield _log("extract", "done", f"선호 {n_pref}개, 필수 조건 {n_con}개, 확인 불가 {len(changes['unsupported'])}개",
                   ms=info.get("ms"), fixes=fixes)

        # 2. 목적지
        dest, follow_up = s.dest, changes.get("follow_up_question")
        if changes.get("destination"):
            q = changes["destination"]
            yield _log("destination", "running", f"목적지 찾기: {q}")
            found = self.data.resolve_destination(q)
            if found:
                dest = found
                yield _log("destination", "done", f"{found.label} → 통근 도착역 {found.key}"
                           + (f" (역에서 도보 {found.walk_from_station_min}분 더함)" if found.walk_from_station_min else ""))
            else:
                follow_up = f"'{q}'을(를) 지도에서 찾지 못했어요. 역 이름이나 회사 이름으로 다시 알려주시겠어요?"
                yield _log("destination", "error", f"'{q}' 검색 결과 없음")
        if not dest and not follow_up:
            follow_up = "어디로 출근(통학)하시나요? 역 이름이나 회사 이름을 알려주세요."

        # 3. 상태 갱신 (what_if 면 복사본에만)
        eng = {
            "set_constraints": {k: v for k, v in changes["set_constraints"].items() if v is not None},
            "clear_constraints": changes["clear_constraints"],
            "params": {**({"destination": dest.key} if dest else {}),
                       **({"house_types": changes["house_types"]} if changes.get("house_types") else {})},
            "preference_changes": changes["preference_changes"],
        }
        what_if = changes.get("intent") == "what_if"
        new_state, report = apply_changes(s.state, eng, destinations=[dest.key] if dest else [], utterance=text)
        yield _ev("interpretation", intent=changes.get("intent"), what_if=what_if,
                  applied=report["applied"], rejected=report["rejected"], unsupported=changes["unsupported"],
                  comparisons=changes.get("comparisons", []), comparison_fixes=fixes,
                  destination=dest.to_dict() if dest else None, follow_up=follow_up,
                  state={**new_state.snapshot(), "destination": dest.to_dict() if dest else None})

        if not dest:
            if not what_if:
                s.state = new_state
            yield from self._say(s, follow_up, "template", follow_up=True)
            yield _ev("done")
            return

        # 4. 후보 지역 데이터 (없으면 수집, 진행 로그를 실시간으로)
        same_destination = s.dest is not None and s.dest.to_dict() == dest.to_dict()
        if s.ds_key != dest.key or s.dataset is None or not same_destination:
            ds = None
            for item in self._run_with_logs(lambda log: self.data.dataset_for(dest, log)):
                if isinstance(item, dict):
                    yield item
                else:
                    ds = item
            if ds is None:
                yield _ev("error", detail="후보 지역 데이터를 만들지 못했어요")
                yield _ev("done")
                return
        else:
            ds = s.dataset
            yield _log("dataset", "done", f"후보 동 {len(ds.dongs)}곳 (이번 대화에서 이미 불러옴)")

        # 5. 점수
        if not ds.dongs:
            yield _ev("error", detail="추천에 사용할 동네 데이터가 없어요. 목적지를 바꾸거나 잠시 후 다시 시도해 주세요.")
            yield _ev("done")
            return
        t0 = time.time()
        res = evaluate(ds, new_state)
        yield _log("score", "done", f"필수 조건 → 정규화 → 가중합: 후보 {res.universe_size}곳 중 통과 {len(res.ranked)}곳",
                   ms=int((time.time() - t0) * 1000))
        prev = s.result if (s.result is not None and same_destination) else None
        diff = compare(prev, res) if prev else None
        trade = presenter.tradeoffs(res)
        if trade:
            yield _log("tradeoff", "warn", " / ".join(f"{'·'.join(t['factors'])}: {t['message']}" for t in trade))
        yield _ev("result", what_if=what_if, payload=presenter.result_payload(res, ds.meta, diff, trade))

        # 6. 설명
        yield _log("explain", "running", "결과 설명 작성 (Gemini, 엔진 숫자만 사용)")
        f = presenter.facts(res, destination=dest.to_dict(), report=report, diff=diff, trade=trade,
                            unsupported=changes["unsupported"], follow_up=follow_up,
                            question=text if changes.get("intent") == "question" else None)
        if what_if:
            f["what_if"] = True
        text_out, einfo = self.llm.explain(f)
        if text_out:
            yield _log("explain", "done", "설명 완료 (숫자 검사 통과)", ms=einfo.get("ms"), info=einfo)
            source = "llm"
        else:
            text_out = presenter.template_explanation(f)
            yield _log("explain", "warn", "LLM 설명이 숫자 검사를 통과하지 못해 템플릿 설명으로 대체", info=einfo)
            source = "template"

        # 7. 확정 (가정 질문이면 상태를 바꾸지 않는다)
        if not what_if:
            s.state, s.dest, s.result, s.dataset, s.ds_key = new_state, dest, res, ds, dest.key
        yield from self._say(s, text_out, source, follow_up=bool(follow_up))
        yield _ev("done")

    # ------------------------------------------------------------------ 가정 비교 (상태 안 바뀜)
    def what_if(self, s: Session, changes: dict) -> dict:
        if s.result is None or s.dataset is None or s.dest is None:
            raise ValueError("먼저 조건을 입력해 순위를 만들어 주세요")
        hyp, report = apply_changes(copy.deepcopy(s.state), changes, destinations=[s.dest.key])
        res = evaluate(s.dataset, hyp)
        diff = compare(s.result, res)
        return {"report": report, "payload": presenter.result_payload(res, s.dataset.meta, diff, presenter.tradeoffs(res))}

    # ------------------------------------------------------------------ 도우미
    def _say(self, s: Session, text: str, source: str, follow_up: bool = False):
        s.messages.append({"role": "assistant", "text": text, "source": source})
        s.last_question = text if follow_up else None
        yield _ev("message", text=text, source=source)

    @staticmethod
    def _run_with_logs(fn):
        """fn(log) 을 다른 스레드에서 돌리며, log 이벤트를 바로바로 내보내고 마지막에 반환값을 낸다."""
        q: queue.Queue = queue.Queue()
        out: dict = {}

        def log(step, status, detail, **kw):
            q.put(_log(step, status, detail, **kw))

        def run():
            try:
                out["value"] = fn(log)
            except Exception as e:  # noqa: BLE001
                q.put(_ev("error", detail=f"{type(e).__name__}: {e}"))
            finally:
                q.put(None)

        threading.Thread(target=run, daemon=True).start()
        while (item := q.get()) is not None:
            yield item
        if "value" in out:
            yield out["value"]
