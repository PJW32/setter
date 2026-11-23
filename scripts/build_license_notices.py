"""설치된 직접 Python 의존성·npm 운영 의존성의 라이선스 원문을 정적 고지로 복사한다.

의존성 설치 후 python scripts/build_license_notices.py 실행. 네트워크 접근 없음.
전체 법적 준수 또는 모든 전이 Python 의존성 검토를 보증하지 않는다.
"""
import importlib.metadata as metadata
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "frontend/public/third-party-notices.txt"
PYTHON_PACKAGES = ("fastapi", "uvicorn", "httpx", "google-genai")


def license_file(path):
    return re.match(r"^(licen[cs]e|copying|notice)([._-]|$)", path.name, re.I) is not None


def generate():
    sections = ["Setter — Third-party notices\n\n"
                "Scope: installed direct Python dependencies and npm production dependencies from package-lock.json.\n"
                "Python transitive dependencies, external data/API terms and competition-specific rules require separate review.\n"
                "react-leaflet and @react-leaflet/core use Hippocratic-2.1, not MIT.\n"
                "Their full license conditions apply; listing a license does not waive its conditions.\n"
                "Versions describe the local installed snapshot, not every future server build.\n"]
    for name in PYTHON_PACKAGES:
        dist = metadata.distribution(name)
        label = dist.metadata.get("License-Expression") or dist.metadata.get("License") or "See license text"
        texts = []
        for item in dist.files or []:
            if ".dist-info/" in str(item).replace("\\", "/") and license_file(Path(item)):
                path = Path(dist.locate_file(item))
                if path.is_file():
                    texts.append(f"--- {path.name} ---\n{path.read_text(encoding='utf-8')}")
        if not texts:
            raise ValueError(f"라이선스 원문 없음: {name}")
        sections.append(f"\n{'=' * 72}\n{name} {dist.version} | {label}\n\n" + "\n".join(texts))
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text(encoding="utf-8"))
    for relative, entry in sorted(lock["packages"].items()):
        if not relative or entry.get("dev") or entry.get("link"):
            continue
        directory = ROOT / "frontend" / relative
        package = directory / "package.json"
        if not package.exists():
            if entry.get("optional"):
                continue
            raise ValueError(f"의존성 설치 필요: {relative}")
        info = json.loads(package.read_text(encoding="utf-8"))
        if info["version"] != entry["version"]:
            raise ValueError(f"설치 버전과 lock 불일치: {relative}")
        files = [p for p in directory.iterdir() if p.is_file() and license_file(p)]
        if not files:
            raise ValueError(f"라이선스 원문 없음: {relative}")
        sections.append(f"\n{'=' * 72}\n{info['name']} {info['version']} | {info.get('license', 'See license text')}\n\n"
                        + "\n".join(f"--- {p.name} ---\n{p.read_text(encoding='utf-8')}" for p in sorted(files)))
    OUTPUT.write_text("\n".join(sections) + "\n", encoding="utf-8")
    print(f"Generated {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    generate()
