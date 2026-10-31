"""OCI e navegação (RF-12, ADR-0025). Permissão em cada rota e alcance por unidade no serviço.

O CPF do paciente vai no corpo, nunca na URL. OCI fora do alcance responde como inexistente, sem
revelar que ela existe.
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Response, status
from fastapi.responses import JSONResponse

from app.api.auth import SEM_CACHE, Config, Ctx, erro
from app.api.deps import Db, agora, exigir, limitar
from app.core.cpf import mascarar_cpf
from app.models import Cid, Oci
from app.schemas.auth import ErroResposta
from app.schemas.oci import (
    CidResumo,
    DiaComVagas,
    DiasComVagas,
    EtapaAlteracao,
    EtapaNova,
    EtapaRemarcacao,
    EtapaResposta,
    HorariosVagos,
    HorarioVago,
    ListaDeCids,
    OciAlteracao,
    OciConclusao,
    OciDetalhe,
    OciListaEntrada,
    OciNova,
    OciOpcoes,
    OciPagina,
    OciResumo,
    OpcaoSimples,
    UnidadeQueAtende,
    UnidadesQueAtendem,
)
from app.services import agenda as agenda_service
from app.services import limite as limite_svc
from app.services import oci as oci_service
from app.services.agenda import FUSO, HorarioIndisponivel
from app.services.autorizacao import Permissao
from app.services.cadastro import CidInvalido, ServicoInvalido, TipoInvalido, UnidadeInvalida
from app.services.oci import (
    DadosPessoais,
    DetalheOci,
    FiltrosOci,
    ForaDoAlcance,
    NavegacaoEncerrada,
    NovaOci,
    OciDuplicada,
    OciEncerrada,
    PacienteIndisponivel,
)
from app.services.sessao import SessaoAtual

router = APIRouter(prefix="/ocis", tags=["ocis"], dependencies=[Depends(limitar(limite_svc.GERAL))])

NAO_ENCONTRADA = "OCI não encontrada."
Leitor = Annotated[SessaoAtual, Depends(exigir(Permissao.OCI_LER))]
Criador = Annotated[SessaoAtual, Depends(exigir(Permissao.OCI_CRIAR))]
Editor = Annotated[SessaoAtual, Depends(exigir(Permissao.OCI_EDITAR))]
Conclusor = Annotated[SessaoAtual, Depends(exigir(Permissao.OCI_CONCLUIR))]
IdInteiro = Annotated[int, Path(ge=1, le=2_147_483_647)]
IdEtapa = Annotated[int, Path(ge=1, le=2**63 - 1)]
IdCid = Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")]
ERROS: dict[int | str, dict[str, Any]] = {
    codigo: {"model": ErroResposta}
    for codigo in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
}
ERROS_ALVO: dict[int | str, dict[str, Any]] = {
    **ERROS,
    status.HTTP_404_NOT_FOUND: {"model": ErroResposta},
    status.HTTP_409_CONFLICT: {"model": ErroResposta},
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErroResposta},
}
_INVALIDOS = (PacienteIndisponivel, TipoInvalido, CidInvalido, UnidadeInvalida, ServicoInvalido)
_CONFLITOS = (OciDuplicada, OciEncerrada, NavegacaoEncerrada, HorarioIndisponivel)
_ETAPA_INVALIDA = (UnidadeInvalida, ServicoInvalido)


def _cid(registro: Cid) -> CidResumo:
    return CidResumo(id=registro.cid_hash.hex(), cid=registro.cid, descricao=registro.descricao)


def _resumo(oci: Oci, pessoa: DadosPessoais, instante: datetime) -> OciResumo:
    return OciResumo(
        id=oci.id_publico,
        paciente_nome=pessoa.nome,
        cpf_mascarado=None if pessoa.cpf is None else mascarar_cpf(pessoa.cpf),
        tipo_oci=oci.tipo.tipo_oci,
        cid=_cid(oci.cid),
        status=oci.status,  # o CHECK do banco garante os 3 valores
        data_criacao=oci.data_criacao,
        prazo_em=oci.prazo_em,
        atrasada=oci.status == "aberta" and oci.prazo_em < instante,
        dias_restantes=_dias_restantes(oci, instante),
    )


def _dias_restantes(oci: Oci, instante: datetime) -> int | None:
    if oci.status != "aberta":
        return None
    return (oci.prazo_em.astimezone(FUSO).date() - agenda_service.hoje(instante)).days


def _detalhe(dados: DetalheOci, instante: datetime) -> OciDetalhe:
    oci = dados.oci
    return OciDetalhe(
        **_resumo(oci, dados.paciente, instante).model_dump(),
        id_tipo_oci=oci.id_tipo_oci,
        paciente_id=dados.paciente.id_publico,
        resultado=dados.resultado,
        resultado_cid=None if oci.resultado_cid is None else _cid(oci.resultado_cid),
        navegacoes=[
            EtapaResposta(
                id=etapa.id_oci_navegacao,
                id_unidade=etapa.id_unidade,
                unidade=etapa.unidade.nome,
                id_servico=etapa.id_servico,
                servico=etapa.servico.nome,
                data_hora=etapa.data_hora,
                status=etapa.status,
                pode_marcar=oci_service.pode_marcar(dados.alcance, etapa, oci),
            )
            for etapa in oci.navegacoes
        ],
    )


def _responder(dados: DetalheOci | None, response: Response) -> OciDetalhe | JSONResponse:
    if dados is None:
        return erro(status.HTTP_404_NOT_FOUND, NAO_ENCONTRADA)
    response.headers.update(SEM_CACHE)
    return _detalhe(dados, agora())


@router.get("/opcoes", response_model=OciOpcoes, responses=ERROS)
def opcoes(atual: Leitor, db: Db) -> OciOpcoes:
    tipos, unidades, abertura = oci_service.opcoes_de_abertura(db, atual.cpf_hash)
    return OciOpcoes(
        tipos=[OpcaoSimples(id=t.id_tipo_oci, nome=t.tipo_oci) for t in tipos],
        unidades=[OpcaoSimples(id=u.id_unidade, nome=u.nome) for u in unidades],
        unidades_abertura=[OpcaoSimples(id=u.id_unidade, nome=u.nome) for u in abertura],
    )


@router.get("/opcoes/tipos/{id_tipo_oci}/cids", response_model=ListaDeCids, responses=ERROS)
def cids_do_tipo(id_tipo_oci: IdInteiro, _atual: Leitor, db: Db) -> ListaDeCids:
    return ListaDeCids(cids=[_cid(c) for c in oci_service.cids_do_tipo(db, id_tipo_oci)])


@router.get("/opcoes/cids/{id_cid}/unidades", response_model=UnidadesQueAtendem, responses=ERROS)
def unidades_que_atendem(id_cid: IdCid, _atual: Leitor, db: Db) -> UnidadesQueAtendem:
    """Unidades que oferecem um serviço deste CID e têm agenda para ele."""
    return UnidadesQueAtendem(
        unidades=[
            UnidadeQueAtende(
                id=item.unidade.id_unidade,
                nome=item.unidade.nome,
                servicos=[OpcaoSimples(id=s.id_servico, nome=s.nome) for s in item.servicos],
            )
            for item in agenda_service.unidades_que_atendem(db, bytes.fromhex(id_cid))
        ]
    )


@router.get(
    "/opcoes/unidades/{id_unidade}/servicos/{id_servico}/dias",
    response_model=DiasComVagas,
    responses=ERROS,
)
def dias_com_vagas(
    id_unidade: IdInteiro, id_servico: IdInteiro, _atual: Leitor, db: Db
) -> DiasComVagas:
    return DiasComVagas(
        dias=[
            DiaComVagas(data=dia.data, vagas=dia.vagas)
            for dia in agenda_service.dias_com_vagas(db, id_unidade, id_servico, agora())
        ]
    )


@router.get(
    "/opcoes/unidades/{id_unidade}/servicos/{id_servico}/dias/{dia}/horarios",
    response_model=HorariosVagos,
    responses=ERROS,
)
def horarios_com_vagas(
    id_unidade: IdInteiro, id_servico: IdInteiro, dia: date, _atual: Leitor, db: Db
) -> HorariosVagos:
    return HorariosVagos(
        horarios=[
            HorarioVago(
                data_hora=horario.data_hora,
                hora=horario.data_hora.strftime("%H:%M"),
                vagas=horario.vagas,
            )
            for horario in agenda_service.horarios_com_vagas(
                db, id_unidade, id_servico, dia, agora()
            )
        ]
    )


@router.post(
    "/lista",
    dependencies=[Depends(limitar(limite_svc.LISTA_OCI))],
    response_model=OciPagina,
    responses=ERROS,
)
def listar(
    dados: OciListaEntrada, atual: Leitor, db: Db, settings: Config, ctx: Ctx, response: Response
) -> OciPagina:
    instante = agora()
    filtros = FiltrosOci(
        status=dados.status,
        id_tipo_oci=dados.id_tipo_oci,
        id_unidade=dados.id_unidade,
        cpf=dados.cpf,
        atrasadas=dados.atrasadas,
    )
    pagina = oci_service.listar(db, settings, filtros, dados.depois, atual.cpf_hash, ctx, instante)
    response.headers.update(SEM_CACHE)
    return OciPagina(
        itens=[_resumo(oci, pessoa, instante) for oci, pessoa in pagina.itens],
        proximo=pagina.proximo,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=OciDetalhe,
    responses=ERROS_ALVO,
)
def abrir(
    dados: OciNova, atual: Criador, db: Db, settings: Config, ctx: Ctx, response: Response
) -> OciDetalhe | JSONResponse:
    nova = NovaOci(
        cpf=dados.cpf,
        id_tipo_oci=dados.id_tipo_oci,
        cid_hash=bytes.fromhex(dados.cid),
        id_unidade=dados.id_unidade,
        id_servico=dados.id_servico,
        data_hora=dados.data_hora,
    )
    instante = agora()
    try:
        criada = oci_service.abrir(db, settings, nova, atual.cpf_hash, ctx, instante)
    except ForaDoAlcance:
        return erro(status.HTTP_403_FORBIDDEN, "Acesso negado.")
    except _INVALIDOS as exc:
        return erro(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    except (OciDuplicada, HorarioIndisponivel) as exc:
        return erro(status.HTTP_409_CONFLICT, str(exc))
    response.headers.update(SEM_CACHE)
    return _detalhe(criada, instante)


@router.get("/{id_oci}", response_model=OciDetalhe, responses=ERROS_ALVO)
def obter(
    id_oci: uuid.UUID, atual: Leitor, db: Db, settings: Config, ctx: Ctx, response: Response
) -> OciDetalhe | JSONResponse:
    return _responder(oci_service.obter(db, settings, id_oci, atual.cpf_hash, ctx), response)


@router.patch("/{id_oci}", response_model=OciDetalhe, responses=ERROS_ALVO)
def alterar(
    id_oci: uuid.UUID,
    dados: OciAlteracao,
    atual: Editor,
    db: Db,
    settings: Config,
    ctx: Ctx,
    response: Response,
) -> OciDetalhe | JSONResponse:
    try:
        resultado = oci_service.alterar_cid(
            db, settings, id_oci, bytes.fromhex(dados.cid), atual.cpf_hash, ctx
        )
    except CidInvalido as exc:
        return erro(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    except OciEncerrada as exc:
        return erro(status.HTTP_409_CONFLICT, str(exc))
    return _responder(resultado, response)


@router.post("/{id_oci}/concluir", response_model=OciDetalhe, responses=ERROS_ALVO)
def concluir(
    id_oci: uuid.UUID,
    dados: OciConclusao,
    atual: Conclusor,
    db: Db,
    settings: Config,
    ctx: Ctx,
    response: Response,
) -> OciDetalhe | JSONResponse:
    cid = None if dados.resultado_cid is None else bytes.fromhex(dados.resultado_cid)
    try:
        resultado = oci_service.concluir(
            db, settings, id_oci, dados.resultado, cid, atual.cpf_hash, ctx
        )
    except CidInvalido as exc:
        return erro(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    except OciEncerrada as exc:
        return erro(status.HTTP_409_CONFLICT, str(exc))
    return _responder(resultado, response)


@router.post("/{id_oci}/cancelar", response_model=OciDetalhe, responses=ERROS_ALVO)
def cancelar(
    id_oci: uuid.UUID, atual: Conclusor, db: Db, settings: Config, ctx: Ctx, response: Response
) -> OciDetalhe | JSONResponse:
    try:
        resultado = oci_service.cancelar(db, settings, id_oci, atual.cpf_hash, ctx)
    except OciEncerrada as exc:
        return erro(status.HTTP_409_CONFLICT, str(exc))
    return _responder(resultado, response)


@router.post(
    "/{id_oci}/navegacoes",
    status_code=status.HTTP_201_CREATED,
    response_model=OciDetalhe,
    responses=ERROS_ALVO,
)
def incluir_etapa(
    id_oci: uuid.UUID,
    dados: EtapaNova,
    atual: Editor,
    db: Db,
    settings: Config,
    ctx: Ctx,
    response: Response,
) -> OciDetalhe | JSONResponse:
    try:
        resultado = oci_service.incluir_etapa(
            db,
            settings,
            id_oci,
            dados.id_unidade,
            dados.id_servico,
            dados.data_hora,
            atual.cpf_hash,
            ctx,
            agora(),
        )
    except _ETAPA_INVALIDA as exc:
        return erro(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    except (OciEncerrada, HorarioIndisponivel) as exc:
        return erro(status.HTTP_409_CONFLICT, str(exc))
    return _responder(resultado, response)


@router.patch("/{id_oci}/navegacoes/{id_etapa}", response_model=OciDetalhe, responses=ERROS_ALVO)
def alterar_etapa(
    id_oci: uuid.UUID,
    id_etapa: IdEtapa,
    dados: EtapaAlteracao,
    atual: Editor,
    db: Db,
    settings: Config,
    ctx: Ctx,
    response: Response,
) -> OciDetalhe | JSONResponse:
    try:
        resultado = oci_service.marcar_etapa(
            db, settings, id_oci, id_etapa, dados.status, atual.cpf_hash, ctx
        )
    except ForaDoAlcance:
        return erro(status.HTTP_403_FORBIDDEN, "Acesso negado.")
    except _CONFLITOS as exc:
        return erro(status.HTTP_409_CONFLICT, str(exc))
    return _responder(resultado, response)


@router.post(
    "/{id_oci}/navegacoes/{id_etapa}/remarcar",
    response_model=OciDetalhe,
    responses=ERROS_ALVO,
)
def remarcar_etapa(
    id_oci: uuid.UUID,
    id_etapa: IdEtapa,
    dados: EtapaRemarcacao,
    atual: Editor,
    db: Db,
    settings: Config,
    ctx: Ctx,
    response: Response,
) -> OciDetalhe | JSONResponse:
    try:
        resultado = oci_service.remarcar_etapa(
            db,
            settings,
            id_oci,
            id_etapa,
            dados.id_unidade,
            dados.id_servico,
            dados.data_hora,
            atual.cpf_hash,
            ctx,
            agora(),
        )
    except ForaDoAlcance:
        return erro(status.HTTP_403_FORBIDDEN, "Acesso negado.")
    except _ETAPA_INVALIDA as exc:
        return erro(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    except _CONFLITOS as exc:
        return erro(status.HTTP_409_CONFLICT, str(exc))
    return _responder(resultado, response)
