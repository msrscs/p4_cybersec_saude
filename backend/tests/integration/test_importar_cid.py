"""ADR-0020: importação do catálogo de CID por script."""

import itertools
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.crypto import FinalidadeHash, hash_busca
from app.models import Cid, Log
from scripts import importar_cid

Fabrica = sessionmaker[Session]


_PROXIMO = itertools.count()


def _codigo() -> str:
    # Sequencial, não aleatório: dois testes nunca geram o mesmo código na mesma rodada.
    return f"T{next(_PROXIMO):02d}.AA"


def _csv(pasta: Path, linhas: list[str], cabecalho: str = "cid,descricao") -> Path:
    arquivo = pasta / "cid.csv"
    arquivo.write_text("\n".join([cabecalho, *linhas]) + "\n", encoding="utf-8")
    return arquivo


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch, settings_integracao: Settings) -> None:
    monkeypatch.setattr(importar_cid, "get_settings", lambda: settings_integracao)


def test_importa_com_hash_correto_e_audita_uma_vez(
    tmp_path: Path,
    fabrica_sessao: Fabrica,
    settings_integracao: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    a, b = _codigo(), _codigo()
    importar_cid.main(
        ["--arquivo", str(_csv(tmp_path, [f"{a},Descrição A", f'{b},"Com, vírgula"']))]
    )
    assert "2 importados, 0 já existiam" in capsys.readouterr().out
    with fabrica_sessao() as db:
        registro = db.scalars(select(Cid).where(Cid.cid == b)).one()
        evento = db.scalars(
            select(Log).where(Log.acao == "catalog_imported").order_by(Log.seq_cadeia.desc())
        ).first()
    assert registro.descricao == "Com, vírgula" and registro.status == "ativo"
    assert registro.cid_hash == hash_busca(settings_integracao.chave_hmac, FinalidadeHash.CID, b)
    assert evento is not None
    assert evento.resumo_acessado == {"recurso": "cid", "criados": 2, "ignorados": 0}


def test_rodar_de_novo_nao_duplica_nem_sobrescreve_correcao(
    tmp_path: Path, fabrica_sessao: Fabrica, capsys: pytest.CaptureFixture[str]
) -> None:
    codigo = _codigo()
    arquivo = _csv(tmp_path, [f"{codigo},Original"])
    importar_cid.main(["--arquivo", str(arquivo)])
    with fabrica_sessao() as db, db.begin():
        db.scalars(select(Cid).where(Cid.cid == codigo)).one().descricao = "Corrigida na tela"
    capsys.readouterr()

    importar_cid.main(["--arquivo", str(arquivo)])
    assert "0 importados, 1 já existiam" in capsys.readouterr().out
    with fabrica_sessao() as db:
        assert db.scalars(select(Cid).where(Cid.cid == codigo)).one().descricao == (
            "Corrigida na tela"
        )


@pytest.mark.parametrize(
    ("linha", "mensagem"),
    [
        ("errado,Descrição", "Linha 3 inválida"),
        ("T01.AA,", "Linha 3 inválida"),
    ],
)
def test_linha_invalida_cancela_tudo(
    tmp_path: Path, fabrica_sessao: Fabrica, linha: str, mensagem: str
) -> None:
    valido = _codigo()
    arquivo = _csv(tmp_path, [f"{valido},Boa", linha])
    with pytest.raises(SystemExit, match=mensagem):
        importar_cid.main(["--arquivo", str(arquivo)])
    with fabrica_sessao() as db:
        assert db.scalars(select(Cid).where(Cid.cid == valido)).first() is None


def test_codigo_repetido_e_cabecalho_errado_e_arquivo_ausente(tmp_path: Path) -> None:
    codigo = _codigo()
    with pytest.raises(SystemExit, match="código repetido"):
        importar_cid.main(
            ["--arquivo", str(_csv(tmp_path, [f"{codigo},Primeira", f"{codigo.lower()},Segunda"]))]
        )
    with pytest.raises(SystemExit, match="cabeçalho"):
        importar_cid.main(["--arquivo", str(_csv(tmp_path, ["A00,x"], "codigo,nome"))])
    with pytest.raises(SystemExit, match="não encontrado"):
        importar_cid.main(["--arquivo", str(tmp_path / "nao-existe.csv")])


def test_catalogo_do_repositorio_e_valido() -> None:
    pares = importar_cid.ler_arquivo(importar_cid.ARQUIVO_PADRAO)
    codigos = {codigo for codigo, _ in pares}
    assert len(pares) == len(codigos) == 1775
    assert {"A00", "C50", "E11", "U99", "Z99"} <= codigos
