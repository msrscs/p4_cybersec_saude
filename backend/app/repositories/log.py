from collections.abc import Iterator
from typing import Any

from sqlalchemy import Text, cast, select
from sqlalchemy.orm import Session

from app.core.cadeia import RegistroCadeia
from app.models import Log, LogCheckpoint


def registrar(
    db: Session,
    *,
    acao: str,
    cpf_usuario_hash: bytes | None = None,
    ip_origem: str | None = None,
    request_id: str | None = None,
    resumo: dict[str, Any] | None = None,
) -> None:
    db.add(
        Log(
            acao=acao,
            cpf_usuario_hash=cpf_usuario_hash,
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


def checkpoints(db: Session) -> list[LogCheckpoint]:
    return list(db.scalars(select(LogCheckpoint).order_by(LogCheckpoint.seq_cadeia)))


def inserir_checkpoint(db: Session, seq_cadeia: int, hash_cadeia: bytes, assinatura: bytes) -> None:
    db.add(LogCheckpoint(seq_cadeia=seq_cadeia, hash_cadeia=hash_cadeia, assinatura=assinatura))
    db.flush()
