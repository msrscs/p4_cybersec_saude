from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.validadores import Cpf, SenhaEntrada

CodigoTotp = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9]{6}$")]
CodigoRecuperacao = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9]{5}-?[A-Za-z0-9]{5}$")
]


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class LoginEntrada(_Entrada):
    cpf: Cpf = Field(examples=["123.456.789-09"])
    senha: SenhaEntrada = Field(repr=False)


class LoginResposta(BaseModel):
    etapa: Literal["mfa", "mfa_cadastro"]


class CodigoTotpEntrada(_Entrada):
    codigo: CodigoTotp = Field(repr=False, examples=["123456"])


class CodigoRecuperacaoEntrada(_Entrada):
    codigo: CodigoRecuperacao = Field(repr=False, examples=["ABCDE-FGHJK"])


class ProvisionamentoResposta(BaseModel):
    otpauth_uri: str
    qr_svg: str
    chave: str


class CodigosRecuperacaoResposta(BaseModel):
    codigos_recuperacao: list[str]


class AutenticadoResposta(BaseModel):
    autenticado: Literal[True] = True
    codigos_restantes: int | None = None


class SessaoResposta(BaseModel):
    autenticado: Literal[True] = True
    expira_em: datetime
    troca_senha_obrigatoria: bool


class TrocaSenhaEntrada(_Entrada):
    senha_atual: SenhaEntrada = Field(repr=False)
    nova_senha: SenhaEntrada = Field(repr=False)


class ErroResposta(BaseModel):
    detail: str
