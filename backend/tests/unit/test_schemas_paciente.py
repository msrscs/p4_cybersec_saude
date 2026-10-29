"""Validação de entrada de pacientes (RF-03): tudo validado no backend."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.core.cpf import formatar_cpf
from app.schemas.paciente import PacienteAlteracao, PacienteCadastro

BASE = {"cpf": "529.982.247-25", "nome": "  Ana Lima  ", "data_nascimento": "1990-02-28"}


def test_cadastro_normaliza_cpf_nome_e_email() -> None:
    p = PacienteCadastro.model_validate({**BASE, "email": " Ana@Recife.PE.gov.br "})
    assert p.cpf == "52998224725"
    assert p.nome == "Ana Lima"
    assert p.email == "ana@recife.pe.gov.br"


@pytest.mark.parametrize("data", ["1990-2-28", "28/02/1990", "1990-02-30", 635_990_400, None])
def test_data_so_no_formato_iso_valido(data: object) -> None:
    with pytest.raises(ValidationError):
        PacienteCadastro.model_validate({**BASE, "data_nascimento": data})


def test_data_futura_e_idade_implausivel_recusadas() -> None:
    hoje = datetime.now(UTC).date()
    PacienteCadastro.model_validate({**BASE, "data_nascimento": hoje.isoformat()})
    for data in (hoje + timedelta(days=1), hoje - timedelta(days=round(365.25 * 131))):
        with pytest.raises(ValidationError):
            PacienteCadastro.model_validate({**BASE, "data_nascimento": data.isoformat()})


def test_erros_nao_ecoam_a_entrada() -> None:
    with pytest.raises(ValidationError) as exc:
        PacienteCadastro.model_validate({**BASE, "nome": "Secreto\x07Nome"})
    assert "Secreto" not in str(exc.value)


def test_alteracao_registra_campos_enviados() -> None:
    assert PacienteAlteracao.model_validate({"email": None}).model_fields_set == {"email"}
    for corpo in ({}, {"nome": None}, {"data_nascimento": None}, {"cpf": BASE["cpf"]}):
        with pytest.raises(ValidationError):
            PacienteAlteracao.model_validate(corpo)


def test_formatar_cpf() -> None:
    assert formatar_cpf("52998224725") == "529.982.247-25"
