import base64
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pyotp
import pytest

from app.core import totp
from app.core.crypto import FinalidadeHash, hash_busca
from app.core.senha import problemas_politica
from app.services.mfa import gerar_codigo_recuperacao
from app.services.usuario import gerar_senha_temporaria

AGORA = datetime(2026, 10, 29, 12, 0, 15, tzinfo=UTC)


def _codigo(segredo: str, passo: int) -> str:
    return pyotp.TOTP(segredo).at(passo * 30)


def test_segredo_tem_160_bits_em_base32() -> None:
    segredo = totp.gerar_segredo()
    assert len(segredo) == 32
    assert len(base64.b32decode(segredo)) == 20
    assert segredo != totp.gerar_segredo()


def test_uri_sem_dado_pessoal_e_com_parametros_padrao() -> None:
    segredo = totp.gerar_segredo()
    uri = urlparse(totp.uri_provisionamento(segredo))
    assert uri.scheme == "otpauth" and uri.netloc == "totp"
    params = parse_qs(uri.query)
    assert params["secret"] == [segredo]
    assert params["issuer"] == ["CyberSec Saúde"]
    assert uri.path == "/CyberSec%20Sa%C3%BAde:Acesso"


def test_qr_svg() -> None:
    svg = totp.qr_svg(totp.uri_provisionamento(totp.gerar_segredo()))
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    # Sem o namespace o navegador não decodifica o SVG em <img> (a tela usa data: URL).
    assert 'xmlns="http://www.w3.org/2000/svg"' in svg
    assert "<script" not in svg


@pytest.mark.parametrize("deslocamento", [-1, 0, 1])
def test_aceita_janela_de_mais_ou_menos_um_passo(deslocamento: int) -> None:
    segredo = totp.gerar_segredo()
    atual = totp.passo(AGORA)
    codigo = _codigo(segredo, atual + deslocamento)
    assert totp.verificar(segredo, codigo, AGORA, None) == atual + deslocamento


@pytest.mark.parametrize("deslocamento", [-3, -2, 2, 3])
def test_recusa_fora_da_janela(deslocamento: int) -> None:
    segredo = totp.gerar_segredo()
    codigo = _codigo(segredo, totp.passo(AGORA) + deslocamento)
    if codigo in {_codigo(segredo, totp.passo(AGORA) + d) for d in (-1, 0, 1)}:
        pytest.skip("colisão improvável de código entre passos")
    assert totp.verificar(segredo, codigo, AGORA, None) is None


def test_recusa_reuso_e_passos_anteriores_ao_ultimo_aceito() -> None:
    segredo = totp.gerar_segredo()
    atual = totp.passo(AGORA)
    assert totp.verificar(segredo, _codigo(segredo, atual), AGORA, atual) is None
    assert totp.verificar(segredo, _codigo(segredo, atual - 1), AGORA, atual) is None
    proximo = AGORA + timedelta(seconds=30)
    assert totp.verificar(segredo, _codigo(segredo, atual + 1), proximo, atual) == atual + 1


@pytest.mark.parametrize(
    "codigo", ["", "12345", "1234567", "12345a", "".join(chr(0xFF10 + d) for d in range(1, 7))]
)
def test_recusa_formato_invalido(codigo: str) -> None:
    assert totp.verificar(totp.gerar_segredo(), codigo, AGORA, None) is None


def test_codigo_de_recuperacao_formato_e_entropia() -> None:
    codigos = {gerar_codigo_recuperacao() for _ in range(500)}
    assert len(codigos) == 500
    for c in codigos:
        assert len(c) == 11 and c[5] == "-"
        assert not set(c.replace("-", "")) & set("01OI")


def test_hash_de_recuperacao_normaliza_caixa_e_hifen() -> None:
    chave = b"k" * 32
    a = hash_busca(chave, FinalidadeHash.CODIGO_RECUPERACAO, "ABCDE-FGHJK")
    assert a == hash_busca(chave, FinalidadeHash.CODIGO_RECUPERACAO, " abcdefghjk ")
    assert a != hash_busca(chave, FinalidadeHash.EMAIL, "abcdefghjk")


def test_senha_temporaria_atende_politica_e_e_unica() -> None:
    senhas = {gerar_senha_temporaria() for _ in range(50)}
    assert len(senhas) == 50
    assert all(problemas_politica(s) == [] for s in senhas)
