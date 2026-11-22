# 백엔드

FastAPI + 에이전트 흐름 + Gemini + 실시간 지역 수집(SQLite).

```powershell
python -m uvicorn backend.main:app --reload --port 8000
```

| 파일 | 역할 |
|---|---|
| `backend/main.py` | API 엔드포인트, 이벤트 스트림(SSE), 세션 보관(메모리), 빌드된 프론트 제공(`frontend/dist`) |
| `backend/agent.py` | 대화 한 턴의 흐름. 이벤트를 하나씩 내보낸다 |
| `backend/llm.py` | Gemini 호출 (조건 추출, 결과 설명), 비교 순서 검증, 설명 숫자 검사 |
| `backend/prompts.py` | 시스템 프롬프트, 조건 추출 JSON 스키마 |
| `backend/regions.py` | 목적지 해석, 후보 시군구, 수집·저장, 통근 계산, 엔진 Dataset 만들기 |
| `backend/presenter.py` | 엔진 결과 → 화면 JSON / LLM facts / 템플릿 설명 / 상충 감지 |
| `backend/store.py` | SQLite 저장소 |

## 1. 한 턴의 흐름 (`Agent.handle`)

```
사용자 발화
 1. [Gemini] 현재 상태 + 직전 질문 + 발화 → 변경분 JSON (스키마 강제)
 2. [코드]  비교("A가 B보다 중요")가 단계 순서에 맞는지 검사, 어긋나면 고침
 3. [카카오] 목적지가 새로 나왔으면 해석 → 가장 가까운 역. 못 찾으면 되묻기
 4. [엔진]  apply_changes: 검증 → 새 상태 (what_if 면 복사본만)
    → 이벤트 interpretation (반영 / 버림 / 확인 불가 / 되묻기)
 5. [수집]  목적지가 바뀌었으면 후보 지역 확보 (없으면 수집, 진행 로그 실시간)
 6. [엔진]  evaluate → 순위, compare(이전, 지금) → 순위 변동 분해, 상충 감지
    → 이벤트 result
 7. [Gemini] 엔진 facts 로 설명 → 설명 속 숫자가 facts 에 있는지 검사
    → 실패하면 한 번 다시 쓰게 하고, 그래도 틀리면 코드 템플릿 설명
    → 이벤트 message
 8. 상태 확정 (what_if 면 확정 안 함) → 이벤트 done
```

## 2. LLM 사용과 오류 대응 (평가 "AI 결과의 오류·불확실성 대응")

| 위험 | 대응 | 위치 |
|---|---|---|
| JSON 형식이 깨짐 | 스키마 강제(`response_json_schema`) + 파싱 실패 시 1회 재시도 + 그래도 실패하면 "다시 말해 주세요" | `llm.extract` |
| 없는 요인·단계·조건 | 스키마 enum + `apply_changes` 가 다시 검증하고 버린 이유를 화면에 표시 | `engine/state.py` |
| 비교 순서를 틀리게 옮김 | `comparisons` 를 따로 받아 코드가 순서를 검사·교정 | `llm.enforce_comparisons` |
| 데이터로 확인 못 할 조건을 지어냄 | 프롬프트로 금지 + `unsupported` 로 분리해 "직접 확인" 체크리스트로 | `prompts.EXTRACT_SYSTEM` |
| 설명에 없는 숫자를 지어냄 | facts 에 없는 숫자 검사 → 재작성 → 템플릿 대체 | `llm.explain`, `presenter.template_explanation` |
| 목적지 오인 | 해석 결과(장소, 붙인 역, 후보 3개)를 해석 카드에 보여주고 고칠 수 있게 | `regions.resolve_destination` |
| 해석을 사용자가 확인 | `evidence`(근거 원문)를 단계 옆에 표시, 가정 질문은 상태를 바꾸지 않음 | `interpretation` 이벤트 |

- 모델: `gemini-3.8-flash` (정식 모델, 환경변수 `GEMINI_MODEL` 로 변경). Vertex 엔드포인트(`vertexai=True`)
- temperature: 추출 0.2, 설명 0.3

