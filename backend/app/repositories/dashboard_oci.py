"""Consultas agregadas do dashboard de OCI (ADR-0027): só contagens, nunca linhas de paciente."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, Select, case, exists, extract, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.models import Cid, Oci, OciNavegacao, ServicoSaude, TipoOci, UnidadeSaude

_SEGUNDOS_POR_DIA = 86400


@dataclass(frozen=True)
class Recorte:
    """O que entra na conta: cada unidade listada precisa ser atendida (alcance e filtro)."""

    unidades: tuple[int, ...] = ()
    id_tipo_oci: int | None = None


@dataclass(frozen=True)
class ResumoAbertas:
    em_aberto: int
    atrasadas: int
    vencem_em_breve: int


@dataclass(frozen=True)
class ResumoConclusoes:
    concluidas: int
    no_prazo: int
    mediana_dias: float | None


@dataclass(frozen=True)
class EtapasDoGrupo:
    nome: str
    agendado: int = 0
    realizado: int = 0
    faltou: int = 0
    cancelado: int = 0
    remarcado: int = 0


def _das_ocis(recorte: Recorte) -> list[ColumnElement[bool]]:
    """Uma OCI entra se tiver etapa em cada unidade do recorte, a mesma regra da lista."""
    condicoes: list[ColumnElement[bool]] = [
        exists().where(OciNavegacao.id_oci == Oci.id_oci, OciNavegacao.id_unidade == unidade)
        for unidade in recorte.unidades
    ]
    if recorte.id_tipo_oci is not None:
        condicoes.append(Oci.id_tipo_oci == recorte.id_tipo_oci)
    return condicoes


def _das_etapas[C: Select[*tuple[Any, ...]]](consulta: C, recorte: Recorte) -> C:
    """Só conta a etapa da própria unidade: a de outra é visível, mas não é trabalho dela."""
    for unidade in recorte.unidades:
        consulta = consulta.where(OciNavegacao.id_unidade == unidade)
    if recorte.id_tipo_oci is not None:
        consulta = consulta.join(Oci, Oci.id_oci == OciNavegacao.id_oci).where(
            Oci.id_tipo_oci == recorte.id_tipo_oci
        )
    return consulta


def resumo_abertas(
    db: Session, recorte: Recorte, agora: datetime, alerta_ate: datetime
) -> ResumoAbertas:
    consulta = select(
        func.count(),
        func.count().filter(Oci.prazo_em < agora),
        func.count().filter(Oci.prazo_em >= agora, Oci.prazo_em < alerta_ate),
    ).where(Oci.status == "aberta", *_das_ocis(recorte))
    em_aberto, atrasadas, vencem_em_breve = db.execute(consulta).one()
    return ResumoAbertas(em_aberto, atrasadas, vencem_em_breve)


def resumo_conclusoes(db: Session, recorte: Recorte, inicio: datetime) -> ResumoConclusoes:
    """OCI encerrada não muda mais (ADR-0025): `atualizado_em` é o instante da conclusão."""
    duracao = extract("epoch", Oci.atualizado_em - Oci.data_criacao) / _SEGUNDOS_POR_DIA
    consulta = select(
        func.count(),
        func.count().filter(Oci.atualizado_em <= Oci.prazo_em),
        func.percentile_cont(0.5).within_group(duracao),
    ).where(Oci.status == "concluida", Oci.atualizado_em >= inicio, *_das_ocis(recorte))
    concluidas, no_prazo, mediana = db.execute(consulta).one()
    return ResumoConclusoes(concluidas, no_prazo, None if mediana is None else float(mediana))


def serie_por_periodo(
    db: Session,
    recorte: Recorte,
    coluna: InstrumentedAttribute[datetime],
    inicio: datetime,
    fuso: timedelta,
    granularidade: str,
    *condicoes: ColumnElement[bool],
) -> dict[date, int]:
    """Contagem por semana ou mês na hora de Recife. O fuso é fixo (ADR-0026)."""
    periodo = func.date_trunc(granularidade, func.timezone("UTC", coluna) + fuso)
    consulta = (
        select(periodo, func.count())
        .where(coluna >= inicio, *condicoes, *_das_ocis(recorte))
        .group_by(periodo)
    )
    return {linha[0].date(): linha[1] for linha in db.execute(consulta)}


def ocis_por_tipo(
    db: Session, recorte: Recorte, inicio: datetime
) -> list[tuple[str, dict[str, int]]]:
    consulta = (
        select(TipoOci.tipo_oci, Oci.status, func.count())
        .select_from(Oci)
        .join(TipoOci, TipoOci.id_tipo_oci == Oci.id_tipo_oci)
        .where(Oci.data_criacao >= inicio, *_das_ocis(recorte))
        .group_by(TipoOci.tipo_oci, Oci.status)
    )
    tipos: dict[str, dict[str, int]] = {}
    for nome, situacao, total in db.execute(consulta):
        tipos.setdefault(nome, {})[situacao] = total
    return list(tipos.items())


def ocis_por_cid(
    db: Session, recorte: Recorte, inicio: datetime, limite: int
) -> list[tuple[str, str, int]]:
    total = func.count()
    consulta = (
        select(Cid.cid, Cid.descricao, total)
        .select_from(Oci)
        .join(Cid, Cid.cid_hash == Oci.cid_hash)
        .where(Oci.data_criacao >= inicio, *_das_ocis(recorte))
        .group_by(Cid.cid, Cid.descricao)
        .order_by(total.desc(), Cid.cid)
        .limit(limite)
    )
    return [(linha[0], linha[1], linha[2]) for linha in db.execute(consulta)]


def _etapas_agrupadas(
    db: Session,
    recorte: Recorte,
    inicio: datetime,
    nome: InstrumentedAttribute[str],
    alvo: type[UnidadeSaude | ServicoSaude],
) -> list[EtapasDoGrupo]:
    situacoes = ("agendado", "realizado", "faltou", "cancelado", "remarcado")
    colunas = [
        func.sum(case((OciNavegacao.status == situacao, 1), else_=0)).label(situacao)
        for situacao in situacoes
    ]
    consulta = (
        select(nome, *colunas)
        .select_from(OciNavegacao)
        .join(alvo)
        .where(OciNavegacao.data_hora >= inicio)
        .group_by(nome)
    )
    linhas = db.execute(_das_etapas(consulta, recorte)).all()
    return [EtapasDoGrupo(linha[0], *map(int, linha[1:])) for linha in linhas]


def etapas_por_unidade(db: Session, recorte: Recorte, inicio: datetime) -> list[EtapasDoGrupo]:
    return _etapas_agrupadas(db, recorte, inicio, UnidadeSaude.nome, UnidadeSaude)


def etapas_por_servico(db: Session, recorte: Recorte, inicio: datetime) -> list[EtapasDoGrupo]:
    return _etapas_agrupadas(db, recorte, inicio, ServicoSaude.nome, ServicoSaude)


def proximas_etapas(db: Session, recorte: Recorte, agora: datetime, ate: datetime) -> int:
    consulta = (
        select(func.count())
        .select_from(OciNavegacao)
        .where(
            OciNavegacao.status == "agendado",
            OciNavegacao.data_hora >= agora,
            OciNavegacao.data_hora < ate,
        )
    )
    return int(db.scalar(_das_etapas(consulta, recorte)) or 0)
