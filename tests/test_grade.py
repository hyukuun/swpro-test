"""/grade 입출력 형식 테스트.

- 피그마 장면 예시 요청 3개가 /grade에서 200으로 처리되고, 응답이 GradeResponse 형식인지
- 잘못된 요청이 422로 거절되는지
- 예시 응답 JSON이 형식에 맞는지
- docs/schema 파일이 schemas.py와 같은지 (고치고 다시 내보내기를 잊지 않게)

판정 결과의 내용(어느 칸이 틀렸는지)은 판정 로직을 넣을 때 테스트한다. 지금 /grade는 형식만 맞춘 임시 응답이다.
"""

import pytest

from app.schemas import GradeResponse
from scripts.export_json_schema import MODELS, OUT_DIR, render
from tests.helpers import STAGES, client
from tests.helpers import load_fixture as load


@pytest.mark.parametrize("stage", STAGES)
def test_grade_accepts_figma_examples(stage):
    req = load(f"grade_request_{stage}.json")
    res = client.post("/grade", json=req)
    assert res.status_code == 200, res.text
    body = res.json()
    GradeResponse.model_validate(body)
    assert body["stage"] == stage
    assert body["sessionId"] == req["sessionId"]
    assert len(body["cells"]) == len(req["cells"])
    # 정답 비교 화면: 정답 문장의 모든 자리(공백 포함)가 alignment에 있다
    assert [a["targetIndex"] for a in body["alignment"]] == list(range(len(req["target"])))


def test_response_is_camel_case():
    body = client.post("/grade", json=load("grade_request_beginner.json")).json()
    assert {"engineVersion", "charCorrect"} <= set(body) | set(body["cells"][0])
    assert "engine_version" not in body


def bad(**change) -> dict:
    return {**load("grade_request_intermediate.json"), **change}


@pytest.mark.parametrize(
    "req, why",
    [
        (bad(cells=load("grade_request_intermediate.json")["cells"][:4]), "중수 칸 수가 정답 글자 수와 다름"),
        (bad(canvas={"w": 0, "h": 300}), "칸 크기 0"),
        ({k: v for k, v in bad().items() if k != "canvas"}, "canvas 없음"),
        (bad(stage="expert"), "없는 단계"),
        (bad(cells=[{"index": 0, "strokes": [{"points": []}]}] * 5), "점 없는 획"),
        (bad(cells=[{"index": 0, "strokes": [{"points": [{"x": 1, "y": 2, "t": 0, "p": 0.5}]}]}] * 5), "예전 점 형식"),
    ],
)
def test_grade_rejects_bad_requests(req, why):
    assert client.post("/grade", json=req).status_code == 422, why


@pytest.mark.parametrize("stage", STAGES)
def test_example_responses_match_schema(stage):
    GradeResponse.model_validate(load(f"grade_response_{stage}.json"))


@pytest.mark.parametrize("name", list(MODELS))
def test_exported_json_schema_is_up_to_date(name):
    path = OUT_DIR / f"{name}.schema.json"
    assert path.read_text(encoding="utf-8") == render(MODELS[name]), (
        "schemas.py가 바뀌었어요. `python -m scripts.export_json_schema`로 다시 내보내세요."
    )
