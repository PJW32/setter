# 외부 패키지 라이선스 고지

2026-11-23 로컬 설치 패키지의 메타데이터와 배포된 라이선스 원문을 확인했다. 버전은 확인 당시 값이며, requirements 범위 설치로 서버 버전이 달라질 수 있다. 이 문서는 전체 의존성의 법적 준수 판정이나 대회 제출 가능 여부를 보증하지 않는다.

| 패키지 | 확인 버전 | 라이선스 |
|---|---|---|
| FastAPI | 설치 버전은 원문 고지 참조 | MIT |
| Uvicorn | 0.54.0 | BSD-3-Clause |
| httpx | 0.28.1 | BSD-3-Clause |
| google-genai | 3.6.1 | Apache-2.0 |
| react-leaflet | 5.0.0 | Hippocratic-2.1 |
| @react-leaflet/core | 3.0.0 | Hippocratic-2.1 |
| Leaflet | 1.9.4 | BSD-2-Clause |

## React Leaflet의 별도 조건

`react-leaflet`을 MIT로 표기하지 않는다. 일부 이전 버전 코드의 MIT 고지가 원문에 함께 있지만 패키지 전체가 MIT라는 의미가 아니다. `@react-leaflet/core`도 Hippocratic-2.1이다.

원문은 인권 관련 법·원칙에 관한 사용 조건과 라이선스·저작권 고지 전달 조건을 포함한다. 무료라는 이유만으로 사용 목적 제한이 없는 라이선스와 동일하게 취급하지 않는다. 공식 원문: https://github.com/PaulLeCam/react-leaflet/blob/master/LICENSE.md . 제출 규정이 허용 라이선스를 한정한다면 팀에서 해당 조건을 별도 확인한다. 이 작업에서 지도 라이브러리를 교체하거나 라이브러리 코드를 수정하지 않았다.

## 원문 제공 및 갱신

### 제출 소개서 별첨 「활용한 외부 자원·출처」 기재 항목

아래는 소개서 지정 양식에 옮겨 넣을 React Leaflet 관련 항목이다. 저장소에 실제 제출 소개서 파일이 없어 이 문서에 기재 내용을 준비했다. 전체 외부 자원 목록을 대체하지 않는다.

| 외부 자원 | 활용 용도 | 출처·링크 | 라이선스 및 이용 조건 |
|---|---|---|---|
| React Leaflet 5.0.0 | React 기반 지도 표시 | [공식 저장소](https://github.com/PaulLeCam/react-leaflet), [라이선스 원문](https://github.com/PaulLeCam/react-leaflet/blob/v5.0.0/LICENSE.md) | Hippocratic-2.1. 인권 관련 법·원칙에 관한 사용 조건 및 라이선스·저작권 등 원문 고지 전달 조건 준수. 일부 이전 코드의 MIT 고지를 포함하나 전체 패키지를 MIT로 표기하지 않음. |
| @react-leaflet/core 3.0.0 | React Leaflet 지도 컴포넌트 연동 | [공식 저장소](https://github.com/PaulLeCam/react-leaflet/tree/v5.0.0/packages/core), [라이선스 원문](https://github.com/PaulLeCam/react-leaflet/blob/v5.0.0/LICENSE.md) | Hippocratic-2.1. 동일한 사용 조건 및 원문 고지 전달 조건 적용. |

라이선스·저작권 원문은 배포물의 `/third-party-notices.txt`에 포함했다. 이는 주최 측의 개별 사용 승인을 의미하지 않는다. 공식 공고(https://korcham-careerfair.com/hackathon)의 외부 자원 활용·적법한 이용 권한·출처 및 이용 조건 기재 안내를 확인했으며, 해당 공고 본문에서 OSI 승인 라이선스만 허용한다는 제한은 확인되지 않았다. 별도 세부 기준이나 운영사무국의 판단까지 확정한 것은 아니다.

[원문 고지](../frontend/public/third-party-notices.txt)에 실제 설치 패키지의 저작권·라이선스·NOTICE 파일을 복사했다. 범위는 직접 Python 의존성 4개와 npm lock의 설치된 운영 의존성이다. 모든 Python 전이 의존성이나 데이터·API·폰트 외부 조건에 관한 전체 감사로 간주하지 않는다.

Vite 빌드에서 이 파일이 `frontend/dist/third-party-notices.txt`로 복사되어 배포 후 `/third-party-notices.txt`로 제공된다. 기존 배포 인증이 활성화되면 같은 인증을 거친다. UI 표시 변경이나 AI 호출은 없다.

의존성을 변경하면 설치 후 다음 명령으로 고지를 갱신하고 변경된 원문을 검토한다. 버전 불일치 또는 라이선스 원문 누락은 오류로 처리한다. 플랫폼별 미설치 선택 의존성은 제외한다.

```bash
python -X utf8 scripts/build_license_notices.py
npm --prefix frontend run build
```

자동 Render 빌드에 생성 명령을 추가하지 않았으므로 서버 Python 설치 버전과 원문 고지의 일치 여부는 배포 의존성 갱신 때 확인해야 한다. 공개 API 데이터 이용 조건과 지도 타일 출처 표시는 패키지 라이선스와 별도로 유지한다.
