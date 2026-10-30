"""Verifica a cadeia de hashes do log de auditoria e, opcionalmente, grava um checkpoint.

A partir de backend/:

    uv run --env-file ../.env python -m scripts.verificar_log
    uv run --env-file ../.env python -m scripts.verificar_log --checkpoint
    uv run --env-file ../.env python -m scripts.verificar_log --ancora 1234:9f86d0...

Exige LOG_CHECKPOINT_KEY (scripts.gerar_chaves). Sai com código 1 se a cadeia estiver
quebrada, para uso em cron/CI. A âncora impressa deve ser guardada fora do sistema (ex.: no
relatório da auditoria): é ela que revela a remoção do fim do log por quem controla o banco.
"""

import argparse
import sys

from sqlalchemy.orm import Session, sessionmaker

from app.core.cadeia import Ancora
from app.core.config import get_settings
from app.core.database import criar_engine, criar_sessionmaker
from app.services import cadeia_log
from app.services.auditoria import ContextoRequisicao
from app.services.cadeia_log import ResultadoVerificacao


def verificar_snapshot(
    fabrica: sessionmaker[Session], chave: bytes, ancora: Ancora | None
) -> ResultadoVerificacao:
    # Retrato consistente do log inteiro, sem escrever nada nesta transação.
    with fabrica() as db:
        db.connection(
            execution_options={"isolation_level": "REPEATABLE READ", "postgresql_readonly": True}
        )
        resultado = cadeia_log.verificar_cadeia(db, chave, ancora)
        db.rollback()
    return resultado


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Verifica a cadeia de hashes do log.")
    parser.add_argument("--checkpoint", action="store_true", help="grava checkpoint assinado")
    parser.add_argument("--ancora", help="último ponto conhecido, no formato seq:hash_hex")
    args = parser.parse_args(argv)
    try:
        ancora = Ancora.de_texto(args.ancora) if args.ancora else None
    except ValueError as erro:
        sys.exit(str(erro))

    settings = get_settings()
    chave = settings.chave_checkpoint
    if chave is None:
        sys.exit("Defina LOG_CHECKPOINT_KEY (cd backend && uv run python -m scripts.gerar_chaves).")

    engine = criar_engine(settings)
    fabrica = criar_sessionmaker(engine)
    try:
        resultado = verificar_snapshot(fabrica, chave, ancora)
        with fabrica() as db, db.begin():
            cadeia_log.registrar_resultado(db, resultado, ContextoRequisicao())
            novo = (
                cadeia_log.criar_checkpoint(db, chave, resultado, ContextoRequisicao())
                if args.checkpoint
                else None
            )
    finally:
        engine.dispose()

    if not resultado.integra:
        sys.exit(
            f"CADEIA QUEBRADA: {resultado.motivo} na posição {resultado.seq_falha} "
            f"({resultado.registros} registros íntegros antes dela)."
        )
    print(f"Cadeia íntegra: {resultado.registros} registros, {resultado.checkpoints} checkpoints.")
    if resultado.ultimo is not None:
        print(f"Âncora (guarde fora do sistema): {resultado.ultimo}")
    if novo is not None:
        print(f"Checkpoint assinado gravado na posição {novo.seq_cadeia}.")


if __name__ == "__main__":
    main()
