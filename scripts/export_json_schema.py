"""스키마를 JSON Schema 파일로 내보낸다. 백엔드는 이 파일을 보고 자바 DTO를 만든다.

실행: python -m scripts.export_json_schema
결과: docs/schema/grade_request·grade_response·error_response·health_response.schema.json

schemas.py를 고치면 다시 실행해서 파일도 같이 커밋한다. (tests/test_grade.py가 최신인지 검사한다)
"""

import json
from pathlib import Path

from app.schemas import ErrorResponse, GradeRequest, GradeResponse, HealthResponse

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "schema"
MODELS = {
    "grade_request": GradeRequest,
    "grade_response": GradeResponse,
    "error_response": ErrorResponse,
    "health_response": HealthResponse,
}


def render(model) -> str:
    return json.dumps(model.model_json_schema(by_alias=True), ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, model in MODELS.items():
        path = OUT_DIR / f"{name}.schema.json"
        path.write_text(render(model), encoding="utf-8")
        print(f"wrote {path.relative_to(OUT_DIR.parent.parent)}")


if __name__ == "__main__":
    main()
