"""Validação de CPF (dígitos verificadores)."""

import re


def normalizar_cpf(valor: str) -> str:
    return re.sub(r"[.\-\s]", "", valor)


def _digito(base: str) -> int:
    peso_inicial = len(base) + 1
    soma = sum(int(d) * peso for d, peso in zip(base, range(peso_inicial, 1, -1), strict=True))
    resto = soma % 11
    return 0 if resto < 2 else 11 - resto


def cpf_valido(valor: str) -> bool:
    cpf = normalizar_cpf(valor)
    if len(cpf) != 11 or not cpf.isascii() or not cpf.isdigit() or len(set(cpf)) == 1:
        return False
    return _digito(cpf[:9]) == int(cpf[9]) and _digito(cpf[:10]) == int(cpf[10])


def validar_cpf(valor: str) -> str:
    """Devolve o CPF só com dígitos ou levanta ValueError (mensagem sem o valor)."""
    if not cpf_valido(valor):
        raise ValueError("CPF inválido.")
    return normalizar_cpf(valor)
