"""[혁윤] 인식 → 정렬 → 획순 → 결과 종합 흐름 제어.

흐름 (README '입력과 출력 한눈에 보기' 2번):
    1. recognizer      (D-01, 혁윤)  칸마다 무슨 글자를 썼나        ← 지금은 임시 인식 (아래)
    2. spacing_align   (D-02, 혁윤)  정답과 줄 맞춤 → alignment, 글자·띄어쓰기 오류
    3. stroke_checker  (D-04, 정진)  글자가 맞은 한글 칸만 획순·균형 판정
    4. aggregate       (D-03, 혁윤)  mark, words, correct, perfect
    5. feedback        (E-03·E-07, 혁윤) explanations, sejong (템플릿 문장)

임시 인식: 진짜 글자 인식(recognize) 전까지 "정답 글자를 썼다"고 가정한다.
그래서 다른 글자를 쓴 경우는 아직 잡지 못하지만, 띄어쓰기 판정과 획순 판정은 진짜로 나온다.

정답 획 데이터(composed_all.json)가 없거나 획 판정 중 오류가 나면 그 칸의 획 판정만 건너뛴다 (strokePass: null).
설명 문장·말풍선 만들다 오류가 나도 판정 결과는 그대로 돌려준다 (explanations는 [], 말풍선은 기본 문장).
TODO(혁윤): 임시 인식을 recognizer.recognize로 바꾼다. LLM 말풍선(llm_feedback)은 붙여도 실패하면 템플릿을 쓴다
"""

from __future__ import annotations

import logging

from app.config import ENGINE_VERSION
from app.core import reference
from app.schemas import Explanation, GradeRequest, GradeResponse, SejongMessage, Stage
from app.services import feedback_templates, spacing_align, stroke_checker
from app.services.aggregate import AggregateResult, aggregate, needs_stroke_check
from app.services.recognizer import Candidate, CellKind, Recognition
from app.services.spacing_align import AlignmentResult
from app.services.stroke_checker import StrokeCheckResult

log = logging.getLogger(__name__)

_warned_no_reference = False


def grade(req: GradeRequest) -> GradeResponse:
    """판정 요청 하나를 받아 결과를 돌려준다."""
    recognitions = _temporary_recognitions(req)
    alignment = spacing_align.align(req.target, req.stage, recognitions)
    strokes = _check_strokes(req, alignment)
    result = aggregate(req, recognitions, alignment, strokes)
    explanations, sejong = _feedback(req, result)
    return GradeResponse(
        session_id=req.session_id,
        engine_version=ENGINE_VERSION,
        stage=req.stage,
        correct=result.correct,
        perfect=result.perfect,
        cells=result.cells,
        alignment=result.alignment,
        words=result.words,
        explanations=explanations,
        sejong=sejong,
    )


# 말풍선까지 실패했을 때 쓰는 문장 (결과를 몰라도 틀리지 않는 말)
_FALLBACK_SEJONG = {
    "ko": SejongMessage(text="결과를 확인해 볼까요?", expression="default"),
    "en": SejongMessage(text="Let's check your result.", expression="default"),
}


def _feedback(req: GradeRequest, result: AggregateResult) -> tuple[list[Explanation], SejongMessage]:
    """설명 문장과 말풍선. 여기서 오류가 나도 /grade 전체가 실패하지 않게 기본값으로 돌려준다."""
    try:
        explanations = feedback_templates.explanations(req, result)
    except Exception:
        log.exception("설명 문장을 만들다 오류, explanations는 비워 둠")
        explanations = []
    try:
        sejong = feedback_templates.sejong_message(req, result)
    except Exception:
        log.exception("킹세종 말풍선을 만들다 오류, 기본 문장을 씀")
        sejong = _FALLBACK_SEJONG["en" if req.locale == "en" else "ko"]
    return explanations, sejong


def _temporary_recognitions(req: GradeRequest) -> list[Recognition]:
    """임시 인식: 획이 있는 칸은 그 자리의 정답 글자를 썼다고 본다 (확신도 1).

    - 초보·중수: 칸 i의 정답 = 공백을 뺀 정답의 i번째 글자
    - 고수: 칸이 밀릴 수 있으므로, k번째로 글자를 쓴 칸 = 공백을 뺀 정답의 k번째 글자
    정답 글자가 남지 않은 칸(더 쓴 칸)은 후보 없는 글자 칸으로 둔다.
    """
    chars = [ch for ch in req.target if ch != " "]
    out: list[Recognition] = []
    k = 0
    for cell in req.cells:
        if not cell.strokes:
            out.append(Recognition(cell_index=cell.index, kind=CellKind.EMPTY, candidates=[]))
            continue
        pos = k if req.stage == Stage.ADVANCED else cell.index
        k += 1
        guess = chars[pos] if pos < len(chars) else None
        candidates = [Candidate(char=guess, score=1.0)] if guess else []
        out.append(Recognition(cell_index=cell.index, kind=CellKind.CHAR, candidates=candidates))
    return out


def _check_strokes(req: GradeRequest, alignment: AlignmentResult) -> dict[int, StrokeCheckResult]:
    """글자를 맞게 쓴 한글 칸만 획순·균형 판정 (aggregate.needs_stroke_check).

    건너뛰는 경우 (건너뛴 칸이 있으면 aggregate가 perfect를 false로 둔다):
    - 정답 획 사전 파일이 없음 → 모든 칸 (로그 경고 한 번)
    - 사전 파일을 읽지 못함 (깨진 파일 등) → 모든 칸 (요청마다 오류 로그 한 번)
    - 사전에 없는 글자 → 그 칸
    - 판정 중 오류 → 그 칸 (오류 위치까지 로그). 칸 하나 때문에 /grade 전체가 실패하지 않게

    원인은 오류 종류로 짐작하지 않고 판정 전에 직접 확인한다. 판정 코드 버그로 난 KeyError·FileNotFoundError가
    '사전에 없는 글자'·'사전 파일 없음'으로 잘못 기록되지 않게 하려는 것.
    """
    global _warned_no_reference
    cells = [c for c in req.cells if needs_stroke_check(c, alignment)]
    if not cells:
        return {}
    if not reference.reference_available():
        if not _warned_no_reference:
            log.warning("정답 획 사전이 없어 획순 판정을 건너뜀 (python -m app.core.stroke_vectorizer.compose --all)")
            _warned_no_reference = True
        return {}

    results: dict[int, StrokeCheckResult] = {}
    for cell in cells:
        expected = alignment.expected[cell.index]
        assert expected is not None  # needs_stroke_check가 확인함
        try:
            known = reference.has_reference(expected)
        except Exception:
            log.exception("정답 획 사전을 읽지 못해 획순 판정을 건너뜀")
            return {}
        if not known:
            log.warning("정답 획 사전에 없는 글자라 획순 판정을 건너뜀: %s", expected)
            continue
        try:
            results[cell.index] = stroke_checker.check_strokes(expected, req.canvas, cell.strokes)
        except Exception:
            log.exception("획순 판정 중 오류, 이 칸은 건너뜀: 칸 %d, 글자 %s", cell.index, expected)
    return results
