"""Consulta do log de auditoria (RF-04, ADR-0015). Somente leitura: não há rota que altere o log."""

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status

from app.api.auth import SEM_CACHE, Config, Ctx
from app.api.deps import Db, exigir, limitar
from app.schemas.auth import ErroResposta
from app.schemas.log import LogAcoes, LogConsulta, LogIntegridade, LogItem, LogPagina
from app.services import consulta_log
from app.services import limite as limite_svc
from app.services.autorizacao import Permissao
from app.services.consulta_log import Filtros
from app.services.sessao import SessaoAtual

router = APIRouter(prefix="/logs", tags=["logs"], dependencies=[Depends(limitar(limite_svc.GERAL))])

Leitor = Annotated[SessaoAtual, Depends(exigir(Permissao.LOG_LER))]
ERROS: dict[int | str, dict[str, Any]] = {
    codigo: {"model": ErroResposta}
    for codigo in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
}


@router.post(
    "/consulta",
    dependencies=[Depends(limitar(limite_svc.CONSULTA_LOG))],
    response_model=LogPagina,
    responses=ERROS,
)
def consultar(
    dados: LogConsulta, atual: Leitor, db: Db, settings: Config, ctx: Ctx, response: Response
) -> LogPagina:
    """Uma página do log. POST: os filtros (com CPF) não podem ir para a URL."""
    filtros = Filtros(
        de=dados.de,
        ate=dados.ate,
        acao=None if dados.acao is None else dados.acao.value,
        cpf=dados.cpf,
        antes=dados.antes,
    )
    pagina = consulta_log.consultar(db, settings, filtros, atual.cpf_hash, ctx)
    response.headers.update(SEM_CACHE)
    return LogPagina(
        itens=[LogItem(**asdict(item)) for item in pagina.itens], proximo=pagina.proximo
    )


@router.get("/acoes", response_model=LogAcoes, responses=ERROS)
def acoes(_atual: Leitor, response: Response) -> LogAcoes:
    response.headers.update(SEM_CACHE)
    return LogAcoes(acoes=consulta_log.acoes())


@router.get("/integridade", response_model=LogIntegridade, responses=ERROS)
def integridade(_atual: Leitor, db: Db, response: Response) -> LogIntegridade:
    """Resultado da última verificação da cadeia. A API só informa: não recalcula (ADR-0015)."""
    response.headers.update(SEM_CACHE)
    return LogIntegridade(**asdict(consulta_log.integridade(db)))
