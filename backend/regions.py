"""목적지 → 후보 지역 → (없으면 수집) → 엔진 Dataset.

저장된 지역만 쓰지 않는다. 처음 보는 목적지면 주변 시군구를 그 자리에서 모아 저장한다.
진행 상황은 log(step, status, detail) 콜백으로 알린다 (화면의 에이전트 작업 로그).
"""

import math
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field

import settings as S
from collectors import kakao, molit, region
from collectors.http import ApiError
from config import get_key
from engine.data import Dataset, Deal

from . import store

OUTER_POOL = ThreadPoolExecutor(max_workers=4)
# 내부 OUTER_POOL/region.POOL과 분리해 중첩 작업의 교착을 피한다.
# 여러 검색이 들어와도 시군구 수집은 프로세스 전체에서 두 곳까지다.
DISTRICT_POOL = ThreadPoolExecutor(max_workers=2)
_sgg_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _profile(event, **values):
    """공급자 본문·좌표·질문·키 없이 Render 표준 서버 로그에 집계값만 남긴다."""
    logging.getLogger("uvicorn.error").info("data_profile %s", json.dumps(
        {"event": event, **values}, ensure_ascii=False, allow_nan=False))


def _noop(*_a, **_k):
    pass


@dataclass
class Destination:
    key: str  # 통근 저장 키 (역 이름 또는 장소 이름)
    label: str  # 화면 표시 이름
    query: str  # 사용자가 말한 이름
    place_name: str
    place_lon: float
    place_lat: float
    lon: float  # 통근 계산 도착점 (역)
    lat: float
    walk_from_station_min: int = 0
    station_lines: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ 목적지
def _region_place(query: str) -> dict | None:
    """'여의도', '역삼동' 같은 동네 이름 → 주소 검색의 지역 결과를 장소처럼."""
    for doc in kakao.search_address(query):
        if doc.get("address_type") == "REGION":
            return {"place_name": doc["address_name"], "x": doc["x"], "y": doc["y"],
                    "address_name": doc["address_name"], "category_group_code": ""}
    return None


def resolve_destination(query: str) -> Destination | None:
    """장소 이름 → 가장 가까운 지하철역에 붙인 목적지. 못 찾으면 None.

    순서: 'OO역'이면 지하철역 → 동네 이름이면 주소 검색 → 그 밖의 장소는 키워드 검색.
    """
    query = query.strip()
    docs = []
    if query.endswith("역"):
        docs = kakao.keyword_search(query, category="SW8").get("documents", [])
    if not docs:
        reg = _region_place(query)
        docs = [reg] if reg else []
    if not docs:
        docs = kakao.keyword_search(query).get("documents", [])
    if not docs:
        return None
    place = docs[0]
    px, py = float(place["x"]), float(place["y"])
    alts = [f"{d['place_name']} ({d.get('road_address_name') or d.get('address_name')})" for d in docs[:3]]
    if place.get("category_group_code") == "SW8":
        st = region.nearest_station(px, py) or {}
        name = region.station_base(place["place_name"])
        return Destination(key=name, label=name, query=query, place_name=place["place_name"], place_lon=px,
                           place_lat=py, lon=px, lat=py, station_lines=st.get("lines", []), alternatives=alts)
    st = region.nearest_station(px, py)
    if not st:  # 3km 안에 역이 없으면 장소 자체를 도착점으로
        return Destination(key=place["place_name"], label=place["place_name"], query=query,
                           place_name=place["place_name"], place_lon=px, place_lat=py, lon=px, lat=py,
                           alternatives=alts)
    return Destination(key=st["name"], label=f"{place['place_name']} (가까운 역: {st['name']})", query=query,
                       place_name=place["place_name"], place_lon=px, place_lat=py, lon=st["lon"], lat=st["lat"],
                       walk_from_station_min=st["walk_min"], station_lines=st["lines"], alternatives=alts)


