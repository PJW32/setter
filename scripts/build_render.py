"""Render 빌드: 의존성, 기존 화면, 허용된 국토부 실거래만 준비한다."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    from config import get_data_go_kr_key
    from backend.security import SecuritySettings

    SecuritySettings.load()  # 비밀값이 없거나 약한 배포는 빌드 단계부터 중단한다.
    codes = os.getenv("DEPLOY_RENT_CODES", "").split()
    if not codes:
        raise RuntimeError("DEPLOY_RENT_CODES에 실거래를 준비할 시군구 코드를 지정하세요")
    if any(len(c) != 5 or not c.isascii() or not c.isdigit() for c in codes):
        raise RuntimeError("DEPLOY_RENT_CODES는 공백으로 구분한 숫자 5자리 코드입니다")
    if not get_data_go_kr_key(required=False):
        raise RuntimeError("배포 빌드에는 DATA_GO_KR_SERVICE_KEY가 필요합니다")
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], cwd=ROOT, check=True)
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        raise RuntimeError("Node.js와 npm이 필요합니다")
    subprocess.run([npm, "ci"], cwd=ROOT / "frontend", check=True)
    subprocess.run([npm, "run", "build"], cwd=ROOT / "frontend", check=True)
    # 공개 저장소에 로컬 DB를 올리지 않고, 서버 빌드에서 공공자료만 준비한다.
    subprocess.run([sys.executable, "scripts/prewarm_rent.py", *codes], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
