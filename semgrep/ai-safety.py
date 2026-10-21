"""Semgrep annotations for the repository's AI-safety policy."""

import logging

from fastapi import HTTPException
from fastapi.responses import JSONResponse


def raw_http_exception(exception: Exception) -> None:
    # ruleid: marketos-fastapi-raw-exception-detail
    raise HTTPException(status_code=500, detail=str(exception))


def raw_http_exception_repr(exception: Exception) -> None:
    # ruleid: marketos-fastapi-raw-exception-detail
    raise HTTPException(status_code=500, detail=repr(exception))


def raw_http_exception_fstring(exception: Exception) -> None:
    # ruleid: marketos-fastapi-raw-exception-detail
    raise HTTPException(status_code=500, detail=f"request failed: {exception}")


def raw_error_object(exception: Exception) -> dict[str, str]:
    # ruleid: marketos-fastapi-raw-exception-detail
    return {"error": str(exception)}


def raw_detail_object(exception: Exception) -> dict[str, str]:
    # ruleid: marketos-fastapi-raw-exception-detail
    return {"detail": str(exception)}


def raw_json_response(exception: Exception) -> JSONResponse:
    # ruleid: marketos-fastapi-raw-exception-detail
    return JSONResponse({"message": str(exception)}, status_code=500)


def stable_http_exception(exception: Exception) -> None:
    # ok: marketos-fastapi-raw-exception-detail
    raise HTTPException(status_code=500, detail="internal_error")


def typed_http_exception(exception: Exception) -> None:
    # ok: marketos-fastapi-raw-exception-detail
    raise HTTPException(
        status_code=500,
        detail={"code": "internal_error", "type": type(exception).__name__},
    )


def stable_error_object(exception: Exception) -> dict[str, str]:
    # ok: marketos-fastapi-raw-exception-detail
    return {"error": "internal_error"}


def server_only_logging(exception: Exception) -> None:
    logger = logging.getLogger(__name__)
    # ok: marketos-fastapi-raw-exception-detail
    logger.exception("request failed", exc_info=exception)
