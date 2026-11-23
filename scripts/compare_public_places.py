"""저장된 기존 대표 지점에서 공공 시설 수를 비교한다. 외부 API·AI 호출 없음."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collectors.public_places import PublicPlaces, DEFAULT_PATH
from config import ROOT


def compare(snapshot, store):
    places = PublicPlaces(snapshot)
    with closing(sqlite3.connect(Path(store).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        dongs = [json.loads(row[0]) for row in db.execute("SELECT data FROM dong ORDER BY code")]
    deltas = {key: [] for key in ("CS2", "PM9", "bars")}
    skipped = 0
    started = time.perf_counter()
    for d in dongs:
        if d["dong_code"][:5] not in places.manifest["regions"]:
            skipped += 1
            continue
        for key, old, radius in [("CS2", d.get("convenience", {}).get("편의점"), 500),
                                 ("PM9", d.get("convenience", {}).get("약국"), 500),
                                 ("bars", d.get("bars", {}).get("count"), 500)]:
            if not isinstance(old, (int, float)):
                continue
            new = places.count(key, d["lon"], d["lat"], radius, sgg_code=d["dong_code"][:5])
            deltas[key].append(new - old)
    return {"as_of": places.manifest["as_of"], "stored_dongs": len(dongs), "skipped_dongs": skipped,
            "lookup_seconds": round(time.perf_counter() - started, 4),
            "comparison": {key: {"compared": len(ds), "equal": sum(v == 0 for v in ds),
                                  "mean_delta": statistics.mean(ds) if ds else None,
                                  "median_absolute_delta": statistics.median(abs(v) for v in ds) if ds else None,
                                  "max_absolute_delta": max(map(abs, ds), default=None)} for key, ds in deltas.items()},
            "runtime_enabled": False,
            "limitations": ["저장된 기존 값과 비교하며 최신 API 동시 비교가 아님",
                            "13개 시군구 외부 업소가 없어 경계 부근 반경 집계가 누락될 수 있음",
                            "대표 지점 변경 및 추천 순위 동등성은 검증하지 않음"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--store", type=Path, default=ROOT / "data/store.sqlite")
    args = parser.parse_args()
    print(json.dumps(compare(args.snapshot, args.store), ensure_ascii=False, indent=2, allow_nan=False))
