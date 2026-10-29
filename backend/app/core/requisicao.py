"""Contexto da requisição: request_id gerado no servidor e IP de origem."""

import ipaddress
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from app.core.config import Settings
from app.services.auditoria import ContextoRequisicao


def registrar_request_id(app: FastAPI) -> None:
    @app.middleware("http")
    async def _request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Sempre gerado aqui: um valor vindo do cliente não é confiável para auditoria.
        request.state.request_id = str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response


def _ip_valido(valor: str | None) -> str | None:
    if valor is None:
        return None
    try:
        return str(ipaddress.ip_address(valor))
    except ValueError:
        return None


def contexto_requisicao(request: Request) -> ContextoRequisicao:
    ip = _ip_valido(request.client.host if request.client else None)
    return ContextoRequisicao(ip=ip, request_id=getattr(request.state, "request_id", None))


def obter_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings
