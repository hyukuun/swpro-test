"""오류 응답 (app/errors.py): 성공이 아니면 항상 ErrorResponse 한 가지 모양인지."""

import json

from app import pipeline
from app.schemas import ErrorResponse
from tests.helpers import load_request as load
from tests.helpers import safe_client as client


def check(res, status: int, code: str) -> dict:
    assert res.status_code == status, res.text
    body = res.json()
    ErrorResponse.model_validate(body)  # 모양이 같은지
    assert body["code"] == code
    assert body["engineVersion"]
    return body


def test_invalid_json_is_400():
    res = client.post("/grade", content=b"{bad json", headers={"content-type": "application/json"})
    check(res, 400, "INVALID_JSON")


def test_rule_violation_is_422_with_reason():
    body = check(client.post("/grade", json={**load("beginner"), "target": "나 너"}), 422, "INVALID_REQUEST")
    assert body["details"] == [{"field": None, "message": "초보는 띄어쓰기 없는 단어 하나(또는 자모 하나)만 써요"}]


def test_field_error_has_path():
    req = load("intermediate")
    req["canvas"]["w"] = 0  # 칸 크기 0
    req["typo"] = 1  # 모르는 필드
    body = check(client.post("/grade", json=req), 422, "INVALID_REQUEST")
    fields = {d["field"]: d["message"] for d in body["details"]}
    assert set(fields) == {"canvas.w", "typo"}


def test_unknown_path_is_404():
    check(client.get("/nope"), 404, "NOT_FOUND")


def test_wrong_method_is_405():
    check(client.get("/grade"), 405, "METHOD_NOT_ALLOWED")


def test_internal_error_is_500_without_leaking_details(monkeypatch):
    def broken(_req):
        raise RuntimeError("secret path C:/engine/data.json")

    monkeypatch.setattr(pipeline, "grade", broken)
    body = check(client.post("/grade", json=load("beginner")), 500, "INTERNAL_ERROR")
    assert "secret" not in json.dumps(body)


def test_success_is_unchanged():
    res = client.post("/grade", json=load("beginner"))
    assert res.status_code == 200 and "code" not in res.json()
