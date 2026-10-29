"""ADR-0004 / THREAT_MODEL I1, T3: criptografia de campo com envelope."""

import base64
import os
from typing import TypedDict

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core import crypto
from app.core.crypto import (
    DekCifrada,
    ErroCriptografia,
    FinalidadeHash,
    Keyring,
    abrir_dek,
    carregar_keyring,
    cifrar_campo,
    decifrar_campo,
    gerar_dek,
    hash_busca,
    rewrap,
)


class Ctx(TypedDict):
    tabela: str
    coluna: str
    id_registro: bytes


CTX: Ctx = {"tabela": "usuario", "coluna": "cpf_cripto", "id_registro": b"\x01" * 32}


def _keyring(*versoes: int, ativa: int | None = None) -> Keyring:
    chaves = {v: os.urandom(32) for v in versoes or (1,)}
    return Keyring(chaves=chaves, ativa=ativa or max(chaves))


# --- Uso correto da primitiva -----------------------------------------------------------


def test_vetor_nist_aes256_gcm() -> None:
    # McGrew & Viega, "The GCM Mode of Operation", Test Case 14 (AES-256, chave/IV/P zerados).
    resultado = AESGCM(bytes(32)).encrypt(bytes(12), bytes(16), None)
    assert resultado.hex() == "cea7403d4d606b6e074ec5d3baf39d18d0d1c8a799996bf0265b98b5d48ab919"


# --- Campos -------------------------------------------------------------------------------


@pytest.mark.parametrize("valor", ["123.456.789-09", "José da Conceição Ñandú 😷", ""])
def test_cifra_e_decifra_campo(valor: str) -> None:
    dek, _ = gerar_dek(_keyring())
    blob = cifrar_campo(dek, valor, **CTX)
    assert valor.encode() not in blob or valor == ""
    assert decifrar_campo(dek, blob, **CTX) == valor


def test_formato_versao_nonce_tag() -> None:
    dek, _ = gerar_dek(_keyring())
    blob = cifrar_campo(dek, "abc", **CTX)
    assert blob[:1] == b"\x01"
    assert len(blob) == 1 + 12 + 3 + 16


def test_nonce_unico_por_cifragem() -> None:
    dek, _ = gerar_dek(_keyring())
    blobs = {cifrar_campo(dek, "mesmo valor", **CTX) for _ in range(200)}
    assert len(blobs) == 200
    assert len({b[1:13] for b in blobs}) == 200


@pytest.mark.parametrize("posicao", [0, 1, 13, -1])
def test_adulteracao_e_detectada(posicao: int) -> None:
    dek, _ = gerar_dek(_keyring())
    blob = bytearray(cifrar_campo(dek, "dado sensível", **CTX))
    blob[posicao] ^= 0x01
    with pytest.raises(ErroCriptografia):
        decifrar_campo(dek, bytes(blob), **CTX)


@pytest.mark.parametrize(
    "outro_ctx",
    [
        Ctx(tabela="usuario", coluna="cpf_cripto", id_registro=b"\x02" * 32),
        Ctx(tabela="usuario", coluna="nome_cripto", id_registro=b"\x01" * 32),
        Ctx(tabela="paciente", coluna="cpf_cripto", id_registro=b"\x01" * 32),
    ],
)
def test_valor_movido_para_outro_contexto_falha(outro_ctx: Ctx) -> None:
    dek, _ = gerar_dek(_keyring())
    blob = cifrar_campo(dek, "123.456.789-09", **CTX)
    with pytest.raises(ErroCriptografia):
        decifrar_campo(dek, blob, **outro_ctx)


def test_aad_sem_ambiguidade_entre_partes() -> None:
    dek, _ = gerar_dek(_keyring())
    blob = cifrar_campo(dek, "x", tabela="ab", coluna="c", id_registro=b"")
    with pytest.raises(ErroCriptografia):
        decifrar_campo(dek, blob, tabela="a", coluna="bc", id_registro=b"")


def test_dek_errada_falha() -> None:
    keyring = _keyring()
    dek, _ = gerar_dek(keyring)
    outra, _ = gerar_dek(keyring)
    with pytest.raises(ErroCriptografia):
        decifrar_campo(outra, cifrar_campo(dek, "x", **CTX), **CTX)


@pytest.mark.parametrize("blob", [b"", b"\x01" + bytes(27), b"\x02" + bytes(40)])
def test_blob_malformado_falha(blob: bytes) -> None:
    dek, _ = gerar_dek(_keyring())
    with pytest.raises(ErroCriptografia):
        decifrar_campo(dek, blob, **CTX)


def test_dek_com_tamanho_errado_e_recusada() -> None:
    with pytest.raises(ErroCriptografia):
        cifrar_campo(b"curta", "x", **CTX)


def test_erro_nao_revela_conteudo() -> None:
    dek, _ = gerar_dek(_keyring())
    blob = cifrar_campo(dek, "segredo-123", **CTX)
    with pytest.raises(ErroCriptografia) as exc:
        decifrar_campo(dek, blob[:-1] + b"\x00", **CTX)
    assert str(exc.value) == "Falha ao decifrar dado."
    assert exc.value.__cause__ is None


# --- Envelope / DEK -----------------------------------------------------------------------


