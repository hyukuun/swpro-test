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
    """획 판정을 못 했으면 perfect가 아니고, 말풍선도 '확인하지 못했다'고 알린다."""
    body = client.post("/grade", json=load_request("beginner")).json()
    assert body["correct"] is True and body["perfect"] is False
    assert all(c["strokePass"] is None and c["strokeMap"] is None for c in body["cells"])
    assert all(c["durationMs"] is not None for c in body["cells"])  # 쓴 칸은 시간이 나옴
    assert body["sejong"]["text"] == "글자와 띄어쓰기는 다 맞았어요"


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


def test_balance_only_is_not_perfect_and_says_so(monkeypatch):
    """'다'의 균형(글자 모양)만 틀림 → 칸 색은 없음, perfect 아님, 말풍선은 모양을 다듬자고 함."""

    def fake_check(target, canvas, strokes):
        if target == "다":
            balance = CellError(type="BALANCE", metric="glyph_size", value=0.4, range=(0.5, 1.0))
            return StrokeCheckResult(passed=False, errors=[balance])
        return StrokeCheckResult(passed=True)

    monkeypatch.setattr(stroke_checker, "check_strokes", fake_check)
    body = client.post("/grade", json=load_request("beginner")).json()
    assert body["correct"] is True and body["perfect"] is False
    assert [c["mark"] for c in body["cells"]] == ["none", "none"]
    assert [c["strokePass"] for c in body["cells"]] == [True, False]
    assert body["sejong"]["expression"] == "encourage"
    assert body["sejong"]["subText"] == "글자 모양을 조금만 다듬어 볼까요?"


def test_all_stroke_checks_pass_is_perfect(monkeypatch):
    monkeypatch.setattr(stroke_checker, "check_strokes", lambda *a: StrokeCheckResult(passed=True))
    body = client.post("/grade", json=load_request("beginner")).json()
    assert body["perfect"] is True and body["sejong"]["expression"] == "praise"
