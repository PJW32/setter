"""동 데이터와 실거래 데이터 읽기."""

import csv
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Deal:
    dong_code: str
    house_type: str
    area_m2: float | None
    area_kind: str
    deposit: float  # 만원
    monthly_rent: float  # 만원
    deal_ym: str
    contract_kind: str


@dataclass
class Dataset:
    dongs: list[dict]
    deals_by_dong: dict[str, list[Deal]]
    meta: dict = field(default_factory=dict)

    @property
    def destinations(self) -> list[str]:
        dests: list[str] = []
        for d in self.dongs:
            for k in d.get("commute", {}):
                if k not in dests:
                    dests.append(k)
        return dests


def _f(s: str) -> float | None:
    s = (s or "").strip()
    return float(s) if s else None


def load_deals(path: Path) -> dict[str, list[Deal]]:
    by_dong: dict[str, list[Deal]] = defaultdict(list)
    with Path(path).open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if not r["dong_code"] or _f(r["deposit"]) is None or _f(r["monthly_rent"]) is None:
                continue
            by_dong[r["dong_code"]].append(Deal(
                dong_code=r["dong_code"], house_type=r["house_type"], area_m2=_f(r["area_m2"]),
                area_kind=r["area_kind"], deposit=_f(r["deposit"]), monthly_rent=_f(r["monthly_rent"]),
                deal_ym=r["deal_ym"], contract_kind=r["contract_kind"],
            ))
    return dict(by_dong)


def load_dataset(dongs_path: Path, deals_path: Path | None) -> Dataset:
    doc = json.loads(Path(dongs_path).read_text(encoding="utf-8"))
    deals = load_deals(deals_path) if deals_path and Path(deals_path).exists() else {}
    return Dataset(dongs=doc["dongs"], deals_by_dong=deals, meta=doc.get("meta", {}))
