from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import get_db
from app.core.requisicao import contexto_requisicao, obter_settings
from app.schemas.auth import ErroResposta, LoginEntrada, LoginResposta
from app.services import auth as auth_service
from app.services.auditoria import ContextoRequisicao

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_PRE_AUTH = "pre_auth"
MENSAGEM_FALHA = "CPF ou senha inválidos."


@router.post(
    "/login",
    response_model=LoginResposta,
    responses={status.HTTP_401_UNAUTHORIZED: {"model": ErroResposta}},
)
def login(
    dados: LoginEntrada,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(obter_settings)],
    ctx: Annotated[ContextoRequisicao, Depends(contexto_requisicao)],
) -> LoginResposta | JSONResponse:
    """Etapa 1 do login. Em caso de sucesso, a próxima etapa é o TOTP (`/auth/mfa`)."""
    resultado = auth_service.autenticar_senha(
        db, settings, cpf=dados.cpf, senha=dados.senha, ctx=ctx
    )
    # Falha devolve resposta (não exceção) para a transação gravar contador e auditoria.
    if not resultado.sucesso or resultado.token is None:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": MENSAGEM_FALHA},
            headers={"Cache-Control": "no-store"},
        )
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        COOKIE_PRE_AUTH,
        resultado.token,
        max_age=int(auth_service.VALIDADE_PRE_AUTH.total_seconds()),
        path="/auth/mfa",
        secure=True,
        httponly=True,
        samesite="strict",
    )
    return LoginResposta(etapa="mfa")
