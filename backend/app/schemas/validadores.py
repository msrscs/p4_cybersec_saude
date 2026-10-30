"""Tipos validados reutilizáveis (toda entrada é validada no backend)."""

import unicodedata
from typing import Annotated

from pydantic import AfterValidator, StringConstraints

from app.core.cpf import validar_cpf
from app.core.senha import BYTES_MAXIMO


def sem_controle(valor: str) -> str:
    if any(unicodedata.category(c).startswith("C") for c in valor):
        raise ValueError("Contém caracteres não permitidos.")
    return valor


def _ate_72_bytes(valor: str) -> str:
    if len(valor.encode("utf-8")) > BYTES_MAXIMO:
        raise ValueError(f"Máximo de {BYTES_MAXIMO} bytes.")
    return valor


Cpf = Annotated[str, StringConstraints(max_length=14), AfterValidator(validar_cpf)]
Nome = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=2, max_length=150),
    AfterValidator(sem_controle),
]
SenhaEntrada = Annotated[str, StringConstraints(min_length=1), AfterValidator(_ate_72_bytes)]