# ------------------------------------------------------------------ 후보 시군구
def candidate_sggs(dest: Destination, radius_km: float) -> dict[str, dict]:
    """목적지 반경 안을 거친 격자로 훑어 시군구 코드 → {sido, name, seed}."""
    step = S.CANDIDATE_GRID_KM * 1000
    n = math.ceil(radius_km * 1000 / step)
    kx = 111_320 * math.cos(math.radians(dest.lat))
    pts = [(dest.lon, dest.lat)]
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            if math.hypot(i * step, j * step) <= radius_km * 1000:
                pts.append((round(dest.lon + i * step / kx, 5), round(dest.lat + j * step / 111_320, 5)))
    out: dict[str, dict] = {}
    for p, r in zip(pts, region.POOL.map(lambda q: kakao.legal_dong_at(*q), pts)):
        if r and r["code"][:5] not in out:
            out[r["code"][:5]] = {"sido": r["sido"], "name": r["sgg"], "seed": p}
    return dict(sorted(out.items()))


# ------------------------------------------------------------------ 시군구 수집
def _months(end_ym: str, n: int) -> list[str]:
    y, m = int(end_ym[:4]), int(end_ym[4:])
    out = []
    for _ in range(n):
        out.append(f"{y}{m:02d}")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return sorted(out)


def _lock(code: str) -> threading.Lock:
    with _locks_guard:
        return _sgg_locks.setdefault(code, threading.Lock())


def ensure_sgg(code: str, sido: str, name: str, seed: tuple[float, float], log=_noop) -> dict:
    """시군구가 저장돼 있으면 그대로, 없으면 수집해서 저장한다."""
    with _lock(code):
        st = store.sgg_status(code)
        if st and st["status"] == "done":
            return {**st, "cached": True}
        t0 = time.time()
        profile_started = time.monotonic()
        timings = {}
        label = f"{sido} {name}"
        try:
            log("collect", "running", f"{label}: 법정동 찾는 중")
            stage_started = time.monotonic()
            raw = region.discover(code, seed)
            timings["discover"] = round((time.monotonic() - stage_started) * 1000)
            log("collect", "done", f"{label}: 법정동 탐색 완료", ms=round((time.monotonic() - stage_started) * 1000))
            log("collect", "running", f"{label}: 법정동 {len(raw)}곳 — 대표 지점·역·편의·주점")
            stage_started = time.monotonic()
            dongs = list(OUTER_POOL.map(region.dong_record, raw.values()))
            timings["points_and_facilities"] = round((time.monotonic() - stage_started) * 1000)
            log("collect", "done", f"{label}: 대표 지점·역·시설 완료", ms=round((time.monotonic() - stage_started) * 1000))

            deals = []
            snapshot_batches, api_batches = 0, 0
            if get_key("DATA_GO_KR_SERVICE_KEY", required=False):
                log("collect", "running", f"{label}: 전월세 실거래 {S.RENT_MONTHS}개월")
                stage_started = time.monotonic()
                code_of = {d["name"]: d["dong_code"] for d in dongs}
                for ht in molit.SERVICES:
                    for ym in _months(S.RENT_END_YM, S.RENT_MONTHS):
                        records = molit.prepared_records(ht, code, ym)
                        if records is None:
                            api_batches += 1
                            records = [molit.normalize(ht, it) for it in molit.fetch_raw(ht, code, ym)]
                        else:
                            snapshot_batches += 1
                        for record in records:
                            r = dict(record)
                            r["dong_code"] = code_of.get(r["dong_name"], "")
                            deals.append(r)
                timings["rent"] = round((time.monotonic() - stage_started) * 1000)
                log("collect", "done", f"{label}: 실거래 수집 완료", ms=timings["rent"])
            stage_started = time.monotonic()
            store.save_sgg(code, sido, name, dongs, deals)
            timings["store_write"] = round((time.monotonic() - stage_started) * 1000)
            _profile("district", code=code, status="done", timings_ms=timings,
                     total_ms=round((time.monotonic() - profile_started) * 1000),
                     dongs=len(dongs), snapshot_batches=snapshot_batches, api_batches=api_batches)
            log("collect", "done", f"{label}: 동 {len(dongs)}곳, 실거래 {len(deals):,}건 ({time.time() - t0:.0f}초)")
            return {**store.sgg_status(code), "cached": False}
        except Exception as e:  # noqa: BLE001 - 한 시군구가 실패해도 나머지는 계속
            _profile("district", code=code, status="error", error_type=type(e).__name__, timings_ms=timings,
                     total_ms=round((time.monotonic() - profile_started) * 1000))
            store.mark_sgg_error(code, sido, name, f"{type(e).__name__}: {e}")
            log("collect", "error", f"{label}: 수집 실패 ({type(e).__name__})")
            return {"code": code, "status": "error", "error": str(e)}


