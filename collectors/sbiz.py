"""소상공인 상가(상권)정보 - 반경 안 업소 수."""

from config import get_data_go_kr_key

from .http import ApiError, get_json

BASE = "https://apis.data.go.kr/B553077/api/open/sdsc2"
BAR_MCLS = "I211"  # 주점: 일반 유흥, 무도 유흥, 생맥주 전문, 요리 주점


def count_in_radius(x: float, y: float, radius: int, *, mcls: str | None = None, scls: str | None = None) -> int:
    params = {"radius": radius, "cx": round(x, 6), "cy": round(y, 6), "type": "json", "pageNo": 1, "numOfRows": 1}
    if mcls:
        params["indsMclsCd"] = mcls
    if scls:
        params["indsSclsCd"] = scls
    data = get_json(
        "sbiz", f"{BASE}/storeListInRadius", params,
        secret_params={"serviceKey": get_data_go_kr_key()},
        cache_ok=lambda d: (d.get("header") or {}).get("resultCode") in ("00", "03"),
    )
    header = data.get("header") or {}
    code = header.get("resultCode")
    if code == "03":  # 데이터 없음
        return 0
    if code != "00":
        raise ApiError(f"상가정보 {code}: {header.get('resultMsg')}")
    return int((data.get("body") or {}).get("totalCount") or 0)


def bar_count(x: float, y: float, radius: int) -> int:
    return count_in_radius(x, y, radius, mcls=BAR_MCLS)
