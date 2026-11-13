"""[혁윤] E-03·E-06 오답 설명 문장, 킹세종 말풍선 템플릿.

TODO: 틀린 곳마다 "바타라고 쓰셨는데 바다라고 써야 해요." 같은 설명 문장과 킹세종 말풍선을 만든다

입출력
- 입력: 요청(req, locale 포함), 묶은 결과(AggregateResult)
- 출력:
    explanations  → list[Explanation]  ('이렇게 고쳐요' 화면, 어절·획순 오류마다 한 줄)
    sejong_message → SejongMessage     (결과 화면 위 킹세종 말풍선, source = template)

문장 형식 (tests/fixtures/grade_response_*.json의 피그마 예시와 같게)
- text에는 따옴표를 넣지 않는다. 강조는 Explanation.wrong·right 필드로 따로 준다.
- 글자:     십었어라고 쓰셨는데 싶었어라고 써야 해요.      (wrong=십었어, right=싶었어)
- 띄어쓰기: 나너는 나 너로 띄어 써요.                      (wrong=나너, right=나 너)
- 획순:     다의 ㄷ은 위 가로획을 먼저 쓰고, …              (right=다, jamo=ㄷ)
- 조사(라고/이라고, 는/은, 로/으로)는 받침에 맞춘다 (core/hangul.has_batchim).
"""

from __future__ import annotations

from app.schemas import Explanation, GradeRequest, SejongMessage
from app.services.aggregate import AggregateResult


def explanations(req: GradeRequest, result: AggregateResult) -> list[Explanation]:
    """정답 공개 화면의 설명 문장 목록. 모두 맞으면 []."""
    raise NotImplementedError


def sejong_message(req: GradeRequest, result: AggregateResult) -> SejongMessage:
    """결과에 맞는 킹세종 말풍선 (칭찬·아쉬움·격려). LLM이 실패해도 항상 이 문장을 쓸 수 있다."""
    raise NotImplementedError
