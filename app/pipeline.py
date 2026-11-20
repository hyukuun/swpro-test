"""[혁윤] 인식 → 정렬 → 획순 → 결과 종합 흐름 제어.

흐름 (README '입력과 출력 한눈에 보기' 2번):
    1. recognizer      (D-01, 혁윤)  칸마다 무슨 글자를 썼나        ← 지금은 임시 인식 (아래)
    2. spacing_align   (D-02, 혁윤)  정답과 줄 맞춤 → alignment, 글자·띄어쓰기 오류
    3. stroke_checker  (D-04, 정진)  글자가 맞은 한글 칸만 획순·균형 판정
    4. aggregate       (D-03, 혁윤)  mark, words, correct, perfect
    5. feedback        (E-03·E-07, 혁윤) sejong (설명 문장 explanations는 아직 [])

임시 인식: 진짜 글자 인식(recognize) 전까지 "정답 글자를 썼다"고 가정한다.
그래서 다른 글자를 쓴 경우는 아직 잡지 못하지만, 띄어쓰기 판정과 획순 판정은 진짜로 나온다.

정답 획 데이터(composed_all.json)가 없거나 획 판정 중 오류가 나면 그 칸의 획 판정만 건너뛴다 (strokePass: null).
TODO(혁윤): 임시 인식을 recognizer.recognize로 바꾸고, explanations를 채운다
"""

from __future__ import annotations

import logging

from app.config import ENGINE_VERSION
from app.schemas import GradeRequest, GradeResponse, Stage
from app.services import feedback_templates, spacing_align, stroke_checker
from app.services.aggregate import aggregate, needs_stroke_check
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
    return GradeResponse(
        session_id=req.session_id,
        engine_version=ENGINE_VERSION,
        stage=req.stage,
        correct=result.correct,
        perfect=result.perfect,
        cells=result.cells,
        alignment=result.alignment,
        words=result.words,
        explanations=[],
        sejong=feedback_templates.sejong_message(req, result),
    )


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
    - 정답 획 데이터 파일이 없음 → 모든 칸 (로그 경고 한 번)
    - 사전에 없는 글자 → 그 칸
    - 판정 중 예상 못 한 오류 → 그 칸 (로그에 오류 전체). 칸 하나 때문에 /grade 전체가 실패하지 않게
    """
    global _warned_no_reference
    results: dict[int, StrokeCheckResult] = {}
    for cell in req.cells:
        if not needs_stroke_check(cell, alignment):
            continue
        expected = alignment.expected[cell.index]
        assert expected is not None  # needs_stroke_check가 확인함
        try:
            results[cell.index] = stroke_checker.check_strokes(expected, req.canvas, cell.strokes)
        except FileNotFoundError:
            if not _warned_no_reference:
                log.warning(
                    "정답 획 데이터가 없어 획순 판정을 건너뜀 (python -m app.core.stroke_vectorizer.compose --all)"
                )
                _warned_no_reference = True
            return {}
        except KeyError:
            log.warning("정답 획 데이터에 없는 글자라 획순 판정을 건너뜀: %s", expected)
        except Exception:
            # 예상 못 한 오류(특이한 손글씨 입력, 판정 코드 버그 등): 이 칸만 '획 판정 못 함'으로 두고
            # 나머지 판정 결과는 그대로 돌려준다. 원인을 찾을 수 있게 오류 전체를 서버 로그에 남긴다.
            log.exception("획순 판정 중 오류, 이 칸은 건너뜀: 칸 %d, 글자 %s", cell.index, expected)
    return results
