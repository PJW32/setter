"""국토부 전월세 실거래가 (연립다세대, 단독다가구, 오피스텔) → 정규화된 거래 행."""

import xml.etree.ElementTree as ET
import json
import sqlite3
from contextlib import closing

from config import ROOT, get_data_go_kr_key

from .http import ApiError, get_text

SERVICES = {
    "연립다세대": "RTMSDataSvcRHRent",
    "단독다가구": "RTMSDataSvcSHRent",
    "오피스텔": "RTMSDataSvcOffiRent",
}
PAGE_SIZE = 1000
RENT_SNAPSHOT_PATH = ROOT / "data" / "rent_snapshot.sqlite"
NORMALIZATION_VERSION = "molit-normalize-v1"


def prepared_records(house_type: str, lawd_cd: str, deal_ym: str) -> list[dict] | None:
    """완료와 행 수가 검증된 사전 실거래를 읽는다. 미준비・손상은 기존 API로 대체한다."""
    if not RENT_SNAPSHOT_PATH.exists():
        return None
    batch = (lawd_cd, house_type, deal_ym, NORMALIZATION_VERSION)
    try:
        with closing(sqlite3.connect(RENT_SNAPSHOT_PATH.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            marker = conn.execute("SELECT count FROM collection WHERE code=? AND house_type=? AND ym=? AND version=?", batch).fetchone()
            if marker is None:
                return None
            records = [json.loads(row[0]) for row in conn.execute(
                "SELECT data FROM rental WHERE code=? AND house_type=? AND ym=? AND version=? ORDER BY rowid", batch)]
        if len(records) != marker[0] or any(r.get("sgg_code") != lawd_cd or r.get("deal_ym") != deal_ym for r in records):
            return None
        return records
    except (sqlite3.Error, ValueError, TypeError, AttributeError):
        return None


def _ok(text: str) -> bool:
    return "<resultCode>000</resultCode>" in text


def _num(s: str | None) -> float | None:
    s = (s or "").replace(",", "").strip()
    return float(s) if s else None


def fetch_raw(house_type: str, lawd_cd: str, deal_ym: str, *, offline: bool = False) -> list[dict]:
    """한 시군구 · 한 달 · 한 유형의 원본 item 목록 (페이지를 모두 받는다)."""
    svc = SERVICES[house_type]
    url = f"https://apis.data.go.kr/1613000/{svc}/get{svc}"
    items: list[dict] = []
    page = 1
    while True:
        text = get_text(
            "molit", url, {"LAWD_CD": lawd_cd, "DEAL_YMD": deal_ym, "pageNo": page, "numOfRows": PAGE_SIZE},
            secret_params={"serviceKey": get_data_go_kr_key(required=not offline)}, cache_ok=_ok, ext="xml",
            offline=offline,
        )
        if not _ok(text):
            raise ApiError(f"국토부 {house_type} {lawd_cd} {deal_ym}: {text[:200]}")
        root = ET.fromstring(text)
        items += [{c.tag: (c.text or "").strip() for c in it} for it in root.iter("item")]
        total = int(root.findtext(".//totalCount") or 0)
        if page * PAGE_SIZE >= total:
            return items
        page += 1


def normalize(house_type: str, it: dict) -> dict:
    """원본 item → 엔진이 읽는 거래 행. 금액은 만원, 면적은 ㎡."""
    contract_area = house_type == "단독다가구"
    return {
        "sgg_code": it.get("sggCd", ""),
        "dong_name": it.get("umdNm", ""),
        "house_type": house_type,
        "sub_type": it.get("houseType", ""),
        "name": it.get("offiNm") or it.get("mhouseNm") or "",
        "area_m2": _num(it.get("totalFloorAr" if contract_area else "excluUseAr")),
        "area_kind": "계약" if contract_area else "전용",
        "deposit": _num(it.get("deposit")),
        "monthly_rent": _num(it.get("monthlyRent")),
        "deal_ym": f"{it.get('dealYear', '')}{int(it.get('dealMonth') or 0):02d}",
        "deal_day": it.get("dealDay", ""),
        "contract_kind": it.get("contractType", ""),
        "build_year": it.get("buildYear", ""),
        "floor": it.get("floor", ""),
    }
