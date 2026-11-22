"""추천 전 지역·실거래·통근을 사전 수집한다. Gemini는 호출하지 않는다.

python scripts/prewarm_data.py --status      # 로컬 DB 조회만 (외부 호출 없음)
python scripts/prewarm_data.py 판교역 --include-kakao  # 사용 범위 별도 확인 필요
python scripts/prewarm_rent.py --saved-regions --offline  # 국토부만 준비
"""

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import settings as S  # noqa: E402
from backend import store  # noqa: E402
from backend.regions import DataService  # noqa: E402
from collectors.http import metrics_snapshot  # noqa: E402
from config import ROOT, get_key  # noqa: E402

REPORT = ROOT / "data" / "raw" / "prewarm_report.json"


def saved_status(path=None):
    """수집기·DB 초기화 없이 기존 SQLite만 읽는다."""
    path = Path(path or store.DB_PATH)
    if not path.exists():
        return {"database_exists": False, "regions": [], "commutes_by_destination": []}
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        regions = [dict(r) for r in conn.execute(
            "SELECT code, name, status, dong_count, deal_count, collected_at FROM sgg ORDER BY code")]
        commutes = [dict(r) for r in conn.execute(
            "SELECT dest_key, COUNT(*) AS stored_rows FROM commute GROUP BY dest_key ORDER BY dest_key")]
    return {"database_exists": True, "regions": regions, "commutes_by_destination": commutes}


def write_report(report, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    pending.replace(path)


def prewarm(destinations, service, report_path=REPORT, emit=print):
    report = {"started_at_utc": datetime.now(timezone.utc).isoformat(),
              "radius_km": service.radius_km, "rent_end_ym": S.RENT_END_YM,
              "rent_months": S.RENT_MONTHS, "results": []}
    write_report(report, report_path)
    interrupted = False
    for query in dict.fromkeys(destinations):
        started = time.monotonic()
        entry = {"query": query, "status": "running"}
        report["results"].append(entry)
        write_report(report, report_path)
        emit(f"\n[시작] {query}")
        errors = 0
        stages = []

        def log(step, status, detail, **_kw):
            nonlocal errors
            if status == "error":
                errors += 1
            if "ms" in _kw:
                stages.append({"step": step, "detail": detail, "ms": _kw["ms"]})
            emit(f"[{time.monotonic() - started:.1f}초] {step}/{status}: {detail}"
                 + (f" ({_kw['ms']}ms)" if "ms" in _kw else ""))

        try:
            destination = service.resolve_destination(query)
            if destination is None:
                entry.update(status="failed", reason="목적지 검색 결과 없음")
            else:
                ds = service.dataset_for(destination, log)
                routes = [d.get("commute", {}).get(destination.key) or {} for d in ds.dongs]
                missing = sum(r.get("min") is None for r in routes)
                missing_fares = sum(r.get("fare") is None for r in routes)
                deals = sum(len(rows) for rows in ds.deals_by_dong.values())
                state = "failed" if not ds.dongs else (
                    "partial" if errors or missing or missing_fares or not deals else "done")
                entry.update(status=state, destination_key=destination.key, dongs=len(ds.dongs),
                             deals=deals, missing_commutes=missing, missing_fares=missing_fares,
                             collection_errors=errors)
        except KeyboardInterrupt:
            entry.update(status="interrupted", reason="사용자 중단")
            interrupted = True
        except Exception as exc:
            # 공급자 예외 본문에는 인증 URL이 포함될 수 있으므로 기록하지 않는다.
            entry.update(status="failed", error_type=type(exc).__name__)
        entry["elapsed_seconds"] = round(time.monotonic() - started, 2)
        entry["stages"] = stages
        report["http_metrics"] = metrics_snapshot()
        write_report(report, report_path)
        emit(json.dumps(entry, ensure_ascii=False))
        if interrupted:
            break
    emit(f"\n수집 결과: {report_path}")
    return 130 if interrupted else (0 if all(r["status"] == "done" for r in report["results"]) else 1)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("destinations", nargs="*", help="공개 목적지 이름 (예: 판교역 강남역)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--all", action="store_true", help="설정된 전체 목적지를 순서대로 수집")
    mode.add_argument("--status", action="store_true", help="외부 호출 없이 기존 DB 상태만 조회")
    parser.add_argument("--include-kakao", action="store_true", help="카카오 저장·재사용 권한을 별도로 확인한 전체 수집")
    args = parser.parse_args(argv)
    if args.destinations and (args.all or args.status):
        parser.error("목적지 직접 지정과 --all/--status는 함께 사용할 수 없습니다")
    if args.status:
        print(json.dumps(saved_status(), ensure_ascii=False, indent=2))
        return 0
    targets = list(dict.fromkeys(S.PREWARM_DESTINATIONS if args.all else args.destinations))
    if not targets:
        parser.print_help()
        print("\n설정된 목적지:", ", ".join(S.PREWARM_DESTINATIONS))
        return 0
    if not args.include_kakao:
        print("전체 수집은 카카오 결과를 저장합니다. 사용 범위 확인 전에는 실행하지 않습니다.\n"
              "국토부 실거래만 준비: python scripts/prewarm_rent.py --saved-regions --offline", file=sys.stderr)
        return 2
    missing = [name for name in ("KAKAO_REST_API_KEY", "DATA_GO_KR_SERVICE_KEY")
               if not get_key(name, required=False)]
    if missing:
        print("설정되지 않은 필수 키: " + ", ".join(missing), file=sys.stderr)
        return 2
    print("수집 대상:", ", ".join(targets), flush=True)
    print("기존 SQLite·응답 캐시를 재사용합니다. 외부 API 사용량이 발생할 수 있습니다. Gemini·ODsay는 호출하지 않습니다.", flush=True)
    return prewarm(targets, DataService(), emit=lambda line: print(line, flush=True))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
