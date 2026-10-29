import pytest
from pydantic import ValidationError

from app.schemas.auth import LoginEntrada
from app.schemas.usuario import UsuarioCadastro

BASE = {
    "cpf": "529.982.247-25",
    "nome": "  Maria da Conceição  ",
    "email": "Maria@Recife.PE.gov.br",
    "senha": "Saúde#Recife2026",
}


def test_cadastro_valido_normaliza() -> None:
    dados = UsuarioCadastro(**BASE)
    assert dados.cpf == "52998224725"
    assert dados.nome == "Maria da Conceição"
    assert "Saúde#Recife2026" not in repr(dados)


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("cpf", "529.982.247-24"),
        ("nome", "M"),
        ("nome", "Maria\x00Drop"),
        ("nome", "Maria‮evil"),
        ("email", "não-é-email"),
        ("senha", "fraca"),
        ("senha", "Ab#5299822472525x"),  # contém o CPF
        ("id_unidade", 0),
    ],
)
def test_cadastro_invalido(campo: str, valor: object) -> None:
    with pytest.raises(ValidationError) as exc:
        UsuarioCadastro(**{**BASE, campo: valor})
    assert str(valor) not in str(exc.value) or campo == "id_unidade"


def test_cadastro_recusa_campos_extras() -> None:
    with pytest.raises(ValidationError):
        UsuarioCadastro.model_validate({**BASE, "status": "ativo"})


def test_login_limita_bytes_e_nao_ecoa_senha() -> None:
    with pytest.raises(ValidationError) as exc:
        LoginEntrada(cpf="529.982.247-25", senha="ç" * 37)
    assert "ç" * 10 not in str(exc.value)
    assert LoginEntrada(cpf="52998224725", senha="qualquer").cpf == "52998224725"
