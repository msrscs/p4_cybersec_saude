"""Rotinas de manutenção (ADR-0013): limpeza de sessões expiradas e contadores vencidos."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.repositories import limite as limite_repo
from app.repositories import sessao as sessao_repo

# Maior janela de limite é 1 h; guarda 1 dia para consulta em incidentes.
RETENCAO_CONTADORES = timedelta(days=1)


@dataclass(frozen=True)
class ResultadoLimpeza:
    sessoes: int
    contadores: int


def limpar(db: Session, agora: datetime) -> ResultadoLimpeza:
    return ResultadoLimpeza(
        sessoes=sessao_repo.remover_expiradas(db, agora),
        contadores=limite_repo.remover_vencidos(db, agora - RETENCAO_CONTADORES),
    )
