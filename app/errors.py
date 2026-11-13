"""[혁윤] 오류 응답 (스프링부트와 통신).

판정하지 못한 모든 경우를 schemas.ErrorResponse 한 가지 모양으로 돌려준다.

| 상황                         | HTTP | code               |
|------------------------------|------|--------------------|
| 본문이 JSON이 아님           | 400  | INVALID_JSON       |
| 요청 검사 규칙을 어김        | 422  | INVALID_REQUEST    |
| 없는 주소                    | 404  | NOT_FOUND          |
| GET/POST가 다름              | 405  | METHOD_NOT_ALLOWED |
| 그 밖의 엔진 내부 오류       | 500  | INTERNAL_ERROR     |

500은 내부 내용(파일 경로, 오류 원문)을 응답에 넣지 않고 서버 로그에만 남긴다.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import ENGINE_VERSION
from app.schemas import ErrorCode, ErrorDetail, ErrorResponse

log = logging.getLogger(__name__)

STATUS_OF = {
    ErrorCode.INVALID_JSON: 400,
    ErrorCode.INVALID_REQUEST: 422,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.METHOD_NOT_ALLOWED: 405,
    ErrorCode.INTERNAL_ERROR: 500,
}


def error_response(code: ErrorCode, message: str, details: list[ErrorDetail] | None = None) -> JSONResponse:
    body = ErrorResponse(code=code, message=message, details=details or [], engine_version=ENGINE_VERSION)
    return JSONResponse(status_code=STATUS_OF[code], content=body.model_dump(by_alias=True, mode="json"))


def _field_path(loc: tuple) -> str | None:
    """('body', 'cells', 0, 'strokes', 1, 'points') → 'cells[0].strokes[1].points'. 요청 전체면 None."""
    path = ""
    for part in loc[1:] if loc and loc[0] == "body" else loc:
        path += f"[{part}]" if isinstance(part, int) else (f".{part}" if path else str(part))
    return path or None


def _message(err: dict) -> str:
    """schemas.py의 우리 규칙은 그 문장 그대로, 나머지는 pydantic 기본 문장."""
    if err["type"] == "value_error":
        return str(err.get("ctx", {}).get("error", err["msg"]))
    return err["msg"]


# 처리 함수는 Starlette 규칙대로 (Request, Exception)을 받는다. 종류는 등록할 때 정해진다.


async def _on_validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = exc.errors()
    if any(e["type"] == "json_invalid" for e in errors):
        return error_response(ErrorCode.INVALID_JSON, "요청 본문이 올바른 JSON이 아니에요")
    details = [ErrorDetail(field=_field_path(tuple(e["loc"])), message=_message(e)) for e in errors]
    return error_response(ErrorCode.INVALID_REQUEST, f"요청 값이 규칙에 맞지 않아요 ({len(details)}개)", details)


async def _on_http_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    if exc.status_code == 404:
        return error_response(ErrorCode.NOT_FOUND, "없는 주소예요")
    if exc.status_code == 405:
        return error_response(ErrorCode.METHOD_NOT_ALLOWED, "이 주소에서 쓸 수 없는 방식(GET/POST)이에요")
    if exc.status_code == 400:
        return error_response(ErrorCode.INVALID_JSON, "요청을 읽을 수 없어요")
    return error_response(ErrorCode.INTERNAL_ERROR, "요청을 처리하지 못했어요")


async def _on_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    log.exception("엔진 내부 오류", exc_info=exc)
    return error_response(ErrorCode.INTERNAL_ERROR, "엔진 내부 오류가 났어요. 잠시 뒤 다시 시도해 주세요")


def register(app: FastAPI) -> None:
    """main.py에서 한 번 부른다."""
    app.add_exception_handler(RequestValidationError, _on_validation_error)
    app.add_exception_handler(StarletteHTTPException, _on_http_error)
    app.add_exception_handler(Exception, _on_unexpected_error)
