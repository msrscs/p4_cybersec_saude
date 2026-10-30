"""Cadastros de unidade, serviço e CID (RF-09/10/11, ADR-0019). Permissão RBAC em cada rota."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Response, status
from fastapi.responses import JSONResponse

from app.api.auth import SEM_CACHE, Config, Ctx, erro
from app.api.deps import Db, exigir, limitar
from app.models import Cid, ServicoSaude, UnidadeSaude
from app.repositories.cadastro import Chave, Registro
from app.schemas.auth import ErroResposta
from app.schemas.cadastro import (
    CidAlteracao,
    CidNovo,
    CidResposta,
    CidsPagina,
    ListaEntrada,
    OpcaoUnidade,
    OpcoesUnidade,
    ServicoAlteracao,
    ServicoNovo,
    ServicoResposta,
    ServicosPagina,
    UnidadeAlteracao,
    UnidadeNova,
    UnidadeResposta,
    UnidadesPagina,
)
from app.services import cadastro
from app.services import limite as limite_svc
from app.services.autorizacao import Permissao
from app.services.cadastro import CadastroDuplicado, CadastroEmUso, Catalogo
from app.services.sessao import SessaoAtual

router = APIRouter(tags=["cadastros"], dependencies=[Depends(limitar(limite_svc.GERAL))])

NAO_ENCONTRADO = "Cadastro não encontrado."
Leitor = Annotated[SessaoAtual, Depends(exigir(Permissao.CADASTRO_LER))]
Gestor = Annotated[SessaoAtual, Depends(exigir(Permissao.CADASTRO_GERENCIAR))]
IdInteiro = Annotated[int, Path(ge=1, le=2_147_483_647)]
IdCid = Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")]
ERROS: dict[int | str, dict[str, Any]] = {
    codigo: {"model": ErroResposta}
    for codigo in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
}
ERROS_ALVO: dict[int | str, dict[str, Any]] = {
    **ERROS,
    status.HTTP_404_NOT_FOUND: {"model": ErroResposta},
    status.HTTP_409_CONFLICT: {"model": ErroResposta},
}


def _unidade(registro: UnidadeSaude) -> UnidadeResposta:
    return UnidadeResposta(
        id=registro.id_unidade,
        nome=registro.nome,
        tipo_unidade=registro.tipo_unidade,
        endereco=registro.endereco,
        telefone=registro.telefone,
        status=registro.status,
    )


def _servico(registro: ServicoSaude) -> ServicoResposta:
    return ServicoResposta(
        id=registro.id_servico,
        nome=registro.nome,
        descricao=registro.descricao,
        status=registro.status,
    )


def _cid(registro: Cid) -> CidResposta:
    return CidResposta(
        id=registro.cid_hash.hex(),
        cid=registro.cid,
        descricao=registro.descricao,
        status=registro.status,
    )


def _alterar[R: Registro](
    catalogo: Catalogo[R],
    chave: Chave,
    alteracoes: dict[str, Any],
    atual: SessaoAtual,
    db: Db,
    ctx: Ctx,
) -> R | JSONResponse:
    try:
        registro = cadastro.atualizar(db, catalogo, chave, alteracoes, atual.cpf_hash, ctx)
    except CadastroDuplicado as exc:
        return erro(status.HTTP_409_CONFLICT, str(exc))
    return registro if registro is not None else erro(status.HTTP_404_NOT_FOUND, NAO_ENCONTRADO)


def _status[R: Registro](
    catalogo: Catalogo[R], chave: Chave, ativo: bool, atual: SessaoAtual, db: Db, ctx: Ctx
) -> Response:
    try:
        registro = cadastro.alterar_status(
            db, catalogo, chave, ativo=ativo, autor=atual.cpf_hash, ctx=ctx
        )
    except CadastroEmUso as exc:
        return erro(status.HTTP_409_CONFLICT, str(exc))
    if registro is None:
        return erro(status.HTTP_404_NOT_FOUND, NAO_ENCONTRADO)
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=SEM_CACHE)


# --- Unidades de saúde -------------------------------------------------------------------


@router.post("/unidades/lista", response_model=UnidadesPagina, responses=ERROS)
def listar_unidades(dados: ListaEntrada, _atual: Leitor, db: Db) -> UnidadesPagina:
    pagina = cadastro.listar(db, cadastro.UNIDADES, dados.busca, dados.pagina)
    return UnidadesPagina(itens=[_unidade(r) for r in pagina.itens], tem_mais=pagina.tem_mais)


@router.get("/unidades/opcoes", response_model=OpcoesUnidade, responses=ERROS)
def opcoes_de_unidade(_atual: Leitor, db: Db) -> OpcoesUnidade:
    """Unidades ativas, para a combobox do cadastro de usuário."""
    return OpcoesUnidade(
        opcoes=[OpcaoUnidade(id=u.id_unidade, nome=u.nome) for u in cadastro.opcoes_de_unidade(db)]
    )


@router.post(
    "/unidades",
    status_code=status.HTTP_201_CREATED,
    response_model=UnidadeResposta,
    responses=ERROS_ALVO,
)
def criar_unidade(
    dados: UnidadeNova, atual: Gestor, db: Db, ctx: Ctx
) -> UnidadeResposta | JSONResponse:
    try:
        return _unidade(cadastro.criar_unidade(db, dados.model_dump(), atual.cpf_hash, ctx))
    except CadastroDuplicado as exc:
        return erro(status.HTTP_409_CONFLICT, str(exc))


@router.patch("/unidades/{id_unidade}", response_model=UnidadeResposta, responses=ERROS_ALVO)
def alterar_unidade(
    id_unidade: IdInteiro, dados: UnidadeAlteracao, atual: Gestor, db: Db, ctx: Ctx
) -> UnidadeResposta | JSONResponse:
    resultado = _alterar(
        cadastro.UNIDADES, id_unidade, dados.model_dump(exclude_unset=True), atual, db, ctx
    )
    return resultado if isinstance(resultado, JSONResponse) else _unidade(resultado)


@router.delete(
    "/unidades/{id_unidade}", status_code=status.HTTP_204_NO_CONTENT, responses=ERROS_ALVO
)
def inativar_unidade(id_unidade: IdInteiro, atual: Gestor, db: Db, ctx: Ctx) -> Response:
    return _status(cadastro.UNIDADES, id_unidade, False, atual, db, ctx)


@router.post(
    "/unidades/{id_unidade}/reativar",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=ERROS_ALVO,
)
def reativar_unidade(id_unidade: IdInteiro, atual: Gestor, db: Db, ctx: Ctx) -> Response:
    return _status(cadastro.UNIDADES, id_unidade, True, atual, db, ctx)


# --- Serviços de saúde -------------------------------------------------------------------


@router.post("/servicos/lista", response_model=ServicosPagina, responses=ERROS)
def listar_servicos(dados: ListaEntrada, _atual: Leitor, db: Db) -> ServicosPagina:
    pagina = cadastro.listar(db, cadastro.SERVICOS, dados.busca, dados.pagina)
    return ServicosPagina(itens=[_servico(r) for r in pagina.itens], tem_mais=pagina.tem_mais)


@router.post(
    "/servicos",
    status_code=status.HTTP_201_CREATED,
    response_model=ServicoResposta,
    responses=ERROS_ALVO,
)
def criar_servico(
    dados: ServicoNovo, atual: Gestor, db: Db, ctx: Ctx
) -> ServicoResposta | JSONResponse:
    try:
        return _servico(cadastro.criar_servico(db, dados.model_dump(), atual.cpf_hash, ctx))
    except CadastroDuplicado as exc:
        return erro(status.HTTP_409_CONFLICT, str(exc))


@router.patch("/servicos/{id_servico}", response_model=ServicoResposta, responses=ERROS_ALVO)
def alterar_servico(
    id_servico: IdInteiro, dados: ServicoAlteracao, atual: Gestor, db: Db, ctx: Ctx
) -> ServicoResposta | JSONResponse:
    resultado = _alterar(
        cadastro.SERVICOS, id_servico, dados.model_dump(exclude_unset=True), atual, db, ctx
    )
    return resultado if isinstance(resultado, JSONResponse) else _servico(resultado)


@router.delete(
    "/servicos/{id_servico}", status_code=status.HTTP_204_NO_CONTENT, responses=ERROS_ALVO
)
def inativar_servico(id_servico: IdInteiro, atual: Gestor, db: Db, ctx: Ctx) -> Response:
    return _status(cadastro.SERVICOS, id_servico, False, atual, db, ctx)


@router.post(
    "/servicos/{id_servico}/reativar",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=ERROS_ALVO,
)
def reativar_servico(id_servico: IdInteiro, atual: Gestor, db: Db, ctx: Ctx) -> Response:
    return _status(cadastro.SERVICOS, id_servico, True, atual, db, ctx)


# --- CID ---------------------------------------------------------------------------------


@router.post("/cids/lista", response_model=CidsPagina, responses=ERROS)
def listar_cids(dados: ListaEntrada, _atual: Leitor, db: Db) -> CidsPagina:
    pagina = cadastro.listar(db, cadastro.CIDS, dados.busca, dados.pagina)
    return CidsPagina(itens=[_cid(r) for r in pagina.itens], tem_mais=pagina.tem_mais)


@router.post(
    "/cids", status_code=status.HTTP_201_CREATED, response_model=CidResposta, responses=ERROS_ALVO
)
def criar_cid(
    dados: CidNovo, atual: Gestor, db: Db, settings: Config, ctx: Ctx
) -> CidResposta | JSONResponse:
    try:
        registro = cadastro.criar_cid(db, settings, dados.cid, dados.descricao, atual.cpf_hash, ctx)
    except CadastroDuplicado as exc:
        return erro(status.HTTP_409_CONFLICT, str(exc))
    return _cid(registro)


@router.patch("/cids/{id_cid}", response_model=CidResposta, responses=ERROS_ALVO)
def alterar_cid(
    id_cid: IdCid, dados: CidAlteracao, atual: Gestor, db: Db, ctx: Ctx
) -> CidResposta | JSONResponse:
    resultado = _alterar(
        cadastro.CIDS, bytes.fromhex(id_cid), dados.model_dump(exclude_unset=True), atual, db, ctx
    )
    return resultado if isinstance(resultado, JSONResponse) else _cid(resultado)


@router.delete("/cids/{id_cid}", status_code=status.HTTP_204_NO_CONTENT, responses=ERROS_ALVO)
def inativar_cid(id_cid: IdCid, atual: Gestor, db: Db, ctx: Ctx) -> Response:
    return _status(cadastro.CIDS, bytes.fromhex(id_cid), False, atual, db, ctx)


@router.post(
    "/cids/{id_cid}/reativar", status_code=status.HTTP_204_NO_CONTENT, responses=ERROS_ALVO
)
def reativar_cid(id_cid: IdCid, atual: Gestor, db: Db, ctx: Ctx) -> Response:
    return _status(cadastro.CIDS, bytes.fromhex(id_cid), True, atual, db, ctx)