def test_dek_cifrada_pela_kek_ativa() -> None:
    keyring = _keyring(1, 2, ativa=2)
    dek, cifrada = gerar_dek(keyring)
    assert cifrada.kek_versao == 2
    assert dek not in cifrada.dek_cripto
    assert abrir_dek(keyring, cifrada) == dek
    assert "dek_cripto" not in repr(cifrada)


def test_kek_errada_falha() -> None:
    _, cifrada = gerar_dek(_keyring())
    with pytest.raises(ErroCriptografia):
        abrir_dek(_keyring(), cifrada)


def test_versao_de_kek_desconhecida_falha() -> None:
    _, cifrada = gerar_dek(_keyring(1))
    with pytest.raises(ErroCriptografia, match="desconhecida"):
        abrir_dek(_keyring(1), DekCifrada(cifrada.dek_cripto, kek_versao=9))


def test_dek_nao_pode_ser_reetiquetada_com_outra_versao() -> None:
    # Mesmo bytes de KEK em duas versões: a AAD da DEK amarra a versão.
    chave = os.urandom(32)
    keyring = Keyring(chaves={1: chave, 2: chave}, ativa=1)
    _, cifrada = gerar_dek(keyring)
    with pytest.raises(ErroCriptografia):
        abrir_dek(keyring, DekCifrada(cifrada.dek_cripto, kek_versao=2))


def test_rotacao_de_kek_mantem_dados_legiveis() -> None:
    antigo = _keyring(1)
    dek, cifrada_v1 = gerar_dek(antigo)
    blob = cifrar_campo(dek, "nome do usuário", **CTX)

    novo = Keyring(chaves={**antigo.chaves, 2: os.urandom(32)}, ativa=2)
    cifrada_v2 = rewrap(novo, cifrada_v1)

    assert cifrada_v2.kek_versao == 2
    assert cifrada_v2.dek_cripto != cifrada_v1.dek_cripto
    assert decifrar_campo(abrir_dek(novo, cifrada_v2), blob, **CTX) == "nome do usuário"
    so_v2 = Keyring(chaves={2: novo.chaves[2]}, ativa=2)
    assert abrir_dek(so_v2, cifrada_v2) == dek


def test_rewrap_na_versao_ativa_nao_muda_nada() -> None:
    keyring = _keyring()
    _, cifrada = gerar_dek(keyring)
    assert rewrap(keyring, cifrada) is cifrada


def test_dek_decifrada_com_tamanho_errado_e_recusada() -> None:
    keyring = _keyring()
    falsa = crypto._cifrar(keyring.kek(1), b"curta", crypto._aad_dek(1))
    with pytest.raises(ErroCriptografia, match="DEK"):
        abrir_dek(keyring, DekCifrada(falsa, 1))


# --- Keyring ------------------------------------------------------------------------------


def _b64(n: int = 32) -> str:
    return base64.b64encode(os.urandom(n)).decode()


def test_carregar_keyring_com_varias_versoes() -> None:
    keyring = carregar_keyring(f"1:{_b64()}, 2:{_b64()}", ativa=2)
    assert sorted(keyring.chaves) == [1, 2]
    assert keyring.ativa == 2


@pytest.mark.parametrize(
    ("texto", "ativa", "mensagem"),
    [
        ("", 1, "vazio"),
        (f"x:{_b64()}", 1, "Formato"),
        (_b64(), 1, "Formato"),
        (f"1:{_b64(16)}", 1, "32 bytes"),
        ("1:não-é-base64!", 1, "base64"),
        (f"1:{_b64()},1:{_b64()}", 1, "repetida"),
        (f"1:{_b64()}", 2, "ativa"),
        (f"0:{_b64()}", 0, "positiva"),
    ],
)
def test_keyring_invalido(texto: str, ativa: int, mensagem: str) -> None:
    with pytest.raises(ValueError, match=mensagem):
        carregar_keyring(texto, ativa)


def test_keyring_com_chave_de_tamanho_errado() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        Keyring(chaves={1: b"curta"}, ativa=1)


# --- Hash de busca ------------------------------------------------------------------------


def test_hash_busca_deterministico_e_normalizado() -> None:
    chave = os.urandom(32)
    a = hash_busca(chave, FinalidadeHash.CPF, "123.456.789-09")
    assert a == hash_busca(chave, FinalidadeHash.CPF, "12345678909")
    assert len(a) == 32
    e = hash_busca(chave, FinalidadeHash.EMAIL, "  Fulano@Recife.PE.gov.br ")
    assert e == hash_busca(chave, FinalidadeHash.EMAIL, "fulano@recife.pe.gov.br")


def test_hash_busca_separa_finalidade_e_chave() -> None:
    chave = os.urandom(32)
    assert hash_busca(chave, FinalidadeHash.CPF, "12345678909") != hash_busca(
        chave, FinalidadeHash.EMAIL, "12345678909"
    )
    assert hash_busca(chave, FinalidadeHash.CPF, "12345678909") != hash_busca(
        os.urandom(32), FinalidadeHash.CPF, "12345678909"
    )


def test_hash_busca_recusa_valor_vazio_e_chave_invalida() -> None:
    with pytest.raises(ValueError):
        hash_busca(os.urandom(32), FinalidadeHash.CPF, "...-")
    with pytest.raises(ErroCriptografia):
        hash_busca(b"curta", FinalidadeHash.CPF, "12345678909")
