"""요인 정의와 가중치 단계."""

from dataclasses import dataclass

# LLM 은 숫자 대신 단계를 고른다. 숫자 변환은 여기서만 한다.
LEVELS = {"매우 중요": 4, "중요": 3, "보통": 2, "조금": 1, "상관없음": 0}
DEFAULT_LEVEL = "보통"


@dataclass(frozen=True)
class Factor:
    key: str
    label: str
    better: str  # "low" 낮을수록 좋음 / "high" 높을수록 좋음
    unit: str
    description: str


FACTORS: dict[str, Factor] = {
    f.key: f
    for f in [
        Factor("monthly_cost", "월 총비용", "low", "만원",
               "월세 + 보증금 × 환산이율 ÷ 12 + 월 교통비 (실거래 중앙값)"),
        Factor("commute", "통근 시간", "low", "분", "대표 지점 → 목적지 대중교통 최단 경로"),
        Factor("station_access", "역 접근성", "low", "분", "가장 가까운 지하철역까지 도보 (추정)"),
        Factor("convenience", "생활 편의", "high", "점", "반경 안 편의점·약국·대형마트 수를 각각 0~100으로 바꾼 평균"),
        Factor("quiet", "조용함", "low", "개", "반경 안 주점 수 (적을수록 조용함)"),
    ]
}
FACTOR_KEYS = tuple(FACTORS)


def default_levels() -> dict[str, str]:
    return {k: DEFAULT_LEVEL for k in FACTOR_KEYS}


def normalize_weights(levels: dict[str, str]) -> dict[str, float]:
    """단계 → 합이 1인 가중치. 모두 '상관없음'이면 똑같이 나눈다."""
    raw = {k: LEVELS[levels.get(k, DEFAULT_LEVEL)] for k in FACTOR_KEYS}
    total = sum(raw.values())
    if total == 0:
        return {k: 1 / len(FACTOR_KEYS) for k in FACTOR_KEYS}
    return {k: v / total for k, v in raw.items()}
