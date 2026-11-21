"""대상 시군구의 법정동 목록과 동별 요인 값을 모아 data/dongs.json 을 만든다.

1. 동 목록: 시군구 대표 지점에서 격자(settings.GRID_STEP_M)를 넓혀 가며 카카오 좌표→법정동 변환
   → 같은 시군구 코드인 점만 따라 퍼진다. 점 개수로 면적도 추정한다
2. 대표 지점: 카카오 주소 검색의 법정동 대표 좌표 (동 밖이면 격자 중심에 가장 가까운 점)
3. 요인: 가장 가까운 지하철역, 반경 안 편의시설·술집 수 (카카오), 목적지별 통근 (ODsay)

모든 응답은 data/cache/ 에 저장되므로 다시 돌리면 API를 다시 부르지 않는다.
실행:  python scripts/build_dongs.py
"""

import json
import math
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import settings as S  # noqa: E402
from collectors import kakao  # noqa: E402
from config import ROOT  # noqa: E402

OUT = ROOT / "data" / "dongs.json"
POOL = ThreadPoolExecutor(max_workers=8)


def log(msg: str) -> None:
    print(msg, flush=True)


# ------------------------------------------------------------------ 1. 동 목록
def region_anchor(region: str) -> tuple[float, float, str]:
    for doc in kakao.search_address(region):
        addr = doc.get("address") or {}
        if doc.get("address_type") == "REGION" and addr.get("b_code"):
            return float(doc["x"]), float(doc["y"]), addr["b_code"][:5]
    raise RuntimeError(f"시군구를 찾지 못함: {region}")


def discover(region: str) -> dict[str, dict]:
    x0, y0, prefix = region_anchor(region)
    dlat = S.GRID_STEP_M / 111_320
    dlon = S.GRID_STEP_M / (111_320 * math.cos(math.radians(y0)))

    def at(ij):
        return kakao.legal_dong_at(x0 + ij[0] * dlon, y0 + ij[1] * dlat)

    visited: set = set()
    frontier = {(0, 0)}
    dongs: dict[str, dict] = {}
    while frontier:
        pts = [p for p in frontier if p not in visited]
        visited.update(pts)
        nxt = set()
        for ij, r in zip(pts, POOL.map(at, pts)):
            if not r or r["code"][:5] != prefix:
                continue
            d = dongs.setdefault(r["code"], {**r, "grid": []})
            d["grid"].append((x0 + ij[0] * dlon, y0 + ij[1] * dlat))
            i, j = ij
            nxt.update(n for n in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)) if n not in visited)
        frontier = nxt
    log(f"  {region}: 격자 {len(visited)}점 → 법정동 {len(dongs)}개")
    return dongs


# ------------------------------------------------------------------ 2. 대표 지점
def _nearest_grid(d: dict, cx: float, cy: float) -> tuple[float, float]:
    return min(d["grid"], key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)


def representative_point(d: dict) -> tuple[float, float, str]:
    """동 안에서 생활이 몰린 곳.

    격자점마다 반경 안 편의점 수를 가중치로 무게중심을 구하고, 가장 가까운 격자점(동 안)에 붙인다.
    넓은 동에서 산·공원·업무지구 한가운데가 대표 지점이 되는 것을 피하려는 것.
    편의점이 하나도 없으면 카카오 법정동 대표 좌표, 그것도 동 밖이면 격자 중심을 쓴다.
    """
    weights = list(POOL.map(lambda p: kakao.category_count("CS2", p[0], p[1], S.ACTIVITY_RADIUS_M), d["grid"]))
    total = sum(weights)
    if total > 0:
        cx = sum(p[0] * w for p, w in zip(d["grid"], weights)) / total
        cy = sum(p[1] * w for p, w in zip(d["grid"], weights)) / total
        x, y = _nearest_grid(d, cx, cy)
        return x, y, f"생활 중심 (격자점별 편의점 {S.ACTIVITY_RADIUS_M}m 개수 가중)"
    pt = kakao.legal_dong_point(f"{d['sido']} {d['sgg']} {d['name']}", d["code"])
    if pt:
        hit = kakao.legal_dong_at(*pt)
        if hit and hit["code"] == d["code"]:
            return pt[0], pt[1], "카카오 법정동 대표 좌표"
    cx = sum(p[0] for p in d["grid"]) / len(d["grid"])
    cy = sum(p[1] for p in d["grid"]) / len(d["grid"])
    x, y = _nearest_grid(d, cx, cy)
    return x, y, "격자 중심에 가장 가까운 점"


