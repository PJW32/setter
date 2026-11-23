"""로컬 저장값·13개 지역·전국 공공 DB 비교. 외부 호출/운영 DB 변경 없음."""
import argparse
import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collectors.public_places import PublicPlaces, DEFAULT_PATH
from config import ROOT
from engine.data import Dataset, Deal
from engine.score import Constraints
from engine.state import State, evaluate


def audit(local_path, national_path, store_path):
    local, national = PublicPlaces(local_path), PublicPlaces(national_path)
    if not national.manifest.get("all_regions") or local.manifest["as_of"] != national.manifest["as_of"]:
        raise ValueError("같은 기준일의 전국 검증 DB가 필요합니다")
    if local.manifest["inputs"] != national.manifest["inputs"]:
        raise ValueError("같은 공공 원본으로 만든 DB가 필요합니다")
    with closing(sqlite3.connect(Path(store_path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        dongs = [json.loads(r[0]) for r in db.execute("SELECT data FROM dong ORDER BY code")]
        commutes = {r["dong_code"]: json.loads(r["data"]) for r in db.execute("SELECT * FROM commute WHERE dest_key='판교역'")}
        deals = {}
        for row in db.execute("SELECT * FROM deal"):
            r = dict(row)
            if r["deposit"] is not None and r["monthly_rent"] is not None:
                deals.setdefault(r["dong_code"], []).append(Deal(**{k: v for k, v in r.items() if k != "sgg_code"}))
    boundaries, differences = [], []
    replacements = {"local": [], "national": []}
    for d in dongs:
        if d["dong_code"][:5] not in local.manifest["regions"]:
            continue
        updated = {key: copy.deepcopy(d) for key in replacements}
        for category, label in [("CS2", "편의점"), ("PM9", "약국"), ("bars", "주점")]:
            counts = {key: snapshot.count(category, d["lon"], d["lat"], 500, sgg_code=d["dong_code"][:5])
                      for key, snapshot in [("local", local), ("national", national)]}
            old = d.get("bars", {}).get("count") if category == "bars" else d.get("convenience", {}).get(label)
            detail = {"dong": f"{d['sgg']} {d['name']}", "category": label, "stored": old, **counts}
            if counts["local"] != counts["national"]:
                boundaries.append(detail)
            if old is not None and old != counts["national"]:
                differences.append(detail)
            for key in updated:
                if category == "bars":
                    updated[key]["bars"] = {"count": counts[key], "source": "공공 상가 스냅샷 검증"}
                else:
                    updated[key]["convenience"][label] = counts[key]
        for key in replacements:
            replacements[key].append(updated[key])
    def dataset(rows):
        selected = []
        for d in rows:
            if d["dong_code"] in commutes:
                d = copy.deepcopy(d)
                d["commute"] = {"판교역": commutes[d["dong_code"]]}
                selected.append(d)
        return Dataset(selected, deals)
    datasets = {"stored": dataset(dongs), **{k: dataset(v) for k, v in replacements.items()}}
    scenarios = []
    for rent, priority in [(60, None), (50, None), (60, "station_access"), (60, "quiet"), (60, "convenience")]:
        state = State(constraints=Constraints(max_deposit=1000, max_monthly_rent=rent, max_commute_min=50))
        if priority:
            state.levels[priority] = "매우 중요"
        ranked = {k: evaluate(ds, state).ranked for k, ds in datasets.items()}
        original = [r["dong_code"] for r in ranked["stored"]]
        scenarios.append({"rent": rent, "priority": priority,
                          "top3": {k: [r["dong_code"] for r in rows[:3]] for k, rows in ranked.items()},
                          "changed_positions": {k: sum(a != b for a, b in zip(original, [r['dong_code'] for r in rows]))
                                                for k, rows in ranked.items() if k != "stored"},
                          "ranked_counts": {k: len(rows) for k, rows in ranked.items()}})
    differences.sort(key=lambda r: abs(r["national"] - r["stored"]), reverse=True)
    return {"as_of": local.manifest["as_of"], "compared_dongs": len(replacements["local"]),
            "boundary_cases": boundaries, "nonmatching_facility_counts": len(differences),
            "largest_differences": differences[:12], "ranking_candidates": len(datasets["stored"].dongs),
            "scenarios": scenarios, "representative_points_recomputed": False,
            "limitations": ["기존 대표 지점·역·통근·대형마트 값 고정", "최신 API 동시 비교 아님",
                            "자료 기준일/업종 차이의 인과관계를 분리하지 못함", "운영 전환 및 속도 벤치마크 아님"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--national", type=Path, default=ROOT / "data/public_places-national-validation.sqlite")
    parser.add_argument("--store", type=Path, default=ROOT / "data/store.sqlite")
    parser.add_argument("--output", type=Path, default=ROOT / "data/raw/public-places-audit.json")
    args = parser.parse_args()
    result = audit(args.local, args.national, args.store)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
