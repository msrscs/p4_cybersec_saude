"""TOTP (RFC 6238) com pyotp: SHA-1, 6 dígitos, 30 s, compatível com Google/Microsoft Authenticator.

A verificação aceita ±1 passo (relógio desajustado) e recusa qualquer passo menor ou igual
ao último aceito: um código já usado não vale de novo, nem dentro da mesma janela.
"""

import hmac
import io
from datetime import datetime

import pyotp
import segno

EMISSOR = "CyberSec Saúde"
INTERVALO = 30
DIGITOS = 6
JANELA = 1


def gerar_segredo() -> str:
    return pyotp.random_base32(length=32)  # 32 caracteres base32 = 160 bits


def uri_provisionamento(segredo: str) -> str:
    # O rótulo não leva CPF, nome nem e-mail (o QR pode ser fotografado/compartilhado).
    return pyotp.TOTP(segredo, digits=DIGITOS, interval=INTERVALO).provisioning_uri(
        name="Acesso", issuer_name=EMISSOR
    )


def qr_svg(uri: str) -> str:
    # Documento SVG completo, não svg_inline: a tela o exibe em <img>, e sem o xmlns o navegador
    # não decodifica a imagem.
    saida = io.BytesIO()
    segno.make(uri, error="m").save(
        saida, kind="svg", xmldecl=False, nl=False, scale=5, dark="#0f1b2d", light="#ffffff"
    )
    return saida.getvalue().decode()


def passo(agora: datetime) -> int:
    return int(agora.timestamp()) // INTERVALO


def verificar(segredo: str, codigo: str, agora: datetime, ultimo_passo: int | None) -> int | None:
    """Devolve o passo aceito (para gravar como último) ou None."""
    if len(codigo) != DIGITOS or not codigo.isascii() or not codigo.isdigit():
        return None
    totp = pyotp.TOTP(segredo, digits=DIGITOS, interval=INTERVALO)
    atual = passo(agora)
    aceito: int | None = None
    for candidato in range(atual - JANELA, atual + JANELA + 1):
        esperado = totp.at(candidato * INTERVALO)
        # Compara todos os candidatos (tempo constante em relação a qual passo casou).
        if hmac.compare_digest(esperado, codigo) and aceito is None:
            aceito = candidato
    if aceito is None or (ultimo_passo is not None and aceito <= ultimo_passo):
        return None
    return aceito
