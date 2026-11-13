"""엔진 내부 모듈의 입출력(함수 이름·매개변수)이 README "입력과 출력 한눈에 보기" 2번 표와 같은지 확인.

함수 본문은 아직 비어 있어도 되지만, 이름이나 매개변수를 바꾸면 이 테스트가 알려 준다.
바꿨다면 README 표와 이 테스트를 같이 고친다.
"""

import inspect

import pytest

from app.core import hangul, reference
from app.services import aggregate, feedback_templates, llm_feedback, recognizer, spacing_align, stroke_checker

EXPECTED = [
    (reference.get_reference, ["char"]),
    (reference.has_reference, ["char"]),
    (hangul.decompose, ["ch"]),
    (hangul.compose, ["cho", "jung", "jong"]),
    (recognizer.recognize, ["cell", "canvas", "expected"]),
    (spacing_align.align, ["target", "stage", "recognitions"]),
    (stroke_checker.check_strokes, ["target", "canvas", "strokes"]),
    (aggregate.aggregate, ["req", "recognitions", "alignment", "strokes"]),
    (feedback_templates.explanations, ["req", "result"]),
    (feedback_templates.sejong_message, ["req", "result"]),
    (llm_feedback.sejong_line, ["req", "result"]),
]


@pytest.mark.parametrize("func, params", EXPECTED, ids=lambda x: getattr(x, "__qualname__", ""))
def test_function_signature(func, params):
    assert list(inspect.signature(func).parameters) == params
