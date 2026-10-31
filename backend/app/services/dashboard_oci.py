"""Dashboard de OCI (ADR-0027): indicadores agregados, com o mesmo alcance por unidade da lista.

Não lê nem devolve dado de paciente e não decifra nada: só contagens, por tipo, CID, unidade e
serviço. A consulta fica no log com os filtros usados, sem nenhum valor do resultado.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from typing import Literal

from sqlalchemy.orm import Session

from app.models import Oci
from app.repositories import dashboard_oci as repo
from app.repositories.dashboard_oci import EtapasDoGrupo, Recorte, ResumoAbertas, ResumoConclusoes
from app.services import agenda, auditoria
from app.services import oci as oci_service
from app.services.auditoria import ContextoRequisicao, Evento

_DIAS_DO_ALERTA = 7  # o mesmo limite do indicador de prazo da lista de OCIs (ADR-0026)
_DIAS_DAS_PROXIMAS = 7
_DIAS_POR_SEMANA = 90  # períodos até aqui são agrupados por semana; acima, por mês
_MAXIMO_DE_LINHAS = 8  # o que passar disso é somado em "Outros"
_OUTROS = "Outros"
_DESLOCAMENTO = agenda.FUSO.utcoffset(None) or timedelta()

Alcance = Literal["todas", "unidade", "nenhuma"]
Granularidade = Literal["week", "month"]


@dataclass(frozen=True)
class FiltrosDashboard:
    dias: int
    id_tipo_oci: int | None = None
    id_unidade: int | None = None


@dataclass(frozen=True)
class PontoDaSerie:
    inicio: date
    abertas: int
    concluidas: int


@dataclass(frozen=True)
class OcisDoTipo:
    nome: str
    aberta: int = 0
    concluida: int = 0
    cancelada: int = 0


@dataclass(frozen=True)
class OcisDoCid:
    codigo: str
    descricao: str
    total: int


@dataclass(frozen=True)
class Dashboard:
    alcance: Alcance
    dias: int
    abertas: ResumoAbertas = field(default_factory=lambda: ResumoAbertas(0, 0, 0))
    conclusoes: ResumoConclusoes = field(default_factory=lambda: ResumoConclusoes(0, 0, None))
    abertas_no_periodo: int = 0
    canceladas_no_periodo: int = 0
    proximas_etapas: int = 0
    granularidade: Granularidade = "week"
    serie: list[PontoDaSerie] = field(default_factory=list)
    por_tipo: list[OcisDoTipo] = field(default_factory=list)
    por_cid: list[OcisDoCid] = field(default_factory=list)
    etapas: EtapasDoGrupo = field(default_factory=lambda: EtapasDoGrupo("Total"))
    por_unidade: list[EtapasDoGrupo] = field(default_factory=list)
    por_servico: list[EtapasDoGrupo] = field(default_factory=list)


def montar(
    db: Session,
    filtros: FiltrosDashboard,
    autor: bytes,
    ctx: ContextoRequisicao,
    agora: datetime,
) -> Dashboard:
    alcance = oci_service.alcance_de(db, autor)
    if not alcance.todas_as_unidades and alcance.unidade is None:
        return Dashboard(alcance="nenhuma", dias=filtros.dias)  # sem unidade, nenhuma OCI

    # Alcance e filtro valem juntos: filtrar outra unidade não amplia o alcance, só zera a conta.
    unidades = [] if alcance.todas_as_unidades else [alcance.unidade]
    if filtros.id_unidade is not None:
        unidades.append(filtros.id_unidade)
    recorte = Recorte(
        unidades=tuple(u for u in dict.fromkeys(unidades) if u is not None),
        id_tipo_oci=filtros.id_tipo_oci,
    )
    resultado = _calcular(db, recorte, filtros.dias, agora)
    auditoria.registrar(
        db,
        Evento.OCI_DASHBOARD_READ,
        ctx,
        cpf_usuario_hash=autor,
        resumo={
            "recurso": "dashboard_oci",
            "dias": filtros.dias,
            "id_tipo_oci": filtros.id_tipo_oci,
            "id_unidade": filtros.id_unidade,
        },
    )
    return replace(resultado, alcance="todas" if alcance.todas_as_unidades else "unidade")


def _calcular(db: Session, recorte: Recorte, dias: int, agora: datetime) -> Dashboard:
    hoje = agenda.hoje(agora)
    inicio = datetime.combine(hoje - timedelta(days=dias - 1), time.min, agenda.FUSO)
    # Até o fim do sétimo dia, na hora de Recife, como na lista de OCIs.
    alerta_ate = datetime.combine(hoje + timedelta(days=_DIAS_DO_ALERTA + 1), time.min, agenda.FUSO)
    por_tipo = repo.ocis_por_tipo(db, recorte, inicio)
    tipos = sorted(
        (OcisDoTipo(nome, **situacoes) for nome, situacoes in por_tipo),
        key=lambda t: (-_total_do_tipo(t), t.nome),
    )
    por_servico = repo.etapas_por_servico(db, recorte, inicio)
    granularidade: Granularidade = "week" if dias <= _DIAS_POR_SEMANA else "month"
    return Dashboard(
        alcance="todas",
        dias=dias,
        abertas=repo.resumo_abertas(db, recorte, agora, alerta_ate),
        conclusoes=repo.resumo_conclusoes(db, recorte, inicio),
        abertas_no_periodo=sum(_total_do_tipo(t) for t in tipos),
        canceladas_no_periodo=sum(t.cancelada for t in tipos),
        proximas_etapas=repo.proximas_etapas(
            db, recorte, agora, agora + timedelta(days=_DIAS_DAS_PROXIMAS)
        ),
        granularidade=granularidade,
        serie=_serie(db, recorte, inicio, hoje, granularidade),
        por_tipo=_dobrar_tipos(tipos),
        por_cid=[
            OcisDoCid(codigo, descricao, total)
            for codigo, descricao, total in repo.ocis_por_cid(
                db, recorte, inicio, _MAXIMO_DE_LINHAS
            )
        ],
        etapas=_somar_etapas("Total", por_servico),
        por_unidade=dobrar_etapas(repo.etapas_por_unidade(db, recorte, inicio)),
        por_servico=dobrar_etapas(por_servico),
    )


def _serie(
    db: Session, recorte: Recorte, inicio: datetime, hoje: date, granularidade: Granularidade
) -> list[PontoDaSerie]:
    abertas = repo.serie_por_periodo(
        db, recorte, Oci.data_criacao, inicio, _DESLOCAMENTO, granularidade
    )
    concluidas = repo.serie_por_periodo(
        db,
        recorte,
        Oci.atualizado_em,
        inicio,
        _DESLOCAMENTO,
        granularidade,
        Oci.status == "concluida",
    )
    return [
        PontoDaSerie(dia, abertas.get(dia, 0), concluidas.get(dia, 0))
        for dia in periodos(inicio.date(), hoje, granularidade)
    ]


def periodos(inicio: date, fim: date, granularidade: Granularidade) -> list[date]:
    """Todos os períodos do intervalo, para um período sem OCI aparecer como zero, não sumir."""
    if granularidade == "week":
        atual = inicio - timedelta(days=inicio.weekday())
        passo = timedelta(days=7)
        saida = []
        while atual <= fim:
            saida.append(atual)
            atual += passo
        return saida
    saida = []
    ano, mes = inicio.year, inicio.month
    while (ano, mes) <= (fim.year, fim.month):
        saida.append(date(ano, mes, 1))
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return saida


def _total_do_tipo(tipo: OcisDoTipo) -> int:
    return tipo.aberta + tipo.concluida + tipo.cancelada


def _dobrar_tipos(tipos: Sequence[OcisDoTipo]) -> list[OcisDoTipo]:
    if len(tipos) <= _MAXIMO_DE_LINHAS:
        return list(tipos)
    resto = tipos[_MAXIMO_DE_LINHAS - 1 :]
    return [
        *tipos[: _MAXIMO_DE_LINHAS - 1],
        OcisDoTipo(
            _OUTROS,
            sum(t.aberta for t in resto),
            sum(t.concluida for t in resto),
            sum(t.cancelada for t in resto),
        ),
    ]


def _total_de_etapas(grupo: EtapasDoGrupo) -> int:
    return grupo.agendado + grupo.realizado + grupo.faltou + grupo.cancelado + grupo.remarcado


def _somar_etapas(nome: str, grupos: Sequence[EtapasDoGrupo]) -> EtapasDoGrupo:
    return EtapasDoGrupo(
        nome,
        sum(g.agendado for g in grupos),
        sum(g.realizado for g in grupos),
        sum(g.faltou for g in grupos),
        sum(g.cancelado for g in grupos),
        sum(g.remarcado for g in grupos),
    )


def dobrar_etapas(grupos: Sequence[EtapasDoGrupo]) -> list[EtapasDoGrupo]:
    """Maiores primeiro; além do limite, o restante é somado em "Outros"."""
    ordenados = sorted(grupos, key=lambda g: (-_total_de_etapas(g), g.nome))
    if len(ordenados) <= _MAXIMO_DE_LINHAS:
        return ordenados
    primeiros = ordenados[: _MAXIMO_DE_LINHAS - 1]
    return [*primeiros, _somar_etapas(_OUTROS, ordenados[_MAXIMO_DE_LINHAS - 1 :])]
