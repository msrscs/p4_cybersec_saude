"""Importa o catálogo de CID de um CSV (colunas cid,descricao). Ver ADR-0020.

A partir de backend/ (por padrão, lê db/seeds/cid10.csv):

    uv run --env-file ../.env python -m scripts.importar_cid [--arquivo caminho.csv]

Pode rodar de novo sem risco: código já cadastrado é ignorado e não tem a descrição sobrescrita,
para não desfazer correções feitas na tela. Qualquer linha inválida cancela a importação inteira,
antes de gravar. É um script, não uma migration, porque o cid_hash usa a HMAC_KEY.
"""

import argparse
import csv
import sys
from pathlib import Path

from pydantic import ValidationError

from app.core.config import get_settings
from app.core.database import criar_engine, criar_sessionmaker
from app.schemas.cadastro import CidNovo
from app.services import cadastro
from app.services.auditoria import ContextoRequisicao

ARQUIVO_PADRAO = Path(__file__).resolve().parents[2] / "db" / "seeds" / "cid10.csv"


def ler_arquivo(arquivo: Path) -> list[tuple[str, str]]:
    """Valida cada linha como o cadastro da tela. Sai com erro, citando a linha, se houver falha."""
    with arquivo.open(encoding="utf-8", newline="") as entrada:
        leitor = csv.DictReader(entrada)
        if leitor.fieldnames != ["cid", "descricao"]:
            sys.exit("O arquivo deve ter o cabeçalho: cid,descricao.")
        pares: list[tuple[str, str]] = []
        vistos: set[str] = set()
        for linha in leitor:
            numero = leitor.line_num
            try:
                dados = CidNovo(cid=linha["cid"], descricao=linha["descricao"])
            except ValidationError:
                sys.exit(f"Linha {numero} inválida. Nada foi importado.")
            if dados.cid in vistos:
                sys.exit(f"Linha {numero}: código repetido ({dados.cid}). Nada foi importado.")
            vistos.add(dados.cid)
            pares.append((dados.cid, dados.descricao))
    return pares


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Importa o catálogo de CID de um CSV.")
    parser.add_argument("--arquivo", type=Path, default=ARQUIVO_PADRAO)
    args = parser.parse_args(argv)
    if not args.arquivo.is_file():
        sys.exit("Arquivo não encontrado.")
    pares = ler_arquivo(args.arquivo)

    settings = get_settings()
    engine = criar_engine(settings)
    try:
        with criar_sessionmaker(engine)() as db, db.begin():
            resultado = cadastro.importar_cids(db, settings, pares, ContextoRequisicao())
    finally:
        engine.dispose()
    print(f"CID: {resultado.criados} importados, {resultado.ignorados} já existiam.")


if __name__ == "__main__":
    main()
