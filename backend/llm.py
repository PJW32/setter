"""Gemini 호출: 앞단(발화 → 변경분), 뒷단(엔진 결과 → 설명).

- 앞단은 JSON 스키마로 출력을 강제하고, 코드가 다시 검증한다 (engine.state.apply_changes).
- 뒷단은 엔진이 만든 facts 에 있는 숫자만 쓰게 하고, 설명에 나온 숫자를 코드로 검사한다.
  facts 에 없는 숫자가 나오면 한 번 다시 쓰게 하고, 그래도 틀리면 코드 템플릿 설명으로 대체한다.
"""

import json
import os
import re
import time

from config import get_key
from engine.factors import LEVELS

from . import prompts

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
_client = None

EMPTY_CHANGES = {
    "intent": "other", "destination": None, "set_constraints": {}, "clear_constraints": [], "house_types": None,
    "preference_changes": [], "comparisons": [], "unsupported": [], "follow_up_question": None,
}


def client():
    global _client
    if _client is None:
        from google import genai  # 테스트에서 import 없이 돌 수 있게 지연 로딩

        # 이 키는 Agent Platform(Vertex) API 용이라 Vertex 엔드포인트로 호출한다
        _client = genai.Client(vertexai=True, api_key=get_key("GEMINI_API_KEY"))
    return _client


def _generate(system: str, contents: str, *, schema: dict | None = None, temperature: float = 0.2) -> str:
    config = {"system_instruction": system, "temperature": temperature}
    if schema:
        config.update({"response_mime_type": "application/json", "response_json_schema": schema})
    resp = client().models.generate_content(model=MODEL, contents=contents, config=config)
    return resp.text or ""


# ------------------------------------------------------------------ 앞단: 조건 추출
def extract(state_snapshot: dict, utterance: str, last_question: str | None = None) -> tuple[dict, dict]:
    """(변경분, 호출 정보). 실패하면 빈 변경분과 error."""
    contents = json.dumps({
        "현재_상태": state_snapshot,
        "직전_질문": last_question,
        "사용자_발화": utterance,
    }, ensure_ascii=False)
    info = {"model": MODEL}
    for attempt in range(2):
        t0 = time.time()
        try:
            text = _generate(prompts.EXTRACT_SYSTEM, contents, schema=prompts.EXTRACT_SCHEMA)
            data = json.loads(text)
            info.update({"ms": int((time.time() - t0) * 1000), "attempts": attempt + 1})
            return {**EMPTY_CHANGES, **data}, info
        except Exception as e:  # noqa: BLE001 - JSON 깨짐·일시 오류는 한 번 재시도
            info["error"] = f"{type(e).__name__}: {str(e)[:200]}"
    return dict(EMPTY_CHANGES), info


def enforce_comparisons(changes: dict, current_levels: dict[str, str]) -> list[str]:
    """'A가 B보다 중요'가 결과 단계에서 지켜지는지 코드로 확인하고, 어긋나면 고친다. 고친 내용을 돌려준다."""
    order = list(LEVELS)  # 매우 중요 → 상관없음 (앞이 높음)
    levels = dict(current_levels)
    pref = {p["factor"]: p for p in changes.get("preference_changes", []) if p.get("factor") in levels}
    for p in pref.values():
        if p.get("level") in LEVELS:
            levels[p["factor"]] = p["level"]
    fixes = []
    for cmp in changes.get("comparisons", []) or []:
        more, less = cmp.get("more"), cmp.get("less")
        if more not in levels or less not in levels or more == less:
            continue
        if order.index(levels[more]) < order.index(levels[less]):
            continue  # 이미 순서가 맞음
        if order.index(levels[less]) > 0:
            new_more = order[order.index(levels[less]) - 1]  # more 를 less 보다 한 단계 위로
            target, value = more, new_more
        else:
            target, value = less, order[1]  # less 가 이미 최고 단계면 less 를 한 단계 내림
        levels[target] = value
        ev = cmp.get("evidence", "")
        if target in pref:
            pref[target]["level"] = value
        else:
            pref[target] = {"factor": target, "level": value, "evidence": ev}
        fixes.append(f"{target} → {value} ('{more}'가 '{less}'보다 중요)")
    changes["preference_changes"] = list(pref.values())
    return fixes


# ------------------------------------------------------------------ 뒷단: 설명
_NUM = re.compile(r"\d+(?:[.,]\d+)*")


def _numbers(text: str) -> set[str]:
    out = set()
    for m in _NUM.findall(text):
        v = m.replace(",", "")
        try:
            f = float(v)
        except ValueError:
            continue
        out.add(f"{f:g}")
    return out


def unknown_numbers(text: str, facts: dict) -> list[str]:
    """설명문에 나왔지만 facts 에 없는 숫자. 순위를 나타내는 1~10 은 허용."""
    allowed = _numbers(json.dumps(facts, ensure_ascii=False)) | {str(i) for i in range(1, 11)}
    return sorted(_numbers(text) - allowed, key=lambda s: float(s))


def explain(facts: dict) -> tuple[str | None, dict]:
    """(설명문 또는 None, 호출 정보). None 이면 템플릿 설명을 쓴다."""
    contents = json.dumps(facts, ensure_ascii=False)
    info = {"model": MODEL, "attempts": 0}
    feedback = ""
    for attempt in range(2):
        info["attempts"] = attempt + 1
        t0 = time.time()
        try:
            text = _generate(prompts.EXPLAIN_SYSTEM, contents + feedback, temperature=0.3).strip()
        except Exception as e:  # noqa: BLE001
            info["error"] = f"{type(e).__name__}: {str(e)[:200]}"
            continue
        info["ms"] = int((time.time() - t0) * 1000)
        bad = unknown_numbers(text, facts)
        if not bad:
            return text, info
        info.setdefault("rejected_numbers", []).append(bad)
        feedback = f"\n\n[검사 결과] 방금 설명에 facts 에 없는 숫자 {bad} 가 있었다. facts 의 숫자만 그대로 써서 다시 써라."
    return None, info
