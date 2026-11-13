"""테스트 공용 도구. 예시 JSON 읽기와 테스트용 클라이언트를 한곳에 둔다."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

FIXTURES = Path(__file__).parent / "fixtures"
STAGES = ["beginner", "intermediate", "advanced"]

# 엔진 안에서 예외가 나면 테스트도 바로 실패하는 클라이언트 (보통 이것을 쓴다)
client = TestClient(app)
# 500 같은 오류 응답 자체를 확인할 때 쓰는 클라이언트 (예외를 응답으로 받음)
safe_client = TestClient(app, raise_server_exceptions=False)


def load_fixture(name: str) -> dict:
    """tests/fixtures/의 JSON 파일 하나 (예: 'grade_request_beginner.json')."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_request(stage: str) -> dict:
    """피그마 장면 예시 요청 (stage: beginner | intermediate | advanced)."""
    return load_fixture(f"grade_request_{stage}.json")
