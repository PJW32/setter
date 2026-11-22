# ERD (데이터 모델)

저장소는 두 가지다.

| 구분 | 위치 | 수명 | 내용 |
|---|---|---|---|
| **영속 저장소** | SQLite `data/store.sqlite` (`backend/store.py`) | 서버를 다시 켜도 남음 | 수집한 시군구·법정동·실거래·통근 |
| **세션 메모리** | 서버 프로세스 메모리 (`backend/agent.py: Session`) | 서버를 다시 켜면 사라짐 | 대화 상태(단계·필수 조건·목적지), 메시지, 마지막 결과 |

외부 API 응답 캐시(`data/cache/<출처>/<해시>.json|xml`)는 파일 저장소로, 모델에는 포함하지 않는다.

## 1. 영속 저장소 (SQLite)

```mermaid
erDiagram
    SGG ||--o{ DONG : "포함한다"
    SGG ||--o{ DEAL : "수집 단위"
    DONG ||--o{ DEAL : "거래가 있다"
    DONG ||--o{ COMMUTE : "목적지역별 통근"

    SGG {
        TEXT code PK "시군구 코드 5자리 (법정동코드 앞 5자리), 예 41135"
        TEXT sido "시도, 예 경기도"
        TEXT name "시군구, 예 성남시 분당구"
        TEXT status "done | error"
        INTEGER dong_count "수집한 법정동 수"
        INTEGER deal_count "수집한 실거래 수"
        TEXT collected_at "수집 시각 ISO8601"
        TEXT error "실패 사유 (status=error)"
    }
    DONG {
        TEXT code PK "법정동 코드 10자리, 예 4113510300"
        TEXT sgg_code FK "SGG.code"
        TEXT data "동 레코드 JSON (아래 1.2)"
    }
    DEAL {
        TEXT dong_code FK "DONG.code (매칭 실패 시 저장 안 함)"
        TEXT sgg_code FK "SGG.code"
        TEXT house_type "오피스텔 | 단독다가구 | 연립다세대"
        REAL area_m2 "면적 ㎡"
        TEXT area_kind "전용 | 계약 (단독다가구)"
        REAL deposit "보증금 만원"
        REAL monthly_rent "월세 만원 (0 = 전세)"
        TEXT deal_ym "계약년월 YYYYMM"
        TEXT contract_kind "신규 | 갱신 | 빈값"
    }
    COMMUTE {
        TEXT dong_code PK, FK "DONG.code"
        TEXT dest_key PK "목적지역 이름, 예 판교역"
        TEXT data "통근 JSON (아래 1.3)"
    }
```

| 테이블 | 키·인덱스 | 쓰기 시점 | 규모 (판교역 주변 13개 시군구 기준) |
|---|---|---|---|
| `sgg` | PK `code` | 시군구 수집 완료·실패 시 | 13행 |
| `dong` | PK `code`, 인덱스 `sgg_code` | 시군구 수집 완료 시 (시군구 단위로 지우고 다시 넣음) | 302행 |
| `deal` | 인덱스 `dong_code` | 시군구 수집 완료 시 | 132,076행 |
| `commute` | PK (`dong_code`, `dest_key`) | 새 목적지역의 후보 동 통근 계산 시 | 71행 (목적지 1곳) |

- `DESTINATION`(목적지역)은 테이블이 아니다. 통근의 `dest_key`(역 이름)로만 쓴다. 회사·동네 이름은 가장 가까운 역으로 바뀌어 같은 키를 공유한다
- 시군구 수집은 시군구 단위로 잠금을 걸어 같은 시군구를 두 번 수집하지 않는다

### 1.1 실거래 기간과 필터

- 기간: `settings.RENT_END_YM`(202610)에서 12개월. 마감 후 고정
- 저장은 전부(전세·갱신·큰 면적 포함), 필터는 엔진이 `Params` 로 한다

### 1.2 `DONG.data` JSON

