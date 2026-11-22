"""발화 테스트 세트로 조건 추출(Gemini)을 평가한다. Docs/mvp-test-scenarios.md 2절과 같은 목록.

실행:  python scripts/eval_utterances.py
결과:  화면 표 + data/raw/eval_utterances.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import llm  # noqa: E402
from config import ROOT  # noqa: E402
from engine.factors import LEVELS  # noqa: E402

BASE_LEVELS = {k: "보통" for k in ("monthly_cost", "commute", "station_access", "convenience", "quiet")}

CASES = [
    ("월세가 제일 중요해", {"levels": {"monthly_cost": "매우 중요"}, "no_constraints": True}),
    ("통근은 1시간까지 괜찮아", {"constraints": {"max_commute_min": 60}, "not_up": ["commute"]}),
    ("보증금 500에 월세 50 이하로만", {"constraints": {"max_deposit": 500, "max_monthly_rent": 50}}),
    ("싸면 좋겠어", {"levels": {"monthly_cost": "up"}, "no_constraints": True}),
    ("역세권이었으면 좋겠어", {"levels": {"station_access": "up"}}),
    ("조용한 동네가 좋아", {"levels": {"quiet": "up"}}),
    ("편의점 많고 조용한 데", {"levels": {"convenience": "up", "quiet": "up"}, "follow_up": True}),
    ("이웃이 친절했으면", {"unsupported": True, "no_level_change": True}),
    ("밤길이 안전했으면 좋겠어", {"unsupported": True, "unchanged": ["quiet"]}),
    ("통근보다 월세가 더 중요해", {"order": ("monthly_cost", "commute")}),
    ("편의시설은 상관없어", {"levels": {"convenience": "상관없음"}}),
    ("오피스텔만 볼래", {"house_types": ["오피스텔"]}),
    ("강남역으로 출근해요", {"destination": "강남역"}),
    ("회사가 카카오 판교아지트야", {"destination": "카카오 판교아지트"}),
    ("월세 한도는 없어도 돼", {"clear": ["max_monthly_rent"]}),
    ("한 달에 총 80만원 넘으면 안 돼", {"constraints": {"max_monthly_cost": 80}}),
    ("보증금 1억까지 가능해", {"constraints": {"max_deposit": 10000}}),
    ("통근 30분 이내면 어떻게 돼?", {"intent": "what_if", "constraints": {"max_commute_min": 30}}),
    ("관리비 싼 곳", {"unsupported_or_cost": True}),
    ("아까보다 월세는 덜 중요해", {"levels": {"monthly_cost": "중요"}, "start": {"monthly_cost": "매우 중요"}}),
    # 의도 분류 (조건을 바꾸지 않는 발화는 순위를 다시 계산하지 않는다)
    ("고마워요", {"intent_in": ["smalltalk", "confirm"], "no_level_change": True, "no_constraints": True}),
    ("정자동은 왜 순위에 없어?", {"intent": "question", "mentioned": ["정자동"], "no_level_change": True, "no_constraints": True}),
    ("1위랑 2위 비교해줘", {"intent": "question", "ranks": [1, 2], "no_level_change": True}),
    ("그 동네 치안은 어때?", {"intent": "question", "no_level_change": True, "no_constraints": True}),
]


def check(ch: dict, exp: dict, start: dict) -> list[str]:
    fails = []
    lv = dict(start)
    for p in ch["preference_changes"]:
        lv[p["factor"]] = p["level"]
    cons = {k: v for k, v in (ch["set_constraints"] or {}).items() if v is not None}
    rank = {k: LEVELS[v] for k, v in lv.items()}
    for f, want in exp.get("levels", {}).items():
        if want == "up" and rank[f] <= LEVELS[start[f]]:
            fails.append(f"{f} 가 올라가지 않음 ({lv[f]})")
        elif want not in ("up",) and lv[f] != want:
            fails.append(f"{f} = {lv[f]} (기대 {want})")
    for k, v in exp.get("constraints", {}).items():
        if cons.get(k) is None or abs(float(cons[k]) - v) > 1e-6:
            fails.append(f"{k} = {cons.get(k)} (기대 {v})")
    if exp.get("no_constraints") and cons:
        fails.append(f"필수 조건이 생김 {cons}")
    for f in exp.get("not_up", []):
        if rank[f] > LEVELS[start[f]]:
            fails.append(f"{f} 가 올라감")
    for f in exp.get("unchanged", []):
        if lv[f] != start[f]:
            fails.append(f"{f} 가 바뀜 ({lv[f]})")
    if exp.get("no_level_change") and lv != start:
        fails.append(f"요인이 바뀜 {lv}")
    if exp.get("unsupported") and not ch["unsupported"]:
        fails.append("unsupported 비어 있음")
    if exp.get("follow_up") and not ch.get("follow_up_question"):
        fails.append("되묻기 없음")
    if "order" in exp:
        a, b = exp["order"]
        if rank[a] <= rank[b]:
            fails.append(f"순서 어긋남 {a}={lv[a]}, {b}={lv[b]}")
    if "house_types" in exp and sorted(ch.get("house_types") or []) != sorted(exp["house_types"]):
        fails.append(f"house_types = {ch.get('house_types')}")
    if "destination" in exp and (ch.get("destination") or "").replace(" ", "") != exp["destination"].replace(" ", ""):
        fails.append(f"destination = {ch.get('destination')}")
    for k in exp.get("clear", []):
        if k not in (ch.get("clear_constraints") or []):
            fails.append(f"{k} 해제 안 됨")
    if "intent" in exp and ch.get("intent") != exp["intent"]:
        fails.append(f"intent = {ch.get('intent')}")
    if "intent_in" in exp and ch.get("intent") not in exp["intent_in"]:
        fails.append(f"intent = {ch.get('intent')}")
    for name in exp.get("mentioned", []):
        if name not in (ch.get("mentioned_dongs") or []):
            fails.append(f"mentioned_dongs = {ch.get('mentioned_dongs')}")
    if "ranks" in exp and sorted(ch.get("mentioned_ranks") or []) != exp["ranks"]:
        fails.append(f"mentioned_ranks = {ch.get('mentioned_ranks')}")
    if exp.get("unsupported_or_cost") and not (ch["unsupported"] or rank["monthly_cost"] > 2):
        fails.append("관리비를 확인 불가로도, 비용 선호로도 받지 않음")
    return fails


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    rows, passed = [], 0
    for i, (text, exp) in enumerate(CASES, 1):
        start = {**BASE_LEVELS, **exp.get("start", {})}
        snapshot = {"levels": start, "constraints": {}, "params": {"house_types": ["오피스텔", "단독다가구"]},
                    "destination": "판교역", "후보_동네": ["이매동", "풍덕천동", "서현동", "정자동", "수내동"],
                    "현재_상위": ["1위 이매동", "2위 풍덕천동", "3위 서현동"],
                    "최근_대화": [{"역할": "assistant", "내용": "1위 이매동, 2위 풍덕천동, 3위 서현동입니다."}]}
        ch, info = llm.extract(snapshot, text)
        fixes = llm.enforce_comparisons(ch, start)
        fails = check(ch, exp, start)
        ok = not fails
        passed += ok
        rows.append({"no": i, "utterance": text, "pass": ok, "fails": fails, "fixes": fixes, "changes": ch, "info": info})
        print(f"{i:>2}. {'통과' if ok else '실패'} | {text} | {'; '.join(fails) if fails else ''}"
              + (f" | 코드 교정: {fixes}" if fixes else ""), flush=True)
    print(f"\n통과 {passed}/{len(CASES)}")
    out = ROOT / "data" / "raw" / "eval_utterances.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"passed": passed, "total": len(CASES), "rows": rows}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"저장: {out}")


if __name__ == "__main__":
    main()
