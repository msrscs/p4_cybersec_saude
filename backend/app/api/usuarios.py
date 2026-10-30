"""Gestão de usuários (RF-01, ADR-0017). Permissão RBAC em cada rota; identificador opaco na URL."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse

from app.api.auth import SEM_CACHE, Config, Ctx, erro
from app.api.deps import Db, agora, exigir, limitar
from app.core.cpf import formatar_cpf, mascarar_cpf
from app.core.crypto import ErroCriptografia
from app.schemas.auth import ErroResposta
from app.schemas.gestao_usuario import (
    ListaDeGrupos,
    SenhaTemporaria,
    UsuarioAlteracao,
    UsuarioCriado,
    UsuarioDetalhe,
    UsuarioGrupos,
    UsuarioListaEntrada,
    UsuarioListaResposta,
    UsuarioNovo,
    UsuarioResumo,
)
from app.services import gestao_usuario
from app.services import limite as limite_svc
from app.services.autorizacao import GrupoNaoEncontrado, Permissao
from app.services.gestao_usuario import (
    Alteracoes,
    DadosUsuario,
    ErroAlteracao,
    NovoCadastro,
    OperacaoProibida,
)
from app.services.sessao import SessaoAtual
from app.services.usuario import ErroCadastro

router = APIRouter(
    prefix="/usuarios", tags=["usuarios"], dependencies=[Depends(limitar(limite_svc.GERAL))]
)

NAO_ENCONTRADO = "Usuário não encontrado."
GRUPO_INVALIDO = "Grupo inválido."
Leitor = Annotated[SessaoAtual, Depends(exigir(Permissao.USUARIO_LER))]
Criador = Annotated[SessaoAtual, Depends(exigir(Permissao.USUARIO_CRIAR))]
Editor = Annotated[SessaoAtual, Depends(exigir(Permissao.USUARIO_EDITAR))]
Inativador = Annotated[SessaoAtual, Depends(exigir(Permissao.USUARIO_INATIVAR))]
Resetador = Annotated[SessaoAtual, Depends(exigir(Permissao.USUARIO_RESETAR))]
GestorDeGrupos = Annotated[SessaoAtual, Depends(exigir(Permissao.USUARIO_GRUPOS))]
ERROS: dict[int | str, dict[str, Any]] = {
    codigo: {"model": ErroResposta}
    for codigo in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
}
ERROS_ALVO: dict[int | str, dict[str, Any]] = {
    **ERROS,
    status.HTTP_404_NOT_FOUND: {"model": ErroResposta},
    status.HTTP_409_CONFLICT: {"model": ErroResposta},
}


def _detalhe(dados: DadosUsuario) -> UsuarioDetalhe:
    return UsuarioDetalhe(
        id=dados.id_publico,
        cpf=formatar_cpf(dados.cpf),
        nome=dados.nome,
        email=dados.email,
        id_unidade=dados.id_unidade,
        status=dados.status,
        mfa_ativo=dados.mfa_ativo,
        troca_senha_obrigatoria=dados.troca_senha_obrigatoria,
        bloqueado=dados.bloqueado,
        grupos=dados.grupos,
        proprio=dados.proprio,
        criado_em=dados.criado_em,
        atualizado_em=dados.atualizado_em,
    )


@router.post(
    "/lista",
    dependencies=[Depends(limitar(limite_svc.LISTA_USUARIO))],
    response_model=UsuarioListaResposta,
    responses=ERROS,
)
def listar(
    dados: UsuarioListaEntrada,
    atual: Leitor,
    db: Db,
    settings: Config,
    ctx: Ctx,
    response: Response,
) -> UsuarioListaResposta:
    pagina = gestao_usuario.listar(db, settings, dados.depois, atual.cpf_hash, ctx)
    response.headers.update(SEM_CACHE)
    return UsuarioListaResposta(
        itens=[
            UsuarioResumo(
                id=item.id_publico,
                cpf_mascarado=None if item.cpf is None else mascarar_cpf(item.cpf),
                nome=item.nome,
                status=item.status,
                grupos=item.grupos,
            )
            for item in pagina.itens
        ],
        proximo=pagina.proximo,
    )


@router.get("/grupos", response_model=ListaDeGrupos, responses=ERROS)
def grupos(_atual: Leitor, db: Db, response: Response) -> ListaDeGrupos:
    response.headers.update(SEM_CACHE)
    return ListaDeGrupos(grupos=gestao_usuario.nomes_dos_grupos(db))


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limitar(limite_svc.ACESSO_USUARIO))],
    response_model=UsuarioCriado,
    responses={**ERROS_ALVO, status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErroResposta}},
)
def cadastrar(
    dados: UsuarioNovo, atual: Criador, db: Db, settings: Config, ctx: Ctx, response: Response
) -> UsuarioCriado | JSONResponse:
    """Devolve a senha temporária uma única vez: ela não é guardada nem registrada em claro."""
    novo = NovoCadastro(
        cpf=dados.cpf,
        nome=dados.nome,
        email=str(dados.email),
        id_unidade=dados.id_unidade,
        grupos=dados.grupos,
    )
    try:
        criado, temporaria = gestao_usuario.cadastrar(
            db, settings, novo, atual.cpf_hash, ctx, agora()
        )
    except ErroCadastro as exc:
        return erro(status.HTTP_409_CONFLICT, str(exc))
    except GrupoNaoEncontrado:
        return erro(status.HTTP_422_UNPROCESSABLE_CONTENT, GRUPO_INVALIDO)
    response.headers.update(SEM_CACHE)
    return UsuarioCriado(usuario=_detalhe(criado), senha_temporaria=temporaria)


@router.get("/{id_usuario}", response_model=UsuarioDetalhe, responses=ERROS_ALVO)
def obter(
    id_usuario: uuid.UUID, atual: Leitor, db: Db, settings: Config, ctx: Ctx, response: Response
) -> UsuarioDetalhe | JSONResponse:
    try:
        dados = gestao_usuario.obter(db, settings, id_usuario, atual.cpf_hash, ctx, agora())
    except ErroCriptografia:
        return erro(status.HTTP_409_CONFLICT, "Não foi possível ler este cadastro.")
    if dados is None:
        return erro(status.HTTP_404_NOT_FOUND, NAO_ENCONTRADO)
    response.headers.update(SEM_CACHE)
    return _detalhe(dados)


@router.patch("/{id_usuario}", response_model=UsuarioDetalhe, responses=ERROS_ALVO)
def atualizar(
    id_usuario: uuid.UUID,
    dados: UsuarioAlteracao,
    atual: Editor,
    db: Db,
    settings: Config,
    ctx: Ctx,
    response: Response,
) -> UsuarioDetalhe | JSONResponse:
    alteracoes = Alteracoes(
        campos=frozenset(dados.model_fields_set),
        nome=dados.nome,
        email=None if dados.email is None else str(dados.email),
        id_unidade=dados.id_unidade,
    )
    try:
        atualizado = gestao_usuario.atualizar(
            db, settings, id_usuario, alteracoes, atual.cpf_hash, ctx, agora()
        )
    except ErroAlteracao as exc:
        return erro(status.HTTP_409_CONFLICT, str(exc))
    if atualizado is None:
        return erro(status.HTTP_404_NOT_FOUND, NAO_ENCONTRADO)
    response.headers.update(SEM_CACHE)
    return _detalhe(atualizado)


def _status(id_usuario: uuid.UUID, ativo: bool, atual: SessaoAtual, db: Db, ctx: Ctx) -> Response:
    try:
        existe = gestao_usuario.alterar_status(
            db, id_usuario, ativo=ativo, autor=atual.cpf_hash, ctx=ctx
        )
    except OperacaoProibida as exc:
        return erro(status.HTTP_409_CONFLICT, str(exc))
    if not existe:
        return erro(status.HTTP_404_NOT_FOUND, NAO_ENCONTRADO)
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=SEM_CACHE)


@router.delete("/{id_usuario}", status_code=status.HTTP_204_NO_CONTENT, responses=ERROS_ALVO)
def inativar(id_usuario: uuid.UUID, atual: Inativador, db: Db, ctx: Ctx) -> Response:
    """Exclusão lógica: encerra as sessões na hora e preserva o histórico."""
    return _status(id_usuario, False, atual, db, ctx)


@router.post("/{id_usuario}/reativar", status_code=status.HTTP_204_NO_CONTENT, responses=ERROS_ALVO)
def reativar(id_usuario: uuid.UUID, atual: Inativador, db: Db, ctx: Ctx) -> Response:
    return _status(id_usuario, True, atual, db, ctx)


@router.post(
    "/{id_usuario}/resetar",
    dependencies=[Depends(limitar(limite_svc.ACESSO_USUARIO))],
    response_model=SenhaTemporaria,
    responses=ERROS_ALVO,
)
def resetar(
    id_usuario: uuid.UUID,
    atual: Resetador,
    db: Db,
    settings: Config,
    ctx: Ctx,
    response: Response,
) -> SenhaTemporaria | JSONResponse:
    """Senha temporária (exibida uma vez), MFA zerado, sessões e códigos revogados."""
    try:
        temporaria = gestao_usuario.resetar(db, settings, id_usuario, atual.cpf_hash, ctx, agora())
    except OperacaoProibida as exc:
        return erro(status.HTTP_409_CONFLICT, str(exc))
    if temporaria is None:
        return erro(status.HTTP_404_NOT_FOUND, NAO_ENCONTRADO)
    response.headers.update(SEM_CACHE)
    return SenhaTemporaria(senha_temporaria=temporaria)


@router.post(
    "/{id_usuario}/grupos",
    response_model=UsuarioDetalhe,
    responses={**ERROS_ALVO, status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErroResposta}},
)
def definir_grupos(
    id_usuario: uuid.UUID,
    dados: UsuarioGrupos,
    atual: GestorDeGrupos,
    db: Db,
    settings: Config,
    ctx: Ctx,
    response: Response,
) -> UsuarioDetalhe | JSONResponse:
    """Deixa o usuário exatamente nos grupos informados. Vale na próxima requisição dele."""
    try:
        atualizado = gestao_usuario.definir_grupos(
            db, settings, id_usuario, dados.grupos, atual.cpf_hash, ctx, agora()
        )
    except OperacaoProibida as exc:
        return erro(status.HTTP_409_CONFLICT, str(exc))
    except GrupoNaoEncontrado:
        return erro(status.HTTP_422_UNPROCESSABLE_CONTENT, GRUPO_INVALIDO)
    if atualizado is None:
        return erro(status.HTTP_404_NOT_FOUND, NAO_ENCONTRADO)
    response.headers.update(SEM_CACHE)
    return _detalhe(atualizado)
