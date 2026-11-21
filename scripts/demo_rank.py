"""실데이터로 페르소나 시나리오를 돌려 순위와 순위 변동을 출력한다 (LLM 없이).

페르소나: 판교 출근 신입, 보증금 1,000만 원·월세 60만 원 이하, 통근 50분 이내.
1단계: 기본 가중치 → 2단계: "월세가 제일 중요해" → 3단계: "조용한 게 더 중요해"

실행:  python scripts/demo_rank.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import ROOT  # noqa: E402
from engine import FACTORS, State, apply_changes, compare, evaluate, load_dataset  # noqa: E402

LABEL = {k: f.label for k, f in FACTORS.items()}


def show(title: str, res, n: int = 10) -> None:
    print(f"\n=== {title}")
    print("가중치:", ", ".join(f"{LABEL[k]} {w:.2f}" for k, w in res.weights.items()))
    print(f"후보 {res.universe_size}곳 중 통과 {len(res.ranked)}곳, 제외 {len(res.excluded)}곳")
    for e in res.top(n):
        r, dt = e["raw"], e["detail"]
        mc = dt["monthly_cost"]
        top2 = sorted(e["contrib"].items(), key=lambda kv: -kv[1])[:2]
        print(f"{e['rank']:>2}. {e['sgg']} {e['name']:<5} {e['score']:5.1f}점 | "
              f"월 {r['monthly_cost'] if r['monthly_cost'] is not None else '?'}만 (표본 {mc['samples']}) "
              f"통근 {r['commute']}분 역 {r['station_access']}분 편의 {r['convenience']} 주점 {r['quiet']:.0f} "
              f"| 강점: {', '.join(LABEL[k] for k, _ in top2)} | {'; '.join(e['flags'])}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ds = load_dataset(ROOT / "data" / "dongs.json", ROOT / "data" / "rent_deals.csv")
    dests = ds.destinations

    s, _ = apply_changes(State(), {
        "set_constraints": {"max_deposit": 1000, "max_monthly_rent": 60, "max_commute_min": 50},
        "params": {"destination": "판교역"},
    }, destinations=dests, utterance="판교 출근, 보증금 1000에 월세 60 이하, 통근 50분 이내")
    r1 = evaluate(ds, s)
    show("1단계: 기본 (모든 요인 '보통')", r1)
    print("제외 예:", ", ".join(f"{e['name']}({e['violations'][0]['constraint']})" for e in r1.excluded[:8]))

    s, rep = apply_changes(s, {"preference_changes": [
        {"factor": "monthly_cost", "level": "매우 중요", "evidence": "월세가 제일 중요해"}]},
        destinations=dests, utterance="월세가 제일 중요해")
    r2 = evaluate(ds, s)
    show("2단계: 월 총비용 '매우 중요'", r2)
    d = compare(r1, r2)
    print("순위 변동:", ", ".join(f"{m['name']} {m['prev_rank']}→{m['cur_rank']}" for m in d["moves"][:8]))
    for o in d["overtakes"][:2]:
        print(f"  {o['a']['name']}가 {o['b']['name']}를 추월: 격차 {o['gap_before']} → {o['gap_after']}, 요인별 {o['by_factor']}")

    s, _ = apply_changes(s, {"preference_changes": [
        {"factor": "quiet", "level": "매우 중요", "evidence": "아까보다 조용한 게 더 중요해"}]},
        destinations=dests, utterance="아까보다 조용한 게 더 중요해")
    r3 = evaluate(ds, s)
    show("3단계: 조용함도 '매우 중요'", r3, n=5)
    d = compare(r2, r3)
    print("순위 변동:", ", ".join(f"{m['name']} {m['prev_rank']}→{m['cur_rank']}" for m in d["moves"][:8]))


if __name__ == "__main__":
    main()
