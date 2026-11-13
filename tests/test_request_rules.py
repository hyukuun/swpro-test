"""요청 검사 규칙 (schemas.GradeRequest 설명, README '요청 검사 규칙')이 지켜지는지.

규칙마다 맞는 요청 하나는 통과, 어긴 요청은 /grade에서 422.
"""

import copy

import pytest

from tests.helpers import client
from tests.helpers import load_request as load

STROKE = {"points": [[60, 60, 0, 0.5], [240, 60, 100, 0.5]]}


def make(stage: str, target: str, n_cells: int | None = None) -> dict:
    """target에 맞는 최소 요청 (칸마다 획 하나, 고수는 띄어쓰기 자리 빈 칸)."""
    if n_cells is None:
        n_cells = len(target) if stage == "advanced" else len(target.replace(" ", ""))
    chars = list(target) if stage == "advanced" else list(target.replace(" ", ""))
    cells = []
    for i in range(n_cells):
        ch = chars[i] if i < len(chars) else " "
        cells.append({"index": i, "strokes": [] if ch == " " else [copy.deepcopy(STROKE)]})
    return {"stage": stage, "target": target, "canvas": {"w": 300, "h": 300}, "cells": cells}


def status(body: dict) -> int:
    return client.post("/grade", json=body).status_code


# ----------------------------------------------------------------- 통과해야 하는 요청


@pytest.mark.parametrize(
    "body",
    [
        make("beginner", "ㄱ"),  # 초보 자모 하나
        make("beginner", "바다"),
        make("intermediate", "보고 싶었어"),
        make("intermediate", "나는 너를 좋아해"),  # 어절 3개
        make("advanced", "나 너 좋아하냐?", n_cells=11),  # 칸 넉넉히
        make("advanced", "가나다라마바사아자 카타파하가나다라마바"),  # 9 + 공백 + 10 = 20칸
    ],
    ids=["자모", "단어", "중수 2어절", "중수 3어절", "고수 +2칸", "고수 20칸"],
)
def test_valid_requests(body):
    assert status(body) == 200


# ----------------------------------------------------------------- 422가 나야 하는 요청


def change(stage: str, **kw) -> dict:
    return {**load(stage), **kw}


BAD = [
    # 정답 문장
    (make("advanced", "hello"), "영어"),
    (make("advanced", "나 1번"), "숫자"),
    (make("advanced", "가나다라마바사아자차 카타파하가나다라마바"), "21칸"),  # 10 + 공백 + 10
    (make("advanced", " 나 너"), "앞 공백"),
    (make("advanced", "나  너"), "연속 공백"),
    (make("advanced", "나~"), "허용 안 된 문장부호"),
    # 단계별 규칙
    (make("beginner", "나 너"), "초보 띄어쓰기"),
    (make("beginner", "ㄱㄴ"), "자모 두 개"),
    (make("intermediate", "ㄱ"), "중수 자모"),
    (make("intermediate", "나는 너를 정말 좋아해"), "중수 어절 4개"),
    # 칸
    (make("advanced", "나 너 좋아하냐?", n_cells=8), "고수 칸 부족"),
    (make("advanced", "나", n_cells=31), "칸 31개"),
    (change("intermediate", cells=list(reversed(load("intermediate")["cells"]))), "칸 순서 뒤집힘"),
    (change("intermediate", cells=load("intermediate")["cells"][:4]), "중수 칸 수 다름"),
    # 칸 크기
    (change("intermediate", canvas={"w": 0, "h": 300}), "칸 크기 0"),
    # 필드
    (change("intermediate", targetText="보고 싶었어"), "모르는 필드"),
]


@pytest.mark.parametrize("body, why", BAD, ids=[why for _, why in BAD])
def test_invalid_requests(body, why):
    assert status(body) == 422, why


def test_error_message_is_readable():
    res = client.post("/grade", json=make("beginner", "나 너"))
    assert "초보는 띄어쓰기 없는 단어 하나" in res.text
