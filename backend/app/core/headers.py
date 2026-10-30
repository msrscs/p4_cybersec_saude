"""Headers de segurança em toda resposta da API (defesa em profundidade, ADR-0013).

A API não é exposta diretamente, mas qualquer resposta que chegue a um navegador não pode
ser enquadrada, interpretada como outro tipo, guardada em cache nem executar conteúdo.
"""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

CABECALHOS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
}
CSP_API = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
# Swagger (só fora de produção) carrega scripts e estilos próprios.
_ROTAS_DOCUMENTACAO = ("/docs", "/openapi.json")


def registrar_headers_seguranca(app: FastAPI) -> None:
    @app.middleware("http")
    async def _headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for nome, valor in CABECALHOS.items():
            response.headers.setdefault(nome, valor)
        if not request.url.path.startswith(_ROTAS_DOCUMENTACAO):
            response.headers.setdefault("Content-Security-Policy", CSP_API)
            response.headers.setdefault("Cache-Control", "no-store")
        return response
