"""Tokens de sessão (ADR-0008/0009). No banco fica só o SHA-256 do token.

- Pré-autenticação (escopo 'mfa'): 5 min, no máximo 5 tentativas de código.
- Sessão completa: 15 min de inatividade (renovada a cada uso) e 8 h de vida absoluta.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import Sessao
from app.repositories import sessao as sessao_repo
from app.services import auditoria
from app.services.auditoria import ContextoRequisicao, Evento

ESCOPO_MFA = "mfa"
ESCOPO_COMPLETA = "completa"
VALIDADE_PRE_AUTH = timedelta(minutes=5)
MAX_TENTATIVAS_MFA = 5
INATIVIDADE = timedelta(minutes=15)
VIDA_MAXIMA = timedelta(hours=8)


@dataclass(frozen=True)
class SessaoAtual:
    cpf_hash: bytes
    token_hash: bytes
    expira_em: datetime


def gerar_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def criar_pre_auth(db: Session, cpf_hash: bytes, ctx: ContextoRequisicao, agora: datetime) -> str:
    token = gerar_token()
    sessao_repo.inserir(
        db,
        Sessao(
            token_hash=hash_token(token),
            cpf_hash=cpf_hash,
            escopo=ESCOPO_MFA,
            expira_em=agora + VALIDADE_PRE_AUTH,
            ip=ctx.ip,
        ),
    )
    return token


def obter_pre_auth(db: Session, token: str | None, agora: datetime) -> Sessao | None:
    if not token:
        return None
    sessao = sessao_repo.buscar(db, hash_token(token), ESCOPO_MFA)
    if sessao is None or sessao.expira_em <= agora:
        return None
    return sessao


def registrar_tentativa_mfa(db: Session, pre_auth: Sessao) -> None:
    """Conta um código errado; na 5ª o token deixa de valer (é preciso refazer o login)."""
    pre_auth.tentativas += 1
    if pre_auth.tentativas >= MAX_TENTATIVAS_MFA:
        sessao_repo.remover(db, pre_auth)
    else:
        db.flush()


def promover(
    db: Session, pre_auth: Sessao, ctx: ContextoRequisicao, agora: datetime, *, metodo: str
) -> str:
    """Consome a pré-autenticação e abre a sessão completa com um token novo."""
    cpf_hash = pre_auth.cpf_hash
    sessao_repo.remover(db, pre_auth)
    token = gerar_token()
    sessao_repo.inserir(
        db,
        Sessao(
            token_hash=hash_token(token),
            cpf_hash=cpf_hash,
            escopo=ESCOPO_COMPLETA,
            expira_em=agora + INATIVIDADE,
            expira_absoluta=agora + VIDA_MAXIMA,
            ultimo_uso=agora,
            ip=ctx.ip,
        ),
    )
    auditoria.registrar(
        db, Evento.SESSION_CREATED, ctx, cpf_usuario_hash=cpf_hash, resumo={"metodo": metodo}
    )
    return token


def validar(db: Session, token: str | None, agora: datetime) -> SessaoAtual | None:
    """Valida a sessão completa e renova a expiração por inatividade."""
    if not token:
        return None
    sessao = sessao_repo.buscar(db, hash_token(token), ESCOPO_COMPLETA)
    if sessao is None or sessao.expira_absoluta is None:
        return None
    if sessao.expira_em <= agora or sessao.expira_absoluta <= agora:
        sessao_repo.remover(db, sessao)
        return None
    sessao.ultimo_uso = agora
    sessao.expira_em = min(agora + INATIVIDADE, sessao.expira_absoluta)
    db.flush()
    return SessaoAtual(
        cpf_hash=sessao.cpf_hash, token_hash=sessao.token_hash, expira_em=sessao.expira_em
    )


def encerrar(db: Session, atual: SessaoAtual, ctx: ContextoRequisicao) -> None:
    sessao = sessao_repo.buscar(db, atual.token_hash, ESCOPO_COMPLETA)
    if sessao is not None:
        sessao_repo.remover(db, sessao)
    auditoria.registrar(db, Evento.LOGOUT, ctx, cpf_usuario_hash=atual.cpf_hash)


def encerrar_outras(db: Session, atual: SessaoAtual) -> int:
    return sessao_repo.remover_do_usuario(db, atual.cpf_hash, exceto=atual.token_hash)