| 필드 | 타입 | 예 | 설명 |
|---|---|---|---|
| `dong_code` | string | `4113510300` | = `DONG.code` |
| `sido`, `sgg`, `name` | string | 경기도, 성남시 분당구, 정자동 | |
| `lon`, `lat` | number | 127.11, 37.36 | 대표 지점 (생활 중심) |
| `point_source` | string | 생활 중심 (…) | 대표 지점을 정한 방법 |
| `area_km2_est` | number | 5.44 | 격자점 수 × 0.16㎢ |
| `station` | object \| null | `{name, lines[], dist_m, walk_min, lon, lat}` | 가장 가까운 지하철역. 3km 안에 없으면 null |
| `convenience` | object | `{"편의점": 21, "약국": 9, "대형마트": 6}` | 반경 안 개수 |
| `bars` | object | `{count, source}` | 반경 500m 주점 수와 출처 |

### 1.3 `COMMUTE.data` JSON

| 필드 | 타입 | 예 | 설명 |
|---|---|---|---|
| `min` | number | 15 | 대표 지점 → 목적지역 분 (역 → 회사 도보는 엔진에 넘길 때 더함) |
| `fare` | number \| null | 1550 | 편도 요금 원 |
| `transfers` | number | 0 | 환승 횟수 |
| `walk_min` | number | 4 | 경로 안 도보 분 |
| `mode` | string | 지하철 | 지하철 / 버스 / 버스+지하철 / 도보 |
| `lines` | string[] | [수인분당선] | 노선 |
| `map_url` | string | https://map.kakao.com/… | 카카오맵 경로 링크 |
| `error` | string | NO_RESULTS | 경로가 없을 때만 |

## 2. 세션 메모리 (대화 상태)

```mermaid
erDiagram
    SESSION ||--|| STATE : "현재 상태"
    SESSION ||--o| DESTINATION : "목적지"
    SESSION ||--o{ MESSAGE : "대화"
    SESSION ||--o| RESULT : "마지막 순위"
    STATE ||--|| CONSTRAINTS : "필수 조건"
    STATE ||--|| PARAMS : "비교 기준"
    STATE ||--o{ HISTORY : "변경 이력"

    SESSION {
        string id PK "12자리 hex"
        float created
        string ds_key "불러온 데이터의 목적지역 (같으면 재사용)"
        string last_question "직전 되묻기 (다음 발화 해석에 사용)"
    }
    STATE {
        map levels "요인 → 단계 (매우 중요·중요·보통·조금·상관없음)"
    }
    CONSTRAINTS {
        number max_deposit "만원"
        number max_monthly_rent "만원"
        number max_commute_min "분"
        number max_monthly_cost "만원"
    }
    PARAMS {
        string destination "목적지역 = COMMUTE.dest_key"
        list house_types "기본 오피스텔, 단독다가구"
        number max_area_m2 "기본 33"
        bool new_contracts_only "기본 true"
        number conversion_rate "0.05"
        int work_days "22"
        int min_samples "5"
    }
    DESTINATION {
        string key "목적지역 이름"
        string label "화면 표시"
        string query "사용자가 말한 이름"
        string place_name
        number lon "도착 역 좌표"
        number lat
        int walk_from_station_min "역 → 장소 도보"
        list alternatives "검색 후보 3개"
    }
    MESSAGE {
        string role "user | assistant"
        string text
        string source "llm | template (assistant)"
    }
    HISTORY {
        string utterance
        list applied "반영된 변경"
        list rejected "버린 변경과 이유"
        object state "변경 후 상태 스냅샷"
    }
    RESULT {
        list ranked "통과한 동 (순위, 점수, 기여도, 원값, 플래그)"
        list excluded "제외된 동 (위반 조건, 완화 제안)"
        list near_misses
        map weights
        map bounds "정규화 구간"
    }
```

## 3. 엔진 입력 (메모리 객체)

| 객체 | 정의 | 만드는 곳 |
|---|---|---|
| `Dataset` | `dongs`(동 레코드 + `commute: {목적지역: COMMUTE.data}`), `deals_by_dong`(동 코드 → `Deal[]`), `meta` | `backend/regions.py: build_dataset` (SQLite → 반경 안 동만) |
| `Deal` | `DEAL` 한 행 | 위와 같음 |
| `DongFeature` | 동별 요인 원값 + 상세 + 조건에 맞는 거래 비용 목록 | `engine/features.py: build_features` |
