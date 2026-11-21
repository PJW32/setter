"""대화 상태: 요인별 단계, 필수 조건, 비교 기준 + 변경 이력.

LLM 은 '변경분'만 낸다. 여기서 검증하고, 알 수 없는 값은 버리고 그 이유를 남긴다.

변경분 형식 (LLM 출력과 같음):
{
  "set_constraints":   {"max_monthly_rent": 60, "max_deposit": 1000, "max_commute_min": 50, "max_monthly_cost": 80},
  "clear_constraints": ["max_commute_min"],
  "params":            {"destination": "판교역", "house_types": ["오피스텔"], "max_area_m2": 33, "new_contracts_only": true},
  "preference_changes": [{"factor": "monthly_cost", "level": "매우 중요", "evidence": "월세가 제일 중요해"}]
}
금액은 만원, 시간은 분.
"""

import copy
from dataclasses import dataclass, field, fields

from .data import Dataset
from .factors import FACTORS, LEVELS, default_levels
from .features import Params, build_features
from .score import Constraints, Result, rank

HOUSE_TYPES = ("오피스텔", "단독다가구", "연립다세대")
CONSTRAINT_KEYS = tuple(f.name for f in fields(Constraints))
CONSTRAINT_RANGE = {  # 말이 안 되는 값은 버린다
    "max_deposit": (0, 100_000),
    "max_monthly_rent": (1, 1_000),
    "max_commute_min": (5, 240),
    "max_monthly_cost": (1, 1_000),
}


@dataclass
class State:
    levels: dict[str, str] = field(default_factory=default_levels)
    constraints: Constraints = field(default_factory=Constraints)
    params: Params = field(default_factory=Params)
    history: list[dict] = field(default_factory=list)

    def snapshot(self) -> dict:
        return {"levels": dict(self.levels), "constraints": self.constraints.to_dict(), "params": self.params.to_dict()}


def apply_changes(state: State, changes: dict, *, destinations: list[str] | None = None,
                  utterance: str | None = None) -> tuple[State, dict]:
    """새 State 와 보고서 {"applied": [...], "rejected": [...]} 를 돌려준다. 원래 state 는 바꾸지 않는다."""
    new = copy.deepcopy(state)
    applied, rejected = [], []

    for key, value in (changes.get("set_constraints") or {}).items():
        if key not in CONSTRAINT_KEYS:
            rejected.append({"item": key, "reason": "알 수 없는 필수 조건"})
            continue
        try:
            v = float(value)
        except (TypeError, ValueError):
            rejected.append({"item": key, "reason": f"숫자가 아님: {value!r}"})
            continue
        lo, hi = CONSTRAINT_RANGE[key]
        if not lo <= v <= hi:
            rejected.append({"item": key, "reason": f"범위 밖 값 {v} (허용 {lo}~{hi})"})
            continue
        before = getattr(new.constraints, key)
        setattr(new.constraints, key, v)
        applied.append({"type": "constraint", "key": key, "before": before, "after": v})

    for key in changes.get("clear_constraints") or []:
        if key in CONSTRAINT_KEYS and getattr(new.constraints, key) is not None:
            applied.append({"type": "constraint", "key": key, "before": getattr(new.constraints, key), "after": None})
            setattr(new.constraints, key, None)

    for key, value in (changes.get("params") or {}).items():
        before = getattr(new.params, key, None)
        if key == "destination":
            if destinations is not None and value not in destinations:
                rejected.append({"item": "destination", "reason": f"지원하지 않는 목적지 {value!r}",
                                 "supported": destinations})
                continue
        elif key == "house_types":
            types = tuple(t for t in (value or []) if t in HOUSE_TYPES)
            if not types:
                rejected.append({"item": "house_types", "reason": f"알 수 없는 주택 유형 {value!r}"})
                continue
            value = types
        elif key == "max_area_m2":
            if not isinstance(value, (int, float)) or not 10 <= value <= 85:
                rejected.append({"item": key, "reason": f"범위 밖 면적 {value!r} (10~85㎡)"})
                continue
            value = float(value)
        elif key == "new_contracts_only":
            value = bool(value)
        else:
            rejected.append({"item": key, "reason": "바꿀 수 없는 파라미터"})
            continue
        if value != before:
            setattr(new.params, key, value)
            applied.append({"type": "param", "key": key, "before": before, "after": value})

    for ch in changes.get("preference_changes") or []:
        factor, level = ch.get("factor"), ch.get("level")
        if factor not in FACTORS:
            rejected.append({"item": factor, "reason": "알 수 없는 요인"})
            continue
        if level not in LEVELS:
            rejected.append({"item": f"{factor}:{level}", "reason": "알 수 없는 단계"})
            continue
        before = new.levels.get(factor)
        if before != level:
            new.levels[factor] = level
            applied.append({"type": "preference", "key": factor, "label": FACTORS[factor].label,
                            "before": before, "after": level, "evidence": ch.get("evidence")})

    report = {"applied": applied, "rejected": rejected}
    new.history.append({"utterance": utterance, **report, "state": new.snapshot()})
    return new, report


def evaluate(ds: Dataset, state: State) -> Result:
    features = build_features(ds, state.params)
    return rank(features, state.levels, state.constraints, min_samples=state.params.min_samples)
