"""[혁윤] 인식 → 정렬 → 획순 → 결과 종합 흐름 제어.

지금은 **형식만 맞춘 임시 응답**이다. 스프링부트·프론트가 연동을 먼저 시작할 수 있도록
GradeResponse 모양만 지키고, 판정은 하지 않는다 (모든 칸 맞음).

진짜 흐름 (README '입력과 출력 한눈에 보기' 2번):
    1. recognizer      (D-01, 혁윤)  칸마다 무슨 글자를 썼나
    2. spacing_align   (D-02, 혁윤)  정답과 줄 맞춤 → alignment, 띄어쓰기 오류
    3. stroke_checker  (D-04, 정진)  글자가 맞은 칸만 획순·균형 판정
    4. aggregate       (D-03, 혁윤)  mark, words, correct, perfect
    5. feedback        (E-03·E-07, 혁윤) explanations, sejong
"""

from __future__ import annotations

from app.config import ENGINE_VERSION
from app.schemas import (
    AlignmentItem,
    CellResult,
    GradeRequest,
    GradeResponse,
    SejongMessage,
    Stage,
    WordResult,
)


def grade(req: GradeRequest) -> GradeResponse:
    """판정 요청 하나를 받아 결과를 돌려준다. (지금은 형식만 맞춘 임시 응답: 모든 칸 맞음)"""
    slots = _slots(req)
    cell_of_target = dict(slots)
    target_of_cell = {c: t for t, c in slots if c is not None}

    cells = []
    for cell in req.cells:
        t_idx = target_of_cell.get(cell.index)
        expected = req.target[t_idx] if t_idx is not None else None
        cells.append(
            CellResult(
                index=cell.index,
                expected=expected,
                recognized=expected if cell.strokes else " ",
                char_correct=True,
            )
        )

    words = []
    start = 0
    for text in req.target.split(" "):
        indexes = [cell_of_target[i] for i in range(start, start + len(text)) if cell_of_target[i] is not None]
        words.append(WordResult(text=text, cell_indexes=indexes, correct=True))
        start += len(text) + 1

    return GradeResponse(
        session_id=req.session_id,
        engine_version=ENGINE_VERSION,
        stage=req.stage,
        correct=True,
        perfect=True,
        cells=cells,
        alignment=[AlignmentItem(target_index=t, target_char=req.target[t], cell_index=c) for t, c in slots],
        words=words,
        sejong=SejongMessage(text="임시 응답이에요", expression="default"),
    )


def _slots(req: GradeRequest) -> list[tuple[int, int | None]]:
    """정답 문장의 각 자리(공백 포함) ↔ 칸 번호. 단계별 칸 규칙(schemas.Stage)대로 그대로 맞춘다.

    - 초보·중수: 공백을 뺀 글자와 칸이 1:1, 공백 자리는 칸이 없다 (None)
    - 고수: 정답 i번째 자리 ↔ i번째 칸 (빈 칸 = 띄어쓰기), 남는 뒤쪽 칸은 대응 없음
    """
    if req.stage == Stage.ADVANCED:
        return [(t, t if t < len(req.cells) else None) for t in range(len(req.target))]
    slots: list[tuple[int, int | None]] = []
    c_idx = 0
    for t, ch in enumerate(req.target):
        if ch == " ":
            slots.append((t, None))
        else:
            slots.append((t, c_idx))
            c_idx += 1
    return slots
