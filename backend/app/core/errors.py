"""Tratamento de erros: o cliente recebe apenas mensagens genéricas."""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


async def _unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    # Registra só o tipo da exceção e a rota: a mensagem pode conter dados sensíveis.
    logger.error("Erro não tratado (%s) em %s", type(exc).__name__, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Erro interno."})


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(Exception, _unhandled_exception)
