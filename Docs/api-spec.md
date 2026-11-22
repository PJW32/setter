# API 명세서

- 서버: FastAPI (`backend/main.py`), 기본 `http://localhost:8000`
- 모든 경로는 `/api` 로 시작한다. 빌드된 프론트(`frontend/dist`)는 같은 서버의 `/` 에서 제공한다
- 요청·응답 본문은 JSON (UTF-8). 메시지 전송만 **이벤트 스트림**(`text/event-stream`)으로 응답한다
- 인증 없음 (해커톤 MVP). 외부 API 키는 서버만 갖는다
- 금액 단위는 **만원**, 시간은 **분**, 요금(`fare`)만 **원**
- 개발 중 CORS 허용: `http://localhost:5173`, `http://127.0.0.1:5173`

## 목록

| # | 메서드 | 경로 | 설명 |
|---|---|---|---|
| 1 | GET | `/api/health` | 서버·키·저장소 상태 |
| 2 | GET | `/api/meta` | 요인·단계 목록, 수집된 시군구 |
| 3 | POST | `/api/sessions` | 대화 세션 만들기 |
| 4 | GET | `/api/sessions/{session_id}` | 세션 상태·대화·마지막 결과 |
| 5 | POST | `/api/sessions/{session_id}/messages` | 발화 보내기 → 이벤트 스트림 |
| 6 | POST | `/api/sessions/{session_id}/what-if` | 가정 비교 (상태 안 바뀜) |

## 오류

| 상태 | 언제 | 본문 |
|---|---|---|
| 400 | 빈 메시지, 순위가 없는데 what-if | `{"detail": "빈 메시지"}` |
| 404 | 없는 세션 (서버 재시작 포함) | `{"detail": "세션이 없습니다"}` → 프론트는 새 세션을 만든다 |
| 409 | 같은 세션의 메시지 또는 가정 비교가 처리 중 | `{"detail": "이 대화의 이전 요청을 처리 중입니다. 완료 후 다시 시도해 주세요."}` |
| 422 | 본문 형식 오류 | FastAPI 기본 검증 오류 |

이벤트 스트림 도중의 오류는 HTTP 상태가 아니라 `error` 이벤트로 온다.

메시지와 가정 비교는 세션 단위로 하나씩 처리한다. 중복 요청은 대기열에 넣지 않고 409로 반환하며, 다른 세션은 독립적으로 처리한다. 정상 완료와 오류 종료 후에는 재요청할 수 있다. 세션과 진행 중 요청 정보가 프로세스 메모리에 있으므로 현재 구성은 단일 서버 프로세스를 전제로 한다.

### 요청 검증

- `messages.text`: 문자열, 최대 4,000자. 누락·null·숫자·길이 초과는 422, 빈 문자열·공백만 있는 입력은 400이다.
- `what-if.changes`: 객체. 허용 필드는 `set_constraints`, `clear_constraints`, `params`, `preference_changes`다. 알 수 없는 최상위 변경 필드는 422다.
- `set_constraints`: 조건 이름 → 유한한 JSON 숫자 또는 null. 숫자 문자열·불리언은 422다. null은 변경하지 않음을 의미하며, 해제는 `clear_constraints`로 요청한다.
- `clear_constraints`: 문자열 배열.
- `params`: `destination`(문자열), `house_types`(문자열 배열), `max_area_m2`(유한한 JSON 숫자), `new_contracts_only`(불리언). 필드는 선택이며 null은 변경하지 않는다. 알 수 없는 필드는 422다.
- `preference_changes`: `{factor: 문자열, level: 문자열, evidence?: 문자열 | null}` 객체 배열.
- 형식이 맞아도 지원하지 않는 요인·한도 범위는 기존 엔진의 `report.rejected`로 반환한다. HTTP 형식 검증은 `backend/schemas.py`가 담당한다.

---

## 1. GET `/api/health`

