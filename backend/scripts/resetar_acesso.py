"""Reset administrativo de acesso (usuário esqueceu a senha ou perdeu o MFA e os códigos).

A partir de backend/:

    uv run --env-file ../.env python -m scripts.resetar_acesso --cpf 123.456.789-09

Efeitos: senha temporária gerada (mostrada UMA vez), MFA zerado, códigos de recuperação e
sessões revogados. No próximo login o usuário recadastra o MFA e é obrigado a trocar a senha.
Entregue a senha temporária ao usuário por um canal seguro, nunca por e-mail ou chat aberto.
"""

import argparse
import sys
from datetime import UTC, datetime

from app.core.config import get_settings
from app.core.cpf import cpf_valido, normalizar_cpf
from app.core.database import criar_engine, criar_sessionmaker
from app.services import usuario as usuario_service
from app.services.auditoria import ContextoRequisicao

CONFIRMACAO = "RESETAR"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Reseta senha e MFA de um usuário.")
    parser.add_argument("--cpf", required=True)
    args = parser.parse_args(argv)
    if not cpf_valido(args.cpf):
        sys.exit("CPF inválido.")
    if input(f"Digite {CONFIRMACAO} para confirmar: ").strip() != CONFIRMACAO:
        sys.exit("Cancelado.")

    settings = get_settings()
    fabrica = criar_sessionmaker(criar_engine(settings))
    try:
        with fabrica() as db, db.begin():
            temporaria = usuario_service.resetar_acesso(
                db, settings, normalizar_cpf(args.cpf), ContextoRequisicao(), datetime.now(UTC)
            )
    except usuario_service.UsuarioNaoEncontrado:
        sys.exit("Usuário não encontrado.")
    print("Acesso resetado. Senha temporária (exibida só agora):")
    print(f"  {temporaria}")
    print("No próximo login o usuário cadastra o MFA de novo e troca a senha.")


if __name__ == "__main__":
    main()
