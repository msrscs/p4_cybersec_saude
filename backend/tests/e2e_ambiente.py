"""Ambiente isolado para o teste ponta a ponta do frontend (Playwright), derrubado no fim.

A partir de backend/:

    uv run --env-file ../.env python -m tests.e2e_ambiente

Cria um banco temporário (como os testes de integração), cadastra um administrador de teste
com CPF e senha aleatórios, sobe a API (porta 8001) e o frontend (porta 3001) em HTTP local, como
ficam atrás da borda na AWS (ADR-0029), roda `npx playwright test` e remove tudo. A senha de teste
só circula por variável de ambiente dos processos filhos; nada é gravado em disco nem impresso.
"""

import os
import subprocess  # nosec B404 - só executa comandos fixos do próprio projeto
import sys
import time
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.core.config import Settings
from app.core.database import criar_engine, criar_sessionmaker
from app.services import autorizacao
from app.services import usuario as usuario_service
from app.services.auditoria import ContextoRequisicao
from app.services.usuario import NovoUsuario, gerar_senha_temporaria
from tests.integration.conftest import banco_temporario, gerar_cpf

RAIZ = Path(__file__).resolve().parents[2]
PORTA_API = 8001
PORTA_FRONT = 3001


def _semear(settings: Settings) -> tuple[str, str]:
    cpf, senha = gerar_cpf(), gerar_senha_temporaria()
    engine = criar_engine(settings)
    try:
        with criar_sessionmaker(engine)() as db, db.begin():
            dados = NovoUsuario(cpf=cpf, nome="Admin E2E", email="e2e@teste.invalid", senha=senha)
            usuario_service.cadastrar(db, settings, dados, ContextoRequisicao())
            autorizacao.alterar_grupo(
                db,
                settings,
                cpf=cpf,
                grupo="Administrador",
                remover=False,
                ctx=ContextoRequisicao(),
            )
    finally:
        engine.dispose()
    return cpf, senha


def _esperar(url: str, prazo: float = 30.0) -> None:
    limite = time.monotonic() + prazo
    while time.monotonic() < limite:
        try:
            with urllib.request.urlopen(url, timeout=2):  # noqa: S310  # nosec B310 - URL local fixa
                return
        except OSError:
            time.sleep(0.3)
    raise SystemExit(f"Serviço não respondeu: {url}")


@contextmanager
def _processo(comando: list[str], cwd: Path, env: dict[str, str]) -> Iterator[None]:
    proc = subprocess.Popen(comando, cwd=cwd, env=env)  # noqa: S603  # nosec B603 - comando fixo
    try:
        yield
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    with banco_temporario("head") as banco:
        os.environ.update(
            {
                "ENVIRONMENT": "test",
                "POSTGRES_DB": banco.name,
                "DB_HOST": banco.host,
                "DB_PORT": str(banco.port),
                "BCRYPT_ROUNDS": "4",
            }
        )
        cpf, senha = _semear(Settings())
        env_api = dict(os.environ)
        env_front = {
            "PATH": os.environ["PATH"],
            "HOME": os.environ.get("HOME", ""),
            "PORT": str(PORTA_FRONT),
            "API_URL": f"http://127.0.0.1:{PORTA_API}",
        }
        uvicorn = [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(PORTA_API),
            "--no-access-log",
        ]
        with (
            _processo(uvicorn, RAIZ / "backend", env_api),
            _processo(["node", "src/server.js"], RAIZ / "frontend", env_front),
        ):
            _esperar(f"http://127.0.0.1:{PORTA_API}/health")
            _esperar(f"http://127.0.0.1:{PORTA_FRONT}/health")
            env_testes = {
                **env_front,
                # localhost (não 127.0.0.1) para o Chromium tratar a página como contexto seguro.
                "E2E_BASE_URL": f"http://localhost:{PORTA_FRONT}",
                "E2E_CPF": cpf,
                "E2E_SENHA": senha,
            }
            if os.environ.get("CI"):
                env_testes["CI"] = os.environ["CI"]
            resultado = subprocess.run(  # nosec B603 B607 - comando fixo
                ["npx", "playwright", "test"],  # noqa: S607
                cwd=RAIZ / "frontend",
                env=env_testes,
                check=False,
            )
    return resultado.returncode


if __name__ == "__main__":
    sys.exit(main())
