"""[혁윤] D-03 단계별 결과 묶기 (칸/어절/문장).

TODO: 판정 결과를 학습 단계에 맞게 칸·어절·문장 단위로 묶어 빨간 박스 위치를 정한다

입출력
- 입력: 요청(req), 인식 결과(recognitions), 정렬 결과(alignment), 칸별 획 판정 결과(strokes)
- 출력: AggregateResult (응답 GradeResponse의 cells·alignment·words·correct·perfect)

규칙 (schemas.Mark 참고)
- 칸 mark: 글자 오류 → char(빨강) / 띄어쓰기 오류 → spacing(빨강) / 획 오류 → stroke(주황) / 맞음 → none
- ORDER·DIRECTION·MISSING·EXTRA는 stroke로 묶는다. BALANCE는 아직 none (디자인 확정 전)
- correct: 글자 + 띄어쓰기가 모두 맞음 / perfect: correct이고 mark가 stroke인 칸도 없음
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas import AlignmentItem, CellResult, GradeRequest, WordResult
from app.services.recognizer import Recognition
from app.services.spacing_align import AlignmentResult
from app.services.stroke_checker import StrokeCheckResult


@dataclass(frozen=True)
class AggregateResult:
    """응답에 들어갈 판정 결과 묶음."""

    cells: list[CellResult]  # 요청 cells와 같은 순서·개수
    alignment: list[AlignmentItem]  # AlignmentResult.items에 mark를 채운 것
    words: list[WordResult]  # 정답 문장의 어절마다 하나 (중수 빨간 상자)
    correct: bool
    perfect: bool


def aggregate(
    req: GradeRequest,
    recognitions: list[Recognition],
    alignment: AlignmentResult,
    strokes: dict[int, StrokeCheckResult],  # 칸 번호 → 획 판정 결과. 획 검사를 안 한 칸은 없음
) -> AggregateResult:
    """인식·정렬·획 판정 결과를 화면에 쓸 모양으로 묶는다."""
    raise NotImplementedError
