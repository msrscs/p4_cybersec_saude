"""Segundo fator (RF-02): TOTP obrigatório e códigos de recuperação de uso único (ADR-0002).

Toda falha conta no bloqueio progressivo da conta e nas tentativas do token de pré-auth.
"""

import secrets
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.core import totp
from app.core.config import Settings
from app.core.crypto import (
    DekCifrada,
    FinalidadeHash,
    abrir_dek,
    cifrar_campo,
    decifrar_campo,
    hash_busca,
)
from app.models import Sessao, Usuario
from app.repositories import codigo_recuperacao as codigo_repo
from app.repositories import usuario as usuario_repo
from app.services import auditoria
from app.services import auth as auth_service
from app.services import sessao as sessao_svc
from app.services.auditoria import ContextoRequisicao, Evento
from app.services.sessao import SessaoAtual

QUANTIDADE_CODIGOS = 10
_ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sem 0/O, 1/I: 5 bits por caractere
_COLUNA_TOTP = "totp_segredo_cripto"


class PreAuthInvalida(Exception):
    """Token de pré-autenticação ausente, expirado, esgotado ou fora da etapa esperada."""


@dataclass(frozen=True)
class Provisionamento:
    uri: str = field(repr=False)
    qr_svg: str = field(repr=False)
    chave: str = field(repr=False)


@dataclass(frozen=True)
class ResultadoMfa:
    sucesso: bool
    token_sessao: str | None = field(default=None, repr=False)
    codigos: list[str] = field(default_factory=list, repr=False)
    restantes: int | None = None


FALHA = ResultadoMfa(sucesso=False)


def gerar_codigo_recuperacao() -> str:
    corpo = "".join(secrets.choice(_ALFABETO) for _ in range(10))
    return f"{corpo[:5]}-{corpo[5:]}"


# --- Etapas com pré-autenticação ---------------------------------------------------------


def iniciar_cadastro(
    db: Session, settings: Settings, token: str | None, agora: datetime
) -> Provisionamento:
    """Gera (ou regenera) o segredo pendente. Só antes de o MFA estar ativo."""
    _, usuario = _pre_auth(db, token, agora)
    if usuario.mfa_ativo:
        raise PreAuthInvalida
    segredo = totp.gerar_segredo()
    usuario.totp_segredo_cripto = _cifrar_segredo(settings, usuario, segredo)
    usuario.totp_ultimo_passo = None
    db.flush()
    uri = totp.uri_provisionamento(segredo)
    return Provisionamento(uri=uri, qr_svg=totp.qr_svg(uri), chave=segredo)


def ativar(
    db: Session,
    settings: Settings,
    token: str | None,
    codigo: str,
    ctx: ContextoRequisicao,
    agora: datetime,
) -> ResultadoMfa:
    pre, usuario = _pre_auth(db, token, agora)
    if usuario.mfa_ativo or usuario.totp_segredo_cripto is None:
        raise PreAuthInvalida
    passo = totp.verificar(_segredo(settings, usuario), codigo, agora, usuario.totp_ultimo_passo)
    if passo is None:
        return _falha(db, pre, usuario, ctx, agora, "totp_invalido")

    usuario.mfa_ativo = True
    _confirmar_fator(usuario, passo)
    auditoria.registrar(db, Evento.MFA_ENROLLED, ctx, cpf_usuario_hash=usuario.cpf_hash)
    codigos = _novos_codigos(db, settings, usuario.cpf_hash, ctx, agora)
    token_sessao = sessao_svc.promover(db, pre, ctx, agora, metodo="totp")
    return ResultadoMfa(sucesso=True, token_sessao=token_sessao, codigos=codigos)


def verificar(
    db: Session,
    settings: Settings,
    token: str | None,
    codigo: str,
    ctx: ContextoRequisicao,
    agora: datetime,
) -> ResultadoMfa:
    pre, usuario = _pre_auth_com_mfa(db, token, agora)
    passo = totp.verificar(_segredo(settings, usuario), codigo, agora, usuario.totp_ultimo_passo)
    if passo is None:
        return _falha(db, pre, usuario, ctx, agora, "totp_invalido")
    _confirmar_fator(usuario, passo)
    auditoria.registrar(db, Evento.MFA_SUCCESS, ctx, cpf_usuario_hash=usuario.cpf_hash)
    return ResultadoMfa(
        sucesso=True, token_sessao=sessao_svc.promover(db, pre, ctx, agora, metodo="totp")
    )


