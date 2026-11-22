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

## 6. 의도별 처리와 답변 형식 (2026-11-22)

조건이 바뀌지 않는 발화는 순위를 다시 계산하지 않는다 (`backend/agent.py`).

| 발화 | 판단 | 처리 | 응답 |
|---|---|---|---|
| 인사·감사·확인 ("고마워요", "좋아") | intent `smalltalk`·`confirm`, 조건 변경 없음 | LLM·엔진 호출 없음 (`presenter.short_reply`) | 짧은 한 문장, 로그 step `reply` |
| 지금 결과에 대한 질문 ("정자동은 왜 없어?", "1위랑 2위 차이는?", "그 동네 치안은?") | 조건 변경 없음 + 결과 있음 | 지금 결과로 답변 (`Agent._answer`), 순위 재계산 없음 | 1~4문장 (`prompts.ANSWER_SYSTEM`), 로그 step `answer` |
| 조건 변경·가정 | 조건 필드가 하나라도 있음 | 기존 전체 흐름 | 6줄 이하로 정리 (`prompts.EXPLAIN_SYSTEM`) |

- **질문한 동네 찾기** (`presenter.find_targets`): LLM 이 뽑은 `mentioned_dongs`·`mentioned_ranks` + 발화를 코드로 훑어 찾은 동 이름. 통과한 동과 **제외된 동 모두** 대상. "그 동네·거기·두 곳"처럼 다시 가리키면 직전 답변의 동네를 이어받는다
- **LLM 이 보는 정보 확대**
  - 조건 추출: 현재 상태 + `후보_동네`(이름 목록) + `현재_상위`(1~5위) + `최근_대화`(4개)
  - 질문 답변(`presenter.answer_facts`): 현재 조건, 순위 요약(10위까지), 제외 요약(이유 포함), 질문한 동네 상세(순위 또는 제외 이유·완화 조건, 요인별 점수, 비용 구성, 통근 노선, 역, 편의·주점), 코드가 계산한 비교, 확인 방법, 데이터 출처·기간, 최근 대화(6개)
- **차이 계산은 코드가** (`presenter.compare_items`): 두 동의 점수·월 총비용·월세·보증금·교통비·통근·역 도보·주점 수의 차이와 유리한 쪽. LLM 은 이 값만 쓰고, 숫자 검사는 그대로
- **구할 수 없는 정보의 확인 방법** (`backend/guides.py`): 치안·관리비·보증금 안전·소음·채광·이웃·반려동물·주차·침수·학교·실제 매물에 대해 공공 사이트(생활안전지도, 인터넷등기소, HUG, 세움터, 학교알리미, K-apt)와 현장 확인 요령을 코드에 고정. 발화나 '확인 불가' 항목의 키워드로 골라 답변과 화면에 함께 넘긴다 (LLM 이 지어내지 않음)
- **화면 자료** (`message.attachments`): 답변 아래에 동네 요약 표(두 곳이면 항목별 비교와 유리한 쪽), 확인 방법 목록. "지도에서 보기"로 해당 동을 지도에서 선택

### 6.1 확인 방법 확대·숫자 단위·화면 연동 (2026-11-22 추가)

- **확인 방법**: 매물 키워드 확대("나와 있는 방", "방 보여줘" 등), 인터넷 안내 추가. 조건 추출 스키마에 `outside_topics`(우리 데이터로 답할 수 없는 주제어) 추가 → 정해 둔 안내가 없는 주제는 "카카오맵에서 '{동네} {주제}' 검색" 기본 안내(링크 포함)
- **숫자 단위** (`presenter.by_unit`): 분·곳·개·건·회·원은 정수, 만원·점은 소수 첫째 자리. facts·화면 자료·비교 차이 모두 적용하고, 프롬프트에 "`.0` 은 떼고 쓴다" 규칙 추가 (숫자 검사는 61.0과 61을 같은 수로 본다)
- **화면 연동** (`presenter.focus_for` → `message.focus`): 두 곳 이상·비교 질문 → '후보 비교' 탭에 그 동네들 / 통근·비용 질문 → '비용·통근' 산점도에서 강조 / 한 곳 → 지도에서 선택. 대상 동네가 없으면 화면은 그대로
- **대화창 비교 차트**: 비교 자료에 `factors`(두 동네의 요인별 점수, 합 = 총점) → 막대 차트
