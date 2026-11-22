"""API 키 로딩.

키는 코드나 깃에 두지 않는다. 다음 순서로 찾는다.
1. 이미 설정된 환경변수 (배포 환경: Streamlit Cloud secrets 등)
2. 프로젝트 루트의 .env 파일 (깃 제외, .env.example 을 복사해서 만든다)
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"

# 키 이름 → 용도 (에러 메시지와 상태 표시에 쓴다)
KEY_NAMES = {
    "GEMINI_API_KEY": "Gemini API (조건 추출, 결과 설명)",
    "DATA_GO_KR_SERVICE_KEY": "공공데이터포털 (전월세 실거래가, 상가정보) - 디코딩 키",
    "KAKAO_REST_API_KEY": "카카오 로컬 API (REST API 키)",
    "ODSAY_API_KEY": "ODsay 대중교통 경로",
}


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        # 이미 있는 환경변수가 우선
        os.environ.setdefault(name, value)


_load_env_file(ENV_FILE)


def get_key(name: str, required: bool = True) -> str | None:
    value = os.environ.get(name, "").strip()
    if not value:
        if required:
            raise RuntimeError(
                f"{name} 가 설정되지 않았습니다 ({KEY_NAMES.get(name, '알 수 없는 키')}). "
                ".env.example 을 .env 로 복사하고 값을 채우세요."
            )
        return None
    return value


def get_data_go_kr_key(required: bool = True) -> str | None:
    """공공데이터포털 키는 인코딩 키(%XX 포함)와 디코딩 키가 있다.
    요청할 때 다시 인코딩하므로 항상 디코딩된 형태로 돌려준다."""
    from urllib.parse import unquote

    key = get_key("DATA_GO_KR_SERVICE_KEY", required)
    return unquote(key) if key else None


def key_status() -> dict[str, bool]:
    """키 값은 노출하지 않고 설정 여부만 돌려준다."""
    return {name: bool(os.environ.get(name, "").strip()) for name in KEY_NAMES}


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    for name, ok in key_status().items():
        print(f"{'OK ' if ok else '-- '} {name:24s} {KEY_NAMES[name]}")
