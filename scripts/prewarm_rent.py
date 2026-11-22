"""저장 가능한 국토부 실거래만 별도 SQLite로 구축한다. 카카오・Gemini 호출 없음.

python scripts/prewarm_rent.py --saved-regions --offline
python scripts/prewarm_rent.py 41135 --offline
"""

import argparse
import json
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import store  # noqa: E402
from backend.regions import _months  # noqa: E402
from collectors import molit  # noqa: E402
from collectors.http import metrics_snapshot  # noqa: E402
from config import ROOT, get_data_go_kr_key  # noqa: E402
import settings as S  # noqa: E402

OUTPUT = ROOT / "data" / "rent_snapshot.sqlite"
VERSION = molit.NORMALIZATION_VERSION


def saved_codes():
    if not store.DB_PATH.exists():
        return []
    with closing(sqlite3.connect(store.DB_PATH.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        return [r[0] for r in conn.execute("SELECT code FROM sgg WHERE status='done' ORDER BY code")]


def build_snapshot(codes, path=OUTPUT, offline=False, fetch=molit.fetch_raw, emit=print):
    """같은 코드・유형・월의 완료 건은 재사용한다. 한 묶음을 한 트랜잭션으로 기록한다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    failed = 0
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS collection (
                code TEXT, house_type TEXT, ym TEXT, version TEXT, count INTEGER,
                collected_at TEXT, source TEXT,
                PRIMARY KEY(code, house_type, ym, version)
            );
            CREATE TABLE IF NOT EXISTS rental (
                code TEXT, house_type TEXT, ym TEXT, version TEXT, data TEXT
            );
            CREATE INDEX IF NOT EXISTS rental_batch ON rental(code, house_type, ym, version);
        """)
        for code in dict.fromkeys(codes):
            started = time.monotonic()
            reused, added, records = 0, 0, 0
            for house_type in molit.SERVICES:
                for ym in _months(S.RENT_END_YM, S.RENT_MONTHS):
                    batch = (code, house_type, ym, VERSION)
                    row = conn.execute("SELECT count FROM collection WHERE code=? AND house_type=? AND ym=? AND version=?", batch).fetchone()
                    if row:
                        reused += 1
                        records += row[0]
                        continue
                    try:
                        raw = fetch(house_type, code, ym, offline=offline)
                        normalized = [molit.normalize(house_type, r) for r in raw]
                        if any(r["sgg_code"] != code or r["deal_ym"] != ym for r in normalized):
                            raise ValueError("응답의 지역・월이 요청과 다릅니다")
                        with conn:
                            conn.execute("DELETE FROM rental WHERE code=? AND house_type=? AND ym=? AND version=?", batch)
                            conn.executemany("INSERT INTO rental VALUES (?,?,?,?,?)", [
                                (*batch, json.dumps(r, ensure_ascii=False, allow_nan=False)) for r in normalized
                            ])
                            conn.execute("INSERT INTO collection VALUES (?,?,?,?,?,datetime('now'),'국토교통부 전월세 실거래가 API')",
                                         (*batch, len(normalized)))
                        added += 1
                        records += len(normalized)
                    except Exception as exc:
                        failed += 1
                        emit(f"[실패] {code}/{house_type}/{ym}: {type(exc).__name__}")
            emit(f"[{code}] 재사용 {reused}묶음, 구축 {added}묶음, 거래 {records:,}건, {time.monotonic()-started:.1f}초")
        emit(f"완료 묶음 {conn.execute('SELECT COUNT(*) FROM collection').fetchone()[0]}, "
             f"저장 거래 {conn.execute('SELECT COUNT(*) FROM rental').fetchone()[0]:,}건")
    emit(f"스냅샷: {path}")
    return 1 if failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("codes", nargs="*", help="시군구 코드 5자리")
    parser.add_argument("--saved-regions", action="store_true", help="기존 DB에서 준비된 시군구 코드만 읽기")
    parser.add_argument("--offline", action="store_true", help="국토부 파일 캐시만 사용하며 네트워크 호출 금지")
    args = parser.parse_args(argv)
    if args.codes and args.saved_regions:
        parser.error("코드 직접 지정과 --saved-regions는 함께 사용할 수 없습니다")
    codes = saved_codes() if args.saved_regions else args.codes
    if not codes:
        parser.print_help()
        return 0
    if any(len(c) != 5 or not c.isascii() or not c.isdigit() for c in codes):
        parser.error("시군구 코드는 숫자 5자리여야 합니다")
    if not args.offline and not get_data_go_kr_key(required=False):
        print("공공데이터 키가 필요합니다. 캐시만 사용하려면 --offline을 지정하세요.", file=sys.stderr)
        return 2
    result = build_snapshot(codes, offline=args.offline, emit=lambda line: print(line, flush=True))
    print(json.dumps(metrics_snapshot(), ensure_ascii=False))
    return result


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
