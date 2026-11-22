"""필수 조건 → 정규화 → 가중합 → 기여도 → 순위.

정규화 구간은 필수 조건을 적용하기 전 '전체 후보'의 5~95 백분위로 정한다.
그래서 예산을 바꿔 동 하나가 빠져도 다른 동의 정규화 값은 바뀌지 않는다.
"""

import math
import statistics
from dataclasses import asdict, dataclass, field

from .factors import FACTOR_KEYS, FACTORS, normalize_weights
from .features import DongFeature

MIN_IN_BUDGET = 3  # 예산 안 거래가 이보다 적으면 제외
NEAR_MISS_COUNT = 3


@dataclass
class Constraints:
    """필수 조건. None 이면 조건 없음. 금액은 만원."""

    max_deposit: float | None = None
    max_monthly_rent: float | None = None
    max_commute_min: float | None = None
    max_monthly_cost: float | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @property
    def has_budget(self) -> bool:
        return self.max_deposit is not None or self.max_monthly_rent is not None


@dataclass
class Result:
    ranked: list[dict]
    excluded: list[dict]
    near_misses: list[dict]
    weights: dict[str, float]
    levels: dict[str, str]
    bounds: dict[str, tuple[float, float]]
    constraints: dict
    universe_size: int
    notes: list[str] = field(default_factory=list)

    def top(self, n: int) -> list[dict]:
        return self.ranked[:n]

    def by_code(self) -> dict[str, dict]:
        return {r["dong_code"]: r for r in self.ranked}

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ 정규화 구간
def compute_bounds(features: list[DongFeature]) -> dict[str, tuple[float, float]]:
    bounds = {}
    for k in FACTOR_KEYS:
        if k == "convenience":  # 이미 0~100 점수
            bounds[k] = (0.0, 100.0)
            continue
        vals = sorted(f.raw[k] for f in features if f.raw.get(k) is not None)
        if len(vals) >= 2:
            q = statistics.quantiles(vals, n=20, method="inclusive")
            lo, hi = q[0], q[-1]
            if hi <= lo:
                lo, hi = vals[0], vals[-1]
        elif vals:
            lo, hi = vals[0], vals[0]
        else:
            lo, hi = 0.0, 1.0
        if hi <= lo:
            hi = lo + 1.0
        bounds[k] = (lo, hi)
    return bounds


def normalize(key: str, value: float, bounds: tuple[float, float]) -> float:
    lo, hi = bounds
    x = min(1.0, max(0.0, (value - lo) / (hi - lo)))
    return 1.0 - x if FACTORS[key].better == "low" else x


# ------------------------------------------------------------------ 필수 조건
def _budget_check(f: DongFeature, c: Constraints, min_samples: int) -> dict:
    """예산 조건 평가. status = pass / exclude / unverified."""
    deals = f.deals
    if len(deals) < min_samples:
        return {"status": "unverified", "samples": len(deals)}

    def need(d) -> float:  # 이 거래가 예산 안에 들어오려면 예산을 몇 배로 늘려야 하나
        r = []
        if c.max_monthly_rent is not None:
            r.append(d.monthly_rent / c.max_monthly_rent if c.max_monthly_rent > 0
                     else (0.0 if d.monthly_rent == 0 else 1.0 + d.monthly_rent))
        if c.max_deposit is not None:
            # 0원 거래는 0원 한도를 충족한다. 양수 거래도 유한한 위반도로 표현한다.
            r.append(d.deposit / c.max_deposit if c.max_deposit > 0
                     else (0.0 if d.deposit == 0 else 1.0 + d.deposit))
        return max(r)

    closest = sorted(deals, key=lambda d: (need(d), d.deposit, d.monthly_rent))[:MIN_IN_BUDGET]
    in_budget = [d for d in deals if need(d) <= 1.0]
    out = {"samples": len(deals), "in_budget": len(in_budget), "share": round(len(in_budget) / len(deals), 2)}
    if len(in_budget) >= MIN_IN_BUDGET:
        out["status"] = "pass"
        totals = [d.monthly_total for d in in_budget]
        out["monthly_cost_in_budget"] = statistics.median(totals) if all(v is not None for v in totals) else None
        out["cost_detail"] = {
            **f.detail.get("monthly_cost", {}),
            "samples": len(in_budget),
            "median_deposit": statistics.median(d.deposit for d in in_budget),
            "median_rent": statistics.median(d.monthly_rent for d in in_budget),
        }
        return out
    k = need(closest[-1])
    out["status"] = "exclude"
    out["severity"] = k
    relax = {}
    # 같은 실제 거래 3건이 들어오도록 필요한 한도만 올린다.
    # 위반도는 정렬용이며, 다른 조건의 한도에 곱할 배수가 아니다 (특히 0원 한도).
    for key, field_name in (("max_monthly_rent", "monthly_rent"), ("max_deposit", "deposit")):
        limit = getattr(c, key)
        required = max(getattr(d, field_name) for d in closest)
        if limit is not None and required > limit:
            relax[key] = math.ceil(required)
    out["relax_to"] = relax
    return out


