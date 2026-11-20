"""설명 문장(feedback_templates.explanations)과 조사 고르기(core/hangul), /grade의 실패 대비."""

import pytest

from app import pipeline
from app.core import hangul
from app.schemas import CellError, GradeRequest, GradeResponse, Locale, Stage
from app.services import feedback_templates, spacing_align
from app.services.aggregate import aggregate
from app.services.recognizer import Candidate, CellKind, Recognition
from tests.helpers import STAGES, client, load_fixture, load_request
from tests.test_aggregate import _inputs


def _result(stage: str):
    req, _, recognitions, strokes = _inputs(stage)
    return req, aggregate(req, recognitions, spacing_align.align(req.target, req.stage, recognitions), strokes)


# ----------------------------------------------------------------- 피그마 예시


@pytest.mark.parametrize("stage", STAGES)
def test_explanations_match_figma_example(stage):
    """피그마 예시와 같은 곳·같은 강조. 획순 문장만 아직 간단한 문장이라 text는 글자·띄어쓰기만 비교."""
    req, result = _result(stage)
    got = feedback_templates.explanations(req, result)
    want = GradeResponse.model_validate(load_fixture(f"grade_response_{stage}.json")).explanations
    assert [e.model_copy(update={"text": ""}) for e in got] == [e.model_copy(update={"text": ""}) for e in want]
    for g, w in zip(got, want, strict=True):
        if g.kind != "stroke":
            assert g.text == w.text
    if stage == "beginner":
        assert got[0].text == "다의 ㄷ은 쓰는 순서가 달라요."


# ----------------------------------------------------------------- 고수: 여러 경우


def _advanced(target: str, written: str, locale: Locale = Locale.KO):
    """written: 칸마다 쓴 글자 ('_' = 빈 칸). 쓴 글자를 그대로 인식했다고 본다.

    고수 요청은 칸이 정답 길이 이상이어야 해서 뒤를 빈 칸으로 채운다 (다 쓴 뒤 빈 칸은 무시됨).
    """
    written += "_" * max(0, len(target) - len(written))
    data = load_request("advanced")
    data.update(target=target, locale=locale.value)
    cell = data["cells"][0]
    data["cells"] = [
        {**cell, "index": i, "strokes": [] if ch == "_" else cell["strokes"]} for i, ch in enumerate(written)
    ]
    req = GradeRequest.model_validate(data)
    recs = [
        Recognition(cell_index=i, kind=CellKind.EMPTY, candidates=[])
        if ch == "_"
        else Recognition(cell_index=i, kind=CellKind.CHAR, candidates=[Candidate(ch, 0.95)])
        for i, ch in enumerate(written)
    ]
    result = aggregate(req, recs, spacing_align.align(req.target, Stage.ADVANCED, recs), {})
    return feedback_templates.explanations(req, result)


def texts(lines):
    return [e.text for e in lines]


def test_missing_spaces_in_a_row_become_one_line():
    assert texts(_advanced("나 너 좋아", "나너좋아")) == ["나너좋아는 나 너 좋아로 띄어 써요."]


def test_extra_space_inside_a_word():
    lines = _advanced("좋아하냐", "좋아_하냐")
    assert texts(lines) == ["좋아 하냐는 좋아하냐로 붙여 써요."]
    assert lines[0].cell_indexes == [0, 1, 2, 3, 4]


def test_double_space():
    assert texts(_advanced("나 밥", "나__밥")) == ["나  밥은 나 밥으로 한 칸만 띄어 써요."]


def test_wrong_and_missing_and_extra_chars():
    assert texts(_advanced("밥 먹어", "밤_먹어")) == ["밤이라고 쓰셨는데 밥이라고 써야 해요."]
    assert texts(_advanced("가나다", "가다")) == ["가다라고 쓰셨는데 가나다라고 써야 해요."]
    assert texts(_advanced("가나", "가라나")) == ["가라나라고 쓰셨는데 가나라고 써야 해요."]


def test_char_and_spacing_lines_in_sentence_order():
    assert texts(_advanced("나 너 밥", "나너_밤")) == [
        "나너는 나 너로 띄어 써요.",
        "밤이라고 쓰셨는데 밥이라고 써야 해요.",
    ]


def test_all_correct_has_no_lines():
    assert _advanced("나 너", "나_너") == []


def test_english():
    assert texts(_advanced("나 너", "나너", Locale.EN)) == ["Write 나너 as 나 너 with a space."]


# ----------------------------------------------------------------- 획순 문장


