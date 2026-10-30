"""Rotinas periódicas (ADR-0013), para o container `tarefas` ou para cron.

A partir de backend/:

    uv run --env-file ../.env python -m scripts.tarefas limpar        # uma vez
    uv run --env-file ../.env python -m scripts.tarefas verificar-log # uma vez (com checkpoint)
    uv run --env-file ../.env python -m scripts.tarefas agendar       # laço contínuo

`agendar`: limpeza a cada 15 min e verificação da cadeia do log, com checkpoint assinado, a
cada hora. Cadeia quebrada fica registrada no log (log_chain_broken) e na saída de erro.
"""

import argparse
import sys
import time
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.database import criar_engine, criar_sessionmaker
from app.services import cadeia_log, manutencao
from app.services.auditoria import ContextoRequisicao
from scripts.verificar_log import verificar_snapshot

INTERVALO_LIMPEZA = 15 * 60
INTERVALO_VERIFICACAO = 60 * 60


def limpar(fabrica: sessionmaker[Session]) -> None:
    with fabrica() as db, db.begin():
        r = manutencao.limpar(db, datetime.now(UTC))
    print(f"Limpeza: {r.sessoes} sessões expiradas, {r.contadores} contadores vencidos.")


def verificar_log(fabrica: sessionmaker[Session], settings: Settings) -> bool:
    chave = settings.chave_checkpoint
    if chave is None:
        print("LOG_CHECKPOINT_KEY ausente: verificação do log não executada.", file=sys.stderr)
        return False
    resultado = verificar_snapshot(fabrica, chave, None)
    with fabrica() as db, db.begin():
        cadeia_log.registrar_resultado(db, resultado, ContextoRequisicao())
        cadeia_log.criar_checkpoint(db, chave, resultado, ContextoRequisicao())
    if not resultado.integra:
        print(
            f"CADEIA QUEBRADA: {resultado.motivo} na posição {resultado.seq_falha}.",
            file=sys.stderr,
        )
        return False
    ancora = resultado.ultimo
    print(f"Cadeia íntegra: {resultado.registros} registros. Âncora: {ancora}")
    return True


def agendar(fabrica: sessionmaker[Session], settings: Settings) -> None:  # pragma: no cover
    proxima_limpeza = proxima_verificacao = 0.0
    while True:
        agora = time.monotonic()
        try:
            if agora >= proxima_limpeza:
                limpar(fabrica)
                proxima_limpeza = agora + INTERVALO_LIMPEZA
            if agora >= proxima_verificacao:
                verificar_log(fabrica, settings)
                proxima_verificacao = agora + INTERVALO_VERIFICACAO
        except Exception as erro:
            print(f"Falha na rotina ({type(erro).__name__}); nova tentativa no próximo ciclo.")
        time.sleep(30)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Rotinas periódicas do CyberSec Saúde.")
    parser.add_argument("rotina", choices=["limpar", "verificar-log", "agendar"])
    args = parser.parse_args(argv)
    settings = get_settings()
    engine = criar_engine(settings)
    fabrica = criar_sessionmaker(engine)
    try:
        if args.rotina == "limpar":
            limpar(fabrica)
        elif args.rotina == "verificar-log":
            if not verificar_log(fabrica, settings):
                sys.exit(1)
        else:
            agendar(fabrica, settings)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
