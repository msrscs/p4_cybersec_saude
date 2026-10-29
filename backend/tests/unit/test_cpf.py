import pytest

from app.core.cpf import cpf_valido, validar_cpf


@pytest.mark.parametrize(
    "cpf", ["529.982.247-25", "52998224725", "111.444.777-35", " 52998224725 "]
)
def test_cpfs_validos(cpf: str) -> None:
    assert cpf_valido(cpf)


@pytest.mark.parametrize(
    "cpf",
    [
        "529.982.247-24",  # 2º dígito errado
        "529.982.247-15",  # 1º dígito errado
        "111.111.111-11",  # repetido (passa no cálculo, mas é inválido)
        "000.000.000-00",
        "5299822472",  # 10 dígitos
        "529982247255",  # 12 dígitos
        "5299822472a",
        "".join(chr(0xFF10 + int(d)) for d in "52998224725"),  # dígitos de largura total
        "",
    ],
)
def test_cpfs_invalidos(cpf: str) -> None:
    assert not cpf_valido(cpf)


def test_validar_cpf_normaliza_e_erro_nao_ecoa_valor() -> None:
    assert validar_cpf("529.982.247-25") == "52998224725"
    with pytest.raises(ValueError) as exc:
        validar_cpf("529.982.247-24")
    assert "529" not in str(exc.value)