def recuperar(
    db: Session,
    settings: Settings,
    token: str | None,
    codigo: str,
    ctx: ContextoRequisicao,
    agora: datetime,
) -> ResultadoMfa:
    pre, usuario = _pre_auth_com_mfa(db, token, agora)
    codigo_hash = hash_busca(settings.chave_hmac, FinalidadeHash.CODIGO_RECUPERACAO, codigo)
    if not codigo_repo.usar(db, usuario.cpf_hash, codigo_hash, agora):
        return _falha(db, pre, usuario, ctx, agora, "codigo_recuperacao_invalido")
    usuario.falhas_login = 0
    restantes = codigo_repo.restantes(db, usuario.cpf_hash)
    auditoria.registrar(
        db,
        Evento.MFA_RECOVERY_USED,
        ctx,
        cpf_usuario_hash=usuario.cpf_hash,
        resumo={"restantes": restantes},
    )
    token_sessao = sessao_svc.promover(db, pre, ctx, agora, metodo="codigo_recuperacao")
    return ResultadoMfa(sucesso=True, token_sessao=token_sessao, restantes=restantes)


# --- Com sessão completa -----------------------------------------------------------------


def regenerar_codigos(
    db: Session,
    settings: Settings,
    atual: SessaoAtual,
    codigo: str,
    ctx: ContextoRequisicao,
    agora: datetime,
) -> list[str] | None:
    """Novo conjunto de códigos (invalida o anterior). Exige um TOTP válido na hora."""
    usuario = usuario_repo.buscar_para_login(db, atual.cpf_hash)
    if usuario is None or not usuario.mfa_ativo:
        return None
    passo = totp.verificar(_segredo(settings, usuario), codigo, agora, usuario.totp_ultimo_passo)
    if passo is None:
        auth_service.contar_falha(
            db, ctx, usuario, agora, motivo="totp_invalido", evento=Evento.MFA_FAILURE
        )
        return None
    usuario.totp_ultimo_passo = passo
    return _novos_codigos(db, settings, usuario.cpf_hash, ctx, agora)


# --- Apoio -------------------------------------------------------------------------------


def _pre_auth(db: Session, token: str | None, agora: datetime) -> tuple[Sessao, Usuario]:
    pre = sessao_svc.obter_pre_auth(db, token, agora)
    if pre is None:
        raise PreAuthInvalida
    usuario = usuario_repo.buscar_para_login(db, pre.cpf_hash)
    bloqueado = usuario is not None and (
        usuario.bloqueado_ate is not None and usuario.bloqueado_ate > agora
    )
    if usuario is None or usuario.status != "ativo" or bloqueado:
        raise PreAuthInvalida
    return pre, usuario


def _pre_auth_com_mfa(db: Session, token: str | None, agora: datetime) -> tuple[Sessao, Usuario]:
    pre, usuario = _pre_auth(db, token, agora)
    if not usuario.mfa_ativo or usuario.totp_segredo_cripto is None:
        raise PreAuthInvalida
    return pre, usuario


def _falha(
    db: Session,
    pre: Sessao,
    usuario: Usuario,
    ctx: ContextoRequisicao,
    agora: datetime,
    motivo: str,
) -> ResultadoMfa:
    sessao_svc.registrar_tentativa_mfa(db, pre)
    auth_service.contar_falha(db, ctx, usuario, agora, motivo=motivo, evento=Evento.MFA_FAILURE)
    return FALHA


def _confirmar_fator(usuario: Usuario, passo: int) -> None:
    usuario.totp_ultimo_passo = passo
    usuario.falhas_login = 0


def _novos_codigos(
    db: Session, settings: Settings, cpf_hash: bytes, ctx: ContextoRequisicao, agora: datetime
) -> list[str]:
    codigo_repo.invalidar_todos(db, cpf_hash, agora)
    codigos = [gerar_codigo_recuperacao() for _ in range(QUANTIDADE_CODIGOS)]
    hashes = [
        hash_busca(settings.chave_hmac, FinalidadeHash.CODIGO_RECUPERACAO, c) for c in codigos
    ]
    codigo_repo.inserir(db, cpf_hash, hashes)
    auditoria.registrar(
        db,
        Evento.RECOVERY_CODES_GENERATED,
        ctx,
        cpf_usuario_hash=cpf_hash,
        resumo={"quantidade": len(codigos)},
    )
    return codigos


def _dek(settings: Settings, usuario: Usuario) -> bytes:
    return abrir_dek(settings.keyring, DekCifrada(usuario.dek_cripto, usuario.kek_versao))


def _cifrar_segredo(settings: Settings, usuario: Usuario, segredo: str) -> bytes:
    return cifrar_campo(
        _dek(settings, usuario),
        segredo,
        tabela="usuario",
        coluna=_COLUNA_TOTP,
        id_registro=usuario.cpf_hash,
    )


def _segredo(settings: Settings, usuario: Usuario) -> str:
    if usuario.totp_segredo_cripto is None:
        raise PreAuthInvalida
    return decifrar_campo(
        _dek(settings, usuario),
        usuario.totp_segredo_cripto,
        tabela="usuario",
        coluna=_COLUNA_TOTP,
        id_registro=usuario.cpf_hash,
    )
