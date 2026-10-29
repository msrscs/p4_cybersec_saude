"""Login, etapa 1: CPF + senha (RF-02). A sessão completa só existe após o TOTP (T05).

- Resposta idêntica para CPF inexistente, senha errada, conta inativa ou bloqueada (I5).
- Mesmo custo de bcrypt em todos os caminhos (hash fictício quando não há o que verificar).
- 5 falhas seguidas bloqueiam a conta: 15 min, dobrando a cada novo bloqueio, até 24 h.
- O token de pré-autenticação só vale para a etapa de MFA; no banco fica só o SHA-256 dele.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core import senha as senha_mod
from app.core.config import Settings
from app.core.crypto import FinalidadeHash, hash_busca
from app.models import Usuario
from app.repositories import usuario as usuario_repo
from app.services import auditoria
from app.services import sessao as sessao_svc
from app.services.auditoria import ContextoRequisicao, Evento

MAX_FALHAS = 5
BLOQUEIO_BASE = timedelta(minutes=15)
BLOQUEIO_MAXIMO = timedelta(hours=24)


@dataclass(frozen=True)
class ResultadoLogin:
    sucesso: bool
    token: str | None = field(default=None, repr=False)
    mfa_ativo: bool = False


FALHA = ResultadoLogin(sucesso=False)


def duracao_bloqueio(bloqueios: int) -> timedelta:
    expoente = min(max(bloqueios, 1) - 1, 10)
    duracao: timedelta = BLOQUEIO_BASE * (1 << expoente)
    return min(duracao, BLOQUEIO_MAXIMO)


def autenticar_senha(
    db: Session,
    settings: Settings,
    *,
    cpf: str,
    senha: str,
    ctx: ContextoRequisicao,
    agora: datetime | None = None,
) -> ResultadoLogin:
    agora = agora or datetime.now(UTC)
    cpf_hash = hash_busca(settings.chave_hmac, FinalidadeHash.CPF, cpf)
    usuario = usuario_repo.buscar_para_login(db, cpf_hash)

    motivo = _motivo_recusa_previa(usuario, agora)
    if usuario is None or motivo:
        senha_mod.verificar_ficticio(senha, settings.bcrypt_rounds)
        _registrar_falha(db, ctx, cpf_hash, motivo or "usuario_inexistente")
        return FALHA

    if not senha_mod.verificar(senha, usuario.senha_hash):
        contar_falha(db, ctx, usuario, agora, motivo="senha_invalida", evento=Evento.LOGIN_FAILURE)
        return FALHA

    return _sucesso(db, settings, ctx, usuario, senha, agora)


def _motivo_recusa_previa(usuario: Usuario | None, agora: datetime) -> str | None:
    if usuario is None:
        return None
    if usuario.status != "ativo":
        return "conta_" + usuario.status
    if usuario.bloqueado_ate is not None and usuario.bloqueado_ate > agora:
        return "conta_bloqueada_temporariamente"
    return None


def _registrar_falha(db: Session, ctx: ContextoRequisicao, cpf_hash: bytes, motivo: str) -> None:
    auditoria.registrar(
        db, Evento.LOGIN_FAILURE, ctx, cpf_usuario_hash=cpf_hash, resumo={"motivo": motivo}
    )


def contar_falha(
    db: Session,
    ctx: ContextoRequisicao,
    usuario: Usuario,
    agora: datetime,
    *,
    motivo: str,
    evento: Evento,
) -> None:
    """Falha de senha ou de MFA: soma no mesmo contador do bloqueio progressivo."""
    usuario.falhas_login += 1
    auditoria.registrar(
        db, evento, ctx, cpf_usuario_hash=usuario.cpf_hash, resumo={"motivo": motivo}
    )
    if usuario.falhas_login < MAX_FALHAS:
        return
    usuario.bloqueios += 1
    duracao = duracao_bloqueio(usuario.bloqueios)
    usuario.bloqueado_ate = agora + duracao
    usuario.falhas_login = 0
    auditoria.registrar(
        db,
        Evento.ACCOUNT_LOCKED,
        ctx,
        cpf_usuario_hash=usuario.cpf_hash,
        resumo={"bloqueios": usuario.bloqueios, "minutos": int(duracao.total_seconds() // 60)},
    )


def _sucesso(
    db: Session,
    settings: Settings,
    ctx: ContextoRequisicao,
    usuario: Usuario,
    senha: str,
    agora: datetime,
) -> ResultadoLogin:
    usuario.falhas_login = 0
    usuario.bloqueios = 0
    usuario.bloqueado_ate = None
    if senha_mod.precisa_rehash(usuario.senha_hash, settings.bcrypt_rounds):
        usuario.senha_hash = senha_mod.gerar_hash(senha, settings.bcrypt_rounds)

    token = sessao_svc.criar_pre_auth(db, usuario.cpf_hash, ctx, agora)
    auditoria.registrar(
        db, Evento.LOGIN_SUCCESS, ctx, cpf_usuario_hash=usuario.cpf_hash, resumo={"etapa": "senha"}
    )
    return ResultadoLogin(sucesso=True, token=token, mfa_ativo=usuario.mfa_ativo)
