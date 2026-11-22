"""API 응답 형태 확인용 스크립트.

키가 있는 API만 한두 번씩 호출해서
  - 결과 코드, 전체 건수
  - 응답 항목의 필드 이름과 예시 값
을 출력하고, 원본 응답을 data/raw/ 에 저장한다 (깃 제외 폴더).
키 값은 출력하거나 파일에 남기지 않는다.

실행:  python scripts/probe_apis.py            (전부)
       python scripts/probe_apis.py molit kakao (일부만)
"""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import ROOT, get_data_go_kr_key, get_key  # noqa: E402

RAW_DIR = ROOT / "data" / "raw"

# 시험 지점: 성남시 분당구 정자역 부근 → 목적지 판교역 (좌표는 대략값)
LAWD_CD = "41135"  # 성남시 분당구 (법정동코드 앞 5자리)
DEAL_YMD = "202610"  # 계약년월
ORIGIN = (127.1114, 37.3670)  # (경도, 위도) 정자역
DEST = (127.1112, 37.3948)  # 판교역


def http_get(url: str, params: dict, headers: dict | None = None) -> tuple[int, str]:
    full = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(full, headers={"User-Agent": "dongnefit-probe/0.1", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        return -1, f"연결 실패: {e.reason}"


def save(name: str, body: str) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / name).write_text(body, encoding="utf-8")


def show_fields(items: list[dict], n: int = 3) -> None:
    if not items:
        print("    (항목 없음)")
        return
    keys = sorted({k for it in items for k in it})
    print(f"    필드 {len(keys)}개: {', '.join(keys)}")
    for it in items[:n]:
        print("    예시:", json.dumps(it, ensure_ascii=False)[:400])


def section(title: str) -> None:
    print(f"\n=== {title} " + "=" * max(0, 60 - len(title)))


# ---------------------------------------------------------------- 국토부 전월세
MOLIT = {
    "연립다세대": "https://apis.data.go.kr/1613000/RTMSDataSvcRHRent/getRTMSDataSvcRHRent",
    "단독다가구": "https://apis.data.go.kr/1613000/RTMSDataSvcSHRent/getRTMSDataSvcSHRent",
    "오피스텔": "https://apis.data.go.kr/1613000/RTMSDataSvcOffiRent/getRTMSDataSvcOffiRent",
}


def probe_molit() -> None:
    key = get_data_go_kr_key(required=False)
    if not key:
        print("\n[건너뜀] 국토부 전월세: DATA_GO_KR_SERVICE_KEY 없음")
        return
    for label, url in MOLIT.items():
        section(f"국토부 전월세 - {label}")
        params = {"serviceKey": key, "LAWD_CD": LAWD_CD, "DEAL_YMD": DEAL_YMD, "pageNo": 1, "numOfRows": 20}
        status, body = http_get(url, params)
        save(f"molit_{label}.xml", body)
        print(f"    HTTP {status}")
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            print("    XML 아님:", body[:300])
            continue
        print("    resultCode:", root.findtext(".//resultCode"), root.findtext(".//resultMsg"))
        print("    totalCount:", root.findtext(".//totalCount"))
        items = [{c.tag: (c.text or "").strip() for c in it} for it in root.iter("item")]
        show_fields(items)


# ---------------------------------------------------------------- 소상공인 상가정보
SBIZ = "https://apis.data.go.kr/B553077/api/open/sdsc2"


def probe_sbiz() -> None:
    key = get_data_go_kr_key(required=False)
    if not key:
        print("\n[건너뜀] 상가정보: DATA_GO_KR_SERVICE_KEY 없음")
        return
    # 오퍼레이션 이름은 문서에서 확인하지 못해 흔히 쓰이는 이름으로 시도한다.
    calls = [
        ("업종 대분류", "largeUpjongList", {}),
        ("업종 중분류(I2)", "middleUpjongList", {"indsLclsCd": "I2"}),
        ("반경 500m 상가", "storeListInRadius", {"radius": 500, "cx": ORIGIN[0], "cy": ORIGIN[1]}),
    ]
    for label, op, extra in calls:
        section(f"상가정보 - {label} ({op})")
        params = {"serviceKey": key, "type": "json", "pageNo": 1, "numOfRows": 10, **extra}
        status, body = http_get(f"{SBIZ}/{op}", params)
        save(f"sbiz_{op}.json", body)
        print(f"    HTTP {status}")
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            print("    JSON 아님:", body[:300])
            continue
        header = data.get("header", {})
        b = data.get("body", {})
        print("    header:", json.dumps(header, ensure_ascii=False)[:300])
        print("    totalCount:", b.get("totalCount"))
        show_fields(b.get("items") or [], n=5 if "Upjong" in op else 3)


# ---------------------------------------------------------------- 카카오 로컬
KAKAO = "https://dapi.kakao.com/v2/local"


def probe_kakao() -> None:
    key = get_key("KAKAO_REST_API_KEY", required=False)
    if not key:
        print("\n[건너뜀] 카카오: KAKAO_REST_API_KEY 없음")
        return
    headers = {"Authorization": f"KakaoAK {key}"}
    x, y = ORIGIN
    calls = [
        ("편의점 반경 800m", "search/category.json", {"category_group_code": "CS2", "x": x, "y": y, "radius": 800}),
        # total_count 가 45를 넘게 나오는지 확인 (넘으면 개수 세기에 한 번 호출로 충분)
        ("음식점 반경 2km", "search/category.json", {"category_group_code": "FD6", "x": x, "y": y, "radius": 2000}),
        ("지하철역 반경 2km 거리순", "search/category.json",
         {"category_group_code": "SW8", "x": x, "y": y, "radius": 2000, "sort": "distance"}),
        ("좌표 → 법정동/행정동", "geo/coord2regioncode.json", {"x": x, "y": y}),
        ("주소 검색", "search/address.json", {"query": "경기도 성남시 분당구 정자동"}),
    ]
    for label, path, params in calls:
        section(f"카카오 - {label}")
        status, body = http_get(f"{KAKAO}/{path}", params, headers)
        stem = path.replace("/", "_").removesuffix(".json")
        save(f"kakao_{stem}_{params.get('category_group_code', 'x')}.json", body)
        print(f"    HTTP {status}")
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            print("    JSON 아님:", body[:300])
            continue
        print("    meta:", json.dumps(data.get("meta"), ensure_ascii=False)[:300])
        show_fields(data.get("documents") or [], n=2)


# ---------------------------------------------------------------- ODsay
def probe_odsay() -> None:
    key = get_key("ODSAY_API_KEY", required=False)
    if not key:
        print("\n[건너뜀] ODsay: ODSAY_API_KEY 없음")
        return
    section("ODsay - 정자역 → 판교역")
    params = {"SX": ORIGIN[0], "SY": ORIGIN[1], "EX": DEST[0], "EY": DEST[1], "apiKey": key}
    status, body = http_get("https://api.odsay.com/v1/api/searchPubTransPathT", params)
    save("odsay_searchPubTransPathT.json", body)
    print(f"    HTTP {status}")
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        print("    JSON 아님:", body[:300])
        return
    if "error" in data:
        print("    error:", json.dumps(data["error"], ensure_ascii=False))
        return
    paths = data.get("result", {}).get("path", [])
    print(f"    경로 {len(paths)}개")
    for p in paths[:3]:
        info = p.get("info", {})
        print(f"    pathType={p.get('pathType')} totalTime={info.get('totalTime')}분 "
              f"payment={info.get('payment')} 환승(버스/지하철)={info.get('busTransitCount')}/"
              f"{info.get('subwayTransitCount')} 도보={info.get('totalWalk')}m")
    if paths:
        print("    info 필드:", ", ".join(sorted(paths[0].get("info", {}))))
        print("    subPath 필드:", ", ".join(sorted({k for s in paths[0].get("subPath", []) for k in s})))


PROBES = {"molit": probe_molit, "sbiz": probe_sbiz, "kakao": probe_kakao, "odsay": probe_odsay}

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    targets = sys.argv[1:] or list(PROBES)
    for t in targets:
        PROBES[t]()
    print(f"\n원본 응답 저장 위치: {RAW_DIR}")
