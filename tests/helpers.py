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


def assume_target_written(monkeypatch) -> None:
    """글자 인식 대신 '정답 글자를 썼다'고 가정하게 바꾼다.

    예시 요청의 획은 대략 그린 가짜 획이라 진짜 인식으로는 다른 글자로 읽힌다.
    인식이 아닌 흐름(띄어쓰기·획순·결과 묶기·말풍선)을 확인하는 테스트에서 쓴다.
    """
    from app import pipeline

    monkeypatch.setattr(pipeline, "_recognitions", pipeline._assumed_recognitions)