def _check(f: DongFeature, c: Constraints, min_samples: int) -> tuple[list[dict], list[str], float | None, dict]:
    """위반 목록, 플래그, 월 총비용, 같은 비교군의 상세 통계를 반환한다."""
    violations, flags = [], []
    cost = f.raw.get("monthly_cost")
    detail = {**f.detail, "monthly_cost": dict(f.detail.get("monthly_cost", {}))}

    if c.has_budget:
        b = _budget_check(f, c, min_samples)
        if b["status"] == "exclude":
            violations.append({"constraint": "budget", "severity": b["severity"], "in_budget": b["in_budget"],
                               "samples": b["samples"], "relax_to": b["relax_to"]})
        elif b["status"] == "unverified":
            flags.append(f"예산 확인 불가 (실거래 {b['samples']}건)")
        else:
            cost = b["monthly_cost_in_budget"]
            detail["monthly_cost"] = b["cost_detail"]
            flags.append(f"예산 안 거래 {b['in_budget']}/{b['samples']}건")

    commute = f.raw.get("commute")
    if c.max_commute_min is not None:
        if commute is None:
            flags.append("통근 한도 확인 불가")
        elif commute > c.max_commute_min:
            violations.append({"constraint": "commute", "severity": commute / c.max_commute_min,
                               "value": commute, "limit": c.max_commute_min,
                               "relax_to": {"max_commute_min": math.ceil(commute)}})

    if detail["monthly_cost"].get("fare_missing"):
        flags.append("교통비 확인 불가")
    if c.max_monthly_cost is not None and cost is None:
        flags.append("월 총비용 한도 확인 불가")
    if c.max_monthly_cost is not None and cost is not None and cost > c.max_monthly_cost:
        violations.append({"constraint": "monthly_cost", "severity": cost / c.max_monthly_cost,
                           "value": round(cost, 1), "limit": c.max_monthly_cost,
                           "relax_to": {"max_monthly_cost": math.ceil(cost)}})
    return violations, flags, cost, detail


# ------------------------------------------------------------------ 순위
def rank(features: list[DongFeature], levels: dict[str, str], constraints: Constraints | None = None,
         *, min_samples: int = 5) -> Result:
    c = constraints or Constraints()
    weights = normalize_weights(levels)
    bounds = compute_bounds(features)

    # 값이 없을 때 쓸 정규화 값: 전체 후보의 중앙값 (이득도 손해도 없게)
    fill = {}
    for k in FACTOR_KEYS:
        ns = [normalize(k, f.raw[k], bounds[k]) for f in features if f.raw.get(k) is not None]
        fill[k] = statistics.median(ns) if ns else 0.5

    ranked, excluded = [], []
    for f in features:
        violations, flags, cost, detail = _check(f, c, min_samples)
        values = {**f.raw, "monthly_cost": cost}
        norm, estimated = {}, []
        for k in FACTOR_KEYS:
            if values.get(k) is None:
                norm[k] = fill[k]
                estimated.append(k)
            else:
                norm[k] = normalize(k, values[k], bounds[k])
        contrib = {k: round(100 * weights[k] * norm[k], 2) for k in FACTOR_KEYS}
        entry = {
            **f.dong,
            "score": round(sum(contrib.values()), 2),
            "raw": {k: (round(v, 1) if isinstance(v, float) else v) for k, v in values.items()},
            "norm": {k: round(v, 4) for k, v in norm.items()},
            "contrib": contrib,
            "estimated": estimated,  # 데이터가 없어 중앙값으로 채운 요인
            "flags": flags + [f"{FACTORS[k].label} 데이터 부족" for k in estimated],
            "detail": detail,
        }
        if violations:
            entry["violations"] = violations
            entry["severity"] = max(v["severity"] for v in violations)
            excluded.append(entry)
        else:
            ranked.append(entry)

    ranked.sort(key=lambda e: (-e["score"], e["dong_code"]))
    for i, e in enumerate(ranked, 1):
        e["rank"] = i
    excluded.sort(key=lambda e: (e["severity"], -e["score"], e["dong_code"]))

    notes, near = [], []
    if len(ranked) < NEAR_MISS_COUNT and excluded:
        near = excluded[:NEAR_MISS_COUNT]
        notes.append(f"조건을 모두 만족하는 동이 {len(ranked)}곳이라, 조건을 조금 풀면 들어오는 동을 함께 보여줍니다.")

    return Result(
        ranked=ranked, excluded=excluded, near_misses=near, weights=weights, levels=dict(levels),
        bounds=bounds, constraints=c.to_dict(), universe_size=len(features), notes=notes,
    )
