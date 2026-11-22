"""엔진 결과 → 화면용 JSON, LLM 설명·답변용 facts, 템플릿 문장, 상충 감지, 대화창 자료."""

import re
import statistics

from engine.factors import FACTORS, LEVELS
from engine.score import Result

LABEL = {k: f.label for k, f in FACTORS.items()}


def _r(v, nd=1):
    return round(v, nd) if isinstance(v, float) else v


# ------------------------------------------------------------------ 화면용
def dong_card(e: dict) -> dict:
    d = e["detail"]
    mc, cm, st = d.get("monthly_cost", {}), d.get("commute", {}), d.get("station_access", {})
    return {
        "dong_code": e["dong_code"], "name": e["name"], "sgg": e["sgg"], "sido": e.get("sido"),
        "lon": e["lon"], "lat": e["lat"],
        "rank": e.get("rank"), "score": e["score"],
        "contrib": e["contrib"], "raw": e["raw"], "norm": e["norm"],
        "flags": e["flags"], "estimated": e["estimated"],
        "cost": {"monthly_total": e["raw"].get("monthly_cost"), "median_deposit": mc.get("median_deposit"),
                 "median_rent": mc.get("median_rent"), "fare_month": mc.get("fare_month"), "samples": mc.get("samples")},
        "commute": cm,
        "station": st,
        "convenience": d.get("convenience", {}),
        "bars": d.get("quiet", {}),
        "violations": e.get("violations"),
    }


def pareto_codes(ranked: list[dict]) -> set[str]:
    """월 총비용·통근 둘 다 더 나은 동이 없는 동."""
    pts = [(e["dong_code"], e["raw"].get("monthly_cost"), e["raw"].get("commute")) for e in ranked]
    pts = [p for p in pts if p[1] is not None and p[2] is not None]
    out = set()
    for code, c, t in pts:
        if not any((c2 <= c and t2 <= t) and (c2 < c or t2 < t) for _, c2, t2 in pts):
            out.add(code)
    return out


def result_payload(res: Result, meta: dict, diff: dict | None, tradeoffs: list[dict]) -> dict:
    front = pareto_codes(res.ranked)
    return {
        "destination": meta.get("destination"),
        "universe_size": res.universe_size,
        "ranked": [dong_card(e) for e in res.ranked],
        "excluded": [dong_card(e) for e in res.excluded],
        "near_misses": [e["dong_code"] for e in res.near_misses],
        "scatter": [{"dong_code": e["dong_code"], "name": e["name"], "rank": e["rank"],
                     "x": e["raw"].get("monthly_cost"), "y": e["raw"].get("commute"),
                     "pareto": e["dong_code"] in front, "estimated": "monthly_cost" in e["estimated"]}
                    for e in res.ranked],
        "weights": res.weights, "levels": res.levels, "constraints": res.constraints,
        "bounds": res.bounds, "notes": res.notes, "diff": diff, "tradeoffs": tradeoffs,
        "sources": meta.get("sources"), "rent_period": meta.get("rent_period"),
        "labels": LABEL,
    }


# ------------------------------------------------------------------ 상충 감지
PAIRS = [  # (요인 A, 요인 B, A가 좋아질 때 B가 나빠지는 관계인지 보는 원값 방향)
    ("convenience", "quiet", "편의시설이 많은 동일수록 주점도 많습니다"),
    ("monthly_cost", "commute", "목적지에 가까운 동일수록 월 총비용이 높습니다"),
]


