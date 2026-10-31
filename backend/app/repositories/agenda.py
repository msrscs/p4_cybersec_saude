from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AgendaServico,
    CidServico,
    OciNavegacao,
    ServicoSaude,
    UnidadeSaude,
    UnidadeServico,
)

# Remarcada e cancelada liberam a vaga; as demais ocupam, inclusive para o histórico.
_NAO_OCUPAM = ("cancelado", "remarcado")


def agendas_ativas(db: Session, id_unidade: int, id_servico: int) -> list[AgendaServico]:
    consulta = select(AgendaServico).where(
        AgendaServico.id_unidade == id_unidade,
        AgendaServico.id_servico == id_servico,
        AgendaServico.status == "ativo",
    )
    return list(db.scalars(consulta))


def outras_agendas_no_dia(
    db: Session, id_unidade: int, id_servico: int, dia_semana: int, exceto: int | None
) -> list[AgendaServico]:
    consulta = select(AgendaServico).where(
        AgendaServico.id_unidade == id_unidade,
        AgendaServico.id_servico == id_servico,
        AgendaServico.dia_semana == dia_semana,
        AgendaServico.status == "ativo",
    )
    if exceto is not None:
        consulta = consulta.where(AgendaServico.id_agenda != exceto)
    return list(db.scalars(consulta))


def ocupacao(
    db: Session, id_unidade: int, id_servico: int, inicio: datetime, fim: datetime
) -> dict[datetime, int]:
    """Quantas etapas ocupam cada horário do período."""
    consulta = (
        select(OciNavegacao.data_hora, func.count())
        .where(
            OciNavegacao.id_unidade == id_unidade,
            OciNavegacao.id_servico == id_servico,
            OciNavegacao.data_hora >= inicio,
            OciNavegacao.data_hora < fim,
            OciNavegacao.status.not_in(_NAO_OCUPAM),
        )
        .group_by(OciNavegacao.data_hora)
    )
    return {data_hora: total for data_hora, total in db.execute(consulta).tuples()}


def travar_vagas(db: Session, id_unidade: int, id_servico: int) -> None:
    """Serializa a marcação por unidade e serviço, até o fim da transação: nunca passa do limite."""
    db.execute(select(func.pg_advisory_xact_lock(id_unidade, id_servico)))


def unidades_do_cid(db: Session, cid_hash: bytes) -> list[tuple[UnidadeSaude, ServicoSaude]]:
    """Unidades ativas que oferecem um serviço ativo do CID, com agenda ativa para ele."""
    consulta = (
        select(UnidadeSaude, ServicoSaude)
        .join(UnidadeServico, UnidadeServico.fk_unidade_saude_id_unidade == UnidadeSaude.id_unidade)
        .join(ServicoSaude, ServicoSaude.id_servico == UnidadeServico.fk_servico_saude_id_servico)
        .join(CidServico, CidServico.fk_servico_saude_id_servico == ServicoSaude.id_servico)
        .where(
            CidServico.fk_cid_cid_hash == cid_hash,
            UnidadeSaude.status == "ativo",
            ServicoSaude.status == "ativo",
            select(AgendaServico.id_agenda)
            .where(
                AgendaServico.id_unidade == UnidadeSaude.id_unidade,
                AgendaServico.id_servico == ServicoSaude.id_servico,
                AgendaServico.status == "ativo",
            )
            .exists(),
        )
        .order_by(func.lower(UnidadeSaude.nome), func.lower(ServicoSaude.nome))
    )
    return [(unidade, servico) for unidade, servico in db.execute(consulta).tuples()]


def servico_do_cid(db: Session, cid_hash: bytes, id_servico: int) -> bool:
    consulta = select(CidServico.fk_cid_cid_hash).where(
        CidServico.fk_cid_cid_hash == cid_hash,
        CidServico.fk_servico_saude_id_servico == id_servico,
    )
    return db.scalars(consulta.limit(1)).first() is not None
