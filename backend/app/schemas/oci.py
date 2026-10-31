import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
)

from app.schemas.validadores import Cpf, sem_controle

IdInteiro = Annotated[int, Field(ge=1, le=2_147_483_647)]
IdCid = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Resultado = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=2, max_length=4000),
    AfterValidator(sem_controle),
]
SituacaoOci = Literal["aberta", "concluida", "cancelada"]
_ANOS_NO_FUTURO = 5


def _data_plausivel(valor: datetime) -> datetime:
    agora = datetime.now(UTC)
    if (
        not agora - timedelta(days=365 * 20)
        <= valor
        <= agora + timedelta(days=365 * _ANOS_NO_FUTURO)
    ):
        raise ValueError("Data fora do período aceito.")
    return valor


DataHora = Annotated[AwareDatetime, AfterValidator(_data_plausivel)]


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class OciNova(_Entrada):
    """O CPF vai no corpo, nunca na URL. A primeira etapa define onde a OCI é vista."""

    cpf: Cpf = Field(repr=False)
    id_tipo_oci: IdInteiro
    cid: IdCid
    id_unidade: IdInteiro
    id_servico: IdInteiro
    data_hora: DataHora


class OciListaEntrada(_Entrada):
    depois: uuid.UUID | None = None
    status: SituacaoOci | None = None
    id_tipo_oci: IdInteiro | None = None
    id_unidade: IdInteiro | None = None
    cpf: Cpf | None = Field(default=None, repr=False)
    atrasadas: bool = False


class DashboardEntrada(_Entrada):
    """Período em opções fechadas: o custo da consulta fica limitado (ADR-0027)."""

    dias: Literal[30, 90, 180, 365] = 90
    id_tipo_oci: IdInteiro | None = None
    id_unidade: IdInteiro | None = None


class OciAlteracao(_Entrada):
    cid: IdCid


class OciConclusao(_Entrada):
    resultado: Resultado = Field(repr=False)
    resultado_cid: IdCid | None = None


class EtapaNova(_Entrada):
    id_unidade: IdInteiro
    id_servico: IdInteiro
    data_hora: DataHora


class EtapaAlteracao(_Entrada):
    status: Literal["realizado", "faltou", "cancelado"]


class EtapaRemarcacao(_Entrada):
    id_unidade: IdInteiro
    id_servico: IdInteiro
    data_hora: DataHora


class CidResumo(BaseModel):
    id: str
    cid: str
    descricao: str


class OciResumo(BaseModel):
    id: uuid.UUID
    paciente_nome: str | None
    cpf_mascarado: str | None
    tipo_oci: str
    cid: CidResumo
    status: SituacaoOci
    data_criacao: datetime
    prazo_em: datetime
    atrasada: bool
    dias_restantes: int | None  # só em OCI aberta; negativo quando o prazo já passou


class OciPagina(BaseModel):
    itens: list[OciResumo]
    proximo: uuid.UUID | None


class EtapaResposta(BaseModel):
    id: int
    id_unidade: int
    unidade: str
    id_servico: int
    servico: str
    data_hora: datetime
    status: str
    pode_marcar: bool


class OciDetalhe(OciResumo):
    id_tipo_oci: int
    paciente_id: uuid.UUID
    resultado: str | None = Field(repr=False)
    resultado_cid: CidResumo | None
    navegacoes: list[EtapaResposta]


class OpcaoSimples(BaseModel):
    id: int
    nome: str


class OciOpcoes(BaseModel):
    tipos: list[OpcaoSimples]
    unidades: list[OpcaoSimples]
    unidades_abertura: list[OpcaoSimples]


class ListaDeCids(BaseModel):
    cids: list[CidResumo]


class UnidadeQueAtende(BaseModel):
    id: int
    nome: str
    servicos: list[OpcaoSimples]


class UnidadesQueAtendem(BaseModel):
    unidades: list[UnidadeQueAtende]


class DiaComVagas(BaseModel):
    data: date
    vagas: int


class DiasComVagas(BaseModel):
    dias: list[DiaComVagas]


class HorarioVago(BaseModel):
    data_hora: datetime
    hora: str
    vagas: int


class HorariosVagos(BaseModel):
    horarios: list[HorarioVago]


class _DoServico(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ResumoAbertasDashboard(_DoServico):
    em_aberto: int
    atrasadas: int
    vencem_em_breve: int


class ResumoConclusoesDashboard(_DoServico):
    concluidas: int
    no_prazo: int
    mediana_dias: float | None


class PontoDoDashboard(_DoServico):
    inicio: date
    abertas: int
    concluidas: int


class OcisDoTipoDashboard(_DoServico):
    nome: str
    aberta: int
    concluida: int
    cancelada: int


class OcisDoCidDashboard(_DoServico):
    codigo: str
    descricao: str
    total: int


class EtapasDashboard(_DoServico):
    nome: str
    agendado: int
    realizado: int
    faltou: int
    cancelado: int
    remarcado: int


class DashboardResposta(_DoServico):
    """Só contagens: nenhum campo identifica paciente ou OCI."""

    alcance: Literal["todas", "unidade", "nenhuma"]
    dias: int
    abertas: ResumoAbertasDashboard
    conclusoes: ResumoConclusoesDashboard
    abertas_no_periodo: int
    canceladas_no_periodo: int
    proximas_etapas: int
    granularidade: Literal["week", "month"]
    serie: list[PontoDoDashboard]
    por_tipo: list[OcisDoTipoDashboard]
    por_cid: list[OcisDoCidDashboard]
    etapas: EtapasDashboard
    por_unidade: list[EtapasDashboard]
    por_servico: list[EtapasDashboard]
