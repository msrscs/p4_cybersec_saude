"""Rotas de pacientes (RF-03). Autorização por permissão RBAC em cada rota (ADR-0011).

O CPF nunca vai na URL (histórico, logs de proxy): a busca recebe o CPF no corpo e as demais
rotas usam o identificador público opaco (UUID).
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse

from app.api.auth import SEM_CACHE, Config, Ctx, erro
from app.api.deps import Db, exigir, limitar
from app.core.cpf import formatar_cpf, mascarar_cpf
from app.schemas.auth import ErroResposta
from app.schemas.paciente import (
    PacienteAlteracao,
    PacienteBusca,
    PacienteCadastro,
    PacienteListaEntrada,
    PacienteListaResposta,
    PacienteResposta,
    PacienteResumo,
)
from app.services import limite as limite_svc
from app.services import paciente as paciente_service
from app.services.autorizacao import Permissao
from app.services.paciente import (
    Alteracoes,
    DadosPaciente,
    ErroCadastroPaciente,
    NovoPaciente,
    PacienteInativo,
)
from app.services.sessao import SessaoAtual

router = APIRouter(
    prefix="/pacientes", tags=["pacientes"], dependencies=[Depends(limitar(limite_svc.GERAL))]
)

NAO_ENCONTRADO = "Paciente não encontrado."
Leitor = Annotated[SessaoAtual, Depends(exigir(Permissao.PACIENTE_LER))]
Listador = Annotated[SessaoAtual, Depends(exigir(Permissao.PACIENTE_LISTAR))]
Criador = Annotated[SessaoAtual, Depends(exigir(Permissao.PACIENTE_CRIAR))]
Editor = Annotated[SessaoAtual, Depends(exigir(Permissao.PACIENTE_EDITAR))]
Inativador = Annotated[SessaoAtual, Depends(exigir(Permissao.PACIENTE_INATIVAR))]
ERROS: dict[int | str, dict[str, Any]] = {
    codigo: {"model": ErroResposta}
    for codigo in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
}


def _resposta(dados: DadosPaciente) -> PacienteResposta:
    return PacienteResposta(
        id=dados.id_publico,
        cpf=formatar_cpf(dados.cpf),
        nome=dados.nome,
        data_nascimento=dados.data_nascimento,
        email=dados.email,
        status="ativo" if dados.status == "ativo" else "inativo",
        criado_em=dados.criado_em,
        atualizado_em=dados.atualizado_em,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=PacienteResposta,
    responses={**ERROS, status.HTTP_409_CONFLICT: {"model": ErroResposta}},
)
def cadastrar(
    dados: PacienteCadastro, atual: Criador, db: Db, settings: Config, ctx: Ctx, response: Response
) -> PacienteResposta | JSONResponse:
    novo = NovoPaciente(
        cpf=dados.cpf, nome=dados.nome, data_nascimento=dados.data_nascimento, email=dados.email
    )
    try:
        criado = paciente_service.cadastrar(db, settings, novo, atual.cpf_hash, ctx)
    except ErroCadastroPaciente as exc:
        return erro(status.HTTP_409_CONFLICT, str(exc))
    response.headers.update(SEM_CACHE)
    return _resposta(criado)


@router.post(
    "/busca",
    dependencies=[Depends(limitar(limite_svc.BUSCA_PACIENTE))],
    response_model=PacienteResposta,
    responses={**ERROS, status.HTTP_404_NOT_FOUND: {"model": ErroResposta}},
)
def buscar(
    dados: PacienteBusca, atual: Leitor, db: Db, settings: Config, ctx: Ctx, response: Response
) -> PacienteResposta | JSONResponse:
    """Busca exata por CPF (enviado no corpo, nunca na URL)."""
    encontrado = paciente_service.buscar_por_cpf(db, settings, dados.cpf, atual.cpf_hash, ctx)
    if encontrado is None:
        return erro(status.HTTP_404_NOT_FOUND, NAO_ENCONTRADO)
    response.headers.update(SEM_CACHE)
    return _resposta(encontrado)


@router.post(
    "/lista",
    dependencies=[Depends(limitar(limite_svc.LISTA_PACIENTE))],
    response_model=PacienteListaResposta,
    responses=ERROS,
)
def listar(
    dados: PacienteListaEntrada,
    atual: Listador,
    db: Db,
    settings: Config,
    ctx: Ctx,
    response: Response,
) -> PacienteListaResposta:
    """Página da lista, com CPF mascarado. POST como a busca: o repasse não aceita query string."""
    pagina = paciente_service.listar(db, settings, dados.depois, atual.cpf_hash, ctx)
    response.headers.update(SEM_CACHE)
    return PacienteListaResposta(
        itens=[
            PacienteResumo(
                id=item.id_publico,
                cpf_mascarado=mascarar_cpf(item.cpf),
                nome=item.nome,
                status="ativo" if item.status == "ativo" else "inativo",
            )
            for item in pagina.itens
        ],
        proximo=pagina.proximo,
    )


@router.get(
    "/{id_paciente}",
    response_model=PacienteResposta,
    responses={**ERROS, status.HTTP_404_NOT_FOUND: {"model": ErroResposta}},
)
def obter(
    id_paciente: uuid.UUID, atual: Leitor, db: Db, settings: Config, ctx: Ctx, response: Response
) -> PacienteResposta | JSONResponse:
    dados = paciente_service.obter(db, settings, id_paciente, atual.cpf_hash, ctx)
    if dados is None:
        return erro(status.HTTP_404_NOT_FOUND, NAO_ENCONTRADO)
    response.headers.update(SEM_CACHE)
    return _resposta(dados)


@router.patch(
    "/{id_paciente}",
    response_model=PacienteResposta,
    responses={
        **ERROS,
        status.HTTP_404_NOT_FOUND: {"model": ErroResposta},
        status.HTTP_409_CONFLICT: {"model": ErroResposta},
    },
)
def atualizar(
    id_paciente: uuid.UUID,
    dados: PacienteAlteracao,
    atual: Editor,
    db: Db,
    settings: Config,
    ctx: Ctx,
    response: Response,
) -> PacienteResposta | JSONResponse:
    """Altera nome, nascimento e/ou e-mail. O CPF é imutável."""
    alteracoes = Alteracoes(
        campos=frozenset(dados.model_fields_set),
        nome=dados.nome,
        data_nascimento=dados.data_nascimento,
        email=dados.email,
    )
    try:
        atualizado = paciente_service.atualizar(
            db, settings, id_paciente, alteracoes, atual.cpf_hash, ctx
        )
    except PacienteInativo:
        return erro(status.HTTP_409_CONFLICT, "Paciente inativo.")
    if atualizado is None:
        return erro(status.HTTP_404_NOT_FOUND, NAO_ENCONTRADO)
    response.headers.update(SEM_CACHE)
    return _resposta(atualizado)


def _status(id_paciente: uuid.UUID, ativo: bool, atual: SessaoAtual, db: Db, ctx: Ctx) -> Response:
    if not paciente_service.alterar_status(
        db, id_paciente, ativo=ativo, autor=atual.cpf_hash, ctx=ctx
    ):
        return erro(status.HTTP_404_NOT_FOUND, NAO_ENCONTRADO)
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=SEM_CACHE)


@router.delete(
    "/{id_paciente}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**ERROS, status.HTTP_404_NOT_FOUND: {"model": ErroResposta}},
)
def inativar(id_paciente: uuid.UUID, atual: Inativador, db: Db, ctx: Ctx) -> Response:
    """Exclusão lógica: o paciente fica inativo (reversível) e o histórico é preservado."""
    return _status(id_paciente, False, atual, db, ctx)


@router.post(
    "/{id_paciente}/reativar",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**ERROS, status.HTTP_404_NOT_FOUND: {"model": ErroResposta}},
)
def reativar(id_paciente: uuid.UUID, atual: Inativador, db: Db, ctx: Ctx) -> Response:
    return _status(id_paciente, True, atual, db, ctx)