## 3. API

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/health` | 키 설정 여부(값 없음), 저장소 통계 |
| GET | `/api/meta` | 요인 목록, 단계 목록, 수집된 시군구 |
| POST | `/api/sessions` | 세션 생성 → `{session_id, state, messages, result}` |
| GET | `/api/sessions/{id}` | 현재 상태·대화·마지막 결과 |
| POST | `/api/sessions/{id}/messages` | `{"text": "..."}` → **이벤트 스트림** (아래) |
| POST | `/api/sessions/{id}/what-if` | `{"changes": {변경분}}` → `{report, payload}` (상태 안 바뀜) |

세션은 서버 메모리에 있다 (서버를 다시 켜면 사라짐). 수집한 지역 데이터는 SQLite 에 남는다.

### 3.1 이벤트 스트림 형식

`Content-Type: text/event-stream`. 한 이벤트 = `event: <type>\ndata: <JSON>\n\n`.
POST 라서 브라우저 `EventSource` 대신 `fetch` 의 `response.body` 스트림을 읽는다.

```ts
const res = await fetch(`/api/sessions/${id}/messages`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({text})});
const reader = res.body!.getReader(); const dec = new TextDecoder(); let buf = "";
for (;;) {
  const {value, done} = await reader.read(); if (done) break;
  buf += dec.decode(value, {stream: true});
  let i; while ((i = buf.indexOf("\n\n")) >= 0) {
    const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
    const data = chunk.split("\n").find(l => l.startsWith("data: "))?.slice(6);
    if (data) onEvent(JSON.parse(data));
  }
}
```

모든 이벤트에 `type`, `t`(유닉스 초).

| type | 필드 | 화면 |
|---|---|---|
| `log` | `step`(extract/destination/region/collect/commute/dataset/score/tradeoff/explain), `status`(running/done/warn/error), `detail`, `ms?` | 에이전트 작업 로그 |
| `interpretation` | `intent`, `what_if`, `applied[]`, `rejected[]`, `unsupported[]`, `comparisons[]`, `comparison_fixes[]`, `destination`, `follow_up`, `state` | "이렇게 이해했어요" 카드, 현재 조건 칩 |
| `result` | `what_if`, `payload` (아래) | 지도·순위표·산점도·비교·순위 변동 |
| `message` | `text`, `source`(llm/template) | 대화창 AI 말풍선 |
| `error` | `detail` | 오류 표시 |
| `done` | | 입력창 다시 활성화 |

`applied[]` 항목: `{type: constraint|param|preference, key, label?, before, after, evidence?}`
`rejected[]` 항목: `{item, reason, supported?}`

### 3.2 `result.payload`

```jsonc
{
  "destination": {"key": "판교역", "label": "...", "lon": 127.11, "lat": 37.39, "walk_from_station_min": 0, "alternatives": ["..."]},
  "universe_size": 120,
  "ranked": [ /* 통과한 동, 순위순 */ {
    "dong_code": "...", "name": "이매동", "sgg": "성남시 분당구", "lon": 127.1, "lat": 37.4,
    "rank": 1, "score": 82.4,
    "contrib": {"monthly_cost": 15.2, "commute": 19.6, ...},   // 점수 = 합
    "raw": {"monthly_cost": 61.0, "commute": 11.0, "station_access": 2.0, "convenience": 33.7, "quiet": 1.0},
    "norm": {...}, "flags": ["예산 안 거래 26/69건"], "estimated": [],
    "cost": {"monthly_total": 61.0, "median_deposit": 1000, "median_rent": 55, "fare_month": 6.8, "samples": 69},
    "commute": {"min": 11, "fare": 1550, "transfers": 0, "mode": "지하철", "lines": ["수인분당선"], "map_url": "https://map.kakao.com/..."},
    "station": {"name": "이매역", "lines": [...], "dist_m": 120, "walk_min": 2},
    "convenience": {"편의점": 8, "약국": 3, "대형마트": 1}, "bars": {"count": 1, "source": "..."}
  }],
  "excluded": [ /* 같은 형식 + violations[{constraint, severity, relax_to, ...}] */ ],
  "near_misses": ["dong_code", ...],
  "scatter": [{"dong_code": "...", "name": "...", "rank": 1, "x": 61.0, "y": 11.0, "pareto": true, "estimated": false}],
  "weights": {...}, "levels": {...}, "constraints": {...}, "bounds": {...},
  "diff": null | {"moves": [...], "overtakes": [{"a": {...}, "b": {...}, "gap_before": -1.42, "gap_after": 2.02, "by_factor": {"월 총비용": 2.56, ...}}], "weight_change": {...}, "entered": [], "dropped": []},
  "tradeoffs": [{"factors": ["생활 편의", "조용함"], "correlation": -0.62, "message": "...", ...}],
  "notes": [], "sources": {...}, "rent_period": "202511~202610", "labels": {...}
}
```

## 4. 운영

- CORS: `http://localhost:5173` (Vite 개발 서버)
- 배포: 백엔드와 빌드된 프론트를 한 서버에. SQLite·캐시가 남는 디스크 필요
- 미리 수집: `settings.PREWARM_DESTINATIONS`
- 실제 API 점검: `python scripts/smoke_agent.py` (판교 시나리오 3턴, 실제 호출)

