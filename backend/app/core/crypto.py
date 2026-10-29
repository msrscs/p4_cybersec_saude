"""Criptografia de campo: AES-256-GCM com envelope encryption e hash de busca (HMAC-SHA256).

Usa somente a biblioteca `cryptography`; nenhuma primitiva é implementada aqui.

- KEK (chave mestra, fora do banco) cifra a DEK de cada registro.
- DEK (32 bytes aleatórios por registro) cifra cada campo sensível do registro.
- Cada campo é cifrado com AAD = (tabela, coluna, id do registro): mover um valor cifrado
  para outro registro ou coluna faz a decifragem falhar.
- Hash de busca: HMAC-SHA256 com chave própria (separada da KEK) e rótulo por finalidade.

Formato de um valor cifrado: versão (1 byte) || nonce (12 bytes) || ciphertext + tag (16 bytes).
"""

import base64
import binascii
import hashlib
import hmac
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import assert_never

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

TAMANHO_CHAVE = 32
TAMANHO_NONCE = 12
TAMANHO_TAG = 16
_VERSAO_FORMATO = b"\x01"
_TAMANHO_MINIMO = len(_VERSAO_FORMATO) + TAMANHO_NONCE + TAMANHO_TAG
_DOMINIO = b"cybersec-saude"


class ErroCriptografia(Exception):
    """Falha genérica: nunca carrega texto em claro, chaves ou detalhes internos."""


class FinalidadeHash(StrEnum):
    CPF = "cpf"
    EMAIL = "email"
    CODIGO_RECUPERACAO = "codigo_recuperacao"


@dataclass(frozen=True)
class Keyring:
    """Conjunto de KEKs por versão; `ativa` é a usada para cifrar novas DEKs."""

    chaves: Mapping[int, bytes] = field(repr=False)
    ativa: int

    def __post_init__(self) -> None:
        if not self.chaves:
            raise ValueError("Keyring vazio.")
        for versao, chave in self.chaves.items():
            if versao <= 0:
                raise ValueError("Versão de KEK deve ser positiva.")
            if len(chave) != TAMANHO_CHAVE:
                raise ValueError(f"KEK versão {versao} deve ter {TAMANHO_CHAVE} bytes.")
        if self.ativa not in self.chaves:
            raise ValueError(f"KEK ativa (versão {self.ativa}) não está no keyring.")

    def kek(self, versao: int) -> bytes:
        try:
            return self.chaves[versao]
        except KeyError:
            raise ErroCriptografia("Versão de chave desconhecida.") from None


@dataclass(frozen=True)
class DekCifrada:
    """DEK cifrada pela KEK, como é guardada no registro (dek_cripto, kek_versao)."""

    dek_cripto: bytes = field(repr=False)
    kek_versao: int


def carregar_keyring(texto: str, ativa: int) -> Keyring:
    """Lê `versao:base64,versao:base64`. Erros não incluem material de chave."""
    chaves: dict[int, bytes] = {}
    for item in filter(None, (parte.strip() for parte in texto.split(","))):
        versao_txt, sep, chave_b64 = item.partition(":")
        if not sep or not versao_txt.isdigit():
            raise ValueError("Formato esperado: versao:base64[,versao:base64].")
        versao = int(versao_txt)
        if versao in chaves:
            raise ValueError(f"Versão de KEK {versao} repetida.")
        chaves[versao] = decodificar_chave(chave_b64)
    return Keyring(chaves=chaves, ativa=ativa)


def decodificar_chave(chave_b64: str) -> bytes:
    try:
        chave = base64.b64decode(chave_b64, validate=True)
    except binascii.Error, ValueError:
        raise ValueError("Chave não está em base64 válido.") from None
    if len(chave) != TAMANHO_CHAVE:
        raise ValueError(f"Chave deve ter {TAMANHO_CHAVE} bytes.")
    return chave


def gerar_chave_b64() -> str:
    return base64.b64encode(secrets.token_bytes(TAMANHO_CHAVE)).decode("ascii")


def _aad(*partes: bytes) -> bytes:
    # Cada parte com prefixo de tamanho: evita ambiguidade (ex.: "ab"+"c" vs "a"+"bc").
    return _DOMINIO + b"".join(len(p).to_bytes(4, "big") + p for p in partes)


