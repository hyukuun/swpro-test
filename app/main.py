"""[혁윤] FastAPI 엔드포인트 (스프링부트와 통신).

- POST /grade            : 판정 요청(GradeRequest) → 판정 결과(GradeResponse)
- GET  /reference/{글자} : 글자 하나의 정답 획(ReferenceResponse). 초보 회색 가이드, 정답 리플레이용
- GET  /health           : 살아 있는지 + engineVersion
- 필드 설명은 서버를 띄운 뒤 /docs 에서 볼 수 있다.

지금 /grade는 띄어쓰기·획순 판정은 진짜, 글자 인식은 임시다 (app/pipeline.py 참고).
"""

import re

from fastapi import FastAPI

from app import errors, pipeline
from app.config import ENGINE_VERSION
from app.core import reference
from app.errors import EngineError
from app.schemas import ErrorCode, ErrorDetail, GradeRequest, GradeResponse, HealthResponse, ReferenceResponse

app = FastAPI(title="Correction Engine", version=ENGINE_VERSION)
errors.register(app)  # 오류는 모두 ErrorResponse 모양으로 (app/errors.py)

REFERENCE_CHAR = re.compile(r"[가-힣ㄱ-ㅣ]")  # /reference가 받는 글자: 한글 음절 또는 자모 하나


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """살아 있는지 확인. engineVersion이 '-stub'으로 끝나면 글자 인식 등 일부가 아직 임시다."""
    return HealthResponse(engine_version=ENGINE_VERSION)


@app.post("/grade", response_model=GradeResponse)
def grade(req: GradeRequest) -> GradeResponse:
    """제출된 원고지 칸 배열을 판정한다. 실패하면 ErrorResponse (400 / 422 / 500)."""
    return pipeline.grade(req)


@app.get("/reference/{char}", response_model=ReferenceResponse)
def get_reference(char: str) -> ReferenceResponse:
    """글자 하나의 정답 획 (쓰는 순서대로). 글자는 URL 인코딩해서 보낸다 (가 → %EA%B0%80).

    실패하면 ErrorResponse: 한글 음절·자모 한 글자가 아님 422 / 정답 획 데이터에 없는 글자 404 /
    엔진에 정답 획 사전이 없음 503
    """
    if not REFERENCE_CHAR.fullmatch(char):
        detail = ErrorDetail(field="char", message="한글 음절이나 자모 한 글자만 쓸 수 있어요")
        raise EngineError(ErrorCode.INVALID_REQUEST, "요청 값이 규칙에 맞지 않아요 (1개)", [detail])
    if not reference.reference_available():
        raise EngineError(ErrorCode.REFERENCE_UNAVAILABLE, "엔진에 정답 획 데이터가 없어요")
    if not reference.has_reference(char):
        raise EngineError(ErrorCode.NOT_FOUND, f"정답 획 데이터에 없는 글자예요: {char}")
    return ReferenceResponse(char=char, strokes=reference.get_reference(char), engine_version=ENGINE_VERSION)
