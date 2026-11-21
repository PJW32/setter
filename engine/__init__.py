"""동네 추천 점수 엔진 (LLM 없음, 지역 무관).

입력: 동 데이터(dongs.json 형식) + 실거래(rent_deals.csv 형식) + 사용자 상태(가중치 단계, 필수 조건, 파라미터)
출력: 순위, 요인별 기여도, 제외 이유, 아깝게 탈락한 동, 순위 변동 분해

같은 입력이면 항상 같은 결과를 낸다.
"""

from .data import Dataset, load_dataset
from .diff import compare
from .factors import FACTORS, LEVELS, normalize_weights
from .features import Params, build_features
from .score import Constraints, Result, rank
from .state import State, apply_changes, evaluate

__all__ = [
    "FACTORS", "LEVELS", "Constraints", "Dataset", "Params", "Result", "State",
    "apply_changes", "build_features", "compare", "evaluate", "load_dataset", "normalize_weights", "rank",
]