def test_stroke_lines_for_each_error_kind():
    req, result = _result("beginner")
    cases = {
        "DIRECTION": "다의 ㄷ은 쓰는 방향이 거꾸로예요.",
        "MISSING": "다의 ㄷ에 빠진 획이 있어요.",
        "EXTRA": "다에 더 쓴 획이 있어요.",
    }
    for kind, text in cases.items():
        jamo = None if kind == "EXTRA" else "ㄷ"
        cells = [
            c.model_copy(update={"errors": [CellError(type=kind, jamo=jamo)]}) if c.index == 1 else c
            for c in result.cells
        ]
        got = feedback_templates.explanations(req, result.__class__(**{**result.__dict__, "cells": cells}))
        assert texts(got) == [text]


# ----------------------------------------------------------------- 조사


def test_particles_follow_batchim():
    assert [hangul.last_jong(w) for w in ("바다", "밥", "물", "ㄷ", "ㅏ", "좋아하냐?", "?")] == [
        "",
        "ㅂ",
        "ㄹ",
        "ㄷ",
        "",
        "",
        "",
    ]
    assert hangul.decompose("닭") == hangul.Syllable("ㄷ", "ㅏ", "ㄺ")
    assert feedback_templates._euro("물") == "로" and feedback_templates._euro("밥") == "으로"


# ----------------------------------------------------------------- 실패해도 /grade는 돌아감


def test_grade_still_answers_when_feedback_breaks(monkeypatch):
    def boom(*_):
        raise RuntimeError("설명 문장 버그")

    monkeypatch.setattr(feedback_templates, "explanations", boom)
    monkeypatch.setattr(feedback_templates, "sejong_message", boom)
    r = client.post("/grade", json=load_request("advanced"))
    assert r.status_code == 200
    body = r.json()
    assert body["explanations"] == []
    assert body["sejong"]["text"] == pipeline._FALLBACK_SEJONG["ko"].text
    assert body["alignment"]  # 판정 결과는 그대로


# ----------------------------------------------------------------- LLM 말풍선 (진짜 Gemini는 부르지 않음)


def _grade_with_llm(monkeypatch, answer, key="test-key"):
    """Gemini 대신 answer를 돌려주게 바꾸고 고수 예시를 판정 (answer가 예외면 그 예외를 낸다)."""
    from app import config
    from app.services import llm_feedback

    def fake_ask(prompt):
        fake_ask.prompt = prompt
        if isinstance(answer, Exception):
            raise answer
        return answer

    fake_ask.prompt = None
    monkeypatch.setattr(config, "GEMINI_API_KEY", key)
    monkeypatch.setattr(llm_feedback, "_ask", fake_ask)
    r = client.post("/grade", json=load_request("advanced"))
    assert r.status_code == 200
    return r.json()["sejong"], fake_ask.prompt


def test_llm_bubble_is_used_when_it_answers(monkeypatch):
    from app.services.llm_feedback import _Bubble

    sejong, prompt = _grade_with_llm(
        monkeypatch, _Bubble(text="거의 다 왔구나!", sub_text="나와 너 사이를 한 칸 띄어 보자.")
    )
    assert sejong == {
        "text": "거의 다 왔구나!",
        "subText": "나와 너 사이를 한 칸 띄어 보자.",
        "expression": "regret",
        "source": "llm",
    }
    assert "나 너 좋아하냐?" in prompt and "나너는 나 너로 띄어 써요." in prompt  # 정답과 틀린 곳만 보냄


@pytest.mark.parametrize(
    "answer",
    [TimeoutError("시간 초과"), None, "bubble-empty", "bubble-too-long"],
    ids=["timeout", "bad-format", "empty", "too-long"],
)
def test_llm_failure_falls_back_to_template(monkeypatch, answer):
    from app.services.llm_feedback import _Bubble

    answer = {
        "bubble-empty": _Bubble(text=" ", sub_text="x"),
        "bubble-too-long": _Bubble(text="가" * 100, sub_text="x"),
    }.get(answer, answer)
    sejong, _ = _grade_with_llm(monkeypatch, answer)
    assert sejong["source"] == "template"


def test_no_key_means_no_llm_call(monkeypatch):
    sejong, prompt = _grade_with_llm(monkeypatch, AssertionError("부르면 안 됨"), key="")
    assert sejong["source"] == "template" and prompt is None


def test_no_mistakes_to_explain_uses_template_without_llm(monkeypatch):
    """글자·띄어쓰기가 맞고 설명할 틀린 곳이 없으면 LLM을 부르지 않는다."""
    data = load_request("advanced")
    data["target"] = "나너 좋아하냐?"  # 예시 손글씨(나너_좋아하냐?)가 그대로 정답
    from app import config
    from app.services import llm_feedback

    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(pipeline, "_check_strokes", lambda req, alignment: {})  # 예시 획은 가짜라 획순 판정은 뺀다
    monkeypatch.setattr(llm_feedback, "_ask", lambda prompt: pytest.fail("다 맞으면 LLM을 부르지 않음"))
    body = client.post("/grade", json=data).json()
    assert body["sejong"]["source"] == "template" and body["explanations"] == []
