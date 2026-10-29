"""Inclui ou remove um usuário de um grupo RBAC (mudança de permissão, auditada).

A partir de backend/:

    uv run --env-file ../.env python -m scripts.atribuir_grupo --cpf 123.456.789-09 --grupo Gestor
    uv run --env-file ../.env python -m scripts.atribuir_grupo --cpf ... --grupo Navegador --remover

Grupos iniciais (ADR-0011): Administrador, Gestor, Gestor do Cuidado, Navegador, Auditor.
A mudança vale na próxima requisição do usuário (as permissões não ficam em cache).
"""

import argparse
import sys

from app.core.config import get_settings
from app.core.cpf import cpf_valido, normalizar_cpf
from app.core.database import criar_engine, criar_sessionmaker
from app.repositories import rbac as rbac_repo
from app.services import autorizacao
from app.services.auditoria import ContextoRequisicao
from app.services.autorizacao import GrupoNaoEncontrado
from app.services.usuario import UsuarioNaoEncontrado

CONFIRMACAO = "CONFIRMAR"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Inclui ou remove um usuário de um grupo.")
    parser.add_argument("--cpf", required=True)
    parser.add_argument("--grupo", required=True)
    parser.add_argument("--remover", action="store_true")
    args = parser.parse_args(argv)
    if not cpf_valido(args.cpf):
        sys.exit("CPF inválido.")
    operacao = "remover do" if args.remover else "incluir no"
    if input(f"Digite {CONFIRMACAO} para {operacao} grupo {args.grupo}: ").strip() != CONFIRMACAO:
        sys.exit("Cancelado.")

    settings = get_settings()
    engine = criar_engine(settings)
    fabrica = criar_sessionmaker(engine)
    try:
        with fabrica() as db, db.begin():
            mudou = autorizacao.alterar_grupo(
                db,
                settings,
                cpf=normalizar_cpf(args.cpf),
                grupo=args.grupo,
                remover=args.remover,
                ctx=ContextoRequisicao(),
            )
    except UsuarioNaoEncontrado:
        sys.exit("Usuário não encontrado.")
    except GrupoNaoEncontrado:
        with fabrica() as db:
            grupos = rbac_repo.nomes_dos_grupos(db)
        sys.exit(f"Grupo inexistente. Grupos: {', '.join(grupos)}.")
    finally:
        engine.dispose()
    if not mudou:
        print("Nada mudou (o usuário já estava nessa situação).")
    elif args.remover:
        print("Usuário removido do grupo.")
    else:
        print("Usuário incluído no grupo.")


if __name__ == "__main__":
    main()
