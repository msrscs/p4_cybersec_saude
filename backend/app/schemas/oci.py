import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
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
    status: Literal["realizado", "faltou", "cancelado"] | None = None
    data_hora: DataHora | None = None

    @model_validator(mode="after")
    def _algum_campo(self) -> Self:
        if self.status is None and self.data_hora is None:
            raise ValueError("Informe a situação ou a data.")
        return self


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


class ListaDeServicos(BaseModel):
    servicos: list[OpcaoSimples]