def _cifrar(chave: bytes, dados: bytes, aad: bytes) -> bytes:
    nonce = secrets.token_bytes(TAMANHO_NONCE)
    return _VERSAO_FORMATO + nonce + AESGCM(chave).encrypt(nonce, dados, aad)


def _decifrar(chave: bytes, blob: bytes, aad: bytes) -> bytes:
    if len(blob) < _TAMANHO_MINIMO or blob[:1] != _VERSAO_FORMATO:
        raise ErroCriptografia("Falha ao decifrar dado.")
    nonce = blob[1 : 1 + TAMANHO_NONCE]
    try:
        return AESGCM(chave).decrypt(nonce, blob[1 + TAMANHO_NONCE :], aad)
    except InvalidTag:
        raise ErroCriptografia("Falha ao decifrar dado.") from None


def _aad_dek(kek_versao: int) -> bytes:
    return _aad(b"dek", str(kek_versao).encode())


def _validar_dek(dek: bytes) -> None:
    if len(dek) != TAMANHO_CHAVE:
        raise ErroCriptografia("DEK inválida.")


def gerar_dek(keyring: Keyring) -> tuple[bytes, DekCifrada]:
    """Gera uma DEK nova; devolve a DEK em claro (só em memória) e a versão cifrada."""
    dek = secrets.token_bytes(TAMANHO_CHAVE)
    versao = keyring.ativa
    cifrada = _cifrar(keyring.kek(versao), dek, _aad_dek(versao))
    return dek, DekCifrada(dek_cripto=cifrada, kek_versao=versao)


def abrir_dek(keyring: Keyring, dek_cifrada: DekCifrada) -> bytes:
    versao = dek_cifrada.kek_versao
    dek = _decifrar(keyring.kek(versao), dek_cifrada.dek_cripto, _aad_dek(versao))
    _validar_dek(dek)
    return dek


def rewrap(keyring: Keyring, dek_cifrada: DekCifrada) -> DekCifrada:
    """Recifra a DEK com a KEK ativa (rotação de KEK sem tocar nos dados)."""
    if dek_cifrada.kek_versao == keyring.ativa:
        return dek_cifrada
    dek = abrir_dek(keyring, dek_cifrada)
    versao = keyring.ativa
    return DekCifrada(
        dek_cripto=_cifrar(keyring.kek(versao), dek, _aad_dek(versao)), kek_versao=versao
    )


def _aad_campo(tabela: str, coluna: str, id_registro: bytes) -> bytes:
    return _aad(b"campo", tabela.encode(), coluna.encode(), id_registro)


def cifrar_campo(dek: bytes, valor: str, *, tabela: str, coluna: str, id_registro: bytes) -> bytes:
    _validar_dek(dek)
    return _cifrar(dek, valor.encode("utf-8"), _aad_campo(tabela, coluna, id_registro))


def decifrar_campo(dek: bytes, blob: bytes, *, tabela: str, coluna: str, id_registro: bytes) -> str:
    _validar_dek(dek)
    dados = _decifrar(dek, blob, _aad_campo(tabela, coluna, id_registro))
    return dados.decode("utf-8")


def normalizar(finalidade: FinalidadeHash, valor: str) -> str:
    match finalidade:
        case FinalidadeHash.CPF:
            normalizado = re.sub(r"\D", "", valor)
        case FinalidadeHash.EMAIL:
            normalizado = valor.strip().lower()
        case FinalidadeHash.CODIGO_RECUPERACAO:
            normalizado = re.sub(r"[\s-]", "", valor).upper()
        case _:  # pragma: no cover
            assert_never(finalidade)
    if not normalizado:
        raise ValueError("Valor vazio após normalização.")
    return normalizado


def hash_busca(chave_hmac: bytes, finalidade: FinalidadeHash, valor: str) -> bytes:
    """HMAC-SHA256 determinístico para busca/unicidade sem decifrar (32 bytes)."""
    if len(chave_hmac) != TAMANHO_CHAVE:
        raise ErroCriptografia("Chave HMAC inválida.")
    mensagem = _aad(b"hash", finalidade.value.encode(), normalizar(finalidade, valor).encode())
    return hmac.new(chave_hmac, mensagem, hashlib.sha256).digest()
