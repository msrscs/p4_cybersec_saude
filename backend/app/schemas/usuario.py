from typing import Self

from pydantic import BaseModel, ConfigDict, EmailStr, Field, PositiveInt, model_validator

from app.core.senha import validar_politica
from app.schemas.validadores import Cpf, Nome, SenhaEntrada


class UsuarioCadastro(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    cpf: Cpf
    nome: Nome
    email: EmailStr = Field(max_length=254)
    senha: SenhaEntrada = Field(repr=False)
    id_unidade: PositiveInt | None = None

    @model_validator(mode="after")
    def _politica_de_senha(self) -> Self:
        validar_politica(self.senha, cpf=self.cpf)
        return self
