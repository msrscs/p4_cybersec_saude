import pytest

from app.core import senha

VALIDA = "Saúde#Recife2026"


def test_senha_valida_passa() -> None:
    assert senha.problemas_politica(VALIDA) == []


@pytest.mark.parametrize(
    ("candidata", "falta"),
    [
        ("Curta#1a", "entre 12 e 64"),
        ("semmaiuscula#2026", "maiúscula"),
        ("SEMMINUSCULA#2026", "minúscula"),
        ("SemNumero#Recife", "número"),
        ("SemEspecial2026Recife", "especial"),
        ("A" * 40 + "a1#" + "ç" * 20, "72 bytes"),
        ("x" * 65 + "A1#", "entre 12 e 64"),
    ],
)
def test_cada_regra_da_politica(candidata: str, falta: str) -> None:
    problemas = "; ".join(senha.problemas_politica(candidata))
    assert falta in problemas


def test_letras_acentuadas_contam_como_maiuscula_e_minuscula() -> None:
    assert senha.problemas_politica("ÇÃOÉÍÓ#12345ção") == []


def test_espaco_nao_conta_como_especial() -> None:
    assert "especial" in "; ".join(senha.problemas_politica("Senha Forte 2026"))


def test_senha_nao_pode_conter_cpf() -> None:
    problemas = senha.problemas_politica("Ab#529.982.247-25x", cpf="52998224725")
    assert "não conter o CPF" in problemas


def test_validar_politica_nao_ecoa_senha() -> None:
    with pytest.raises(ValueError) as exc:
        senha.validar_politica("fraca-demais")
    assert "fraca-demais" not in str(exc.value)


def test_hash_e_verificacao() -> None:
    h = senha.gerar_hash(VALIDA, rounds=4)
    assert h.startswith("$2b$04$")
    assert VALIDA not in h
    assert senha.verificar(VALIDA, h)
    assert not senha.verificar(VALIDA + "x", h)


def test_salt_unico_por_hash() -> None:
    assert senha.gerar_hash(VALIDA, 4) != senha.gerar_hash(VALIDA, 4)


def test_acima_de_72_bytes_e_recusada_e_nao_verifica() -> None:
    longa = "ç" * 37  # 74 bytes
    with pytest.raises(ValueError, match="72 bytes"):
        senha.gerar_hash(longa, 4)
    assert not senha.verificar(longa, senha.gerar_hash("x", 4))


def test_hash_corrompido_nao_verifica() -> None:
    assert not senha.verificar(VALIDA, "isto-nao-e-bcrypt")


def test_verificacao_ficticia_executa_bcrypt() -> None:
    senha.verificar_ficticio(VALIDA, 4)  # não levanta; usa hash em cache


@pytest.mark.parametrize(
    ("hash_armazenado", "rounds", "esperado"),
    [
        ("$2b$10$abc", 12, True),
        ("$2b$12$abc", 12, False),
        ("$2b$13$abc", 12, False),
        ("lixo", 12, True),
    ],
)
def test_precisa_rehash(hash_armazenado: str, rounds: int, esperado: bool) -> None:
    assert senha.precisa_rehash(hash_armazenado, rounds) is esperado
