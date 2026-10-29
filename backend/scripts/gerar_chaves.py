"""Gera as chaves de criptografia e grava no .env sem exibi-las.

A partir de backend/:

    uv run python -m scripts.gerar_chaves               # cria as chaves que faltarem
    uv run python -m scripts.gerar_chaves --rotacionar  # adiciona nova KEK e a torna ativa

A HMAC_KEY nunca é trocada por este script: trocá-la exige recalcular todos os hashes de busca.
A LOG_CHECKPOINT_KEY também não: trocá-la invalida os checkpoints já gravados (ADR-0010).
"""

import argparse
import os
import re
from pathlib import Path

from app.core.crypto import gerar_chave_b64

_ENV_PADRAO = Path(__file__).resolve().parents[2] / ".env"


def _ler(linhas: list[str], nome: str) -> str | None:
    for linha in linhas:
        if linha.startswith(f"{nome}="):
            return linha.split("=", 1)[1]
    return None


def _definir(linhas: list[str], nome: str, valor: str) -> list[str]:
    novas = [linha for linha in linhas if not linha.startswith(f"{nome}=")]
    return [*novas, f"{nome}={valor}"]


def atualizar_env(caminho: Path, *, rotacionar: bool) -> list[str]:
    """Aplica as mudanças e devolve os nomes das variáveis alteradas."""
    linhas = caminho.read_text().splitlines() if caminho.exists() else []
    alteradas: list[str] = []

    keyring = _ler(linhas, "KEK_KEYRING")
    if not keyring:
        linhas = _definir(linhas, "KEK_KEYRING", f"1:{gerar_chave_b64()}")
        linhas = _definir(linhas, "KEK_ATIVA", "1")
        alteradas += ["KEK_KEYRING", "KEK_ATIVA"]
    elif rotacionar:
        versoes = [int(v) for v in re.findall(r"(?:^|,)\s*(\d+):", keyring)]
        nova = max(versoes, default=0) + 1
        linhas = _definir(linhas, "KEK_KEYRING", f"{keyring},{nova}:{gerar_chave_b64()}")
        linhas = _definir(linhas, "KEK_ATIVA", str(nova))
        alteradas += ["KEK_KEYRING", "KEK_ATIVA"]

    if not _ler(linhas, "HMAC_KEY"):
        linhas = _definir(linhas, "HMAC_KEY", gerar_chave_b64())
        alteradas.append("HMAC_KEY")

    if not _ler(linhas, "LOG_CHECKPOINT_KEY"):
        linhas = _definir(linhas, "LOG_CHECKPOINT_KEY", gerar_chave_b64())
        alteradas.append("LOG_CHECKPOINT_KEY")

    if alteradas:
        caminho.write_text("\n".join(linhas) + "\n")
        os.chmod(caminho, 0o600)
    return alteradas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--env", type=Path, default=_ENV_PADRAO)
    parser.add_argument("--rotacionar", action="store_true")
    args = parser.parse_args()
    alteradas = atualizar_env(args.env, rotacionar=args.rotacionar)
    print(f"Atualizadas: {', '.join(alteradas)}" if alteradas else "Nada a fazer.")


if __name__ == "__main__":
    main()
