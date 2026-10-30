"""Cadastros de catálogo: tipos de unidade, unidades, serviços e CID (ADR-0019, ADR-0021).

São dados públicos, sem cifragem e sem auditoria de leitura; toda escrita é auditada. A exclusão
é lógica, porque as OCIs vão apontar para estes registros.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.core.config import Settings
from app.core.crypto import FinalidadeHash, hash_busca
from app.models import Cid, ServicoSaude, TipoUnidade, UnidadeSaude
from app.repositories import cadastro as cadastro_repo
from app.repositories.cadastro import Chave, Ordem, Registro
from app.services import auditoria
from app.services.auditoria import ContextoRequisicao, Evento

TAMANHO_PAGINA = 20
LIMITE_OPCOES = 1000
LOTE_IMPORTACAO = 500


class CadastroDuplicado(Exception):
    def __init__(self) -> None:
        super().__init__("Já existe um cadastro com esses dados.")


class CadastroEmUso(Exception):
    """A mensagem é exibida ao administrador e diz o que fazer antes de inativar."""


class TipoInvalido(Exception):
    def __init__(self) -> None:
        super().__init__("Tipo de unidade inválido.")


class UnidadeInvalida(Exception):
    def __init__(self) -> None:
        super().__init__("Unidade inválida.")


@dataclass(frozen=True)
class Catalogo[R: Registro]:
    recurso: str
    modelo: type[R]
    ordem: Ordem
    condicao_de_busca: Callable[[str], ColumnElement[bool]]


def _contem(*colunas: InstrumentedAttribute[str]) -> Callable[[str], ColumnElement[bool]]:
    # autoescape: % e _ digitados são texto, não curinga.
    return lambda termo: or_(*(coluna.icontains(termo, autoescape=True) for coluna in colunas))


def _busca_de_unidade(termo: str) -> ColumnElement[bool]:
    return or_(
        _contem(UnidadeSaude.nome, UnidadeSaude.endereco)(termo),
        UnidadeSaude.tipo.has(_contem(TipoUnidade.nome)(termo)),
    )


TIPOS_UNIDADE = Catalogo(
    "tipo_unidade",
    TipoUnidade,
    func.lower(TipoUnidade.nome),
    _contem(TipoUnidade.nome, TipoUnidade.descricao),
)
UNIDADES = Catalogo("unidade_saude", UnidadeSaude, func.lower(UnidadeSaude.nome), _busca_de_unidade)
SERVICOS = Catalogo(
    "servico_saude",
    ServicoSaude,
    func.lower(ServicoSaude.nome),
    _contem(ServicoSaude.nome, ServicoSaude.descricao),
)
CIDS = Catalogo("cid", Cid, Cid.cid, _contem(Cid.cid, Cid.descricao))


@dataclass(frozen=True)
class ResultadoImportacao:
    criados: int
    ignorados: int


@dataclass(frozen=True)
class Pagina[R: Registro]:
    itens: list[R]
    tem_mais: bool


def listar[R: Registro](
    db: Session, catalogo: Catalogo[R], busca: str | None, pagina: int
) -> Pagina[R]:
    linhas = cadastro_repo.listar(
        db,
        catalogo.modelo,
        ordem=catalogo.ordem,
        condicao=catalogo.condicao_de_busca(busca) if busca else None,
        limite=TAMANHO_PAGINA + 1,
        deslocamento=(pagina - 1) * TAMANHO_PAGINA,
    )
    return Pagina(itens=linhas[:TAMANHO_PAGINA], tem_mais=len(linhas) > TAMANHO_PAGINA)


def opcoes_de_unidade(db: Session) -> list[UnidadeSaude]:
    return cadastro_repo.unidades_ativas(db, LIMITE_OPCOES)


def opcoes_de_tipo(db: Session) -> list[TipoUnidade]:
    return cadastro_repo.tipos_ativos(db, LIMITE_OPCOES)


def criar_tipo(
    db: Session, valores: dict[str, Any], autor: bytes, ctx: ContextoRequisicao
) -> TipoUnidade:
    registro = TipoUnidade(**valores)
    _inserir(db, registro)
    _auditar(db, Evento.CATALOG_CREATED, TIPOS_UNIDADE, registro.id_tipo_unidade, autor, ctx)
    return registro


def criar_unidade(
    db: Session, valores: dict[str, Any], autor: bytes, ctx: ContextoRequisicao
) -> UnidadeSaude:
    _validar_tipo_ativo(db, valores["id_tipo_unidade"])
    registro = UnidadeSaude(**valores)
    _inserir(db, registro)
    _auditar(db, Evento.CATALOG_CREATED, UNIDADES, registro.id_unidade, autor, ctx)
    return registro


def criar_servico(
    db: Session, valores: dict[str, Any], autor: bytes, ctx: ContextoRequisicao
) -> ServicoSaude:
    registro = ServicoSaude(**valores)
    _inserir(db, registro)
    _auditar(db, Evento.CATALOG_CREATED, SERVICOS, registro.id_servico, autor, ctx)
    return registro


def criar_cid(
    db: Session,
    settings: Settings,
    codigo: str,
    descricao: str,
    autor: bytes,
    ctx: ContextoRequisicao,
) -> Cid:
    cid_hash = hash_busca(settings.chave_hmac, FinalidadeHash.CID, codigo)
    registro = Cid(cid_hash=cid_hash, cid=codigo, descricao=descricao)
    _inserir(db, registro)
    _auditar(db, Evento.CATALOG_CREATED, CIDS, codigo, autor, ctx)
    return registro


def importar_cids(
    db: Session, settings: Settings, pares: Sequence[tuple[str, str]], ctx: ContextoRequisicao
) -> ResultadoImportacao:
    """Carga do catálogo (ADR-0020): não altera códigos existentes; um evento por importação."""
    linhas = [
        {
            "cid_hash": hash_busca(settings.chave_hmac, FinalidadeHash.CID, codigo),
            "cid": codigo,
            "descricao": descricao,
        }
        for codigo, descricao in pares
    ]
    criados = sum(
        cadastro_repo.inserir_cids_novos(db, linhas[inicio : inicio + LOTE_IMPORTACAO])
        for inicio in range(0, len(linhas), LOTE_IMPORTACAO)
    )
    resultado = ResultadoImportacao(criados=criados, ignorados=len(linhas) - criados)
    auditoria.registrar(
        db,
        Evento.CATALOG_IMPORTED,
        ctx,
        resumo={
            "recurso": CIDS.recurso,
            "criados": resultado.criados,
            "ignorados": resultado.ignorados,
        },
    )
    return resultado


def atualizar_unidade(
    db: Session,
    chave: int,
    alteracoes: dict[str, Any],
    autor: bytes,
    ctx: ContextoRequisicao,
) -> UnidadeSaude | None:
    """Só valida o tipo se ele mudou: unidade com tipo inativo continua editável."""
    atual = cadastro_repo.buscar(db, UnidadeSaude, chave, travar=True)
    if atual is None:
        return None
    novo_tipo = alteracoes.get("id_tipo_unidade", atual.id_tipo_unidade)
    if novo_tipo != atual.id_tipo_unidade:
        _validar_tipo_ativo(db, novo_tipo)
    return atualizar(db, UNIDADES, chave, alteracoes, autor, ctx)


def atualizar[R: Registro](
    db: Session,
    catalogo: Catalogo[R],
    chave: Chave,
    alteracoes: dict[str, Any],
    autor: bytes,
    ctx: ContextoRequisicao,
) -> R | None:
    registro = cadastro_repo.buscar(db, catalogo.modelo, chave, travar=True)
    if registro is None:
        return None
    for campo, valor in alteracoes.items():
        setattr(registro, campo, valor)
    _gravar(db, registro)
    _auditar(
        db,
        Evento.CATALOG_UPDATED,
        catalogo,
        _identificador(registro),
        autor,
        ctx,
        campos=sorted(alteracoes),
    )
    return registro


def alterar_status[R: Registro](
    db: Session,
    catalogo: Catalogo[R],
    chave: Chave,
    *,
    ativo: bool,
    autor: bytes,
    ctx: ContextoRequisicao,
) -> R | None:
    """Sem mudança, não audita. Devolve None se o registro não existe."""
    registro = cadastro_repo.buscar(db, catalogo.modelo, chave, travar=True)
    if registro is None:
        return None
    novo = "ativo" if ativo else "inativo"
    if registro.status == novo:
        return registro
    if not ativo:
        _garantir_sem_uso(db, registro)
    registro.status = novo
    _gravar(db, registro)
    evento = Evento.CATALOG_REACTIVATED if ativo else Evento.CATALOG_DEACTIVATED
    _auditar(db, evento, catalogo, _identificador(registro), autor, ctx)
    return registro


def validar_unidade_ativa(db: Session, id_unidade: int) -> None:
    """Para vincular um usuário: a unidade precisa existir e estar ativa."""
    unidade = cadastro_repo.buscar(db, UnidadeSaude, id_unidade)
    if unidade is None or unidade.status != "ativo":
        raise UnidadeInvalida


def nome_da_unidade(db: Session, id_unidade: int | None) -> str | None:
    if id_unidade is None:
        return None
    unidade = cadastro_repo.buscar(db, UnidadeSaude, id_unidade)
    return None if unidade is None else unidade.nome


# --- Apoio -------------------------------------------------------------------------------


def _validar_tipo_ativo(db: Session, id_tipo_unidade: int) -> None:
    tipo = cadastro_repo.buscar(db, TipoUnidade, id_tipo_unidade)
    if tipo is None or tipo.status != "ativo":
        raise TipoInvalido


def _garantir_sem_uso(db: Session, registro: Registro) -> None:
    if (
        isinstance(registro, UnidadeSaude)
        and cadastro_repo.usuarios_ativos_na_unidade(db, registro.id_unidade) > 0
    ):
        raise CadastroEmUso("Há usuários ativos nesta unidade: mova-os antes de inativar.")
    if (
        isinstance(registro, TipoUnidade)
        and cadastro_repo.unidades_ativas_do_tipo(db, registro.id_tipo_unidade) > 0
    ):
        raise CadastroEmUso("Há unidades ativas deste tipo: mude o tipo delas antes de inativar.")


def _inserir(db: Session, registro: Registro) -> None:
    try:
        with db.begin_nested():
            cadastro_repo.inserir(db, registro)
    except IntegrityError:
        raise CadastroDuplicado from None
    db.refresh(registro)


def _gravar(db: Session, registro: Registro) -> None:
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        raise CadastroDuplicado from None
    db.refresh(registro)


def _identificador(registro: Registro) -> int | str:
    if isinstance(registro, TipoUnidade):
        return registro.id_tipo_unidade
    if isinstance(registro, UnidadeSaude):
        return registro.id_unidade
    if isinstance(registro, ServicoSaude):
        return registro.id_servico
    return registro.cid


def _auditar[R: Registro](
    db: Session,
    evento: Evento,
    catalogo: Catalogo[R],
    identificador: int | str,
    autor: bytes,
    ctx: ContextoRequisicao,
    *,
    campos: list[str] | None = None,
) -> None:
    resumo: dict[str, Any] = {"recurso": catalogo.recurso, "id": identificador}
    if campos is not None:
        resumo["campos"] = campos
    auditoria.registrar(db, evento, ctx, cpf_usuario_hash=autor, resumo=resumo)
