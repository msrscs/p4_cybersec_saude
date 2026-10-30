from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import Any

from sqlalchemy import Text, cast, func, select
from sqlalchemy.orm import Session

from app.core.cadeia import RegistroCadeia
from app.models import Log, LogCheckpoint


def registrar(
    db: Session,
    *,
    acao: str,
    cpf_usuario_hash: bytes | None = None,
    cpf_paciente_hash: bytes | None = None,
    ip_origem: str | None = None,
    request_id: str | None = None,
    resumo: dict[str, Any] | None = None,
) -> None:
    db.add(
        Log(
            acao=acao,
            cpf_usuario_hash=cpf_usuario_hash,
            cpf_paciente_hash=cpf_paciente_hash,
            ip_origem=ip_origem,
            request_id=request_id,
            resumo_acessado=resumo or {},
        )
    )
    db.flush()


def iterar_cadeia(db: Session, lote: int = 1000) -> Iterator[RegistroCadeia]:
    """Percorre o log em ordem de seq_cadeia, em lotes (cursor no servidor)."""
    consulta = (
        select(
            Log.seq_cadeia,
            Log.id_log,
            Log.data_hora,
            Log.acao,
            cast(Log.resumo_acessado, Text).label("resumo"),
            cast(Log.ip_origem, Text).label("ip_origem"),
            cast(Log.request_id, Text).label("request_id"),
            Log.geolocalizacao,
            Log.cpf_usuario_hash,
            Log.cpf_paciente_hash,
            Log.id_oci,
            Log.prev_hash,
            Log.hash_assinatura_worm,
        )
        .order_by(Log.seq_cadeia)
        .execution_options(yield_per=lote)
    )
    for linha in db.execute(consulta):
        yield RegistroCadeia(**linha._asdict())


def consultar(
    db: Session,
    *,
    limite: int,
    antes: int | None = None,
    de: datetime | None = None,
    ate: datetime | None = None,
    acao: str | None = None,
    cpf_usuario_hash: bytes | None = None,
) -> list[Log]:
    """Mais recentes primeiro, por cursor (seq_cadeia); só os filtros informados se aplicam."""
    consulta = select(Log).order_by(Log.seq_cadeia.desc()).limit(limite)
    if antes is not None:
        consulta = consulta.where(Log.seq_cadeia < antes)
    if de is not None:
        consulta = consulta.where(Log.data_hora >= de)
    if ate is not None:
        consulta = consulta.where(Log.data_hora <= ate)
    if acao is not None:
        consulta = consulta.where(Log.acao == acao)
    if cpf_usuario_hash is not None:
        consulta = consulta.where(Log.cpf_usuario_hash == cpf_usuario_hash)
    return list(db.scalars(consulta))


def ultimo_evento(db: Session, acoes: Iterable[str]) -> Log | None:
    consulta = select(Log).where(Log.acao.in_(list(acoes)))
    return db.scalars(consulta.order_by(Log.seq_cadeia.desc()).limit(1)).one_or_none()


def ultimo_checkpoint(db: Session) -> LogCheckpoint | None:
    consulta = select(LogCheckpoint).order_by(LogCheckpoint.seq_cadeia.desc()).limit(1)
    return db.scalars(consulta).one_or_none()


def total_registros(db: Session) -> int:
    return int(db.scalar(select(func.coalesce(func.max(Log.seq_cadeia), 0))) or 0)


def checkpoints(db: Session) -> list[LogCheckpoint]:
    return list(db.scalars(select(LogCheckpoint).order_by(LogCheckpoint.seq_cadeia)))


def inserir_checkpoint(db: Session, seq_cadeia: int, hash_cadeia: bytes, assinatura: bytes) -> None:
    db.add(LogCheckpoint(seq_cadeia=seq_cadeia, hash_cadeia=hash_cadeia, assinatura=assinatura))
    db.flush()