```json
{
  "ok": true,
  "keys": {"GEMINI_API_KEY": true, "DATA_GO_KR_SERVICE_KEY": true, "KAKAO_REST_API_KEY": true, "ODSAY_API_KEY": true},
  "store": {"sgg": 13, "dong": 302, "deal": 132076, "commute": 71}
}
```
`keys` 는 설정 여부만 준다 (값은 절대 응답하지 않는다).

## 2. GET `/api/meta`

```json
{
  "factors": [
    {"key": "monthly_cost", "label": "월 총비용", "better": "low", "unit": "만원", "description": "월세 + 보증금 × 환산이율 ÷ 12 + 월 교통비 (실거래 중앙값)"},
    {"key": "commute", "label": "통근 시간", "better": "low", "unit": "분", "description": "..."},
    {"key": "station_access", "label": "역 접근성", "better": "low", "unit": "분", "description": "..."},
    {"key": "convenience", "label": "생활 편의", "better": "high", "unit": "점", "description": "..."},
    {"key": "quiet", "label": "조용함", "better": "low", "unit": "개", "description": "..."}
  ],
  "levels": ["매우 중요", "중요", "보통", "조금", "상관없음"],
  "regions": [{"code": "41135", "sido": "경기도", "name": "성남시 분당구", "status": "done", "dong_count": 18, "deal_count": 12971, "collected_at": "2026-11-21T14:02:11", "error": null}]
}
```

## 3. POST `/api/sessions`

본문 없음. 응답은 4번과 같은 `SessionView` (새 세션이라 `messages: []`, `result: null`, `state.destination: null`).

## 4. GET `/api/sessions/{session_id}`

```ts
interface SessionView {
  session_id: string;
  state: StateSnapshot;
  messages: {role: "user" | "assistant"; text: string; source?: "llm" | "template"}[];
  result: ResultPayload | null;   // 마지막 순위 (diff 는 null)
}

interface StateSnapshot {
  levels: Record<FactorKey, Level>;
  constraints: Partial<Record<"max_deposit" | "max_monthly_rent" | "max_commute_min" | "max_monthly_cost", number>>;
  params: {destination: string; house_types: string[]; max_area_m2: number; new_contracts_only: boolean;
           conversion_rate: number; work_days: number; min_samples: number};
  destination: Destination | null;
}

type FactorKey = "monthly_cost" | "commute" | "station_access" | "convenience" | "quiet";
type Level = "매우 중요" | "중요" | "보통" | "조금" | "상관없음";

interface Destination {
  key: string;                 // 목적지역 이름 (통근 키)
  label: string;               // "카카오판교아지트 (가까운 역: 판교역)"
  query: string;               // 사용자가 말한 이름
  place_name: string; place_lon: number; place_lat: number;
  lon: number; lat: number;    // 도착 역 좌표
  walk_from_station_min: number;
  station_lines: string[];
  alternatives: string[];      // 검색 후보 3개 (다른 곳이면 사용자가 고쳐 말함)
}
```

## 5. POST `/api/sessions/{session_id}/messages`

요청
```json
{"text": "판교역으로 출근해요. 보증금 1000에 월세 60 넘으면 안 되고, 싼 게 제일 중요해요."}
```

응답: `Content-Type: text/event-stream`. 이벤트마다
```
event: <type>
data: <JSON 한 줄>

```
POST 라서 `EventSource` 를 쓸 수 없다. `fetch` 로 `response.body` 를 읽어 빈 줄(`\n\n`)로 나눈다 (예시 코드: [backend.md](backend.md) 3.1).

### 이벤트 순서

```
log(extract) → [log(destination)] → interpretation →
  [log(region) → log(collect)* → log(commute) → log(dataset)]   ← 목적지가 바뀌었을 때
  → log(score) → [log(tradeoff)] → result → log(explain) → message → done
```
목적지가 없으면 `interpretation → message(되묻기) → done` 으로 끝난다. 처리 중 예외는 `error` 다음 `done`.

### 이벤트 형식