## 5. 테스트

### API 요청과 세션 처리

`backend/schemas.py`에서 HTTP 요청 구조를 검증한다. 메시지는 최대 4,000자이며, 가정 비교의 배열·객체·유한한 숫자·불리언 형식을 확인한다. 조건의 의미와 범위는 기존 엔진이 계속 검증한다. 상세 오류 계약은 `api-spec.md`의 요청 검증 절을 따른다.

같은 세션의 메시지와 가정 비교는 동시에 처리하지 않는다. 처리 중에는 409를 반환하며, 다른 세션은 독립적으로 진행한다. 스트림 정리 시 요청 토큰을 확인하므로 이전 응답의 늦은 정리가 다음 요청의 잠금을 해제하지 않는다. 세션 조회 API의 기존 응답 형식과 추천 계산·AI 프롬프트는 유지한다.

`tests/test_api_contract.py`는 잘못된 형식, 메시지 길이, 400/404/409/422 구분, 가정 비교의 상태 보존, 실제 동시 요청, 오류 후 재시도, 늦은 정리의 토큰 소유권을 가짜 LLM·데이터로 검증한다. 외부 API 호출은 하지 않는다.

현재는 단일 서버 프로세스로 운영한다. 재시작 후 대화 복원, 세션 만료·삭제, 여러 워커에서 공유하는 세션·잠금은 별도 후속 작업이다. `/api/health`의 키 상태는 설정 유무이며 외부 공급자의 인증 성공이나 실제 호출 가능 여부를 보장하지 않는다.

목적지역이 같아도 회사 좌표·도보 등 목적지 정보가 달라지면 Dataset을 다시 구성한다. 역까지 통근 캐시는 재사용하되 역에서 회사까지의 도보와 화면 목적지 정보는 새로 반영한다. 목적지 변경 전후에는 순위 변동 비교를 하지 않는다.

가정 질문에서 불러온 Dataset은 확정 세션에 저장하지 않는다. 수집 결과가 비거나 처리 중 예외가 발생하면 `error`와 `done` 이벤트로 종료하고 기존 확정 결과를 유지한다.

회귀 테스트: 같은 역의 다른 회사로 변경, 다른 목적지 가정 후 현재 조건 재계산, 빈 후보 데이터, 목적지 API 실패를 포함한다. 전체 실행은 `python -m unittest discover -s tests -v`.

`tests/test_backend.py` (가짜 LLM·가짜 데이터, 네트워크 없음, 9개)
- 비교 순서 교정, 설명 숫자 검사, 파레토
- 목적지 없으면 되묻기 / 모르는 목적지 되묻기
- 2턴 대화: 결과·순위 변동·같은 목적지 재사용·숫자 검사 실패 시 템플릿 대체·확인 불가 조건 안내
- 가정 질문은 상태를 바꾸지 않음
- API: 세션 생성 → 메시지 → 이벤트 스트림 → 세션 조회
