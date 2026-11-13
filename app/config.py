"""환경변수 설정."""

import os

# 응답의 engineVersion. 판정 로직이 붙기 전(임시 응답) 동안은 "-stub"을 붙여 백엔드가 구분할 수 있게 한다.
ENGINE_VERSION = os.getenv("ENGINE_VERSION", "0.1.0-stub")
