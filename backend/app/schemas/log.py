from datetime import datetime
from typing import Any, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.schemas.validadores import Cpf
from app.services.auditoria import Evento


class LogConsulta(BaseModel):
    """Filtros opcionais. O CPF do usuário vai no corpo, nunca na URL."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    de: AwareDatetime | None = None
    ate: AwareDatetime | None = None
    acao: Evento | None = None
    cpf: Cpf | None = Field(default=None, repr=False)
    antes: int | None = Field(default=None, ge=1, le=2**63 - 1)

    @model_validator(mode="after")
    def _periodo(self) -> Self:
        if self.de is not None and self.ate is not None and self.de > self.ate:
            raise ValueError("Período inválido.")
        return self


class LogItem(BaseModel):
    seq: int
    data_hora: datetime
    acao: str
    ip_origem: str | None
    request_id: str | None
    usuario: str | None  # hash truncado: existe mesmo quando o CPF não tem cadastro
    paciente: str | None
    usuario_cpf: str | None = Field(repr=False)  # só com log:ver_cpf; nunca gravado no log
    paciente_cpf: str | None = Field(repr=False)
    id_oci: int | None
    pacientes_lista: list[str] = Field(repr=False)  # eventos de lista: CPF ou hash de cada um
    hash: str
    resumo: dict[str, Any]


class LogPagina(BaseModel):
    itens: list[LogItem]
    proximo: int | None


class LogAcoes(BaseModel):
    acoes: list[str]


class LogIntegridade(BaseModel):
    total_registros: int
    verificada_em: datetime | None
    integra: bool | None
    checkpoint_em: datetime | None
    checkpoint_seq: int | None
