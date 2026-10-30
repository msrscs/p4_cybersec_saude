"""Dependências HTTP: sessão autenticada, autorização RBAC e cookies de autenticação."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session, sessionmaker

from app.core.crypto import csrf_valido
from app.core.database import get_db
from app.core.requisicao import contexto_requisicao, obter_settings
from app.repositories import usuario as usuario_repo
from app.services import auditoria, autorizacao
from app.services import limite as limite_svc
from app.services import sessao as sessao_svc
from app.services.auditoria import ContextoRequisicao, Evento
from app.services.autorizacao import Permissao
from app.services.limite import Limite
from app.services.sessao import SessaoAtual

COOKIE_PRE_AUTH = "pre_auth"
PATH_PRE_AUTH = "/auth/mfa"
COOKIE_SESSAO = "__Host-sessao"  # prefixo __Host-: exige Secure, Path=/ e sem Domain

Db = Annotated[Session, Depends(get_db)]
Ctx = Annotated[ContextoRequisicao, Depends(contexto_requisicao)]
METODOS_SEGUROS = frozenset({"GET", "HEAD", "OPTIONS"})
CABECALHO_CSRF = "X-CSRF-Token"


def agora() -> datetime:
    return datetime.now(UTC)


def definir_pre_auth(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_PRE_AUTH,
        token,
        max_age=int(sessao_svc.VALIDADE_PRE_AUTH.total_seconds()),
        path=PATH_PRE_AUTH,
        secure=True,
        httponly=True,
        samesite="strict",
    )


def definir_sessao(response: Response, token: str) -> None:
    # Sem Max-Age: some ao fechar o navegador; a expiração real é controlada no servidor.
    response.set_cookie(
        COOKIE_SESSAO, token, path="/", secure=True, httponly=True, samesite="strict"
    )
    response.delete_cookie(
        COOKIE_PRE_AUTH, path=PATH_PRE_AUTH, secure=True, httponly=True, samesite="strict"
    )


def apagar_sessao(response: Response) -> None:
    response.delete_cookie(COOKIE_SESSAO, path="/", secure=True, httponly=True, samesite="strict")


def sessao_atual(request: Request, db: Db, ctx: Ctx) -> SessaoAtual:
    atual = sessao_svc.validar(db, request.cookies.get(COOKIE_SESSAO), agora())
    if atual is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Não autenticado.")
    if request.method not in METODOS_SEGUROS:
        settings = obter_settings(request)
        enviado = request.headers.get(CABECALHO_CSRF)
        if not csrf_valido(settings.chave_hmac, atual.token_hash, enviado):
            rota = getattr(request.scope.get("route"), "path", "")
            resumo = {"metodo": request.method, "rota": rota, "token_enviado": bool(enviado)}
            _em_transacao_propria(
                request,
                lambda outra: auditoria.registrar(
                    outra, Evento.CSRF_REJECTED, ctx, cpf_usuario_hash=atual.cpf_hash, resumo=resumo
                ),
            )
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Requisição recusada.")
    return atual


Sessao = Annotated[SessaoAtual, Depends(sessao_atual)]


def usuario_liberado(atual: Sessao, db: Db) -> SessaoAtual:
    """Base das rotas protegidas: exige sessão completa e senha já trocada após reset."""
    usuario = usuario_repo.buscar(db, atual.cpf_hash)
    if usuario is None or usuario.status != "ativo":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Não autenticado.")
    if usuario.troca_senha_obrigatoria:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Troca de senha obrigatória.")
    return atual


SessaoLiberada = Annotated[SessaoAtual, Depends(usuario_liberado)]


def exigir(permissao: Permissao) -> Callable[..., SessaoAtual]:
    """Dependência de rota: sessão liberada + permissão RBAC, verificada a cada requisição."""

    def dependencia(request: Request, atual: SessaoLiberada, db: Db, ctx: Ctx) -> SessaoAtual:
        if autorizacao.tem_permissao(db, atual.cpf_hash, permissao):
            return atual
        _em_transacao_propria(
            request,
            lambda outra: autorizacao.registrar_negado(outra, atual.cpf_hash, permissao, ctx),
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Acesso negado.")

    return dependencia


def limitar(limites: tuple[Limite, ...]) -> Callable[..., None]:
    """Dependência de rota: limite de requisições por IP (429 + Retry-After)."""

    def dependencia(request: Request, ctx: Ctx) -> None:
        if not obter_settings(request).limite_requisicoes_ativo:
            return
        espera = _em_transacao_propria(
            request, lambda outra: limite_svc.verificar(outra, limites, ctx, agora())
        )
        if espera is not None:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Muitas requisições. Tente novamente mais tarde.",
                headers={"Retry-After": str(espera)},
            )

    return dependencia


def _em_transacao_propria[T](request: Request, acao: Callable[[Session], T]) -> T:
    # Transação própria: um 4xx desfaz a transação da requisição, mas contadores e eventos
    # de segurança têm de ficar gravados. Seguro contra espera circular no lock da cadeia do
    # log porque, nestes pontos, a transação da requisição ainda não gravou nenhum evento.
    fabrica: sessionmaker[Session] = request.app.state.sessionmaker
    with fabrica() as db, db.begin():
        return acao(db)
