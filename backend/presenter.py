"""엔진 결과 → 화면용 JSON, LLM 설명용 facts, 템플릿 설명, 상충 감지."""

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
          top: int = 3) -> dict:
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
    return f


def template_explanation(f: dict) -> str:
    """LLM 설명이 실패하거나 숫자 검사를 통과하지 못했을 때 쓰는 코드 설명."""
    parts = []
    ch = f.get("changes")
    if ch and ch["순위변동"]:
        moves = ", ".join(f"{m['동']} {m['이전']}→{m['지금']}위" for m in ch["순위변동"][:3])
        parts.append(f"조건이 바뀌어 순위가 움직였어요: {moves}.")
    if f["상위"]:
        tops = []
        for d in f["상위"]:
            s = ", ".join(x["요인"] for x in d["강점"])
            tops.append(f"{d['순위']}위 {d['동']}(월 총비용 {d['월총비용_만원']}만 원, 통근 {d['통근_분']}분, 강점: {s})")
        parts.append(f"{f['목적지']} 기준 후보 {f['후보_동_수']}곳 중 조건을 만족한 {f['통과_동_수']}곳의 상위는 " + "; ".join(tops) + "입니다.")
    else:
        parts.append("조건을 모두 만족하는 동이 없어요.")
    if f.get("조건을_조금_풀면"):
        parts.append("조건을 조금 풀면 들어오는 동: " + ", ".join(x["동"] for x in f["조건을_조금_풀면"]) + ".")
    for t in f.get("tradeoffs", []):
        parts.append(f"참고로 {t['message']}.")
    if f.get("unsupported"):
        parts.append("'" + "', '".join(f["unsupported"]) + "'은(는) 데이터로 확인할 수 없어 직접 확인이 필요해요.")
    parts.append("월세는 실거래 기준 시세 참고용이에요.")
    if f.get("follow_up"):
        parts.append(f["follow_up"])
    return " ".join(parts)
