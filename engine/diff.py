"""두 결과 비교: 순위 변동과 "왜 바뀌었나" 요인별 분해.

두 동 A, B 의 점수 차 = Σ 100 × w_k × (A 정규화 값_k − B 정규화 값_k).
이전과 지금의 이 항을 요인별로 빼면, 격차 변화가 요인별로 정확히 나뉜다 (합이 맞아떨어짐).
"""

from .factors import FACTOR_KEYS, FACTORS
from .score import Result


def _gap_terms(a: dict, b: dict, weights: dict[str, float]) -> dict[str, float]:
    return {k: 100 * weights[k] * (a["norm"][k] - b["norm"][k]) for k in FACTOR_KEYS}


def explain_pair(prev: Result, cur: Result, code_a: str, code_b: str) -> dict:
    """A 와 B 사이 점수 격차(A − B)가 이전→지금 어떻게 바뀌었는지 요인별로."""
    pa, pb = prev.by_code()[code_a], prev.by_code()[code_b]
    ca, cb = cur.by_code()[code_a], cur.by_code()[code_b]
    before = _gap_terms(pa, pb, prev.weights)
    after = _gap_terms(ca, cb, cur.weights)
    change = {k: round(after[k] - before[k], 2) for k in FACTOR_KEYS}
    return {
        "a": {"dong_code": code_a, "name": ca["name"]},
        "b": {"dong_code": code_b, "name": cb["name"]},
        "gap_before": round(sum(before.values()), 2),
        "gap_after": round(sum(after.values()), 2),
        "by_factor": {FACTORS[k].label: v for k, v in sorted(change.items(), key=lambda kv: -abs(kv[1]))},
    }


def compare(prev: Result, cur: Result, top_n: int = 10) -> dict:
    p, c = prev.by_code(), cur.by_code()
    watch = list(dict.fromkeys([r["dong_code"] for r in prev.top(top_n)] + [r["dong_code"] for r in cur.top(top_n)]))

    moves = []
    for code in watch:
        pr, cr = p.get(code, {}).get("rank"), c.get(code, {}).get("rank")
        if pr != cr:
            name = (c.get(code) or p.get(code))["name"]
            moves.append({"dong_code": code, "name": name, "prev_rank": pr, "cur_rank": cr,
                          "change": (pr - cr) if pr and cr else None})
    moves.sort(key=lambda m: (m["cur_rank"] or 10**6, m["dong_code"]))

    # 지금 상위 3곳이 이전에 앞서 있던 동을 추월한 경우만 분해한다
    overtakes = []
    for a in cur.top(3):
        for b in prev.top(top_n):
            ca, cb = a["dong_code"], b["dong_code"]
            if ca == cb or ca not in p or cb not in c:
                continue
            if p[ca]["rank"] > p[cb]["rank"] and c[ca]["rank"] < c[cb]["rank"]:
                overtakes.append(explain_pair(prev, cur, ca, cb))

    weight_change = {FACTORS[k].label: round(cur.weights[k] - prev.weights[k], 3) for k in FACTOR_KEYS
                     if abs(cur.weights[k] - prev.weights[k]) > 1e-9}
    return {
        "moves": moves,
        "overtakes": overtakes,
        "weight_change": weight_change,
        "entered": [c[x]["name"] for x in c if x not in p],
        "dropped": [p[x]["name"] for x in p if x not in c],
    }
