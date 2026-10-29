from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.main import create_app


def test_health_retorna_ok() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_erro_interno_e_generico_sem_detalhes() -> None:
    app = create_app()
    router = APIRouter()

    @router.get("/boom")
    def boom() -> None:
        raise RuntimeError("segredo-que-nao-pode-vazar")

    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/boom")
    assert response.status_code == 500
    assert response.json() == {"detail": "Erro interno."}
    assert "segredo" not in response.text
