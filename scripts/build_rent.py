"""data/dongs.json 의 시군구에 대해 전월세 실거래를 모아 data/rent_deals.csv 를 만든다.

- 시군구 코드는 dongs.json 의 dong_code 앞 5자리에서 뽑는다 (지역을 바꿔도 그대로 동작)
- 기간: settings.RENT_END_YM 에서 거꾸로 settings.RENT_MONTHS 개월
- 법정동 매칭: (시군구 코드, 동 이름) → dong_code. 못 맞춘 거래는 dong_code 를 비워 두고 개수를 알린다
- 원본 응답은 data/cache/molit 에 저장 (다시 돌리면 API 를 부르지 않음)

실행:  python scripts/build_rent.py
"""

import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import settings as S  # noqa: E402
from collectors import molit  # noqa: E402
from config import ROOT  # noqa: E402

DONGS = ROOT / "data" / "dongs.json"
OUT = ROOT / "data" / "rent_deals.csv"
FIELDS = ["dong_code", "sgg_code", "dong_name", "house_type", "sub_type", "name", "area_m2", "area_kind",
          "deposit", "monthly_rent", "deal_ym", "deal_day", "contract_kind", "build_year", "floor"]


def months(end_ym: str, n: int) -> list[str]:
    y, m = int(end_ym[:4]), int(end_ym[4:])
    out = []
    for _ in range(n):
        out.append(f"{y}{m:02d}")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return sorted(out)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    dongs = json.loads(DONGS.read_text(encoding="utf-8"))["dongs"]
    code_of = {(d["dong_code"][:5], d["name"]): d["dong_code"] for d in dongs}
    sggs = sorted({d["dong_code"][:5] for d in dongs})
    yms = months(S.RENT_END_YM, S.RENT_MONTHS)
    print(f"시군구 {len(sggs)}개 × {len(yms)}개월 ({yms[0]}~{yms[-1]}) × 유형 {len(molit.SERVICES)}개", flush=True)

    t0 = time.time()
    rows, unmatched = [], Counter()
    for i, sgg in enumerate(sggs, 1):
        n0 = len(rows)
        for ht in molit.SERVICES:
            for ym in yms:
                for it in molit.fetch_raw(ht, sgg, ym):
                    r = molit.normalize(ht, it)
                    r["dong_code"] = code_of.get((r["sgg_code"], r["dong_name"]), "")
                    if not r["dong_code"]:
                        unmatched[(r["sgg_code"], r["dong_name"])] += 1
                    rows.append(r)
        print(f"  [{i}/{len(sggs)}] {sgg}: {len(rows) - n0}건", flush=True)

    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"완료: {len(rows)}건 → {OUT} ({time.time() - t0:.0f}초)")
    if unmatched:
        print(f"법정동 매칭 실패 {sum(unmatched.values())}건: {unmatched.most_common(10)}")


if __name__ == "__main__":
    main()
