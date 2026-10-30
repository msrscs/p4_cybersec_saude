import uuid
from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, StringConstraints, model_validator

from app.schemas.paciente import Email
from app.schemas.validadores import Cpf, Nome

NomeGrupo = Annotated[str, StringConstraints(min_length=1, max_length=60)]
Grupos = Annotated[list[NomeGrupo], Field(max_length=20)]


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class UsuarioListaEntrada(_Entrada):
    depois: uuid.UUID | None = None


class UsuarioNovo(_Entrada):
    """Sem senha: o sistema gera uma temporária, com troca obrigatória no primeiro acesso."""

    cpf: Cpf = Field(examples=["123.456.789-09"])
    nome: Nome
    email: Email
    id_unidade: PositiveInt | None = None
    grupos: Grupos = []


class UsuarioAlteracao(_Entrada):
    """Só os campos enviados são alterados; `id_unidade: null` remove a unidade. CPF é imutável."""

    nome: Nome | None = None
    email: Email | None = None
    id_unidade: PositiveInt | None = None

    @model_validator(mode="after")
    def _algum_campo(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Informe ao menos um campo.")
        for campo in ("nome", "email"):
            if campo in self.model_fields_set and getattr(self, campo) is None:
                raise ValueError(f"{campo} não pode ser nulo.")
        return self


class UsuarioGrupos(_Entrada):
    grupos: Grupos


class UsuarioResumo(BaseModel):
    id: uuid.UUID
    cpf_mascarado: str | None  # None: cadastro ilegível
    nome: str | None
    status: str
    grupos: list[str]


class UsuarioListaResposta(BaseModel):
    itens: list[UsuarioResumo]
    proximo: uuid.UUID | None


class UsuarioDetalhe(BaseModel):
    id: uuid.UUID
    cpf: str
    nome: str
    email: str
    id_unidade: int | None
    unidade_nome: str | None
    status: str
    mfa_ativo: bool
    troca_senha_obrigatoria: bool
    bloqueado: bool
    grupos: list[str]
    proprio: bool  # a interface esconde o que o backend recusaria para a própria conta
    criado_em: datetime
    atualizado_em: datetime


class UsuarioCriado(BaseModel):
    usuario: UsuarioDetalhe
    senha_temporaria: str = Field(repr=False)


class SenhaTemporaria(BaseModel):
    senha_temporaria: str = Field(repr=False)


class ListaDeGrupos(BaseModel):
    grupos: list[str]
