"""모든 테스트 공통 설정."""

import pytest

from app import config


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    """컴퓨터에 GEMINI_API_KEY가 있어도 테스트는 진짜 Gemini를 부르지 않는다 (LLM 테스트는 키를 직접 넣는다)."""
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
