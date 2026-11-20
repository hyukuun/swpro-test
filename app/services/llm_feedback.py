"""[혁윤] E-07 킹세종 LLM 한마디 (P1, 실패 시 템플릿).

Gemini Flash로 결과 화면 위 킹세종 말풍선을 학습자에게 맞는 말투로 바꾼다.
판정은 엔진이 하고 LLM은 말투만 바꾼다. 표정(expression)도 템플릿 기준 그대로 쓴다.

입출력
- 입력: 요청(req), 묶은 결과(AggregateResult)
  LLM에는 정답 문장, 틀린 곳 설명(엔진이 칸별 errors로 만든 템플릿 문장), 언어만 넘긴다 (정진님 명세 4번).
  학습자 손글씨·세션 정보는 보내지 않는다.
- 출력: SejongMessage(source = llm). 아래 경우에는 None → feedback_templates.sejong_message를 쓴다
    - GEMINI_API_KEY가 없음 (config.py)
    - 설명할 틀린 곳이 없음 (다 맞음, 균형만 통과 못 함, 획 판정을 못 함) → 미리 써 둔 템플릿 문구
    - 시간 초과(LLM_TIMEOUT_MS)·호출 실패·형식이 이상한 답 (빈 문장, 너무 긴 문장)
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from app import config
from app.schemas import GradeRequest, SejongMessage
from app.services import feedback_templates
from app.services.aggregate import AggregateResult

log = logging.getLogger(__name__)

MAX_LEN = 60  # 말풍선 한 줄 최대 글자 수 (넘으면 화면이 깨질 수 있어 템플릿을 쓴다)

SYSTEM = (
    "You are King Sejong, the creator of Hangul, gently teaching Korean handwriting to a foreign learner "
    "who just traced K-pop lyrics. Write a speech bubble with exactly two lines: "
    "text = a short, warm first line (at most 20 characters); "
    "sub_text = one sentence saying what to look at again (at most 40 characters). "
    "Do not invent mistakes: mention only the mistakes given. Do not use quotation marks or emoji. "
    "Write in the language requested."
)


class _Bubble(BaseModel):
    """LLM이 돌려줄 형식."""

    text: str
    sub_text: str


_client: Any = None


def _gemini() -> Any:
    """Gemini 클라이언트 (처음 부를 때 한 번 만든다). 재시도 없이 시간 제한만 둔다."""
    global _client
    if _client is None:
        from google import genai
        from google.genai import types

        _client = genai.Client(
            api_key=config.GEMINI_API_KEY,
            http_options=types.HttpOptions(
                timeout=config.LLM_TIMEOUT_MS, retry_options=types.HttpRetryOptions(attempts=1)
            ),
        )
    return _client


def _ask(prompt: str) -> _Bubble | None:
    """Gemini에 묻고 답을 _Bubble로 받는다."""
    from google.genai import types

    response = _gemini().models.generate_content(
        model=config.LLM_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM,
            response_mime_type="application/json",
            response_schema=_Bubble,
            temperature=0.7,
        ),
    )
    parsed = response.parsed
    return parsed if isinstance(parsed, _Bubble) else None


def sejong_line(req: GradeRequest, result: AggregateResult) -> SejongMessage | None:
    """킹세종 말투 한마디. 실패하거나 쓸 필요가 없으면 None."""
    if not config.GEMINI_API_KEY:
        return None
    mistakes = [e.text for e in feedback_templates.explanations(req, result)]
    if not mistakes:
        return None
    language = "English" if req.locale == "en" else "Korean"
    prompt = f"Language: {language}\nTarget sentence: {req.target}\nMistakes:\n" + "\n".join(f"- {m}" for m in mistakes)
    try:
        bubble = _ask(prompt)
    except Exception as e:  # 시간 초과·키 오류·네트워크 등: 화면은 템플릿으로
        log.warning("LLM 말풍선 실패, 템플릿을 씀: %s", type(e).__name__)
        return None
    if bubble is None:
        log.warning("LLM 말풍선 형식이 이상해 템플릿을 씀")
        return None
    text, sub_text = bubble.text.strip(), bubble.sub_text.strip()
    if not text or not sub_text or len(text) > MAX_LEN or len(sub_text) > MAX_LEN:
        log.warning("LLM 말풍선이 비었거나 너무 길어 템플릿을 씀")
        return None
    expression = feedback_templates.sejong_message(req, result).expression  # 표정은 판정 결과로 정한다
    return SejongMessage(text=text, sub_text=sub_text, expression=expression, source="llm")
