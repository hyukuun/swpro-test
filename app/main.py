"""[혁윤] FastAPI 엔드포인트 (스프링부트와 통신).

- POST /grade  : 판정 요청(GradeRequest) → 판정 결과(GradeResponse)
- GET  /health : 살아 있는지 + engineVersion
- 필드 설명은 서버를 띄운 뒤 /docs 에서 볼 수 있다.

지금 /grade는 형식만 맞춘 임시 응답이다 (app/pipeline.py 참고).
"""

from fastapi import FastAPI

from app import errors, pipeline
from app.config import ENGINE_VERSION
from app.schemas import GradeRequest, GradeResponse, HealthResponse

app = FastAPI(title="Correction Engine", version=ENGINE_VERSION)
errors.register(app)  # 오류는 모두 ErrorResponse 모양으로 (app/errors.py)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """살아 있는지 확인. engineVersion이 '-stub'으로 끝나면 임시 응답 중이다."""
    return HealthResponse(engine_version=ENGINE_VERSION)


@app.post("/grade", response_model=GradeResponse)
def grade(req: GradeRequest) -> GradeResponse:
    """제출된 원고지 칸 배열을 판정한다. 실패하면 ErrorResponse (400 / 422 / 500)."""
    return pipeline.grade(req)
