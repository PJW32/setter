"""공공 상가 스냅샷의 읽기 전용 반경 조회. 미확인 지역을 0건으로 반환하지 않는다."""
import json
import math
from contextlib import closing
from pathlib import Path
import sqlite3

from config import ROOT

DEFAULT_PATH = ROOT / "data/public_places-essential.sqlite"
CATEGORIES = {"CS2": ("small_code", "G20405"), "PM9": ("small_code", "G21501"),
              "bars": ("middle_code", "I211")}


class PublicPlaces:
    def __init__(self, path=DEFAULT_PATH):
        self.path = Path(path).resolve()
        with self.connect() as db:
            self.manifest = json.loads(db.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0])
        if self.manifest.get("schema_version") != 2:
            raise ValueError("지원하지 않는 공공 시설 DB 버전")

    def connect(self):
        return closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True))

    def count(self, category, lon, lat, radius, *, sgg_code):
        if sgg_code not in self.manifest["regions"]:
            raise ValueError("스냅샷에 없는 지역")
        if not all(math.isfinite(v) for v in (lon, lat, radius)) or not (124 <= lon <= 132 and 33 <= lat <= 39 and 0 < radius <= 3000):
            raise ValueError("잘못된 좌표 또는 반경")
        column, code = CATEGORIES[category]
        dy = radius / 111_320
        # Conservative bounding box; exact approximate metric matches collectors.region.meters.
        dx = radius / (111_320 * math.cos(math.radians(lat + dy)))
        with self.connect() as db:
            candidates = db.execute(
                f"SELECT lon, lat FROM place WHERE {column}=? AND lon BETWEEN ? AND ? AND lat BETWEEN ? AND ?",
                (code, lon - dx, lon + dx, lat - dy, lat + dy)).fetchall()
        return sum(math.hypot((x - lon) * 111_320 * math.cos(math.radians((y + lat) / 2)),
                              (y - lat) * 111_320) <= radius for x, y in candidates)

