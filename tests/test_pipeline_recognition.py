"""판정 흐름(/grade)의 글자 인식 연결 (pipeline._recognitions → recognizer.recognize).

- 단계마다 recognize에 넘기는 '이 칸에 올 수 있는 정답 글자'가 맞는지
- 정답 획 사전이 없거나 칸 하나의 인식이 실패하면 '정답 글자를 썼다'고 가정하는지
- 정답 획 사전이 있으면: 정답 획으로 쓴 칸은 맞음, 다른 글자를 쓴 칸은 글자 오류와 설명 문장이 나오는지
"""

import pytest

from app import pipeline
from app.core import reference
from app.services.recognizer import Candidate, CellKind, Recognition
from tests.helpers import client, load_request

needs_data = pytest.mark.skipif(
    not reference.reference_available(), reason="정답 획 사전 없음 (python -m app.core.stroke_vectorizer.compose --all)"
)


@pytest.fixture
def recorded(monkeypatch):
    """recognize 대신 (칸 번호, expected)를 기록하고, expected의 첫 글자를 썼다고 돌려준다."""
    calls = []

    def fake_recognize(cell, canvas, expected):
        calls.append((cell.index, list(expected)))
        if not cell.strokes:
            return Recognition(cell_index=cell.index, kind=CellKind.EMPTY, candidates=[])
        candidates = [Candidate(char=expected[0], score=1.0)] if expected else []
        return Recognition(cell_index=cell.index, kind=CellKind.CHAR, candidates=candidates)

    monkeypatch.setattr(reference, "reference_available", lambda: True)
    monkeypatch.setattr(pipeline, "recognize", fake_recognize)
    monkeypatch.setattr(pipeline, "_check_strokes", lambda req, alignment: {})
    return calls


def test_beginner_and_intermediate_pass_the_cell_target_char(recorded):
    client.post("/grade", json=load_request("beginner"))
    assert recorded == [(0, ["바"]), (1, ["다"])]

    recorded.clear()
    client.post("/grade", json=load_request("intermediate"))
    assert recorded == [(0, ["보"]), (1, ["고"]), (2, ["싶"]), (3, ["었"]), (4, ["어"])]


def test_advanced_passes_every_target_char(recorded):
    req = load_request("advanced")
    client.post("/grade", json=req)
    chars = ["나", "너", "좋", "아", "하", "냐", "?"]
    assert [i for i, _ in recorded] == [c["index"] for c in req["cells"]]
    assert all(expected == chars for _, expected in recorded)


def test_without_reference_data_assumes_target_chars(monkeypatch, caplog):
    """사전이 없으면 recognize를 부르지 않고 정답 글자를 썼다고 가정한다 (경고는 한 번)."""
    monkeypatch.setattr(reference, "reference_available", lambda: False)
    monkeypatch.setattr(pipeline, "_warned_no_reference_for_recognition", False)
    monkeypatch.setattr(pipeline, "recognize", lambda *a: pytest.fail("사전이 없으면 recognize를 부르지 않음"))
    for _ in range(2):
        body = client.post("/grade", json=load_request("beginner")).json()
        assert body["correct"] is True and body["perfect"] is False
    warnings = [r for r in caplog.records if "글자 인식 대신" in r.getMessage()]
    assert len(warnings) == 1


def test_recognition_crash_assumes_only_that_cell(recorded, monkeypatch, caplog):
    """칸 하나의 인식 중 오류 → 500이 아니라 그 칸만 정답 글자를 썼다고 가정, 오류 위치까지 기록."""
    fake = pipeline.recognize

    def crash_on_second(cell, canvas, expected):
        if cell.index == 1:
            raise ValueError("인식 코드 버그")
        return fake(cell, canvas, expected)

    monkeypatch.setattr(pipeline, "recognize", crash_on_second)
    res = client.post("/grade", json=load_request("beginner"))
    assert res.status_code == 200
    assert res.json()["correct"] is True
    errors = [r for r in caplog.records if "글자 인식 중 오류" in r.getMessage()]
    assert len(errors) == 1 and errors[0].exc_info


# ---------------- 정답 획 사전으로 (진짜 인식) ----------------


def _cell(index: int, char: str, size: float = 300) -> dict:
    """정답 획을 그대로 따라 쓴 칸 (픽셀, 10ms 간격)."""
    t = 0
    strokes = []
    for s in reference.get_reference(char):
        points = []
        for x, y in s.points:
            points.append([x * size, y * size, t, 0.5])
            t += 10
        strokes.append({"points": points})
    return {"index": index, "strokes": strokes}


def _beginner(*written: str) -> dict:
    req = load_request("beginner")
    req["cells"] = [_cell(i, ch) for i, ch in enumerate(written)]
    return req


@needs_data
def test_writing_the_target_is_correct():
    body = client.post("/grade", json=_beginner("바", "다")).json()
    assert body["correct"] is True
    assert [c["charCorrect"] for c in body["cells"]] == [True, True]


@needs_data
def test_writing_a_different_char_is_a_char_error():
    """'바다' 자리에 '바나'를 씀 → '다' 칸이 글자 오류(빨강), 설명 문장이 나온다."""
    body = client.post("/grade", json=_beginner("바", "나")).json()
    assert body["correct"] is False
    assert [c["charCorrect"] for c in body["cells"]] == [True, False]
    assert body["cells"][1]["mark"] == "char"
    assert body["cells"][1]["strokePass"] is None  # 글자가 틀린 칸은 획 판정을 하지 않음
    assert [(e["wrong"], e["right"]) for e in body["explanations"] if e["kind"] == "char"] == [("바나", "바다")]
