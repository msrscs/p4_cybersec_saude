"""Limite de requisições por IP em janela fixa (RNF-07, ADR-0013).

Complementa o bloqueio progressivo por conta (ADR-0008): barra quem testa muitas contas ou
muitos CPFs a partir do mesmo IP. O excesso é auditado uma vez por janela (rate_limited).
"""

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.repositories import limite as limite_repo
from app.services import auditoria
from app.services.auditoria import ContextoRequisicao, Evento

# Balde comum quando o IP não é válido (não é endereço de bind).
IP_DESCONHECIDO = "0.0.0.0"  # noqa: S104  # nosec B104
_EPOCA = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class Limite:
    grupo: str
    maximo: int
    janela: timedelta

    @property
    def chave(self) -> str:
        return f"{self.grupo}:{int(self.janela.total_seconds())}"


LOGIN = (
    Limite("login", 10, timedelta(minutes=1)),
    Limite("login", 50, timedelta(hours=1)),
)
MFA = (Limite("mfa", 15, timedelta(minutes=1)),)
BUSCA_PACIENTE = (Limite("busca_paciente", 30, timedelta(minutes=1)),)
LISTA_PACIENTE = (
    Limite("lista_paciente", 30, timedelta(minutes=1)),
    Limite("lista_paciente", 300, timedelta(hours=1)),
)
LISTA_OCI = (
    Limite("lista_oci", 60, timedelta(minutes=1)),
    Limite("lista_oci", 600, timedelta(hours=1)),
)
CONSULTA_LOG = (Limite("consulta_log", 60, timedelta(minutes=1)),)
LISTA_USUARIO = (Limite("lista_usuario", 30, timedelta(minutes=1)),)
# Criar e resetar geram hash bcrypt: caros de propósito.
ACESSO_USUARIO = (Limite("acesso_usuario", 20, timedelta(minutes=1)),)
GERAL = (Limite("geral", 300, timedelta(minutes=1)),)


def inicio_da_janela(agora: datetime, janela: timedelta) -> datetime:
    passos = (agora - _EPOCA) // janela
    return _EPOCA + passos * janela


def verificar(
    db: Session, limites: tuple[Limite, ...], ctx: ContextoRequisicao, agora: datetime
) -> int | None:
    """Conta a requisição em cada janela; devolve segundos de espera se algum limite estourou."""
    ip = ctx.ip or IP_DESCONHECIDO
    espera: int | None = None
    for limite in limites:
        inicio = inicio_da_janela(agora, limite.janela)
        total = limite_repo.incrementar(db, limite.chave, ip, inicio)
        if total <= limite.maximo:
            continue
        if total == limite.maximo + 1:
            auditoria.registrar(
                db,
                Evento.RATE_LIMITED,
                ctx,
                resumo={"grupo": limite.chave, "maximo": limite.maximo},
            )
        restante = math.ceil((inicio + limite.janela - agora).total_seconds())
        espera = max(espera or 0, max(restante, 1))
    return espera
