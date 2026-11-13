"""[혁윤] E-07 킹세종 LLM 한마디 (P1, 실패 시 템플릿).

TODO: LLM으로 킹세종 격려 한마디를 만들고, 실패하면 템플릿 문장을 쓴다

입출력
- 입력: 요청(req), 묶은 결과(AggregateResult)
  LLM에는 정답 문장과 칸별 errors만 넘긴다 (정진님 명세 4번). 판정은 엔진이 하고 LLM은 말투만 바꾼다.
- 출력: SejongMessage(source = llm). 아래 경우에는 None → feedback_templates.sejong_message를 쓴다
    - LLM을 쓰지 않도록 설정됨
    - 오류가 없음 (perfect) → 미리 써 둔 칭찬 문구
    - 시간 초과·호출 실패
"""

from __future__ import annotations

from app.schemas import GradeRequest, SejongMessage
from app.services.aggregate import AggregateResult


async def sejong_line(req: GradeRequest, result: AggregateResult) -> SejongMessage | None:
    """킹세종 말투 한마디. 실패하거나 쓸 필요가 없으면 None."""
    raise NotImplementedError
