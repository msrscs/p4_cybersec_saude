import re
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.schemas.validadores import Nome, sem_controle

IdTipo = Annotated[int, Field(ge=1, le=2_147_483_647)]
IdsServicos = Annotated[list[Annotated[int, Field(ge=1, le=2_147_483_647)]], Field(max_length=1000)]
_CID = re.compile(r"[A-Z][0-9]{2}(\.[0-9A-Z]{1,2})?")


def _telefone(valor: str) -> str:
    if not re.fullmatch(r"[0-9()\s+-]+", valor):
        raise ValueError("Telefone inválido.")
    digitos = re.sub(r"\D", "", valor)
    if len(digitos) not in (10, 11):
        raise ValueError("Telefone com DDD: 10 ou 11 dígitos.")
    return digitos


def _codigo_cid(valor: str) -> str:
    codigo = valor.strip().upper()
    if not _CID.fullmatch(codigo):
        raise ValueError("Código CID inválido. Exemplo: C50.9.")
    return codigo


Endereco = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=300),
    AfterValidator(sem_controle),
]
Descricao = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=500), AfterValidator(sem_controle)
]
DescricaoCid = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=2, max_length=500),
    AfterValidator(sem_controle),
]
Telefone = Annotated[str, StringConstraints(max_length=20), AfterValidator(_telefone)]
CodigoCid = Annotated[str, StringConstraints(max_length=10), AfterValidator(_codigo_cid)]
Busca = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=100), AfterValidator(sem_controle)
]


Prazo = Annotated[int, Field(ge=1, le=3650)]
IdsCids = Annotated[
    list[Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]], Field(max_length=1000)
]
BuscaObrigatoria = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=2, max_length=100),
    AfterValidator(sem_controle),
]


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Parcial(_Entrada):
    """Só os campos enviados são alterados; os obrigatórios não aceitam nulo."""

    _obrigatorios: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _algum_campo(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Informe ao menos um campo.")
        for campo in self._obrigatorios:
            if campo in self.model_fields_set and getattr(self, campo) is None:
                raise ValueError(f"{campo} não pode ser nulo.")
        return self


class ListaEntrada(_Entrada):
    pagina: int = Field(default=1, ge=1, le=100_000)
    busca: Busca | None = None


class TipoNovo(_Entrada):
    nome: Nome
    descricao: Descricao = ""


class TipoAlteracao(_Parcial):
    _obrigatorios = ("nome", "descricao")

    nome: Nome | None = None
    descricao: Descricao | None = None


class UnidadeNova(_Entrada):
    nome: Nome
    id_tipo_unidade: IdTipo
    endereco: Endereco
    telefone: Telefone | None = None
    servicos: IdsServicos = []


class UnidadeAlteracao(_Parcial):
    _obrigatorios = ("nome", "id_tipo_unidade", "endereco", "servicos")

    nome: Nome | None = None
    id_tipo_unidade: IdTipo | None = None
    endereco: Endereco | None = None
    telefone: Telefone | None = None
    servicos: IdsServicos | None = None


class ServicoNovo(_Entrada):
    nome: Nome
    descricao: Descricao = ""


class ServicoAlteracao(_Parcial):
    _obrigatorios = ("nome", "descricao")

    nome: Nome | None = None
    descricao: Descricao | None = None


class CidNovo(_Entrada):
    cid: CodigoCid = Field(examples=["C50.9"])
    descricao: DescricaoCid


class CidOpcoesEntrada(_Entrada):
    busca: BuscaObrigatoria


class TipoOciNovo(_Entrada):
    tipo_oci: Nome
    prazo_diagnostico: Prazo
    cids: IdsCids = []


class TipoOciAlteracao(_Parcial):
    _obrigatorios = ("tipo_oci", "prazo_diagnostico", "cids")

    tipo_oci: Nome | None = None
    prazo_diagnostico: Prazo | None = None
    cids: IdsCids | None = None


class CidAlteracao(_Parcial):
    """O código é imutável: identifica o registro (cid_hash) e será referenciado pelas OCIs."""

    _obrigatorios = ("descricao",)

    descricao: DescricaoCid | None = None


class Opcao(BaseModel):
    id: int
    nome: str


class TipoResposta(BaseModel):
    id: int
    nome: str
    descricao: str
    status: str


class UnidadeResposta(BaseModel):
    id: int
    nome: str
    id_tipo_unidade: int
    tipo_unidade: str
    endereco: str
    telefone: str | None
    status: str
    servicos: list[Opcao]


class ServicoResposta(BaseModel):
    id: int
    nome: str
    descricao: str
    status: str


class CidResposta(BaseModel):
    id: str  # cid_hash em hexadecimal
    cid: str
    descricao: str
    status: str


class TiposPagina(BaseModel):
    itens: list[TipoResposta]
    tem_mais: bool


class CidOpcao(BaseModel):
    id: str
    cid: str
    descricao: str
    status: str


class CidOpcoes(BaseModel):
    opcoes: list[CidOpcao]


class TipoOciResposta(BaseModel):
    id: int
    tipo_oci: str
    prazo_diagnostico: int
    status: str
    cids: list[CidOpcao]


class TiposOciPagina(BaseModel):
    itens: list[TipoOciResposta]
    tem_mais: bool


class UnidadesPagina(BaseModel):
    itens: list[UnidadeResposta]
    tem_mais: bool


class ServicosPagina(BaseModel):
    itens: list[ServicoResposta]
    tem_mais: bool


class CidsPagina(BaseModel):
    itens: list[CidResposta]
    tem_mais: bool


class Opcoes(BaseModel):
    opcoes: list[Opcao]
