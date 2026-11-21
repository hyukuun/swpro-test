"""환경변수 설정."""

import os

# 응답의 engineVersion. 판정의 일부(글자 인식 등)가 아직 임시인 동안은 "-stub"을 붙여 백엔드가 구분할 수 있게 한다.
ENGINE_VERSION = os.getenv("ENGINE_VERSION", "0.1.0-stub")

# 킹세종 LLM 말풍선 (services/llm_feedback.py). 키가 없으면 LLM을 쓰지 않고 템플릿 말풍선만 쓴다.
# 키는 Google AI Studio에서 발급한다. 절대 깃에 올리지 않는다 (서버 환경변수로만 넣는다).
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
LLM_MODEL = os.getenv(
    "LLM_MODEL", "gemini-3.5-flash-lite"
)  # 무료 등급이 있는 Flash-Lite (2026-11 확인). 바꾸려면 이름을 넣는다
LLM_TIMEOUT_MS = int(os.getenv("LLM_TIMEOUT_MS", "3000"))  # 이 시간 안에 답이 없으면 템플릿 말풍선
