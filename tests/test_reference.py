"""GET /reference/{글자}: 정답 획 주소.

진짜 정답 획을 확인하는 테스트는 정답 획 사전이 있어야 해서, 없으면(CI) 건너뛴다.
오류 응답은 사전을 바꿔 끼워 어디서나 확인한다.
"""

import pytest

from app import pipeline
from app.config import ENGINE_VERSION
from app.core import reference
from app.schemas import ReferenceResponse
from tests.helpers import client

needs_data = pytest.mark.skipif(
    not pipeline.reference_available(), reason="정답 획 사전 없음 (python -m app.core.stroke_vectorizer.compose --all)"
)


@needs_data
def test_syllable_strokes_in_writing_order():
    res = client.get("/reference/가")
    assert res.status_code == 200
    body = res.json()
    ReferenceResponse.model_validate(body)
    assert body["char"] == "가" and body["engineVersion"] == ENGINE_VERSION
    strokes = body["strokes"]
    assert [s["order"] for s in strokes] == [1, 2, 3]
    assert [(s["jamo"], s["role"], s["strokeNo"]) for s in strokes] == [
        ("ㄱ", "cho", 1),
        ("ㅏ", "jung", 1),
        ("ㅏ", "jung", 2),
    ]
    assert all(0 <= v <= 1 for s in strokes for p in s["points"] for v in p)


@needs_data
def test_jamo_alone_for_beginner():
    body = client.get("/reference/ㄱ").json()
    assert body["char"] == "ㄱ" and len(body["strokes"]) >= 1


@needs_data
def test_url_encoded_char_is_the_same():
    assert client.get("/reference/%EA%B0%80").json() == client.get("/reference/가").json()


@pytest.mark.parametrize("char", ["가나", "a", "%3F", "1", "%20"])  # %3F = '?', %20 = 공백 (URL 인코딩)
def test_not_one_hangul_char_is_422(char):
    """사전이 있든 없든 글자 검사가 먼저 (그래서 CI에서도 422)."""
    res = client.get(f"/reference/{char}")
    assert res.status_code == 422
    body = res.json()
    assert body["code"] == "INVALID_REQUEST"
    assert body["details"] == [{"field": "char", "message": "한글 음절이나 자모 한 글자만 쓸 수 있어요"}]


def test_char_missing_from_reference_is_404(monkeypatch):
    monkeypatch.setattr(pipeline, "reference_available", lambda: True)
    monkeypatch.setattr(reference, "has_reference", lambda char: False)
    res = client.get("/reference/똠")
    assert res.status_code == 404
    assert res.json()["code"] == "NOT_FOUND"


def test_no_reference_data_is_503(monkeypatch):
    monkeypatch.setattr(pipeline, "reference_available", lambda: False)
    res = client.get("/reference/가")
    assert res.status_code == 503
    assert res.json() == {
        "code": "REFERENCE_UNAVAILABLE",
        "message": "엔진에 정답 획 데이터가 없어요",
        "details": [],
        "engineVersion": ENGINE_VERSION,
    }


def test_post_is_405():
    assert client.post("/reference/가").json()["code"] == "METHOD_NOT_ALLOWED"
