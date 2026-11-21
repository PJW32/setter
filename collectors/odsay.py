"""ODsay 대중교통 경로 → 통근 요약값."""

from config import get_key

from .http import ApiError, get_json

URL = "https://api.odsay.com/v1/api/searchPubTransPathT"
PATH_TYPE = {1: "지하철", 2: "버스", 3: "버스+지하철"}
# 다시 불러도 같은 결과인 오류: 정류장 없음, 서비스 지역 밖, 700m 이내, 결과 없음
PERMANENT_ERRORS = ("3", "4", "5", "6", "-98", "-99")


class QuotaOrTemporaryError(ApiError):
    """한도 초과(429) 등. 캐시하지 않고, 수집을 멈추는 신호로 쓴다."""


def _error_code(data: dict) -> str | None:
    if "error" not in data:
        return None
    err = data["error"][0] if isinstance(data["error"], list) and data["error"] else data["error"]
    return str(err.get("code")) if isinstance(err, dict) else "unknown"


def commute(sx: float, sy: float, ex: float, ey: float) -> dict:
    """가장 빠른 경로의 소요 시간·요금·환승.

    실패하면 {"error": 코드, "message": ...}. -98 은 출발·도착이 700m 이내(도보권).
    """
    params = {"SX": round(sx, 6), "SY": round(sy, 6), "EX": round(ex, 6), "EY": round(ey, 6)}
    data = get_json("odsay", URL, params, secret_params={"apiKey": get_key("ODSAY_API_KEY")}, pause=0.15,
                    cache_ok=lambda d: _error_code(d) in (None, *PERMANENT_ERRORS))
    code = _error_code(data)
    if code is not None:
        err = data["error"][0] if isinstance(data["error"], list) else data["error"]
        if code not in PERMANENT_ERRORS:
            raise QuotaOrTemporaryError(f"ODsay {code}: {err.get('msg') or err.get('message')}")
        return {"error": code, "message": err.get("msg") or err.get("message")}
    paths = data.get("result", {}).get("path", [])
    if not paths:
        raise ApiError("ODsay 경로 없음")
    best = min(paths, key=lambda p: p["info"]["totalTime"])
    info = best["info"]
    lines = []
    for sp in best.get("subPath", []):
        for lane in sp.get("lane", []) or []:
            name = lane.get("name") or lane.get("busNo")
            if name and name not in lines:
                lines.append(name)
    return {
        "min": info["totalTime"],
        "fare": info.get("payment"),
        "transfers": max(0, info.get("busTransitCount", 0) + info.get("subwayTransitCount", 0) - 1),
        "walk_m": info.get("totalWalk"),
        "mode": PATH_TYPE.get(best.get("pathType"), str(best.get("pathType"))),
        "lines": lines,
    }
