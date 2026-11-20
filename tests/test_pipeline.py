"""판정 흐름(/grade): 임시 인식으로도 띄어쓰기·획순 판정이 진짜로 나오는지.

획순 판정은 정답 획 데이터가 필요해서, 여기서는 stroke_checker.check_strokes를 바꿔 끼워 흐름만 확인한다.
"""

import pytest

from app.schemas import CellError, StrokeMapItem
from app.services import stroke_checker
from app.services.stroke_checker import StrokeCheckResult
from tests.helpers import client, load_request


@pytest.fixture
def no_reference(monkeypatch):
    """정답 획 데이터가 없는 상황 (CI와 같음)."""

    def missing(*_args, **_kwargs):
        raise FileNotFoundError("정답 획 사전이 없어요")

    monkeypatch.setattr(stroke_checker, "check_strokes", missing)


def test_advanced_missing_space_is_judged(no_reference):
    """고수 '나 너 좋아하냐?'를 '나너 좋아하냐?'로 붙여 씀 → 띄어쓰기 오류, 양옆 어절 틀림."""
    body = client.post("/grade", json=load_request("advanced")).json()
    assert body["correct"] is False and body["perfect"] is False
    assert [(a["targetIndex"], a["cellIndex"], a["error"], a["mark"]) for a in body["alignment"] if a["error"]] == [
        (1, None, "MISSING_SPACE", "spacing")
    ]
    assert [w["correct"] for w in body["words"]] == [False, False, True]
    assert all(c["errors"] == [] for c in body["cells"])  # 띄어쓰기 오류는 칸에 붙지 않음
    assert body["sejong"]["expression"] == "regret"


def test_without_reference_data_strokes_are_skipped(no_reference):
    body = client.post("/grade", json=load_request("beginner")).json()
    assert body["correct"] is True and body["perfect"] is True
    assert all(c["strokePass"] is None and c["strokeMap"] is None for c in body["cells"])
    assert all(c["durationMs"] is not None for c in body["cells"])  # 쓴 칸은 시간이 나옴


def test_stroke_errors_flow_into_the_response(monkeypatch):
    """'다'의 획순을 틀렸다고 판정되면 → 칸 주황(stroke), correct는 그대로, perfect는 아님."""

    def fake_check(target, canvas, strokes):
        if target == "다":
            error = CellError(type="ORDER", jamo="ㄷ", role="cho", stroke_index=1, expected=1, actual=2)
            return StrokeCheckResult(passed=False, errors=[error], stroke_map=[StrokeMapItem(user_index=0)])
        return StrokeCheckResult(passed=True)

    monkeypatch.setattr(stroke_checker, "check_strokes", fake_check)
    body = client.post("/grade", json=load_request("beginner")).json()
    assert body["correct"] is True and body["perfect"] is False
    assert [c["mark"] for c in body["cells"]] == ["none", "stroke"]
    assert body["cells"][1]["errors"][0]["type"] == "ORDER" and body["cells"][1]["strokePass"] is False
    assert body["alignment"][1]["mark"] == "stroke"
    assert body["words"][0]["correct"] is True  # 획순 오류는 어절 정답 여부에 넣지 않음
    assert body["sejong"]["expression"] == "encourage"


def test_empty_submission_is_all_wrong(no_reference):
    req = load_request("intermediate")
    req["cells"] = [{"index": c["index"], "strokes": []} for c in req["cells"]]
    body = client.post("/grade", json=req).json()
    assert body["correct"] is False
    assert {c["mark"] for c in body["cells"]} == {"char"}
    assert all(not w["correct"] for w in body["words"])


def test_punctuation_cell_is_not_stroke_checked(monkeypatch):
    seen = []

    def fake_check(target, canvas, strokes):
        seen.append(target)
        return StrokeCheckResult(passed=True)

    monkeypatch.setattr(stroke_checker, "check_strokes", fake_check)
    client.post("/grade", json=load_request("advanced"))
    assert "?" not in seen and seen == ["나", "너", "좋", "아", "하", "냐"]
