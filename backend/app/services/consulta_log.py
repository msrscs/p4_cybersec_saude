"""Consulta do log de auditoria (RF-04, ADR-0015): somente leitura, e a leitura é auditada.

Hashes saem truncados: bastam para correlacionar eventos na tela e reduzem o que fica exposto,
mas não anonimizam. A integridade exibida é a da última verificação feita pelo container
`tarefas`; a API não recalcula a cadeia nem recebe a chave dos checkpoints (ADR-0010).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.crypto import FinalidadeHash, hash_busca
from app.models import Log
from app.repositories import log as log_repo
from app.services import auditoria
from app.services.auditoria import ContextoRequisicao, Evento

TAMANHO_PAGINA = 50  # fixo: o cliente não escolhe quantos registros ler por requisição
_TAMANHO_HASH = 12


@dataclass(frozen=True)
class Filtros:
    de: datetime | None = None
    ate: datetime | None = None
    acao: str | None = None
    cpf: str | None = field(default=None, repr=False)
    antes: int | None = None


@dataclass(frozen=True)
class ItemLog:
    seq: int
    data_hora: datetime
    acao: str
    ip_origem: str | None
    request_id: str | None
    usuario: str | None
    paciente: str | None
    hash: str
    resumo: dict[str, Any]


@dataclass(frozen=True)
class PaginaLog:
    itens: list[ItemLog]
    proximo: int | None


@dataclass(frozen=True)
class Integridade:
    total_registros: int
    verificada_em: datetime | None
    integra: bool | None  # None: ainda não houve verificação
    checkpoint_em: datetime | None
    checkpoint_seq: int | None


def acoes() -> list[str]:
    return sorted(evento.value for evento in Evento)


def consultar(
    db: Session, settings: Settings, filtros: Filtros, autor: bytes, ctx: ContextoRequisicao
) -> PaginaLog:
    cpf_hash = (
        None
        if filtros.cpf is None
        else hash_busca(settings.chave_hmac, FinalidadeHash.CPF, filtros.cpf)
    )
    linhas = log_repo.consultar(
        db,
        limite=TAMANHO_PAGINA + 1,
        antes=filtros.antes,
        de=filtros.de,
        ate=filtros.ate,
        acao=filtros.acao,
        cpf_usuario_hash=cpf_hash,
    )
    pagina = linhas[:TAMANHO_PAGINA]
    auditoria.registrar(
        db,
        Evento.LOG_READ,
        ctx,
        cpf_usuario_hash=autor,
        resumo=_resumo_da_leitura(filtros, cpf_hash, len(pagina)),
    )
    return PaginaLog(
        itens=[_item(linha) for linha in pagina],
        proximo=pagina[-1].seq_cadeia if len(linhas) > TAMANHO_PAGINA else None,
    )


def integridade(db: Session) -> Integridade:
    verificacao = log_repo.ultimo_evento(
        db, (Evento.LOG_CHAIN_VERIFIED.value, Evento.LOG_CHAIN_BROKEN.value)
    )
    checkpoint = log_repo.ultimo_checkpoint(db)
    return Integridade(
        total_registros=log_repo.total_registros(db),
        verificada_em=verificacao.data_hora if verificacao else None,
        integra=verificacao.acao == Evento.LOG_CHAIN_VERIFIED.value if verificacao else None,
        checkpoint_em=checkpoint.criado_em if checkpoint else None,
        checkpoint_seq=checkpoint.seq_cadeia if checkpoint else None,
    )


def _resumo_da_leitura(filtros: Filtros, cpf_hash: bytes | None, registros: int) -> dict[str, Any]:
    # Quem consultou quem fica registrado pelo hash truncado, nunca pelo CPF.
    resumo: dict[str, Any] = {"registros": registros}
    if filtros.de is not None:
        resumo["de"] = filtros.de.isoformat()
    if filtros.ate is not None:
        resumo["ate"] = filtros.ate.isoformat()
    if filtros.acao is not None:
        resumo["acao"] = filtros.acao
    if cpf_hash is not None:
        resumo["usuario"] = _curto(cpf_hash)
    if filtros.antes is not None:
        resumo["antes"] = filtros.antes
    return resumo


def _item(linha: Log) -> ItemLog:
    return ItemLog(
        seq=linha.seq_cadeia,
        data_hora=linha.data_hora,
        acao=linha.acao,
        ip_origem=None if linha.ip_origem is None else str(linha.ip_origem),
        request_id=None if linha.request_id is None else str(linha.request_id),
        usuario=_curto(linha.cpf_usuario_hash),
        paciente=_curto(linha.cpf_paciente_hash),
        hash=linha.hash_assinatura_worm.hex()[:_TAMANHO_HASH],
        resumo=linha.resumo_acessado,
    )


def _curto(valor: bytes | None) -> str | None:
    return None if valor is None else valor.hex()[:_TAMANHO_HASH]
