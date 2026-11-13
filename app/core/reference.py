"""[정진] D-08 정답 획 데이터 읽기 (compose() 결과 사전).

TODO: 정답 획 사전을 서버 시작 때 한 번 읽고, 글자로 정답 획을 꺼내 준다

입출력 (정진님 명세 5번 compose() 출력과 같은 모양)
- 입력: 글자 하나 (음절, 초보용 자모 단독)
- 출력: ReferenceStroke 목록, order 순서 = 쓰는 순서
    order      : 글자 전체 기준 획 번호, 1부터
    jamo, role : 소속 자모와 자리 (cho / jung / jong)
    points     : 획 중심선 [x, y], 0~1, 쓰는 방향 순서

쓰는 곳
- recognizer: 정답 그림 그리기 (모양 비교)
- stroke_checker: 획순·방향·균형 비교
"""

from __future__ import annotations

from app.schemas import ReferenceStroke


def get_reference(char: str) -> list[ReferenceStroke]:
    """글자 하나의 정답 획. 데이터에 없는 글자면 KeyError."""
    raise NotImplementedError


def has_reference(char: str) -> bool:
    """정답 획 데이터가 있는 글자인지 (인식 후보를 고를 때 사용)."""
    raise NotImplementedError
