"""카카오 로컬 API (좌표→법정동, 주소 검색, 카테고리·키워드 개수)."""

from config import get_key

from .http import get_json

BASE = "https://dapi.kakao.com/v2/local"


def _get(path: str, params: dict) -> dict:
    headers = {"Authorization": f"KakaoAK {get_key('KAKAO_REST_API_KEY')}"}
    return get_json("kakao", f"{BASE}/{path}", params, headers=headers)


def legal_dong_at(x: float, y: float) -> dict | None:
    """좌표가 속한 법정동 {code, name, sgg, sido}. 바다·경계 밖이면 None."""
    data = _get("geo/coord2regioncode.json", {"x": round(x, 6), "y": round(y, 6)})
    for doc in data.get("documents", []):
        if doc.get("region_type") == "B":
            return {
                "code": doc["code"],
                "sido": doc["region_1depth_name"],
                "sgg": doc["region_2depth_name"],
                "name": doc["region_3depth_name"],
            }
    return None


def search_address(query: str) -> list[dict]:
    return _get("search/address.json", {"query": query, "size": 30}).get("documents", [])


def legal_dong_point(query: str, b_code: str) -> tuple[float, float] | None:
    """법정동 주소 검색 결과 중 b_code 가 일치하는 대표 좌표."""
    for doc in search_address(query):
        addr = doc.get("address") or {}
        if addr.get("b_code") == b_code:
            return float(doc["x"]), float(doc["y"])
    return None


def category_count(code: str, x: float, y: float, radius: int) -> int:
    data = _get(
        "search/category.json",
        {"category_group_code": code, "x": round(x, 6), "y": round(y, 6), "radius": radius, "size": 1},
    )
    return int(data["meta"]["total_count"])


def category_nearby(code: str, x: float, y: float, radius: int, pages: int = 1) -> list[dict]:
    docs: list[dict] = []
    for page in range(1, pages + 1):
        data = _get(
            "search/category.json",
            {"category_group_code": code, "x": round(x, 6), "y": round(y, 6), "radius": radius,
             "sort": "distance", "page": page, "size": 15},
        )
        docs += data.get("documents", [])
        if data["meta"].get("is_end"):
            break
    return docs


def keyword_search(query: str, *, x: float | None = None, y: float | None = None, radius: int | None = None,
                   category: str | None = None, page: int = 1) -> dict:
    params: dict = {"query": query, "page": page, "size": 15}
    if x is not None:
        params.update({"x": round(x, 6), "y": round(y, 6)})
    if radius:
        params["radius"] = radius
    if category:
        params["category_group_code"] = category
    return _get("search/keyword.json", params)


TRANSIT_URL = "https://dapi.kakao.com/v2/routing/publictraffic"
TRANSIT_TYPE = {"SUBWAY": "지하철", "BUS": "버스", "BUS_AND_SUBWAY": "버스+지하철"}


def _is_night(route: dict) -> bool:
    for s in route.get("steps", []):
        for v in s["properties"].get("vehicles", []) or []:
            if "심야" in (v.get("name") or ""):
                return True
    return False


def transit(sx: float, sy: float, ex: float, ey: float) -> dict:
    """카카오 대중교통 경로 중 가장 빠른 것. 실패하면 {"error": status}.

    무료 일 1,000건. 출발 시각은 지정할 수 없다 (시각 무관 추정값).
    """
    headers = {"Authorization": f"KakaoAK {get_key('KAKAO_REST_API_KEY')}"}
    params = {"start_x": round(sx, 6), "start_y": round(sy, 6), "end_x": round(ex, 6), "end_y": round(ey, 6)}
    data = get_json("kakao_transit", TRANSIT_URL, params, headers=headers)
    if data.get("status") != "OK" or not data.get("routes"):
        return {"error": data.get("status", "NO_RESULTS")}
    # 출퇴근 비교이므로 심야버스가 들어간 경로는 뺀다. 요금이 있는 경로를 먼저 고른다.
    day = [r for r in data["routes"] if not _is_night(r)] or data["routes"]
    with_fare = [r for r in day if (r["properties"].get("fare") or {}).get("value") is not None]
    best = min(with_fare or day, key=lambda r: r["properties"]["totalTime"])
    p = best["properties"]
    steps = [s["properties"] for s in best.get("steps", [])]
    lines: list[str] = []
    for s in steps:
        for v in s.get("vehicles", []) or []:
            if v.get("name") and v["name"] not in lines:
                lines.append(v["name"])
    return {
        "min": round(p["totalTime"] / 60),
        "fare": (p.get("fare") or {}).get("value"),
        "transfers": p.get("transfers", 0),
        "walk_min": round(sum(s.get("time", 0) for s in steps if s.get("type") == "WALKING") / 60),
        "mode": TRANSIT_TYPE.get(p.get("type"), p.get("type")),
        "lines": lines,
        "map_url": (data.get("properties") or {}).get("landingURL"),
    }


def bar_count(x: float, y: float, radius: int) -> dict:
    """반경 안 술집 수 추정.

    키워드 '술집' 검색의 total_count 에, 받은 문서(최대 45개) 중 분류가 실제 '술집'인 비율을 곱한다.
    """
    first = keyword_search("술집", x=x, y=y, radius=radius, category="FD6")
    total = int(first["meta"]["total_count"])
    docs = list(first.get("documents", []))
    page = 1
    while not first["meta"].get("is_end") and page < 3:
        page += 1
        first = keyword_search("술집", x=x, y=y, radius=radius, category="FD6", page=page)
        docs += first.get("documents", [])
    if not docs:
        return {"count": 0, "raw_total": total, "precision": None}
    hits = sum(1 for d in docs if "> 술집" in d.get("category_name", ""))
    precision = hits / len(docs)
    return {"count": round(total * precision), "raw_total": total, "precision": round(precision, 2)}
