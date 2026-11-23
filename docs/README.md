# 첫동네 — 문서 목차

> 낯선 도시로 가는 청년이 자연어로 생활 조건을 말하면, 매물이 아니라 "살 동네"를 근거 있는 숫자로 추천하는 AI 에이전트.
> 2026 대한민국 청년 CAREER FAIR AI 해커톤 출품용. 기획 원문은 루트의 `hackathon-handoff.md`.

| 문서 | 내용 |
|---|---|
| [licenses.md](licenses.md) | 외부 패키지 라이선스, React Leaflet 별도 조건, 배포 원문 고지와 갱신 방법 |
| [feature-spec.md](feature-spec.md) | 기능 명세서: 화면 구성, 기능 목록(F-01~18), 기능별 수용 기준, 비기능 요구사항 |
| [api-spec.md](api-spec.md) | API 명세서: 엔드포인트, 요청·응답, 이벤트 스트림 형식, 타입 정의 |
| [erd.md](erd.md) | ERD: SQLite 테이블, JSON 필드, 세션 메모리 모델 |
| [response-format.md](response-format.md) | 에이전트 응답 형식: 응답 종류별 길이·구조·예시, 숫자 표기, 숫자 검사, 함께 보내는 자료와 화면 연동, 모르는 정보 대응, 고칠 곳 |
| [engine.md](engine.md) | 추천 모델(점수 엔진): 요인, 가중치 단계, 필수 조건, 정규화, 데이터 부족 처리, 순위 변동 분해, 대화 상태 |
| [data.md](data.md) | 데이터: 출처, 수집 방식(실시간 지역 수집), 저장 형태, 한도, 한계 |
| [data-prewarm.md](data-prewarm.md) | 사전 수집 명령, 로컬 저장 상태, 결과 보고서, 부분 실패와 배포 시 데이터 유지 |
| [public-data-snapshot.md](public-data-snapshot.md) | 공공 상가 원본의 지역별 SQLite 구축, 출처·누락 검사, 추천 연결 전 검증 |
| [backend.md](backend.md) | 백엔드: 구조, 에이전트 한 턴의 흐름, API·이벤트 형식(프론트엔드용), LLM 사용과 검증 |
| [render-deploy.md](render-deploy.md) | Render 무료 심사용 배포, 접속 인증, 대화 접근 제한, 비밀값 설정과 검증 |
| [mvp-test-scenarios.md](mvp-test-scenarios.md) | MVP 테스트 시나리오: 시연 대본, 발화 테스트 세트, 예외 상황, 통과 기준 |
| [data-sources.md](data-sources.md) | (조사 기록) API 명세 확인 과정과 실제 응답 확인 결과 |

## 빠른 시작

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env      # 키 4개 입력 (아래)
python config.py                 # 키 설정 여부 확인 (값은 출력 안 함)
python -m unittest discover -s tests -v
python -m uvicorn backend.main:app --reload --port 8000

# 프론트엔드 (React + Vite, 다른 터미널)
npm --prefix frontend install
npm --prefix frontend run dev      # http://localhost:5173 (/api 는 8000 으로 프록시)
npm --prefix frontend run build    # frontend/dist → FastAPI 가 http://localhost:8000 에서 함께 제공
```

| 키 | 필수 | 용도 |
|---|---|---|
| `KAKAO_REST_API_KEY` | 필수 | 동 목록·대표 지점·역·편의시설·통근(대중교통 경로). 카카오맵 사용 설정 ON |
| `GEMINI_API_KEY` | 필수 | 조건 추출·결과 설명. Agent Platform(Vertex)용 키 → 코드는 `vertexai=True` |
| `DATA_GO_KR_SERVICE_KEY` | 필수(월세) | 전월세 실거래가, 상가정보(주점). 인코딩·디코딩 키 모두 가능 |
| `ODSAY_API_KEY` | 선택 | 통근 교차 확인용 (무료 한도 하루 약 30건) |

## 폴더 구조

```
engine/       점수 엔진 (LLM·API 없음, 지역 무관)
backend/      FastAPI, 에이전트 흐름, Gemini, 지역 수집·저장(SQLite)
collectors/   외부 API 클라이언트 (카카오, 국토부, 상가정보, ODsay) + 응답 캐시
scripts/      수집·시연·점검 스크립트
tests/        단위 테스트 (가상 지역, 네트워크 없음)
frontend/     React(Vite, TypeScript) 화면: 대화·해석 카드·지도(Leaflet/OSM)·순위표·산점도(Recharts)·비교·순위 변동·작업 노선도
data/         dongs.json·rent_deals.csv(초기 수집본), store.sqlite(실시간 수집 저장소), cache/
docs/         문서
```