```ts
type AgentEvent =
  | {type: "log"; t: number; step: LogStep; status: "running" | "done" | "warn" | "error"; detail: string; ms?: number}
  | {type: "interpretation"; t: number; intent: Intent; what_if: boolean;
     applied: Applied[]; rejected: Rejected[]; unsupported: string[];
     comparisons: {more: FactorKey; less: FactorKey; evidence: string}[]; comparison_fixes: string[];
     destination: Destination | null; follow_up: string | null; state: StateSnapshot}
  | {type: "result"; t: number; what_if: boolean; payload: ResultPayload}
  | {type: "message"; t: number; text: string; source: "llm" | "template"}
  | {type: "error"; t: number; detail: string}
  | {type: "done"; t: number};

type LogStep = "extract" | "destination" | "region" | "collect" | "commute" | "dataset" | "score" | "tradeoff" | "explain";
type Intent = "update" | "what_if" | "question" | "confirm" | "other";

interface Applied {
  type: "constraint" | "param" | "preference";
  key: string;                     // 조건 키, 파라미터 키, 또는 요인 키
  label?: string;                  // preference 일 때 요인 이름
  before: unknown; after: unknown; // 조건 해제면 after = null
  evidence?: string;               // preference 일 때 근거 원문
}
interface Rejected {item: string; reason: string; supported?: string[]}
```

| step | 뜻 |
|---|---|
| `extract` | Gemini 조건 추출 (`ms` 포함) |
| `destination` | 목적지 검색·역 붙이기 |
| `region` | 후보 시군구 찾기 |
| `collect` | 시군구 수집 (시군구마다 running 여러 번 → done/error) |
| `commute` | 후보 동 → 목적지역 통근 계산 |
| `dataset` | 후보 동·실거래 불러오기 |
| `score` | 엔진 순위 계산 |
| `tradeoff` | 상충 감지 (있을 때만, status=warn) |
| `explain` | Gemini 설명 + 숫자 검사 (실패 시 warn, 템플릿 설명) |

### `ResultPayload`

```ts
interface ResultPayload {
  destination: Destination;
  universe_size: number;                 // 후보 동 수 (목적지 반경 10km)
  ranked: DongCard[];                    // 통과한 동, 순위순
  excluded: DongCard[];                  // 제외된 동 (violations 포함), 덜 어긋난 순
  near_misses: string[];                 // 통과가 3곳 미만일 때, 조금 풀면 들어오는 동 코드
  scatter: {dong_code: string; name: string; rank: number; x: number | null; y: number | null;
            pareto: boolean; estimated: boolean}[];   // x 월 총비용(만원), y 통근(분)
  weights: Record<FactorKey, number>;    // 합 1
  levels: Record<FactorKey, Level>;
  constraints: StateSnapshot["constraints"];
  bounds: Record<FactorKey, [number, number]>;   // 정규화 구간 (5~95 백분위)
  notes: string[];
  diff: Diff | null;                     // 같은 목적지에서 이전 결과가 있을 때
  tradeoffs: Tradeoff[];
  sources: Record<string, string>;       // 화면 하단 출처 표기
  rent_period: string;                   // "202511~202610"
  labels: Record<FactorKey, string>;
}

interface DongCard {
  dong_code: string; name: string; sgg: string; sido: string; lon: number; lat: number;
  rank: number | null; score: number;                       // 0~100
  contrib: Record<FactorKey, number>;                       // 요인별 기여 점수, 합 = score
  raw: Record<FactorKey, number | null>;                    // 원값 (월 총비용은 예산 안 거래 기준일 수 있음)
  norm: Record<FactorKey, number>;                          // 0~1
  flags: string[];                                          // "예산 안 거래 26/69건", "월 총비용 데이터 부족" …
  estimated: FactorKey[];                                   // 데이터가 없어 중앙값으로 채운 요인
  cost: {monthly_total: number | null; median_deposit: number | null; median_rent: number | null;
         fare_month: number | null; samples: number};
  commute: {min?: number; fare?: number; transfers?: number; mode?: string; lines?: string[];
            map_url?: string; error?: string};
  station: {name: string | null; lines?: string[]; dist_m?: number; walk_min?: number; note?: string};
  convenience: Record<string, number>;
  bars: {count?: number; source?: string};
  violations: Violation[] | null;                           // excluded 에만
}

interface Violation {
  constraint: "budget" | "commute" | "monthly_cost";
  severity: number;                      // 한도의 몇 배인지 (1 초과)
  relax_to: Partial<StateSnapshot["constraints"]>;   // 이만큼 풀면 들어옴
  in_budget?: number; samples?: number; value?: number; limit?: number;
}

interface Diff {
  moves: {dong_code: string; name: string; prev_rank: number | null; cur_rank: number | null; change: number | null}[];
  overtakes: {a: {dong_code: string; name: string}; b: {dong_code: string; name: string};
              gap_before: number; gap_after: number; by_factor: Record<string, number>}[];  // 요인 이름 → 격차 변화
  weight_change: Record<string, number>;
  entered: string[]; dropped: string[];
}

interface Tradeoff {factors: [string, string]; correlation: number; message: string; [k: string]: unknown}
```

