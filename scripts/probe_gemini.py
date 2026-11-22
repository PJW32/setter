"""Gemini 키와 구조화 출력(JSON 스키마) 동작 확인.

실행:  python scripts/probe_gemini.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_key  # noqa: E402

from google import genai  # noqa: E402

MODEL = "gemini-3.8-flash"

SCHEMA = {
    "type": "object",
    "properties": {
        "max_monthly_rent": {"type": ["integer", "null"], "description": "월세 상한 (원). 언급 없으면 null"},
        "preference_changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "factor": {"type": "string", "enum": ["monthly_cost", "commute", "station_access", "convenience", "quiet"]},
                    "level": {"type": "string", "enum": ["매우 중요", "중요", "보통", "조금", "상관없음"]},
                    "evidence": {"type": "string"},
                },
                "required": ["factor", "level", "evidence"],
            },
        },
        "unsupported": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["max_monthly_rent", "preference_changes", "unsupported"],
}

PROMPT = (
    "사용자 발화에서 집 찾기 조건을 추출하라. 데이터로 확인할 수 없는 조건은 unsupported에 넣어라.\n"
    "발화: 판교로 출근해요. 월세는 60만원 넘으면 안 되고, 조용한 동네면 좋겠어요. 이웃이 친절했으면 해요."
)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    # 이 키는 Agent Platform(Vertex) API로 제한된 키라 Vertex 엔드포인트로 호출한다.
    client = genai.Client(vertexai=True, api_key=get_key("GEMINI_API_KEY"))
    resp = client.models.generate_content(
        model=MODEL,
        contents=PROMPT,
        config={"response_mime_type": "application/json", "response_json_schema": SCHEMA},
    )
    print(f"모델 {MODEL} (Vertex)")
    print(json.dumps(json.loads(resp.text), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
