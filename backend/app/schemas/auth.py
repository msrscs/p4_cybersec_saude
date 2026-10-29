from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.validadores import Cpf, SenhaEntrada


class LoginEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    cpf: Cpf = Field(examples=["123.456.789-09"])
    senha: SenhaEntrada = Field(repr=False)


class LoginResposta(BaseModel):
    etapa: Literal["mfa"]


class ErroResposta(BaseModel):
    detail: str
