"""Cadastra um usuário pelo terminal (enquanto o CRUD HTTP depende de sessão + RBAC).

A partir de backend/ (banco com migrations aplicadas):

    uv run --env-file ../.env python -m scripts.criar_usuario --cpf 123.456.789-09 \\
        --nome "Fulana de Tal" --email fulana@recife.pe.gov.br [--unidade 1]

A senha é pedida com getpass: não aparece na tela nem no histórico do shell.
"""

import argparse
import getpass
import sys

from pydantic import ValidationError

from app.core.config import get_settings
from app.core.database import criar_engine, criar_sessionmaker
from app.schemas.usuario import UsuarioCadastro
from app.services import usuario as usuario_service
from app.services.auditoria import ContextoRequisicao


def _ler_senha() -> str:
    senha = getpass.getpass("Senha: ")
    if senha != getpass.getpass("Confirme a senha: "):
        sys.exit("As senhas não conferem.")
    return senha


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Cadastra um usuário do CyberSec Saúde.")
    parser.add_argument("--cpf", required=True)
    parser.add_argument("--nome", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--unidade", type=int)
    args = parser.parse_args(argv)

    try:
        dados = UsuarioCadastro(
            cpf=args.cpf,
            nome=args.nome,
            email=args.email,
            senha=_ler_senha(),
            id_unidade=args.unidade,
        )
    except ValidationError as exc:
        for erro in exc.errors():
            campo = ".".join(str(p) for p in erro["loc"]) or "dados"
            print(f"- {campo}: {erro['msg']}", file=sys.stderr)
        sys.exit(1)

    settings = get_settings()
    fabrica = criar_sessionmaker(criar_engine(settings))
    novo = usuario_service.NovoUsuario(
        cpf=dados.cpf,
        nome=dados.nome,
        email=str(dados.email),
        senha=dados.senha,
        id_unidade=dados.id_unidade,
    )
    try:
        with fabrica() as db, db.begin():
            usuario_service.cadastrar(db, settings, novo, ContextoRequisicao())
    except usuario_service.ErroCadastro as exc:
        sys.exit(str(exc))
    print("Usuário cadastrado.")


if __name__ == "__main__":
    main()
