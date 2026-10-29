"""Registro de eventos no log WORM. Nunca recebe dado sensível em claro (só hashes e metadados)."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy.orm import Session

from app.repositories import log as log_repo


class Evento(StrEnum):
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILURE = "login_failure"
    ACCOUNT_LOCKED = "account_locked"
    USER_CREATED = "user_created"


@dataclass(frozen=True)
class ContextoRequisicao:
    ip: str | None = None
    request_id: str | None = None


def registrar(
    db: Session,
    evento: Evento,
    ctx: ContextoRequisicao,
    *,
    cpf_usuario_hash: bytes | None = None,
    resumo: dict[str, Any] | None = None,
) -> None:
    log_repo.registrar(
        db,
        acao=evento.value,
        cpf_usuario_hash=cpf_usuario_hash,
        ip_origem=ctx.ip,
        request_id=ctx.request_id,
        resumo=resumo,
    )
