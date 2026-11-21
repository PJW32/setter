"""시군구 하나의 법정동 목록·대표 지점·요인 값을 모은다 (통근 제외).

격자는 전국 공통 고정 격자(위도 37.5° 기준 간격)를 쓴다. 어느 지점에서 시작해도
같은 격자점을 쓰므로 응답 캐시를 다시 쓰고, 결과가 재현된다.
"""

import math
from concurrent.futures import ThreadPoolExecutor

import settings as S
from config import get_key

from . import kakao, sbiz

DLAT = S.GRID_STEP_M / 111_320
DLON = S.GRID_STEP_M / (111_320 * math.cos(math.radians(37.5)))

POOL = ThreadPoolExecutor(max_workers=8)


def lattice(i: int, j: int) -> tuple[float, float]:
    return (round(i * DLON, 6), round(j * DLAT, 6))


def snap(x: float, y: float) -> tuple[int, int]:
    return (round(x / DLON), round(y / DLAT))


def meters(a: tuple[float, float], b: tuple[float, float]) -> float:
    """두 (경도, 위도) 사이 대략 거리(m)."""
    kx = 111_320 * math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot((a[0] - b[0]) * kx, (a[1] - b[1]) * 111_320)


# ------------------------------------------------------------------ 동 목록
def discover(sgg_code: str, seed: tuple[float, float]) -> dict[str, dict]:
    """seed 에서 격자를 넓혀 가며, 법정동 코드 앞 5자리가 sgg_code 인 점만 따라간다."""
    def at(ij):
        return kakao.legal_dong_at(*lattice(*ij))

    visited: set = set()
    frontier = {snap(*seed)}
    dongs: dict[str, dict] = {}
    while frontier:
        pts = [p for p in frontier if p not in visited]
        visited.update(pts)
        nxt = set()
        for ij, r in zip(pts, POOL.map(at, pts)):
            if not r or r["code"][:5] != sgg_code:
                continue
            dongs.setdefault(r["code"], {**r, "grid": []})["grid"].append(lattice(*ij))
            i, j = ij
            nxt.update(n for n in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)) if n not in visited)
        frontier = nxt
    return dongs


# ------------------------------------------------------------------ 대표 지점
def representative_point(d: dict) -> tuple[float, float, str]:
    """동 안에서 생활이 몰린 곳: 격자점별 편의점 수로 가중한 무게중심에 가장 가까운 격자점."""
    grid = d["grid"]
    weights = list(POOL.map(lambda p: kakao.category_count("CS2", p[0], p[1], S.ACTIVITY_RADIUS_M), grid))
    total = sum(weights)

    def nearest(cx, cy):
        return min(grid, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)

    if total > 0:
        cx = sum(p[0] * w for p, w in zip(grid, weights)) / total
        cy = sum(p[1] * w for p, w in zip(grid, weights)) / total
        x, y = nearest(cx, cy)
        return x, y, f"생활 중심 (격자점별 편의점 {S.ACTIVITY_RADIUS_M}m 개수 가중)"
    pt = kakao.legal_dong_point(f"{d['sido']} {d['sgg']} {d['name']}", d["code"])
    if pt:
        hit = kakao.legal_dong_at(*pt)
        if hit and hit["code"] == d["code"]:
            return pt[0], pt[1], "카카오 법정동 대표 좌표"
    cx = sum(p[0] for p in grid) / len(grid)
    cy = sum(p[1] for p in grid) / len(grid)
    x, y = nearest(cx, cy)
    return x, y, "격자 중심에 가장 가까운 점"


# ------------------------------------------------------------------ 요인
def station_base(place_name: str) -> str:
    return place_name.split(" ")[0]


def nearest_station(x: float, y: float) -> dict | None:
    docs = kakao.category_nearby("SW8", x, y, S.STATION_SEARCH_RADIUS_M)
    if not docs:
        return None
    name = station_base(docs[0]["place_name"])
    same = [d for d in docs if station_base(d["place_name"]) == name]
    dist = min(int(d["distance"]) for d in same)
    return {
        "name": name,
        "lines": sorted({d["category_name"].split(" > ")[-1] for d in same}),
        "dist_m": dist,
        "walk_min": round(dist * S.WALK_DETOUR / S.WALK_SPEED_M_PER_MIN),
        "lon": float(same[0]["x"]),
        "lat": float(same[0]["y"]),
    }


def bars(x: float, y: float) -> dict:
    """주점 수: 상가정보(I211)가 기본, 키가 없거나 실패하면 카카오 추정."""
    if get_key("DATA_GO_KR_SERVICE_KEY", required=False):
        try:
            return {"count": sbiz.bar_count(x, y, S.BAR_RADIUS_M), "source": "상가정보 주점(I211)"}
        except Exception:  # noqa: BLE001 - 카카오로 대체
            pass
    k = kakao.bar_count(x, y, S.BAR_RADIUS_M)
    return {**k, "source": "카카오 '술집' 분류 추정"}


def dong_record(d: dict) -> dict:
    """discover 결과 하나 → 저장용 동 레코드 (통근 제외)."""
    x, y, how = representative_point(d)
    return {
        "dong_code": d["code"], "sido": d["sido"], "sgg": d["sgg"], "name": d["name"],
        "lon": round(x, 6), "lat": round(y, 6), "point_source": how,
        "area_km2_est": round(len(d["grid"]) * S.GRID_STEP_M ** 2 / 1e6, 2),
        "station": nearest_station(x, y),
        "convenience": {k: kakao.category_count(code, x, y, r) for k, (code, r) in S.CONVENIENCE.items()},
        "bars": bars(x, y),
    }
