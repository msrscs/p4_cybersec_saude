import re
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    model_validator,
)

from app.schemas.validadores import Cpf, Nome

IDADE_MAXIMA = 130


def _nascimento_plausivel(valor: date) -> date:
    hoje = datetime.now(UTC).date()
    if valor > hoje:
        raise ValueError("Data de nascimento no futuro.")
    if valor < hoje - timedelta(days=round(365.25 * IDADE_MAXIMA)):
        raise ValueError(f"Data de nascimento acima de {IDADE_MAXIMA} anos.")
    return valor


def _so_iso(valor: object) -> object:
    # Só texto AAAA-MM-DD: recusa números (timestamps) e outros formatos ambíguos.
    if not isinstance(valor, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor):
        raise ValueError("Data no formato AAAA-MM-DD.")
    return valor


def _email_normalizado(valor: str) -> str:
    return valor.strip().lower()


DataNascimento = Annotated[
    date,
    Field(examples=["1980-05-17"]),
    BeforeValidator(_so_iso),
    AfterValidator(_nascimento_plausivel),
]
Email = Annotated[EmailStr, Field(max_length=254), AfterValidator(_email_normalizado)]


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class PacienteCadastro(_Entrada):
    cpf: Cpf = Field(examples=["123.456.789-09"])
    nome: Nome
    data_nascimento: DataNascimento
    email: Email | None = None


class PacienteBusca(_Entrada):
    cpf: Cpf = Field(examples=["123.456.789-09"])


class PacienteListaEntrada(_Entrada):
    """`depois` é o cursor devolvido em `proximo`; sem ele, começa do paciente mais recente."""

    depois: uuid.UUID | None = None


class PacienteAlteracao(_Entrada):
    """Só os campos enviados são alterados; `email: null` remove o e-mail."""

    nome: Nome | None = None
    data_nascimento: DataNascimento | None = None
    email: Email | None = None

    @model_validator(mode="after")
    def _algum_campo(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Informe ao menos um campo.")
        for campo in ("nome", "data_nascimento"):
            if campo in self.model_fields_set and getattr(self, campo) is None:
                raise ValueError(f"{campo} não pode ser nulo.")
        return self


class PacienteResumo(BaseModel):
    id: uuid.UUID
    cpf_mascarado: str | None  # None: cadastro ilegível
    nome: str | None
    status: Literal["ativo", "inativo"]


class PacienteListaResposta(BaseModel):
    itens: list[PacienteResumo]
    proximo: uuid.UUID | None


class PacienteResposta(BaseModel):
    id: uuid.UUID
    cpf: str
    nome: str
    data_nascimento: date
    email: str | None
    status: Literal["ativo", "inativo"]
    criado_em: datetime
    atualizado_em: datetime
