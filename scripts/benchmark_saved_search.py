"""저장된 통근 후보의 DB 읽기·점수 계산 및 빈 DB 복원 검증. 외부 호출 없음.

첫 검색 전체가 아니라 저장 데이터 경로만 측정한다. OS 캐시는 비우지 않는다.
"""
import argparse
from contextlib import closing
from dataclasses import fields
import hashlib
import json
from pathlib import Path
import sqlite3
import statistics
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import ROOT
from engine.data import Dataset, Deal
from engine.features import Params
from engine.score import Constraints
from engine.state import State, evaluate


def readonly(path):
    return closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True))


def measure(path, destination):
    started = time.perf_counter()
    with readonly(path) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")  # Three reads use the same snapshot if the service writes concurrently.
        routes = {r["dong_code"]: json.loads(r["data"]) for r in db.execute(
            "SELECT * FROM commute WHERE dest_key=?", (destination,))}
        dongs = []
        for row in db.execute("SELECT code,data FROM dong ORDER BY code"):
            if row["code"] in routes:
                d = json.loads(row["data"])
                d["commute"] = {destination: routes[row["code"]]}
                dongs.append(d)
        if not dongs:
            raise ValueError("저장된 통근 후보가 없어 오프라인 검색을 측정할 수 없습니다")
        codes = {d["dong_code"] for d in dongs}
        deals = {}
        deal_fields = [f.name for f in fields(Deal)]
        for r in db.execute("SELECT * FROM deal WHERE dong_code IN (SELECT dong_code FROM commute WHERE dest_key=?)", (destination,)):
            if r["dong_code"] in codes and r["deposit"] is not None and r["monthly_rent"] is not None:
                deals.setdefault(r["dong_code"], []).append(Deal(**{key: r[key] for key in deal_fields}))
    read_seconds = time.perf_counter() - started
    ds = Dataset(dongs, deals)
    state = State(params=Params(destination=destination),
                  constraints=Constraints(max_deposit=1000, max_monthly_rent=60, max_commute_min=50))
    scoring_started = time.perf_counter()
    result = evaluate(ds, state)
    scoring_seconds = time.perf_counter() - scoring_started
    canonical = json.dumps(result.to_dict(), sort_keys=True, ensure_ascii=False, allow_nan=False)
    return {"db_read_seconds": round(read_seconds, 6), "score_seconds": round(scoring_seconds, 6),
            "total_seconds": round(scoring_started + scoring_seconds - started, 6),
            "candidate_count": len(dongs), "deal_count": sum(map(len, deals.values())),
            "ranked_count": len(result.ranked), "result_sha256": hashlib.sha256(canonical.encode()).hexdigest()}


def benchmark(path, destination="판교역", repeats=3):
    if not 1 <= repeats <= 10:
        raise ValueError("반복 횟수는 1~10회입니다")
    # SQLite backup includes WAL changes; copying only the main file would not.
    with tempfile.TemporaryDirectory() as directory:
        restored = Path(directory) / "restored.sqlite"
        with readonly(path) as source, closing(sqlite3.connect(restored)) as target:
            source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("복원 DB 무결성 오류")
        runs = [measure(restored, destination) for _ in range(repeats)]
    fingerprints = {r["result_sha256"] for r in runs}
    if len(fingerprints) != 1:
        raise ValueError("동일 복원본에서 추천 결과가 달라졌습니다")
    return {"scope": "저장된 통근 후보의 DB 읽기·엔진 계산", "network_calls": 0,
            "isolated_sqlite_restore": "passed", "result_repeatability": "passed", "runs": runs,
            "median_seconds": statistics.median(r["total_seconds"] for r in runs),
            "limitations": ["API 요청·Gemini·지역/역/시설/통근 신규 수집 제외",
                            "저장 통근 후보만 비교하며 목적지 재탐색/반경 계산 제외",
                            "임시 복원본 첫 실행도 OS 캐시를 공유하므로 무캐시 측정이 아님",
                            "Render 서버 속도·512MB 메모리 내 동작을 검증하지 않음"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=ROOT / "data/store.sqlite")
    parser.add_argument("--destination", default="판교역")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    print(json.dumps(benchmark(args.store, args.destination, args.repeats), ensure_ascii=False, indent=2))
