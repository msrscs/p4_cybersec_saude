from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import Db, Sessao, agora, apagar_sessao, definir_pre_auth
from app.core.config import Settings
from app.core.requisicao import contexto_requisicao, obter_settings
from app.repositories import usuario as usuario_repo
from app.schemas.auth import (
    ErroResposta,
    LoginEntrada,
    LoginResposta,
    SessaoResposta,
    TrocaSenhaEntrada,
)
from app.services import auth as auth_service
from app.services import autorizacao
from app.services import sessao as sessao_svc
from app.services import usuario as usuario_service
from app.services.auditoria import ContextoRequisicao

router = APIRouter(prefix="/auth", tags=["auth"])

MENSAGEM_FALHA = "CPF ou senha inválidos."
SEM_CACHE = {"Cache-Control": "no-store"}
Ctx = Annotated[ContextoRequisicao, Depends(contexto_requisicao)]
Config = Annotated[Settings, Depends(obter_settings)]


def erro(status_code: int, detail: str) -> JSONResponse:
    # Devolver (não levantar) mantém o commit: contadores e auditoria são gravados.
    return JSONResponse(status_code=status_code, content={"detail": detail}, headers=SEM_CACHE)


@router.post(
    "/login",
    response_model=LoginResposta,
    responses={status.HTTP_401_UNAUTHORIZED: {"model": ErroResposta}},
)
def login(
    dados: LoginEntrada, response: Response, db: Db, settings: Config, ctx: Ctx
) -> LoginResposta | JSONResponse:
    """Etapa 1: CPF + senha. Em seguida, `/auth/mfa/verificar` (ou `/cadastro` no 1º acesso)."""
    resultado = auth_service.autenticar_senha(
        db, settings, cpf=dados.cpf, senha=dados.senha, ctx=ctx
    )
    if not resultado.sucesso or resultado.token is None:
        return erro(status.HTTP_401_UNAUTHORIZED, MENSAGEM_FALHA)
    response.headers.update(SEM_CACHE)
    definir_pre_auth(response, resultado.token)
    return LoginResposta(etapa="mfa" if resultado.mfa_ativo else "mfa_cadastro")


@router.get("/sessao", response_model=SessaoResposta)
def sessao(atual: Sessao, db: Db, response: Response) -> SessaoResposta:
    usuario = usuario_repo.buscar(db, atual.cpf_hash)
    response.headers.update(SEM_CACHE)
    return SessaoResposta(
        expira_em=atual.expira_em,
        troca_senha_obrigatoria=bool(usuario and usuario.troca_senha_obrigatoria),
        permissoes=sorted(autorizacao.permissoes(db, atual.cpf_hash)),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(atual: Sessao, db: Db, ctx: Ctx, response: Response) -> None:
    sessao_svc.encerrar(db, atual, ctx)
    apagar_sessao(response)


@router.post(
    "/senha",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErroResposta}},
)
def trocar_senha(
    dados: TrocaSenhaEntrada, atual: Sessao, db: Db, settings: Config, ctx: Ctx
) -> Response:
    try:
        usuario_service.trocar_senha(
            db,
            settings,
            atual,
            senha_atual=dados.senha_atual,
            nova_senha=dados.nova_senha,
            ctx=ctx,
            agora=agora(),
        )
    except ValueError as exc:  # ErroSenha ou política (mensagens sem a senha)
        return erro(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=SEM_CACHE)