# ------------------------------------------------------------------ 통근
def _commute(dong: dict, dest: Destination) -> dict:
    origin, target = (dong["lon"], dong["lat"]), (dest.lon, dest.lat)
    dist = region.meters(origin, target)
    if dist < 700:
        walk = round(dist * S.WALK_DETOUR / S.WALK_SPEED_M_PER_MIN)
        return {"min": walk, "fare": 0, "transfers": 0, "walk_min": walk, "mode": "도보", "lines": []}
    r = kakao.transit(*origin, *target)
    if r.get("error") == "EQUAL_POINTS":
        return {"min": 0, "fare": 0, "transfers": 0, "walk_min": 0, "mode": "도보", "lines": []}
    return r


def ensure_commutes(dest: Destination, dongs: list[dict], log=_noop) -> dict[str, dict]:
    started = time.monotonic()
    codes = [d["dong_code"] for d in dongs]
    have = store.commutes(dest.key, codes)
    todo = [d for d in dongs if d["dong_code"] not in have]
    if not todo:
        log("commute", "done", f"통근 {len(have)}곳 저장된 값 사용", ms=round((time.monotonic() - started) * 1000))
        return have
    log("commute", "running", f"통근 계산: 새로 {len(todo)}곳 (저장된 값 {len(have)}곳)")
    new, failed = {}, 0
    for d, r in zip(todo, OUTER_POOL.map(lambda d: _safe(_commute, d, dest), todo)):
        if r is None:
            failed += 1
        else:
            new[d["dong_code"]] = r
    store.save_commutes(dest.key, new)
    msg = f"통근 계산 완료: {len(new)}곳" + (f", 실패 {failed}곳 (통근 데이터 없음으로 표시)" if failed else "")
    log("commute", "done" if not failed else "warn", msg, ms=round((time.monotonic() - started) * 1000))
    return {**have, **new}


def _safe(fn, *a):
    try:
        return fn(*a)
    except ApiError:
        return None


# ------------------------------------------------------------------ Dataset
def build_dataset(dest: Destination, sgg_codes: list[str], radius_km: float, log=_noop) -> Dataset:
    target = (dest.lon, dest.lat)
    dongs = sorted(
        (d for d in store.dongs_in(sgg_codes) if region.meters((d["lon"], d["lat"]), target) <= radius_km * 1000),
        key=lambda d: d["dong_code"],
    )
    commutes = ensure_commutes(dest, dongs, log)
    for d in dongs:
        c = commutes.get(d["dong_code"])
        if c and "min" in c:
            c = {**c, "min": c["min"] + dest.walk_from_station_min, "walk_from_station": dest.walk_from_station_min}
        d["commute"] = {dest.key: c or {"error": "통근 데이터 없음"}}
    deals: dict[str, list[Deal]] = {}
    for r in store.deals_for([d["dong_code"] for d in dongs]):
        if r["deposit"] is None or r["monthly_rent"] is None:
            continue
        deals.setdefault(r["dong_code"], []).append(Deal(
            r["dong_code"], r["house_type"], r["area_m2"], r["area_kind"], r["deposit"], r["monthly_rent"],
            r["deal_ym"], r["contract_kind"]))
    meta = {
        "destination": dest.to_dict(),
        "radius_km": radius_km,
        "sgg_codes": sgg_codes,
        "rent_period": f"{_months(S.RENT_END_YM, S.RENT_MONTHS)[0]}~{S.RENT_END_YM}",
        "sources": SOURCES,
    }
    return Dataset(dongs=dongs, deals_by_dong=deals, meta=meta)


