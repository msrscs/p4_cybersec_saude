from typing import Annotated, Any

from fastapi import APIRouter, Cookie, Depends, Response, status
from fastapi.responses import JSONResponse

from app.api.auth import SEM_CACHE, Config, Ctx, erro
from app.api.deps import COOKIE_PRE_AUTH, Db, SessaoLiberada, agora, definir_sessao, limitar
from app.schemas.auth import (
    AutenticadoResposta,
    CodigoRecuperacaoEntrada,
    CodigosRecuperacaoResposta,
    CodigoTotpEntrada,
    ErroResposta,
    ProvisionamentoResposta,
)
from app.services import limite as limite_svc
from app.services import mfa as mfa_service
from app.services.mfa import PreAuthInvalida

router = APIRouter(
    prefix="/auth/mfa", tags=["mfa"], dependencies=[Depends(limitar(limite_svc.MFA))]
)

PRE_AUTH_INVALIDA = "Sessão de login inválida ou expirada. Entre novamente."
CODIGO_INVALIDO = "Código inválido."
PreAuth = Annotated[str | None, Cookie(alias=COOKIE_PRE_AUTH, include_in_schema=False)]
ERROS: dict[int | str, dict[str, Any]] = {status.HTTP_401_UNAUTHORIZED: {"model": ErroResposta}}


@router.post("/cadastro", response_model=ProvisionamentoResposta, responses=ERROS)
def cadastro(
    db: Db, settings: Config, response: Response, pre_auth: PreAuth = None
) -> ProvisionamentoResposta | JSONResponse:
    """1º acesso: gera o segredo TOTP e o QR code para o aplicativo autenticador."""
    try:
        prov = mfa_service.iniciar_cadastro(db, settings, pre_auth, agora())
    except PreAuthInvalida:
        return erro(status.HTTP_401_UNAUTHORIZED, PRE_AUTH_INVALIDA)
    response.headers.update(SEM_CACHE)
    return ProvisionamentoResposta(otpauth_uri=prov.uri, qr_svg=prov.qr_svg, chave=prov.chave)


@router.post("/ativar", response_model=CodigosRecuperacaoResposta, responses=ERROS)
def ativar(
    dados: CodigoTotpEntrada,
    db: Db,
    settings: Config,
    ctx: Ctx,
    response: Response,
    pre_auth: PreAuth = None,
) -> CodigosRecuperacaoResposta | JSONResponse:
    """Confirma o 1º código, ativa o MFA e devolve os códigos de recuperação (só desta vez)."""
    try:
        resultado = mfa_service.ativar(db, settings, pre_auth, dados.codigo, ctx, agora())
    except PreAuthInvalida:
        return erro(status.HTTP_401_UNAUTHORIZED, PRE_AUTH_INVALIDA)
    if not resultado.sucesso or resultado.token_sessao is None:
        return erro(status.HTTP_401_UNAUTHORIZED, CODIGO_INVALIDO)
    response.headers.update(SEM_CACHE)
    definir_sessao(response, resultado.token_sessao)
    return CodigosRecuperacaoResposta(codigos_recuperacao=resultado.codigos)


@router.post("/verificar", response_model=AutenticadoResposta, responses=ERROS)
def verificar(
    dados: CodigoTotpEntrada,
    db: Db,
    settings: Config,
    ctx: Ctx,
    response: Response,
    pre_auth: PreAuth = None,
) -> AutenticadoResposta | JSONResponse:
    """Etapa 2 do login: código do aplicativo autenticador."""
    try:
        resultado = mfa_service.verificar(db, settings, pre_auth, dados.codigo, ctx, agora())
    except PreAuthInvalida:
        return erro(status.HTTP_401_UNAUTHORIZED, PRE_AUTH_INVALIDA)
    if not resultado.sucesso or resultado.token_sessao is None:
        return erro(status.HTTP_401_UNAUTHORIZED, CODIGO_INVALIDO)
    definir_sessao(response, resultado.token_sessao)
    return AutenticadoResposta()


@router.post("/recuperar", response_model=AutenticadoResposta, responses=ERROS)
def recuperar(
    dados: CodigoRecuperacaoEntrada,
    db: Db,
    settings: Config,
    ctx: Ctx,
    response: Response,
    pre_auth: PreAuth = None,
) -> AutenticadoResposta | JSONResponse:
    """Etapa 2 com um código de recuperação (uso único), se o celular não estiver disponível."""
    try:
        resultado = mfa_service.recuperar(db, settings, pre_auth, dados.codigo, ctx, agora())
    except PreAuthInvalida:
        return erro(status.HTTP_401_UNAUTHORIZED, PRE_AUTH_INVALIDA)
    if not resultado.sucesso or resultado.token_sessao is None:
        return erro(status.HTTP_401_UNAUTHORIZED, CODIGO_INVALIDO)
    definir_sessao(response, resultado.token_sessao)
    return AutenticadoResposta(codigos_restantes=resultado.restantes)


@router.post("/codigos", response_model=CodigosRecuperacaoResposta, responses=ERROS)
def novos_codigos(
    dados: CodigoTotpEntrada,
    atual: SessaoLiberada,
    db: Db,
    settings: Config,
    ctx: Ctx,
    response: Response,
) -> CodigosRecuperacaoResposta | JSONResponse:
    """Gera um novo conjunto de códigos de recuperação (o anterior deixa de valer)."""
    codigos = mfa_service.regenerar_codigos(db, settings, atual, dados.codigo, ctx, agora())
    if codigos is None:
        return erro(status.HTTP_401_UNAUTHORIZED, CODIGO_INVALIDO)
    response.headers.update(SEM_CACHE)
    return CodigosRecuperacaoResposta(codigos_recuperacao=codigos)
