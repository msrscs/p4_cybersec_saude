from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.auth import ResultadoLogin, duracao_bloqueio
from app.services.sessao import hash_token


@pytest.mark.parametrize(
    ("bloqueios", "minutos"),
    [(0, 15), (1, 15), (2, 30), (3, 60), (4, 120), (7, 960), (8, 1440), (500, 1440)],
)
def test_bloqueio_progressivo_ate_24h(bloqueios: int, minutos: int) -> None:
    assert duracao_bloqueio(bloqueios) == timedelta(minutes=minutos)


def test_hash_token_e_sha256() -> None:
    assert len(hash_token("abc")) == 32
    assert hash_token("abc") != hash_token("abd")


def test_resultado_nao_expoe_token() -> None:
    assert "segredo" not in repr(ResultadoLogin(sucesso=True, token="segredo"))


def test_erro_de_validacao_nao_ecoa_entrada() -> None:
    client = TestClient(create_app())
    resp = client.post("/auth/login", json={"cpf": "529.982.247-24", "senha": "MinhaSenha#123"})
    assert resp.status_code == 422
    assert resp.json() == {"detail": "Dados inválidos.", "campos": ["cpf"]}
    assert "MinhaSenha" not in resp.text
    assert "529" not in resp.text
    assert resp.headers["x-request-id"]