def _pearson(xs, ys):
    if len(xs) < 5:
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def tradeoffs(res: Result) -> list[dict]:
    """함께 '중요' 이상으로 올린 두 요인이 후보 동에서 서로 부딪히면 숫자와 함께 알린다."""
    out = []
    entries = res.ranked + res.excluded
    for a, b, msg in PAIRS:
        if LEVELS[res.levels.get(a, "보통")] < 3 or LEVELS[res.levels.get(b, "보통")] < 3:
            continue
        pts = [(e["norm"][a], e["norm"][b], e) for e in entries if a not in e["estimated"] and b not in e["estimated"]]
        r = _pearson([p[0] for p in pts], [p[1] for p in pts])
        if r is None or r > -0.3:  # 정규화 값(좋음=1)끼리 음의 상관이면 상충
            continue
        pts.sort(key=lambda p: p[0])
        q = max(1, len(pts) // 4)
        best_a, worst_a = pts[-q:], pts[:q]
        out.append({
            "factors": [LABEL[a], LABEL[b]], "correlation": round(r, 2), "message": msg,
            f"{LABEL[a]} 상위 25% 동의 {LABEL[b]} 원값 중앙값": _r(statistics.median(p[2]["raw"][b] for p in best_a)),
            f"{LABEL[a]} 하위 25% 동의 {LABEL[b]} 원값 중앙값": _r(statistics.median(p[2]["raw"][b] for p in worst_a)),
        })
    return out


# ------------------------------------------------------------------ LLM 설명용 facts
def _strengths(e: dict, n: int = 2) -> list[dict]:
    top = sorted(e["contrib"].items(), key=lambda kv: -kv[1])[:n]
    return [{"요인": LABEL[k], "기여점수": _r(v)} for k, v in top]


def dong_facts(e: dict) -> dict:
    c = dong_card(e)
    return {
        "순위": e.get("rank"), "동": f"{e['sgg']} {e['name']}", "점수": _r(e["score"]),
        "월총비용_만원": _r(c["cost"]["monthly_total"]),
        "보증금_중앙값_만원": _r(c["cost"]["median_deposit"]), "월세_중앙값_만원": _r(c["cost"]["median_rent"]),
        "월교통비_만원": c["cost"]["fare_month"], "실거래_표본": c["cost"]["samples"],
        "통근_분": c["raw"].get("commute"), "통근_수단": c["commute"].get("mode"), "노선": c["commute"].get("lines"),
        "가까운역": c["station"].get("name"), "역까지_도보_분": c["raw"].get("station_access"),
        "편의시설": c["convenience"], "주점_수": c["raw"].get("quiet"),
        "강점": _strengths(e), "주의": e["flags"],
    }


def facts(res: Result, *, destination: dict | None, report: dict | None, diff: dict | None,
          trade: list[dict], unsupported: list[str], follow_up: str | None, question: str | None,
          top: int = 3, targets: list[dict] | None = None, guides_: list[dict] | None = None,
          first: bool = False) -> dict:
    f = {
        "목적지": destination.get("label") if destination else None,
        "후보_동_수": res.universe_size, "통과_동_수": len(res.ranked), "제외_동_수": len(res.excluded),
        "가중치_단계": {LABEL[k]: v for k, v in res.levels.items()},
        "필수조건": res.constraints,
        "상위": [dong_facts(e) for e in res.top(top)],
        "tradeoffs": trade, "unsupported": unsupported, "follow_up": follow_up,
    }
    if report:
        f["이번_변경"] = [{k: v for k, v in a.items() if k != "type"} for a in report.get("applied", [])]
    if diff:
        f["changes"] = {
            "순위변동": [{"동": m["name"], "이전": m["prev_rank"], "지금": m["cur_rank"]} for m in diff["moves"][:6]],
            "overtakes": [{"앞선_동": o["a"]["name"], "뒤진_동": o["b"]["name"], "격차_이전": o["gap_before"],
                           "격차_지금": o["gap_after"], "요인별_변화": o["by_factor"]} for o in diff["overtakes"][:2]],
        }
    if res.near_misses:
        f["조건을_조금_풀면"] = [{"동": e["name"], "풀어야_할_조건": [v["relax_to"] for v in e["violations"]]}
                           for e in res.near_misses]
    if question:
        f["user_question"] = question
    if targets:
        f["대상_동네"] = [target_facts(e) for e in targets]
        if len(targets) >= 2:
            f["비교"] = [compare_facts(targets[0], t) for t in targets[1:3]]
    if guides_:
        f["확인_방법"] = guides_
    f["첫_결과"] = first
    return f


def template_explanation(f: dict) -> str:
    """LLM 설명이 실패하거나 숫자 검사를 통과하지 못했을 때 쓰는 코드 설명."""
    parts = []
    ch = f.get("changes")
    if ch and ch["순위변동"]:
        moves = ", ".join(f"{m['동']} {m['이전']}→{m['지금']}위" for m in ch["순위변동"][:3])
        parts.append(f"조건이 바뀌어 순위가 움직였어요: {moves}.")
    if f["상위"]:
        parts.append(f"{f['목적지']} 기준 후보 {f['후보_동_수']}곳 중 {f['통과_동_수']}곳이 조건에 맞아요.")
        for d in f["상위"]:
            s = ", ".join(x["요인"] for x in d["강점"])
            cost = "확인 불가" if d["월총비용_만원"] is None else f"{d['월총비용_만원']}만 원"
            commute = "확인 불가" if d["통근_분"] is None else f"{d['통근_분']}분"
            parts.append(f"{d['순위']}위 {d['동']}: 월 총비용 {cost}, 통근 {commute} (강점: {s})")
    else:
        parts.append("조건을 모두 만족하는 동이 없어요.")
    if f.get("조건을_조금_풀면"):
        parts.append("조건을 조금 풀면 들어오는 동: " + ", ".join(x["동"] for x in f["조건을_조금_풀면"]) + ".")
    for t in f.get("tradeoffs", []):
        parts.append(f"참고로 {t['message']}.")
    if f.get("unsupported"):
        parts.append("'" + "', '".join(f["unsupported"]) + "'은(는) 데이터로 확인할 수 없어 직접 확인이 필요해요.")
    if f.get("첫_결과", True):
        parts.append("월세는 실거래 기준 시세 참고용이에요.")
    if f.get("follow_up"):
        parts.append(f["follow_up"])
    return "\n".join(parts)


# ------------------------------------------------------------------ 질문 속 동네 찾기
_RANK_RE = re.compile(r"(\d{1,2})\s*위")
CONSTRAINT_TEXT = {
    "max_deposit": ("보증금 상한", "만원"), "max_monthly_rent": ("월세 상한", "만원"),
    "max_commute_min": ("통근 상한", "분"), "max_monthly_cost": ("월 총비용 상한", "만원"),
}


def _stem(name: str) -> str:
    return name[:-1] if name.endswith("동") and len(name) >= 3 else name


def find_targets(res: Result, text: str, names: list[str] | None = None, ranks: list[int] | None = None,
                 limit: int = 4) -> tuple[list[dict], list[str]]:
    """질문에 나온 동네를 지금 결과(통과+제외)에서 찾는다. (찾은 동 entry 목록, 못 찾은 이름 목록)

    LLM 이 뽑은 이름·순위와, 발화를 코드로 훑은 결과를 함께 쓴다.
    """
    entries = res.ranked + res.excluded
    found: list[dict] = []

    def add(e):
        if all(e["dong_code"] != f["dong_code"] for f in found):
            found.append(e)

    for r in list(ranks or []) + [int(m) for m in _RANK_RE.findall(text or "")]:
        if 1 <= r <= len(res.ranked):
            add(res.ranked[r - 1])
    missing = []
    for raw in names or []:
        n = (raw or "").replace(" ", "")
        if not n:
            continue
        hit = [e for e in entries if _stem(n) == _stem(e["name"])]
        if hit:
            for e in hit:
                add(e)
        elif not any(_stem(n) == _stem(e["name"]) for e in found):
            missing.append(raw)
    compact = (text or "").replace(" ", "")
    for e in entries:  # LLM 이 놓친 동 이름도 발화에서 직접 찾는다 ('정자동', '정자동은' 등)
        if e["name"] in compact:
            add(e)
    return found[:limit], missing


# ------------------------------------------------------------------ 동네 상세·비교 (숫자 계산은 코드가)
def violation_text(v: dict) -> str:
    if v["constraint"] == "budget":
        return f"예산 안 실거래가 {v.get('in_budget')}/{v.get('samples')}건으로 기준(3건)보다 적음"
    if v["constraint"] == "commute":
        return f"통근 {_r(v.get('value'))}분이 한도 {_r(v.get('limit'))}분을 넘음"
    return f"월 총비용 {_r(v.get('value'))}만 원이 한도 {_r(v.get('limit'))}만 원을 넘음"


def relax_text(relax: dict) -> dict:
    return {CONSTRAINT_TEXT[k][0]: f"{_r(v)}{CONSTRAINT_TEXT[k][1]}" for k, v in relax.items() if k in CONSTRAINT_TEXT}


def target_facts(e: dict) -> dict:
    f = dong_facts(e)
    if e.get("rank"):
        f["상태"] = f"조건을 만족한 동네 중 {e['rank']}위"
    else:
        f["상태"] = "조건 밖이라 순위에서 제외"
        f["제외_이유"] = [violation_text(v) for v in e.get("violations") or []]
        f["풀면_들어오는_조건"] = [relax_text(v["relax_to"]) for v in e.get("violations") or [] if v.get("relax_to")]
    f["요인별_점수"] = {LABEL[k]: _r(v) for k, v in e["contrib"].items()}
    return f


# (표시 이름, dong_facts 키, 단위, 낮을수록 좋은가)
COMPARE_FIELDS = [
    ("점수", "점수", "점", False),
    ("월 총비용", "월총비용_만원", "만원", True),
    ("월세 중앙값", "월세_중앙값_만원", "만원", True),
    ("보증금 중앙값", "보증금_중앙값_만원", "만원", True),
    ("월 교통비", "월교통비_만원", "만원", True),
    ("통근 시간", "통근_분", "분", True),
    ("역까지 도보", "역까지_도보_분", "분", True),
    ("주변 주점", "주점_수", "곳", True),
]


def compare_items(a: dict, b: dict) -> list[dict]:
    """두 동네의 항목별 값과 차이(A − B). 화면과 LLM 이 쓰는 차이는 모두 여기서 계산한다."""
    fa, fb = dong_facts(a), dong_facts(b)
    items = []
    for label, key, unit, lower_better in COMPARE_FIELDS:
        va, vb = fa.get(key), fb.get(key)
        diff = round(va - vb, 1) if isinstance(va, (int, float)) and isinstance(vb, (int, float)) else None
        better = None
        if diff:
            better = a["name"] if (diff < 0) == lower_better else b["name"]
        items.append({"label": label, "unit": unit, "a": _r(va), "b": _r(vb), "diff": diff,
                      "abs_diff": abs(diff) if diff is not None else None, "better": better})
    return items


def compare_facts(a: dict, b: dict) -> dict:
    return {
        "A": a["name"], "B": b["name"],
        "항목": [{"항목": i["label"], "A": i["a"], "B": i["b"], "차이_A빼기B": i["diff"], "차이_크기": i["abs_diff"],
                 "단위": i["unit"], "더_나은_쪽": i["better"]} for i in compare_items(a, b)],
    }


def _summary_row(e: dict) -> dict:
    return {"순위": e.get("rank"), "동": e["name"], "점수": _r(e["score"]),
            "월총비용_만원": _r(e["raw"].get("monthly_cost")), "통근_분": e["raw"].get("commute"),
            "역까지_도보_분": e["raw"].get("station_access")}


def answer_facts(res: Result, *, question: str, destination: dict | None, params: dict, targets: list[dict],
                 missing: list[str], guides_: list[dict], history: list[dict], meta: dict) -> dict:
    """질문 답변용 facts: 지금 결과 요약 + 질문한 동네 상세 + 코드가 계산한 비교 + 확인 방법 + 최근 대화."""
    f = {
        "user_question": question,
        "목적지": destination.get("label") if destination else None,
        "현재_조건": {
            "필수조건": {CONSTRAINT_TEXT[k][0]: f"{_r(v)}{CONSTRAINT_TEXT[k][1]}" for k, v in res.constraints.items()},
            "가중치_단계": {LABEL[k]: v for k, v in res.levels.items()},
            "주택_유형": params.get("house_types"), "원룸_면적_상한_m2": params.get("max_area_m2"),
            "신규계약만": params.get("new_contracts_only"),
        },
        "후보_동_수": res.universe_size, "통과_동_수": len(res.ranked), "제외_동_수": len(res.excluded),
        "순위_요약": [_summary_row(e) for e in res.top(10)],
        "제외_요약": [{"동": e["name"], "이유": [violation_text(v) for v in e.get("violations") or []]}
                    for e in res.excluded[:8]],
        "대상_동네": [target_facts(e) for e in targets],
        "찾지_못한_동네": missing,
        "확인_방법": guides_,
        "데이터_출처": meta.get("sources"), "실거래_기간": meta.get("rent_period"),
        "최근_대화": [{"역할": m["role"], "내용": m["text"][:200]} for m in history[-6:]],
    }
    if len(targets) >= 2:
        f["비교"] = [compare_facts(targets[0], t) for t in targets[1:3]]
    return f


def template_answer(f: dict) -> str:
    """LLM 답변이 실패하거나 숫자 검사를 통과하지 못했을 때 쓰는 코드 답변."""
    lines = []
    for d in f.get("대상_동네", []):
        cost = "확인 불가" if d["월총비용_만원"] is None else f"{d['월총비용_만원']}만 원"
        lines.append(f"· {d['동']}: {d['상태']}, 월 총비용 {cost}, 통근 {d['통근_분']}분")
        for why in d.get("제외_이유", []):
            lines.append(f"  제외 이유: {why}")
    for c in f.get("비교", []):
        cost = next(i for i in c["항목"] if i["항목"] == "월 총비용")
        if cost["차이_크기"]:
            lines.append(f"· 월 총비용은 {cost['더_나은_쪽']}이(가) {cost['차이_크기']}만 원 낮아요.")
    if f.get("찾지_못한_동네"):
        lines.append(f"'{', '.join(f['찾지_못한_동네'])}'은(는) 지금 목적지 주변 후보에 없어요. 목적지를 바꾸면 볼 수 있어요.")
    for g in f.get("확인_방법", []):
        lines.append(f"· {g['topic']}: {g['how']}")
    if not lines:
        lines.append("지금 결과로는 답하기 어려운 질문이에요. 궁금한 동네 이름이나 조건을 넣어 다시 물어봐 주세요.")
    return "\n".join(lines)


# ------------------------------------------------------------------ 짧은 대답 (인사·확인)
def short_reply(intent: str, text: str, has_result: bool) -> str:
    t = (text or "").lower()
    if any(k in t for k in ("고마", "감사", "땡큐", "thank")):
        return "도움이 됐다니 다행이에요. 다른 동네나 조건이 궁금하면 편하게 물어보세요."
    if any(k in t for k in ("안녕", "하이", "hello", "hi")):
        return ("안녕하세요! 지금 결과에서 궁금한 동네를 묻거나 조건을 바꿔 보세요." if has_result
                else "안녕하세요! 어디로 출근하는지와 예산을 알려 주시면 살기 좋은 동네를 찾아 드릴게요.")
    if intent == "confirm":
        return ("좋아요, 지금 조건으로 볼게요. 바꾸고 싶은 점이 생기면 말씀해 주세요." if has_result
                else "좋아요. 출근할 곳과 예산을 알려 주세요.")
    return ("지금 결과에 대해 묻거나(예: '정자동은 어때?'), 조건을 바꿔 보세요(예: '월세 70까지 괜찮아')." if has_result
            else "출근할 곳, 예산, 중요하게 생각하는 점을 알려 주시면 동네를 비교해 드릴게요.")


# ------------------------------------------------------------------ 대화창에 함께 보여줄 자료
def attachment_row(e: dict) -> dict:
    return {
        "dong_code": e["dong_code"], "name": e["name"], "sgg": e["sgg"],
        "status": f"{e['rank']}위" if e.get("rank") else "조건 밖",
        "excluded": not e.get("rank"),
        "score": _r(e["score"]), "monthly_cost": _r(e["raw"].get("monthly_cost")),
        "commute": e["raw"].get("commute"), "station_walk": e["raw"].get("station_access"),
        "bars": e["raw"].get("quiet"),
        "reason": "; ".join(violation_text(v) for v in e.get("violations") or []) or None,
    }


def attachments(*, rows: list[dict], title: str, guides_: list[dict]) -> list[dict]:
    out = []
    if rows:
        att = {"kind": "dongs", "title": title, "rows": [attachment_row(e) for e in rows]}
        if len(rows) == 2:
            att["compare"] = {"a": rows[0]["name"], "b": rows[1]["name"], "items": compare_items(rows[0], rows[1])}
        out.append(att)
    if guides_:
        out.append({"kind": "guides", "title": "직접 확인하는 방법", "items": guides_})
    return out
