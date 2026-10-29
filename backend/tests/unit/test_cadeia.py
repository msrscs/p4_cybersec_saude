"""Serialização do hash encadeado e assinatura dos checkpoints (ADR-0010)."""

import dataclasses
import os
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from app.core.cadeia import (
    GENESIS,
    Ancora,
    RegistroCadeia,
    assinar_checkpoint,
    checkpoint_valido,
    hash_registro,
    microssegundos,
)

BASE = RegistroCadeia(
    seq_cadeia=1,
    id_log=1,
    data_hora=datetime(2026, 10, 29, 12, 0, 0, 123456, tzinfo=UTC),
    acao="login_success",
    resumo='{"etapa": "senha"}',
    ip_origem="203.0.113.7/32",
    request_id="6f1c2a8e-1f0b-4c55-9d1e-2b4b9b6b7c11",
    geolocalizacao=None,
    cpf_usuario_hash=bytes(range(32)),
    cpf_paciente_hash=None,
    id_oci=None,
    prev_hash=GENESIS,
    hash_assinatura_worm=b"",
)


def test_hash_deterministico_de_32_bytes() -> None:
    assert hash_registro(GENESIS, BASE) == hash_registro(GENESIS, BASE)
    assert len(hash_registro(GENESIS, BASE)) == 32


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("seq_cadeia", 2),
        ("id_log", 2),
        ("data_hora", BASE.data_hora + timedelta(microseconds=1)),
        ("acao", "login_failure"),
        ("resumo", '{"etapa": "mfa"}'),
        ("ip_origem", "203.0.113.8/32"),
        ("request_id", None),
        ("geolocalizacao", "Recife"),
        ("cpf_usuario_hash", None),
        ("cpf_paciente_hash", bytes(32)),
        ("id_oci", 1),
    ],
)
def test_qualquer_campo_altera_o_hash(campo: str, valor: Any) -> None:
    alterado = dataclasses.replace(BASE, **{campo: valor})
    assert hash_registro(GENESIS, alterado) != hash_registro(GENESIS, BASE)


def test_prev_hash_altera_o_hash() -> None:
    assert hash_registro(os.urandom(32), BASE) != hash_registro(GENESIS, BASE)


def test_nulo_diferente_de_vazio_e_sem_ambiguidade_entre_campos() -> None:
    nulo = dataclasses.replace(BASE, geolocalizacao=None)
    vazio = dataclasses.replace(BASE, geolocalizacao="")
    assert hash_registro(GENESIS, nulo) != hash_registro(GENESIS, vazio)
    # Mover texto de um campo para o vizinho muda o hash (prefixo de tamanho).
    a = dataclasses.replace(BASE, acao="ab", resumo="c")
    b = dataclasses.replace(BASE, acao="a", resumo="bc")
    assert hash_registro(GENESIS, a) != hash_registro(GENESIS, b)


def test_hash_nao_depende_do_fuso_do_datetime() -> None:
    recife = timezone(timedelta(hours=-3))
    local = dataclasses.replace(BASE, data_hora=BASE.data_hora.astimezone(recife))
    assert hash_registro(GENESIS, local) == hash_registro(GENESIS, BASE)


def test_microssegundos_exatos() -> None:
    assert microssegundos(datetime(1970, 1, 1, tzinfo=UTC)) == 0
    assert microssegundos(BASE.data_hora) == 1_793_275_200_123_456


def test_assinatura_do_checkpoint_depende_da_chave_seq_e_hash() -> None:
    chave, hash_cadeia = os.urandom(32), os.urandom(32)
    assinatura = assinar_checkpoint(chave, 10, hash_cadeia)
    assert checkpoint_valido(chave, 10, hash_cadeia, assinatura)
    assert not checkpoint_valido(os.urandom(32), 10, hash_cadeia, assinatura)
    assert not checkpoint_valido(chave, 11, hash_cadeia, assinatura)
    assert not checkpoint_valido(chave, 10, os.urandom(32), assinatura)


def test_ancora_ida_e_volta() -> None:
    ancora = Ancora(1234, os.urandom(32))
    assert Ancora.de_texto(str(ancora)) == ancora
    assert Ancora.de_texto(f"  {ancora}\n") == ancora


@pytest.mark.parametrize(
    "texto", ["", "1234", "abc:00", "0:" + "00" * 32, "-1:" + "00" * 32, "5:zz", "5:" + "00" * 31]
)
def test_ancora_invalida(texto: str) -> None:
    with pytest.raises(ValueError, match="seq:hash_hex"):
        Ancora.de_texto(texto)
