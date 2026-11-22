// API 명세서와 백엔드 응답에 대응하는 화면 타입
export interface SessionView {
  session_id: string;
  state: StateSnapshot;
  messages: {role: "user" | "assistant"; text: string; source?: "llm" | "template"; attachments?: Attachment[]}[];
  result: ResultPayload | null;   // 마지막 순위 (diff 는 null)
}

export interface StateSnapshot {
  levels: Record<FactorKey, Level>;
  constraints: Partial<Record<"max_deposit" | "max_monthly_rent" | "max_commute_min" | "max_monthly_cost", number>>;
  params: {destination: string; house_types: string[]; max_area_m2: number; new_contracts_only: boolean;
           conversion_rate: number; work_days: number; min_samples: number};
  destination: Destination | null;
}

export type FactorKey = "monthly_cost" | "commute" | "station_access" | "convenience" | "quiet";
export type Level = "매우 중요" | "중요" | "보통" | "조금" | "상관없음";

export interface Destination {
  key: string;                 // 목적지역 이름 (통근 키)
  label: string;               // "카카오판교아지트 (가까운 역: 판교역)"
  query: string;               // 사용자가 말한 이름
  place_name: string; place_lon: number; place_lat: number;
  lon: number; lat: number;    // 도착 역 좌표
  walk_from_station_min: number;
  station_lines: string[];
  alternatives: string[];      // 검색 후보 3개 (다른 곳이면 사용자가 고쳐 말함)
}

export type AgentEvent =
  | {type: "log"; t: number; step: LogStep; status: "running" | "done" | "warn" | "error"; detail: string; ms?: number}
  | {type: "interpretation"; t: number; intent: Intent; what_if: boolean;
     applied: Applied[]; rejected: Rejected[]; unsupported: string[];
     comparisons: {more: FactorKey; less: FactorKey; evidence: string}[]; comparison_fixes: string[];
     guides?: Guide[];
     destination: Destination | null; follow_up: string | null; state: StateSnapshot}
  | {type: "result"; t: number; what_if: boolean; payload: ResultPayload}
  | {type: "message"; t: number; text: string; source: "llm" | "template"; attachments?: Attachment[]; focus?: Focus | null}
  | {type: "error"; t: number; detail: string}
  | {type: "done"; t: number};

export type LogStep = "extract" | "reply" | "answer" | "destination" | "region" | "collect" | "commute" | "dataset" | "score" | "tradeoff" | "explain";
export type Intent = "update" | "what_if" | "question" | "confirm" | "smalltalk" | "other";

/** 데이터로 구할 수 없는 정보를 직접 확인하는 방법 */
export interface Guide {topic: string; how: string; links: {label: string; url: string}[]}

/** 답변과 함께 대화창에 보여주는 자료 */
export interface AttachmentRow {
  dong_code: string; name: string; sgg: string; status: string; excluded: boolean;
  score: number | null; monthly_cost: number | null; commute: number | null; station_walk: number | null;
  bars: number | null; reason: string | null;
}
export interface CompareItem {label: string; unit: string; a: number | null; b: number | null; diff: number | null;
  abs_diff: number | null; better: string | null}
export interface FactorPoint {key: FactorKey; label: string; a: number; b: number}   // 요인별 점수, 합 = 동네 점수
export interface CompareData {a: string; b: string; items: CompareItem[]; factors?: FactorPoint[]}
export type Attachment =
  | {kind: "dongs"; title: string; rows: AttachmentRow[]; compare?: CompareData}
  | {kind: "guides"; title: string; items: Guide[]};

/** 답변에 맞춰 오른쪽 화면을 옮기는 지시 */
export interface Focus {tab: "map" | "compare" | "tradeoff"; dong_codes: string[]}

export interface Applied {
  type: "constraint" | "param" | "preference";
  key: string;                     // 조건 키, 파라미터 키, 또는 요인 키
  label?: string;                  // preference 일 때 요인 이름
  before: unknown; after: unknown; // 조건 해제면 after = null
  evidence?: string;               // preference 일 때 근거 원문
}
export interface Rejected {item: string; reason: string; supported?: string[]}

export interface ResultPayload {
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

export interface DongCard {
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
            map_url?: string; walk_from_station?: number; error?: string};
  station: {name: string | null; lines?: string[]; dist_m?: number; walk_min?: number; note?: string};
  convenience: Record<string, number>;
  bars: {count?: number; source?: string};
  violations: Violation[] | null;                           // excluded 에만
}

export interface Violation {
  constraint: "budget" | "commute" | "monthly_cost";
  severity: number;                      // 한도의 몇 배인지 (1 초과)
  relax_to: Partial<StateSnapshot["constraints"]>;   // 이만큼 풀면 들어옴
  in_budget?: number; samples?: number; value?: number; limit?: number;
}

export interface Diff {
  moves: {dong_code: string; name: string; prev_rank: number | null; cur_rank: number | null; change: number | null}[];
  overtakes: {a: {dong_code: string; name: string}; b: {dong_code: string; name: string};
              gap_before: number; gap_after: number; by_factor: Record<string, number>}[];  // 요인 이름 → 격차 변화
  weight_change: Record<string, number>;
  entered: string[]; dropped: string[];
}

export interface Tradeoff {factors: [string, string]; correlation: number; message: string; [k: string]: unknown}

export type ConstraintKey = "max_deposit" | "max_monthly_rent" | "max_commute_min" | "max_monthly_cost";
export type Interpretation = Extract<AgentEvent, {type: "interpretation"}>;
export type LogEvent = Extract<AgentEvent, {type: "log"}>;