## 6. POST `/api/sessions/{session_id}/what-if`

대화 없이 조건만 바꿔 본다 (예: 화면의 "통근 한도 60분이면?" 버튼). 세션 상태는 바뀌지 않는다.

요청 (변경분 형식은 [engine.md](engine.md) 9절)
```json
{"changes": {"set_constraints": {"max_commute_min": 60}}}
```

응답
```ts
{report: {applied: Applied[]; rejected: Rejected[]}; payload: ResultPayload}   // payload.diff = 현재 결과 대비
```
순위가 아직 없으면 400.

## 예시: curl

```powershell
$s = Invoke-RestMethod -Method Post http://localhost:8000/api/sessions
curl.exe -N -X POST "http://localhost:8000/api/sessions/$($s.session_id)/messages" -H "Content-Type: application/json" -d '{\"text\": \"판교역으로 출근해요\"}'
```

## 7. 2026-11-22 추가: 의도별 답변과 화면 자료

- `intent` 에 `smalltalk`(인사·감사) 추가. 조건 변경이 없으면 `interpretation`·`result` 이벤트 없이 `log` → `message` → `done`
- `LogStep` 에 `reply`(짧은 대답), `answer`(지금 결과로 답변) 추가
- `interpretation.guides?: Guide[]` (확인 불가 항목의 확인 방법)
- `message.attachments?: Attachment[]`, `SessionView.messages[].attachments?` (세션을 다시 불러와도 남음)

```ts
interface Guide {topic: string; how: string; links: {label: string; url: string}[]}
interface AttachmentRow {
  dong_code: string; name: string; sgg: string; status: string;   // "3위" | "조건 밖"
  excluded: boolean; score: number | null; monthly_cost: number | null; commute: number | null;
  station_walk: number | null; bars: number | null; reason: string | null;  // 제외 이유
}
interface CompareItem {label: string; unit: string; a: number | null; b: number | null;
  diff: number | null;       // A − B
  abs_diff: number | null; better: string | null}   // 유리한 동 이름 (같으면 null)
type Attachment =
  | {kind: "dongs"; title: string; rows: AttachmentRow[]; compare?: {a: string; b: string; items: CompareItem[]}}
  | {kind: "guides"; title: string; items: Guide[]};
```

### 7.1 2026-11-22 추가

- `message.focus?: {tab: "map" | "compare" | "tradeoff"; dong_codes: string[]} | null` — 답변에 맞춰 오른쪽 화면을 옮기는 지시
- `compare.factors?: {key: FactorKey; label: string; a: number; b: number}[]` — 두 동네의 요인별 점수 (대화창 막대 차트)
- `Guide.default?: true` — 정해 둔 안내가 없는 주제의 기본 안내 (카카오맵 검색 링크)
- 숫자 단위: `commute`, `station_walk`, `bars`, 비교 항목의 분·곳 값은 정수
