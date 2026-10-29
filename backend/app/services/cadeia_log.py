"""Verificação da cadeia de hashes do log de auditoria e checkpoints assinados (RNF-04, ADR-0010).

A verificação recalcula cada hash em Python (sem usar a função do banco) e detecta:
- registro alterado (hash divergente) ou inserido sem passar pela trigger;
- registro removido do meio (lacuna na seq ou prev_hash que não bate);
- fim do log removido, se houver checkpoint ou âncora posterior ao último registro;
- cadeia recalculada por quem não tem a chave dos checkpoints (checkpoint divergente).

O resultado nunca carrega conteúdo do log, só posições, contagens e o motivo.
"""

import hmac
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy.orm import Session

from app.core.cadeia import GENESIS, Ancora, assinar_checkpoint, checkpoint_valido, hash_registro
from app.repositories import log as log_repo
from app.services import auditoria
from app.services.auditoria import ContextoRequisicao, Evento


class Motivo(StrEnum):
    LACUNA = "lacuna_na_sequencia"
    PREV_HASH = "prev_hash_divergente"
    HASH = "hash_divergente"
    CHECKPOINT_ASSINATURA = "checkpoint_assinatura_invalida"
    CHECKPOINT_DIVERGENTE = "checkpoint_divergente"
    ANCORA_DIVERGENTE = "ancora_divergente"
    TRUNCADO = "log_truncado"


@dataclass(frozen=True)
class ResultadoVerificacao:
    registros: int
    checkpoints: int
    ultimo: Ancora | None = None
    motivo: Motivo | None = None
    seq_falha: int | None = None

    @property
    def integra(self) -> bool:
        return self.motivo is None


def verificar_cadeia(
    db: Session, chave_checkpoint: bytes, ancora: Ancora | None = None, *, lote: int = 1000
) -> ResultadoVerificacao:
    """Percorre o log inteiro. Para um retrato consistente, rode em REPEATABLE READ."""
    pontos = log_repo.checkpoints(db)
    for cp in pontos:
        if not checkpoint_valido(chave_checkpoint, cp.seq_cadeia, cp.hash_cadeia, cp.assinatura):
            return ResultadoVerificacao(
                0, len(pontos), None, Motivo.CHECKPOINT_ASSINATURA, cp.seq_cadeia
            )

    referencias: dict[int, list[tuple[bytes, Motivo]]] = {}
    for cp in pontos:
        referencias.setdefault(cp.seq_cadeia, []).append(
            (cp.hash_cadeia, Motivo.CHECKPOINT_DIVERGENTE)
        )
    if ancora is not None:
        referencias.setdefault(ancora.seq_cadeia, []).append(
            (ancora.hash_cadeia, Motivo.ANCORA_DIVERGENTE)
        )

    def falha(motivo: Motivo, seq: int, verificados: int) -> ResultadoVerificacao:
        return ResultadoVerificacao(verificados, len(pontos), None, motivo, seq)

    prev, total = GENESIS, 0
    for r in log_repo.iterar_cadeia(db, lote):
        if r.seq_cadeia != total + 1:
            return falha(Motivo.LACUNA, total + 1, total)
        if not hmac.compare_digest(r.prev_hash, prev):
            return falha(Motivo.PREV_HASH, r.seq_cadeia, total)
        calculado = hash_registro(prev, r)
        if not hmac.compare_digest(r.hash_assinatura_worm, calculado):
            return falha(Motivo.HASH, r.seq_cadeia, total)
        for esperado, motivo in referencias.get(r.seq_cadeia, []):
            if not hmac.compare_digest(esperado, calculado):
                return falha(motivo, r.seq_cadeia, total)
        prev, total = calculado, r.seq_cadeia

    if referencias and max(referencias) > total:
        return falha(Motivo.TRUNCADO, total + 1, total)
    ultimo = Ancora(total, prev) if total else None
    return ResultadoVerificacao(total, len(pontos), ultimo)


def registrar_resultado(
    db: Session, resultado: ResultadoVerificacao, ctx: ContextoRequisicao
) -> None:
    resumo: dict[str, Any]
    if resultado.integra:
        resumo = {
            "registros": resultado.registros,
            "checkpoints": resultado.checkpoints,
            "ultimo_seq": resultado.ultimo.seq_cadeia if resultado.ultimo else 0,
        }
        auditoria.registrar(db, Evento.LOG_CHAIN_VERIFIED, ctx, resumo=resumo)
        return
    resumo = {
        "motivo": str(resultado.motivo),
        "seq": resultado.seq_falha,
        "registros_verificados": resultado.registros,
    }
    auditoria.registrar(db, Evento.LOG_CHAIN_BROKEN, ctx, resumo=resumo)


def criar_checkpoint(
    db: Session, chave_checkpoint: bytes, resultado: ResultadoVerificacao, ctx: ContextoRequisicao
) -> Ancora | None:
    """Assina o último ponto de uma cadeia já verificada. Nunca sobre cadeia quebrada."""
    if not resultado.integra or resultado.ultimo is None:
        return None
    ponto = resultado.ultimo
    assinatura = assinar_checkpoint(chave_checkpoint, ponto.seq_cadeia, ponto.hash_cadeia)
    log_repo.inserir_checkpoint(db, ponto.seq_cadeia, ponto.hash_cadeia, assinatura)
    auditoria.registrar(db, Evento.LOG_CHECKPOINT_CREATED, ctx, resumo={"seq": ponto.seq_cadeia})
    return ponto
