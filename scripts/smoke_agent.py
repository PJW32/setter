"""실제 API(카카오·공공데이터·Gemini)로 대화 몇 턴을 돌려 이벤트를 출력한다.

실행:  python scripts/smoke_agent.py            (기본 판교 시나리오)
       python scripts/smoke_agent.py "발화1" "발화2" ...
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.agent import Agent  # noqa: E402
from backend.regions import DataService  # noqa: E402

DEFAULT = [
    "판교역으로 출근해요. 보증금 1000에 월세 60 넘으면 안 되고 통근은 50분 이내였으면 해요. "
    "싼 게 제일 중요하고 조용했으면 좋겠어요. 이웃이 친절했으면 좋겠어요.",
    "아까보다 역 가까운 게 더 중요해요. 통근보다는 역이 더 중요해요.",
    "통근 30분 이내로 줄이면 어떻게 돼?",
]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    agent = Agent(DataService())
    s = agent.new_session()
    for text in sys.argv[1:] or DEFAULT:
        print(f"\n######## 사용자: {text}", flush=True)
        t0 = time.time()
        for ev in agent.handle(s, text):
            t = ev["type"]
            if t == "log":
                print(f"  [{ev['step']}:{ev['status']}] {ev['detail']}" + (f" ({ev['ms']}ms)" if ev.get("ms") else ""), flush=True)
            elif t == "interpretation":
                print("  해석:", json.dumps({k: ev[k] for k in ("intent", "applied", "rejected", "unsupported", "comparison_fixes", "follow_up")},
                                           ensure_ascii=False, default=str)[:900], flush=True)
            elif t == "result":
                p = ev["payload"]
                print(f"  결과{' (가정)' if ev['what_if'] else ''}: 후보 {p['universe_size']} 통과 {len(p['ranked'])}", flush=True)
                for d in p["ranked"][:5]:
                    print(f"    {d['rank']}. {d['sgg']} {d['name']} {d['score']}점 월{d['cost']['monthly_total']}만 통근{d['raw']['commute']}분 "
                          f"역{d['raw']['station_access']}분 주점{d['raw']['quiet']} | {'; '.join(d['flags'])}", flush=True)
                if p["diff"]:
                    print("    변동:", ", ".join(f"{m['name']} {m['prev_rank']}→{m['cur_rank']}" for m in p["diff"]["moves"][:6]))
                if p["tradeoffs"]:
                    print("    상충:", p["tradeoffs"])
            elif t == "message":
                print(f"  AI({ev['source']}): {ev['text']}", flush=True)
            elif t == "error":
                print("  오류:", ev["detail"], flush=True)
        print(f"  ({time.time() - t0:.0f}초)", flush=True)


if __name__ == "__main__":
    main()
