"""Política e hash de senhas com bcrypt (ADR-0003)."""

import re
import secrets
from collections.abc import Callable
from functools import lru_cache

import bcrypt

TAMANHO_MINIMO = 12
TAMANHO_MAXIMO = 64
BYTES_MAXIMO = 72  # limite do bcrypt; acima disso a senha é recusada (ADR-0003)
ROUNDS_MINIMO_PRODUCAO = 12

_REGRAS: tuple[tuple[Callable[[str], bool], str], ...] = (
    (str.isupper, "uma letra maiúscula"),
    (str.islower, "uma letra minúscula"),
    (str.isdigit, "um número"),
    (lambda c: not c.isalnum() and not c.isspace(), "um caractere especial"),
)


def problemas_politica(senha: str, *, cpf: str | None = None) -> list[str]:
    """Lista o que falta na senha (RF-01). Mensagens nunca incluem a senha."""
    problemas: list[str] = []
    if not TAMANHO_MINIMO <= len(senha) <= TAMANHO_MAXIMO:
        problemas.append(f"ter entre {TAMANHO_MINIMO} e {TAMANHO_MAXIMO} caracteres")
    if len(senha.encode("utf-8")) > BYTES_MAXIMO:
        problemas.append(f"ter no máximo {BYTES_MAXIMO} bytes")
    problemas += [f"conter {desc}" for regra, desc in _REGRAS if not any(map(regra, senha))]
    if cpf and cpf in re.sub(r"\D", "", senha):
        problemas.append("não conter o CPF")
    return problemas


def validar_politica(senha: str, *, cpf: str | None = None) -> None:
    if problemas := problemas_politica(senha, cpf=cpf):
        raise ValueError("A senha deve " + "; ".join(problemas) + ".")


def _bytes(senha: str) -> bytes:
    dados = senha.encode("utf-8")
    if len(dados) > BYTES_MAXIMO:
        raise ValueError(f"Senha acima de {BYTES_MAXIMO} bytes.")
    return dados


def gerar_hash(senha: str, rounds: int) -> str:
    return bcrypt.hashpw(_bytes(senha), bcrypt.gensalt(rounds)).decode("ascii")


def verificar(senha: str, hash_armazenado: str) -> bool:
    try:
        return bcrypt.checkpw(_bytes(senha), hash_armazenado.encode("ascii"))
    except ValueError:
        return False


@lru_cache
def _hash_ficticio(rounds: int) -> str:
    return gerar_hash(secrets.token_urlsafe(16), rounds)


def verificar_ficticio(senha: str, rounds: int) -> None:
    """Gasta o mesmo tempo de uma verificação real (usuário inexistente/bloqueado, ameaça I5)."""
    verificar(senha, _hash_ficticio(rounds))


def precisa_rehash(hash_armazenado: str, rounds: int) -> bool:
    try:
        return int(hash_armazenado.split("$")[2]) < rounds
    except IndexError, ValueError:
        return True
