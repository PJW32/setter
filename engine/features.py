"""동 데이터 + 실거래 + 파라미터 → 동별 요인 원값.

필수 조건(예산 등)과 무관한 값만 만든다. 필수 조건은 score.rank 에서 적용한다.
"""

import statistics
from dataclasses import dataclass, field

from .data import Dataset, Deal

NO_STATION_WALK_MIN = 60  # 반경 안에 역이 없으면 이 값으로 둔다 (데이터 없음이 아니라 "멀다")


@dataclass
class Params:
    """비교 기준. 바꾸면 모든 동의 값이 같이 바뀐다 (필수 조건과 다름)."""

    destination: str = "판교역"
    house_types: tuple[str, ...] = ("오피스텔", "단독다가구")
    max_area_m2: float = 33.0  # 원룸 기준 (단독다가구는 계약면적, 나머지는 전용면적)
    new_contracts_only: bool = True  # 갱신 계약은 시세보다 낮게 잡혀 제외 (구분 없는 거래는 포함)
    conversion_rate: float = 0.05  # 보증금 환산이율: 법정 전월세 전환율 (기준금리 3.00% + 2%p, 2026-11-20)
    work_days: int = 22
    min_samples: int = 5  # 이보다 적으면 월 총비용 "데이터 부족"

    def to_dict(self) -> dict:
        return {**self.__dict__, "house_types": list(self.house_types)}


@dataclass
class DealCost:
    deposit: float
    monthly_rent: float
    monthly_total: float  # 만원


@dataclass
class DongFeature:
    dong: dict  # dong_code, name, sgg, sido, lon, lat
    raw: dict[str, float | None]
    detail: dict[str, dict]
    deals: list[DealCost] = field(default_factory=list)

    @property
    def code(self) -> str:
        return self.dong["dong_code"]


def eligible(deal: Deal, p: Params) -> bool:
    if deal.house_type not in p.house_types or deal.monthly_rent <= 0:
        return False
    if deal.area_m2 is None or deal.area_m2 > p.max_area_m2:
        return False
    if p.new_contracts_only and deal.contract_kind == "갱신":
        return False
    return True


def _bounds_0_100(values: list[float]) -> tuple[float, float]:
    vals = sorted(v for v in values if v is not None)
    if len(vals) < 2:
        return (0.0, max(vals[0], 1.0) if vals else 1.0)
    q = statistics.quantiles(vals, n=20, method="inclusive")
    lo, hi = q[0], q[-1]
    return (lo, hi) if hi > lo else (vals[0], vals[-1] if vals[-1] > vals[0] else vals[0] + 1)


def build_features(ds: Dataset, p: Params) -> list[DongFeature]:
    if p.destination not in ds.destinations:
        raise ValueError(f"지원하지 않는 목적지: {p.destination} (가능: {', '.join(ds.destinations)})")

    # 생활 편의: 항목별로 전체 동 기준 0~100 으로 바꾼 뒤 평균
    conv_items = sorted({k for d in ds.dongs for k in d.get("convenience", {})})
    conv_bounds = {k: _bounds_0_100([d.get("convenience", {}).get(k) for d in ds.dongs]) for k in conv_items}

    out: list[DongFeature] = []
    for d in ds.dongs:
        raw: dict[str, float | None] = {}
        detail: dict[str, dict] = {}
        dong = {k: d.get(k) for k in ("dong_code", "sido", "sgg", "name", "lon", "lat")}

        # 통근
        c = d.get("commute", {}).get(p.destination) or {}
        if "min" in c:
            raw["commute"] = float(c["min"])
            detail["commute"] = {k: c.get(k) for k in ("min", "fare", "transfers", "mode", "lines", "map_url")}
        else:
            raw["commute"] = None
            detail["commute"] = {"error": c.get("error", "데이터 없음")}
        fare = c.get("fare")
        fare_month = (fare * 2 * p.work_days / 10_000) if fare is not None else None  # 원 → 만원

        # 월 총비용
        deals = []
        for deal in ds.deals_by_dong.get(d["dong_code"], []):
            if eligible(deal, p):
                total = deal.monthly_rent + deal.deposit * p.conversion_rate / 12 + (fare_month or 0.0)
                deals.append(DealCost(deal.deposit, deal.monthly_rent, round(total, 2)))
        n = len(deals)
        if n >= p.min_samples:
            raw["monthly_cost"] = statistics.median(x.monthly_total for x in deals)
        else:
            raw["monthly_cost"] = None
        detail["monthly_cost"] = {
            "samples": n,
            "median_deposit": statistics.median(x.deposit for x in deals) if deals else None,
            "median_rent": statistics.median(x.monthly_rent for x in deals) if deals else None,
            "fare_month": round(fare_month, 1) if fare_month is not None else None,
            "fare_missing": fare_month is None,
        }

        # 역 접근성
        st = d.get("station")
        if st:
            raw["station_access"] = float(st["walk_min"])
            detail["station_access"] = {k: st.get(k) for k in ("name", "lines", "dist_m", "walk_min")}
        else:
            raw["station_access"] = float(NO_STATION_WALK_MIN)
            detail["station_access"] = {"name": None, "note": "반경 안에 역 없음"}

        # 생활 편의
        counts = d.get("convenience", {})
        parts = []
        for k in conv_items:
            if counts.get(k) is None:
                continue
            lo, hi = conv_bounds[k]
            parts.append(min(1.0, max(0.0, (counts[k] - lo) / (hi - lo))))
        raw["convenience"] = round(100 * sum(parts) / len(parts), 1) if parts else None
        detail["convenience"] = dict(counts)

        # 조용함 (주점 수)
        bars = d.get("bars") or {}
        raw["quiet"] = float(bars["count"]) if bars.get("count") is not None else None
        detail["quiet"] = {k: v for k, v in bars.items()}

        out.append(DongFeature(dong=dong, raw=raw, detail=detail, deals=deals))
    return out