# ------------------------------------------------------------------ 3. 요인
def nearest_station(x: float, y: float) -> dict | None:
    docs = kakao.category_nearby("SW8", x, y, S.STATION_SEARCH_RADIUS_M)
    if not docs:
        return None
    name = docs[0]["place_name"].split(" ")[0]
    same = [d for d in docs if d["place_name"].split(" ")[0] == name]
    dist = min(int(d["distance"]) for d in same)
    return {
        "name": name,
        "lines": sorted({d["category_name"].split(" > ")[-1] for d in same}),
        "dist_m": dist,
        "walk_min": round(dist * S.WALK_DETOUR / S.WALK_SPEED_M_PER_MIN),
        "lon": float(same[0]["x"]),
        "lat": float(same[0]["y"]),
    }


def destination_points() -> dict[str, tuple[float, float]]:
    out = {}
    for name, query in S.DESTINATIONS.items():
        docs = kakao.keyword_search(query, category="SW8").get("documents", [])
        if not docs:
            raise RuntimeError(f"목적지를 찾지 못함: {name} ({query})")
        out[name] = (float(docs[0]["x"]), float(docs[0]["y"]))
    return out


def _walk_only(x: float, y: float, dest: tuple[float, float]) -> dict:
    dist = math.dist((x * 88_000, y * 111_000), (dest[0] * 88_000, dest[1] * 111_000))
    walk = round(dist * S.WALK_DETOUR / S.WALK_SPEED_M_PER_MIN)
    return {"min": walk, "fare": 0, "transfers": 0, "walk_min": walk, "mode": "도보", "lines": []}


def commute_to(x: float, y: float, dest: tuple[float, float]) -> dict:
    """카카오 대중교통(기본). 도보권이면 도보 추정, 경로가 없으면 오류를 그대로 남긴다."""
    if math.dist((x * 88_000, y * 111_000), (dest[0] * 88_000, dest[1] * 111_000)) < 700:
        return _walk_only(x, y, dest)
    r = kakao.transit(x, y, *dest)
    if r.get("error") == "EQUAL_POINTS":
        return _walk_only(x, y, dest)
    return r


def features(d: dict, dests: dict) -> dict:
    x, y = d["lon"], d["lat"]
    out = {
        "station": nearest_station(x, y),
        "convenience": {k: kakao.category_count(code, x, y, r) for k, (code, r) in S.CONVENIENCE.items()},
        "bars": kakao.bar_count(x, y, S.BAR_RADIUS_M),
    }
    out["commute"] = {name: commute_to(x, y, pt) for name, pt in dests.items()}
    return out


# ------------------------------------------------------------------ main
def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    t0 = time.time()
    log("1. 법정동 목록 수집")
    raw: dict[str, dict] = {}
    for region in S.REGIONS:
        raw.update(discover(region))

    log(f"2. 대표 지점 ({len(raw)}개 동)")
    dongs = []
    for d in raw.values():
        x, y, how = representative_point(d)
        dongs.append({
            "dong_code": d["code"], "sido": d["sido"], "sgg": d["sgg"], "name": d["name"],
            "lon": round(x, 6), "lat": round(y, 6), "point_source": how,
            "area_km2_est": round(len(d["grid"]) * S.GRID_STEP_M ** 2 / 1e6, 2),
        })

    log("3. 요인 값 수집 (카카오, ODsay)")
    dests = destination_points()
    for i, d in enumerate(dongs, 1):
        try:
            d.update(features(d, dests))
        except Exception as e:  # noqa: BLE001 - 한 동이 실패해도 나머지는 계속
            d["error"] = f"{type(e).__name__}: {e}"
            log(f"  [실패] {d['sgg']} {d['name']}: {d['error'][:150]}")
        if i % 20 == 0:
            log(f"  {i}/{len(dongs)}")

    dongs.sort(key=lambda d: d["dong_code"])
    meta = {
        "generated": date.today().isoformat(),
        "regions": S.REGIONS,
        "destinations": {k: {"lon": v[0], "lat": v[1]} for k, v in dests.items()},
        "sources": {
            "동 목록·대표 좌표": "카카오 로컬 API (좌표→행정구역, 주소 검색)",
            "역 접근성": f"카카오 지하철역(SW8), 도보 분 = 직선거리 × {S.WALK_DETOUR} ÷ {S.WALK_SPEED_M_PER_MIN}m (추정)",
            "생활 편의": "카카오 카테고리 검색 개수 " + ", ".join(f"{k} {r}m" for k, (_, r) in S.CONVENIENCE.items()),
            "조용함": f"카카오 '술집' 분류 개수 추정, 반경 {S.BAR_RADIUS_M}m (상가정보로 교체 예정)",
            "대표 지점": f"동 안 격자점별 편의점 {S.ACTIVITY_RADIUS_M}m 개수로 가중한 생활 중심",
            "통근": "카카오 대중교통 경로, 가장 빠른 경로 (출발 시각 지정 불가, 직선 700m 이내는 도보 추정)",
        },
        "grid_step_m": S.GRID_STEP_M,
    }
    OUT.write_text(json.dumps({"meta": meta, "dongs": dongs}, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"완료: {len(dongs)}개 동 → {OUT} ({time.time() - t0:.0f}초)")


if __name__ == "__main__":
    main()
