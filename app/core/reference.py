"""[정진] D-08 정답 획 데이터 읽기 (정답 획 사전).

정답 획 사전 = data/extracted/<기본 폰트>/composed_all.json
- 현대 한글 11,172자 + 자모 단독 51개(초보 자모 연습)의 정답 획
- 만드는 법: python -m app.core.stroke_vectorizer.compose --all
  (extract로 재료를 다시 뽑았거나 editor로 수동 조정했으면 다시 만들어야 반영된다)
- 처음 부를 때 한 번 읽어 두고, 이후에는 사전에서 찾기만 한다 (서버는 compose()를 부르지 않음)

입출력 (정진님 명세 5번 compose() 출력과 같은 모양)
- 입력: 글자 하나 (음절, 초보용 자모 단독)
- 출력: ReferenceStroke 목록, order 순서 = 쓰는 순서
    order      : 글자 전체 기준 획 번호, 1부터
    jamo, role : 소속 자모와 자리 (cho / jung / jong)
    stroke_no  : 그 자모 안에서 몇 번째 획, 1부터
    points     : 획 중심선 [x, y], 0~1, 쓰는 방향 순서

쓰는 곳
- recognizer: 정답 그림 그리기 (모양 비교)
- stroke_checker: 획순·방향·균형 비교
"""

from __future__ import annotations

import json
from functools import cache
from typing import Any

from app.core.stroke_vectorizer.compose import composed_path, relative_to_root
from app.schemas import ReferenceStroke


@cache
def _table() -> dict[str, list[dict[str, Any]]]:
    """정답 획 사전 (글자 → compose 형식 획 목록). 처음 한 번만 파일에서 읽는다."""
    path = composed_path()
    if not path.exists():
        raise FileNotFoundError(
            f"정답 획 사전이 없어요 ({relative_to_root(path)}). "
            "먼저 실행: python -m app.core.stroke_vectorizer.compose --all"
        )
    with open(path, encoding="utf-8") as f:
        table: dict[str, list[dict[str, Any]]] = json.load(f)
    return table


def get_reference(char: str) -> list[ReferenceStroke]:
    """글자 하나의 정답 획. 데이터에 없는 글자면 KeyError."""
    strokes = sorted(_table()[char], key=lambda s: s["order"])
    seen: dict[tuple[str, str], int] = {}
    out = []
    for s in strokes:
        key = (s["role"], s["jamo"])
        seen[key] = seen.get(key, 0) + 1
        out.append(
            ReferenceStroke(
                order=s["order"],
                jamo=s["jamo"],
                role=s["role"],
                stroke_no=seen[key],
                points=[(x, y) for x, y in s["points"]],
            )
        )
    return out


def has_reference(char: str) -> bool:
    """정답 획 데이터가 있는 글자인지 (인식 후보를 고를 때 사용)."""
    return char in _table()
