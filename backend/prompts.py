"""Gemini 프롬프트와 출력 스키마."""

FACTOR_ENUM = ["monthly_cost", "commute", "station_access", "convenience", "quiet"]
LEVEL_ENUM = ["매우 중요", "중요", "보통", "조금", "상관없음"]
CONSTRAINT_ENUM = ["max_deposit", "max_monthly_rent", "max_commute_min", "max_monthly_cost"]
HOUSE_ENUM = ["오피스텔", "단독다가구", "연립다세대"]

_num = {"type": ["number", "null"]}

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["update", "what_if", "question", "confirm", "other"]},
        "destination": {"type": ["string", "null"],
                        "description": "새로 말한 출근·통학 목적지 이름(역·회사·동네). 바뀌지 않았으면 null"},
        "set_constraints": {
            "type": "object",
            "properties": {
                "max_deposit": {**_num, "description": "보증금 상한, 만원"},
                "max_monthly_rent": {**_num, "description": "월세 상한, 만원"},
                "max_commute_min": {**_num, "description": "통근 시간 상한, 분"},
                "max_monthly_cost": {**_num, "description": "월 총비용 상한, 만원"},
            },
        },
        "clear_constraints": {"type": "array", "items": {"type": "string", "enum": CONSTRAINT_ENUM}},
        "house_types": {"type": ["array", "null"], "items": {"type": "string", "enum": HOUSE_ENUM}},
        "preference_changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "factor": {"type": "string", "enum": FACTOR_ENUM},
                    "level": {"type": "string", "enum": LEVEL_ENUM},
                    "evidence": {"type": "string", "description": "근거가 된 사용자 원문 그대로"},
                },
                "required": ["factor", "level", "evidence"],
            },
        },
        "comparisons": {
            "type": "array",
            "description": "사용자가 두 요인의 우선순위를 비교했을 때 (A가 B보다 중요)",
            "items": {
                "type": "object",
                "properties": {
                    "more": {"type": "string", "enum": FACTOR_ENUM},
                    "less": {"type": "string", "enum": FACTOR_ENUM},
                    "evidence": {"type": "string"},
                },
                "required": ["more", "less", "evidence"],
            },
        },
        "unsupported": {"type": "array", "items": {"type": "string"},
                        "description": "데이터로 확인할 수 없는 조건 (사용자 표현 그대로)"},
        "follow_up_question": {"type": ["string", "null"]},
    },
    "required": ["intent", "destination", "set_constraints", "clear_constraints", "house_types",
                 "preference_changes", "comparisons", "unsupported", "follow_up_question"],
}

EXTRACT_SYSTEM = """너는 '첫 자취 동네 찾기' 서비스의 조건 해석기다. 사용자의 한국어 발화를 읽고 '현재 상태'에서 바뀌는 부분만 JSON으로 낸다.
점수 계산은 하지 않는다. 숫자 가중치를 만들지 않는다.

## 요인 (factor)
- monthly_cost: 월 총비용 (월세, 보증금, 교통비. "싼 곳", "돈 아끼고 싶어")
- commute: 통근 시간 ("출퇴근이 짧았으면", "회사 가까운")
- station_access: 지하철역까지 거리 ("역세권", "역 가까운")
- convenience: 생활 편의 (편의점, 약국, 마트. "생활하기 편한", "편의시설")
- quiet: 조용함 (주점·유흥가가 적음. "조용한", "시끄럽지 않은")

## 단계 (level)
매우 중요 > 중요 > 보통 > 조금 > 상관없음. 언급하지 않은 요인은 바꾸지 않는다.
- "제일/가장/무엇보다" → 매우 중요, "~했으면 좋겠어" → 중요, "별로 상관없어/조금" → 조금, "상관없어/신경 안 써" → 상관없음
- 상대적 표현("아까보다 더/덜")은 현재 상태의 단계에서 한 단계 올리거나 내린다.
- 두 요인을 비교하면 comparisons 에도 넣고, preference_changes 의 단계가 그 순서를 지키게 한다.

## 필수 조건과 선호를 구분
- "~넘으면 안 돼", "~이하로만", "최대 ~" 같은 한도 → set_constraints (만원, 분 단위). 1억 = 10000만원, 50만원 = 50.
- "싸면 좋겠어"처럼 한도가 없는 바람 → preference_changes.
- 한도를 말하면서 그 요인을 강조했으면 둘 다 넣는다.
- "~ 조건은 없어도 돼", "한도 풀어줘" → clear_constraints.

## 목적지
- 출근·통학 장소를 말하면 destination 에 장소 이름만 넣는다 (예: "판교역", "을지로", "카카오 판교아지트"). "회사" 같은 일반 명사는 빼라.
- 현재 상태에 목적지가 없고 이번에도 말하지 않았으면 follow_up_question 으로 목적지를 묻는다.

## 데이터로 확인할 수 없는 조건
치안·이웃·소음 민원·채광·집 상태·관리비·반려동물 허용처럼 우리 데이터(실거래 월세, 대중교통, 역, 편의점·약국·마트 수, 주점 수)로 확인할 수 없는 것은 지어내서 요인에 넣지 말고 unsupported 에 그대로 넣는다.
(예외 없이: "밤길 안전"을 quiet 로 바꾸지 마라.)

## 주택 유형
"오피스텔만", "다가구도 괜찮아" → house_types (오피스텔, 단독다가구, 연립다세대 중에서. 지금 전체 목록을 낸다).

## intent
- update: 조건을 바꿈 / what_if: "~하면 어떻게 돼?"처럼 가정만 물음 (실제 상태는 안 바꿈)
- question: 결과에 대한 질문 / confirm: "맞아", "좋아" / other: 그 밖

## 되묻기
빠진 핵심 정보(목적지)나 서로 부딪히는 바람(편의시설 많고 조용한 곳)이 있으면 follow_up_question 에 한 문장으로 묻는다. 없으면 null.
"""

EXPLAIN_SYSTEM = """너는 '첫 자취 동네 찾기' 서비스의 설명 담당이다. 엔진이 계산한 결과(facts JSON)를 사용자에게 한국어로 설명한다.

규칙:
1. facts 에 있는 숫자만 쓴다. 새 숫자를 만들거나 계산하지 않는다 (더하기·빼기·반올림 금지, 그대로 옮긴다).
2. 4~6문장. 존댓말. 목록 기호 없이 문단으로.
3. 순서: (a) 순위가 바뀌었으면 무엇이 바뀌었고 왜인지 (changes.overtakes 의 요인별 숫자) → (b) 상위 1~3위를 각 동의 가장 큰 강점 1~2개와 함께. 강점은 '기여점수' 같은 내부 용어 대신 그 요인의 실제 값으로 말한다 (예: 월 총비용 61.0만 원, 역까지 도보 8.0분, 주점 1.0곳) → (c) 주의할 점 (flags 의 데이터 부족, 예산 안 거래 비율, tradeoffs) → (d) unsupported 가 있으면 "데이터로 확인할 수 없어 직접 확인이 필요한 조건"으로 언급.
4. 매물(집)을 추천하지 않는다. 동네만 말한다. 실거래가는 시세 참고용이라고 한 번 밝힌다.
5. follow_up 이 있으면 마지막 문장으로 그 질문을 한다.
6. user_question 이 있으면 먼저 facts 로 답한다. facts 로 답할 수 없으면 그렇다고 말한다.
7. what_if 가 true 면 "가정해 보면"으로 시작하고, 실제 조건은 바뀌지 않았다고 밝힌다.
"""