SOURCES = {
    "월 총비용": f"국토교통부 전월세 실거래가 (연립다세대·단독다가구·오피스텔), 최근 {S.RENT_MONTHS}개월 계약 중앙값. 시세 참고용 (현재 매물 가격 아님)",
    "통근 시간": "카카오 대중교통 경로, 가장 빠른 경로 (출발 시각 지정 불가, 심야버스 제외)",
    "역 접근성": f"카카오 지하철역 검색, 도보 분 = 직선거리 × {S.WALK_DETOUR} ÷ 분당 {S.WALK_SPEED_M_PER_MIN}m (추정)",
    "생활 편의": "카카오 장소 카테고리 개수 " + ", ".join(f"{k} {r}m" for k, (_, r) in S.CONVENIENCE.items()),
    "조용함": f"소상공인시장진흥공단 상가정보 주점(I211) 반경 {S.BAR_RADIUS_M}m 개수",
    "대표 지점": "동 안에서 편의점이 몰린 생활 중심 한 점 기준",
}


class DataService:
    """에이전트가 쓰는 데이터 계층. 테스트에서는 가짜로 바꿔 끼운다."""

    def __init__(self, radius_km: float = S.SEARCH_RADIUS_KM):
        self.radius_km = radius_km
        store.init()

    def resolve_destination(self, query: str) -> Destination | None:
        return resolve_destination(query)

    def dataset_for(self, dest: Destination, log=_noop) -> Dataset:
        started = time.monotonic()
        stage_started = started
        log("region", "running", f"{dest.label} 반경 {self.radius_km:g}km 후보 지역 찾는 중")
        sggs = candidate_sggs(dest, self.radius_km)
        cached = [c for c in sggs if (store.sgg_status(c) or {}).get("status") == "done"]
        region_ms = round((time.monotonic() - stage_started) * 1000)
        log("region", "done", f"후보 시군구 {len(sggs)}곳 (저장됨 {len(cached)}, 새로 수집 {len(sggs) - len(cached)})",
            ms=round((time.monotonic() - stage_started) * 1000))
        stage_started = time.monotonic()
        pending = [DISTRICT_POOL.submit(ensure_sgg, code, info["sido"], info["name"], info["seed"], log)
                   for code, info in sggs.items() if code not in cached]
        # 요청이 실패해도 이미 시작한 작업이 끝나기 전 반환하지 않는다.
        error = None
        for future in pending:
            try:
                future.result()
            except Exception as exc:
                if error is None:
                    error = exc
        if error is not None:
            raise error
        collect_ms = round((time.monotonic() - stage_started) * 1000)
        log("collect", "done", f"후보 지역 준비 완료 — 전체 경과 {collect_ms / 1000:.1f}초",
            ms=collect_ms)
        ok = [c for c in sggs if (store.sgg_status(c) or {}).get("status") == "done"]
        stage_started = time.monotonic()
        ds = build_dataset(dest, ok, self.radius_km, log)
        dataset_ms = round((time.monotonic() - stage_started) * 1000)
        total_ms = round((time.monotonic() - started) * 1000)
        _profile("dataset", timings_ms={"regions": region_ms, "collection": collect_ms,
                                        "dataset_including_commutes": dataset_ms, "total": total_ms},
                 candidate_regions=len(sggs), cached_regions=len(cached), ready_regions=len(ok),
                 candidate_dongs=len(ds.dongs), deals=sum(map(len, ds.deals_by_dong.values())))
        log("dataset", "done", f"후보 동 {len(ds.dongs)}곳, 실거래 {sum(len(v) for v in ds.deals_by_dong.values()):,}건"
            f" — 데이터 준비 전체 경과 {total_ms / 1000:.1f}초 (조건 해석·설명 제외)",
            ms=dataset_ms, total_ms=total_ms)
        return ds
