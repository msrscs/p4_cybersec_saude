"""Dias e horários com vaga (RF-12, ADR-0026).

Os horários são calculados a partir da agenda de cada unidade e serviço, e as vagas livres
descontam as etapas marcadas. As agendas estão na hora de Recife, sem horário de verão: o fuso fixo
evita depender de base de fusos na imagem do container.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import AgendaServico, ServicoSaude, UnidadeSaude
from app.repositories import agenda as agenda_repo

FUSO = timezone(timedelta(hours=-3), "America/Recife")
HORIZONTE_DIAS = 60


class HorarioIndisponivel(Exception):
    def __init__(self) -> None:
        super().__init__("Este horário não está mais disponível: escolha outro.")


@dataclass(frozen=True)
class Horario:
    data_hora: datetime
    vagas: int


@dataclass(frozen=True)
class DiaComVagas:
    data: date
    vagas: int


@dataclass(frozen=True)
class UnidadeQueAtende:
    unidade: UnidadeSaude
    servicos: list[ServicoSaude]


def hoje(agora: datetime) -> date:
    return agora.astimezone(FUSO).date()


def unidades_que_atendem(db: Session, cid_hash: bytes) -> list[UnidadeQueAtende]:
    agrupadas: dict[int, UnidadeQueAtende] = {}
    for unidade, servico in agenda_repo.unidades_do_cid(db, cid_hash):
        item = agrupadas.setdefault(unidade.id_unidade, UnidadeQueAtende(unidade, []))
        item.servicos.append(servico)
    return list(agrupadas.values())


def _capacidade_do_dia(agendas: list[AgendaServico], dia: date) -> dict[datetime, int]:
    capacidade: dict[datetime, int] = defaultdict(int)
    for agenda in agendas:
        if agenda.dia_semana != dia.weekday():
            continue
        inicio = datetime.combine(dia, agenda.hora_inicio, FUSO)
        fim = datetime.combine(dia, agenda.hora_fim, FUSO)
        passo = timedelta(minutes=agenda.duracao_minutos)
        horario = inicio
        while horario + passo <= fim:
            capacidade[horario] += agenda.vagas_por_horario
            horario += passo
    return capacidade


def _horarios_do_periodo(
    db: Session, id_unidade: int, id_servico: int, primeiro: date, ultimo: date, agora: datetime
) -> list[Horario]:
    agendas = agenda_repo.agendas_ativas(db, id_unidade, id_servico)
    if not agendas:
        return []
    inicio = datetime.combine(primeiro, datetime.min.time(), FUSO)
    fim = datetime.combine(ultimo + timedelta(days=1), datetime.min.time(), FUSO)
    ocupados = agenda_repo.ocupacao(db, id_unidade, id_servico, inicio, fim)
    horarios: list[Horario] = []
    for deslocamento in range((ultimo - primeiro).days + 1):
        dia = primeiro + timedelta(days=deslocamento)
        for data_hora, capacidade in sorted(_capacidade_do_dia(agendas, dia).items()):
            vagas = capacidade - ocupados.get(data_hora, 0)
            if vagas > 0 and data_hora > agora:
                horarios.append(Horario(data_hora.astimezone(FUSO), vagas))
    return horarios


def dias_com_vagas(
    db: Session, id_unidade: int, id_servico: int, agora: datetime
) -> list[DiaComVagas]:
    primeiro = hoje(agora)
    ultimo = primeiro + timedelta(days=HORIZONTE_DIAS)
    totais: dict[date, int] = defaultdict(int)
    for horario in _horarios_do_periodo(db, id_unidade, id_servico, primeiro, ultimo, agora):
        totais[horario.data_hora.date()] += horario.vagas
    return [DiaComVagas(dia, vagas) for dia, vagas in sorted(totais.items())]


def horarios_com_vagas(
    db: Session, id_unidade: int, id_servico: int, dia: date, agora: datetime
) -> list[Horario]:
    if not hoje(agora) <= dia <= hoje(agora) + timedelta(days=HORIZONTE_DIAS):
        return []
    return _horarios_do_periodo(db, id_unidade, id_servico, dia, dia, agora)


def reservar(
    db: Session, id_unidade: int, id_servico: int, data_hora: datetime, agora: datetime
) -> None:
    """Confere, sob trava, que o horário existe na agenda e tem vaga, antes de gravar a etapa."""
    agenda_repo.travar_vagas(db, id_unidade, id_servico)
    dia = data_hora.astimezone(FUSO).date()
    for horario in _horarios_do_periodo(db, id_unidade, id_servico, dia, dia, agora):
        if horario.data_hora == data_hora.astimezone(UTC):
            return
    raise HorarioIndisponivel
