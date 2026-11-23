"""소진공 공식 CSV/ZIP → 지역별 최소 항목 SQLite. 추천 연결 전 검증용.

python scripts/build_public_places.py data/raw/stores.zip --as-of 2026-09-30
네트워크·인증키·카카오·Gemini를 사용하지 않는다.
"""
import argparse
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
from contextlib import ExitStack, closing
from datetime import date, datetime, timezone
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CODES = "11650 11680 11710 41111 41131 41133 41135 41290 41430 41461 41463 41465 41610".split()
SOURCE = "https://www.data.go.kr/data/15083033/fileData.do"
SMALL_CODES = {"G20405", "G21501"}  # 편의점, 약국
MIDDLE_CODES = {"I211"}  # 주점 전체
FIELDS = ["상가업소번호", "시군구코드", "법정동코드", "상권업종중분류코드", "상권업종소분류코드", "상권업종소분류명", "경도", "위도"]


def build(inputs, output, as_of, codes=CODES):
    date.fromisoformat(as_of)
    codes = None if codes is None else set(codes)
    if codes is not None and (not codes or any(len(c) != 5 or not c.isascii() or not c.isdigit() for c in codes)):
        raise ValueError("시군구 코드는 5자리 숫자여야 합니다")
    output = Path(output)
    if output.exists():
        raise FileExistsError("기존 DB는 덮어쓰지 않습니다")
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=output.parent, prefix="public_places-", suffix=".sqlite.tmp")
    os.close(fd)
    report = {"schema_version": 2, "source": SOURCE, "license": "이용허락범위 제한 없음", "as_of": as_of,
              "built_at_utc": datetime.now(timezone.utc).isoformat(),
              "inputs": [], "invalid_coordinates": 0, "missing_dong_code": 0,
              "category_filter": {"small_codes": sorted(SMALL_CODES), "middle_codes": sorted(MIDDLE_CODES)},
              "excluded_other_categories": 0,
              "all_regions": codes is None,
              "runtime_enabled": False, "geometry_included": False, "stations_included": False}
    try:
        with closing(sqlite3.connect(temporary)) as db, ExitStack() as stack:
            db.execute("CREATE TABLE place (id TEXT PRIMARY KEY, sgg TEXT NOT NULL, dong TEXT, middle_code TEXT, small_code TEXT, category TEXT, lon REAL NOT NULL, lat REAL NOT NULL)")
            db.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            for source in map(Path, inputs):
                with source.open("rb") as f:
                    digest = hashlib.file_digest(f, "sha256").hexdigest()
                report["inputs"].append({"name": source.name, "sha256": digest})
                if zipfile.is_zipfile(source):
                    archive = stack.enter_context(zipfile.ZipFile(source))
                    streams = ((n, archive.open(n)) for n in archive.namelist() if n.lower().endswith(".csv"))
                else:
                    streams = [(source.name, source.open("rb"))]
                for name, raw in streams:
                    with raw, io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text:
                        reader = csv.DictReader(text)
                        if not set(FIELDS).issubset(reader.fieldnames or []):
                            raise ValueError(f"CSV 필수 열 누락: {name}")
                        for row in reader:
                            sgg = row["시군구코드"].strip()
                            if codes is not None and sgg not in codes:
                                continue
                            middle, small = row[FIELDS[3]].strip(), row[FIELDS[4]].strip()
                            if small not in SMALL_CODES and middle not in MIDDLE_CODES:
                                report["excluded_other_categories"] += 1
                                continue
                            try:
                                lon, lat = float(row["경도"]), float(row["위도"])
                                if not (math.isfinite(lon) and math.isfinite(lat) and 124 <= lon <= 132 and 33 <= lat <= 39):
                                    raise ValueError()
                            except ValueError:
                                report["invalid_coordinates"] += 1
                                continue
                            identity = row["상가업소번호"].strip()
                            if not identity:
                                raise ValueError("업소 식별자 누락")
                            dong = row["법정동코드"].strip()
                            if len(dong) != 10 or not dong.isdigit() or not dong.startswith(sgg):
                                dong = None
                                report["missing_dong_code"] += 1
                            values = (identity, sgg, dong, middle, small, row[FIELDS[5]], lon, lat)
                            existing = db.execute("SELECT * FROM place WHERE id=?", (identity,)).fetchone()
                            if existing and existing != values:
                                raise ValueError("같은 업소 식별자에 서로 다른 값이 있습니다")
                            db.execute("INSERT OR IGNORE INTO place VALUES (?,?,?,?,?,?,?,?)", values)
            report["regions"] = dict(db.execute("SELECT sgg, COUNT(*) FROM place GROUP BY sgg ORDER BY sgg"))
            missing = sorted(codes - report["regions"].keys()) if codes is not None else []
            if missing or not report["regions"]:
                raise ValueError("자료가 없는 요청 지역: " + ", ".join(missing))
            report["rows"] = sum(report["regions"].values())
            report["categories"] = [list(r) for r in db.execute("SELECT small_code, category, COUNT(*) FROM place GROUP BY small_code, category ORDER BY small_code")]
            db.execute("CREATE INDEX place_location ON place(lon, lat)")
            db.execute("CREATE INDEX place_region ON place(sgg, small_code)")
            db.execute("INSERT INTO metadata VALUES ('manifest', ?)", (json.dumps(report, ensure_ascii=False),))
            db.commit()
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("DB 무결성 검사 실패")
        # Hard link publishes atomically and refuses an output created by another process.
        os.link(temporary, output)
        return report
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--as-of", required=True, help="공식 원본의 기준일 YYYY-MM-DD")
    parser.add_argument("--output", type=Path, default=ROOT / "data/public_places-essential.sqlite")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--codes", nargs="+", default=CODES)
    scope.add_argument("--all-regions", action="store_true", help="지역 경계 누락 검증용 전국 필요 업종")
    args = parser.parse_args()
    report = build(args.inputs, args.output, args.as_of, None if args.all_regions else args.codes)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
