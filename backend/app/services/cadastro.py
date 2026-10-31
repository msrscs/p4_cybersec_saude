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
from app.models import AgendaServico, Cid, ServicoSaude, TipoOci, TipoUnidade, UnidadeSaude
from app.repositories import agenda as agenda_repo
from app.repositories import cadastro as cadastro_repo
from app.repositories.cadastro import Chave, Ordem, Registro
from app.services import auditoria
from app.services.auditoria import ContextoRequisicao, Evento

TAMANHO_PAGINA = 20
LIMITE_OPCOES = 1000
LOTE_IMPORTACAO = 500
LIMITE_BUSCA_CID = 20


class CadastroDuplicado(Exception):
    def __init__(self) -> None:
        super().__init__("Já existe um cadastro com esses dados.")


class CadastroEmUso(Exception):
    """A mensagem é exibida ao administrador e diz o que fazer antes de inativar."""


class AgendaSobreposta(Exception):
    def __init__(self) -> None:
        super().__init__("Já existe agenda neste horário para esta unidade e serviço.")


class CidInvalido(Exception):
    def __init__(self) -> None:
        super().__init__("CID inválido.")


class AgendaInvalida(Exception):
    def __init__(self) -> None:
        super().__init__("O horário final deve ser depois do inicial e caber um atendimento.")


class ServicoInvalido(Exception):
    def __init__(self) -> None:
        super().__init__("Serviço inválido.")


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
        UnidadeSaude.servicos.any(_contem(ServicoSaude.nome)(termo)),
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
AGENDAS = Catalogo(
    "agenda_servico",
    AgendaServico,
    AgendaServico.id_agenda,
    lambda termo: or_(
        AgendaServico.unidade.has(_contem(UnidadeSaude.nome)(termo)),
        AgendaServico.servico.has(_contem(ServicoSaude.nome)(termo)),
    ),
)
TIPOS_OCI = Catalogo("tipo_oci", TipoOci, func.lower(TipoOci.tipo_oci), _contem(TipoOci.tipo_oci))


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
    return cadastro_repo.ativos(db, UnidadeSaude, LIMITE_OPCOES)


def opcoes_de_tipo(db: Session) -> list[TipoUnidade]:
    return cadastro_repo.ativos(db, TipoUnidade, LIMITE_OPCOES)


def opcoes_de_servico(db: Session) -> list[ServicoSaude]:
    return cadastro_repo.ativos(db, ServicoSaude, LIMITE_OPCOES)


def opcoes_de_cid(db: Session, busca: str) -> list[Cid]:
    return cadastro_repo.cids_ativos(db, CIDS.condicao_de_busca(busca), LIMITE_BUSCA_CID)


def criar_tipo_oci(
    db: Session, valores: dict[str, Any], autor: bytes, ctx: ContextoRequisicao
) -> TipoOci:
    campos = dict(valores)
    cids = {bytes.fromhex(c) for c in campos.pop("cids", ())}
    _validar_cids_ativos(db, cids)
    registro = TipoOci(**campos)
    _inserir(db, registro)
    cadastro_repo.incluir_cids(db, registro.id_tipo_oci, cids)
    db.refresh(registro)
    extra = {"cids_adicionados": cadastro_repo.codigos_dos_cids(db, cids)} if cids else None
    _auditar(db, Evento.CATALOG_CREATED, TIPOS_OCI, registro.id_tipo_oci, autor, ctx, extra=extra)
    return registro


def atualizar_tipo_oci(
    db: Session,
    chave: int,
    alteracoes: dict[str, Any],
    autor: bytes,
    ctx: ContextoRequisicao,
) -> TipoOci | None:
    atual = cadastro_repo.buscar(db, TipoOci, chave, travar=True)
    if atual is None:
        return None
    campos = dict(alteracoes)
    extra = None
    if "cids" in campos:
        extra = _aplicar_cids(db, chave, {bytes.fromhex(c) for c in campos.pop("cids")})
    if not campos and extra is None:
        return atual  # só CIDs, e nada mudou: sem evento
    return atualizar(db, TIPOS_OCI, chave, campos, autor, ctx, extra=extra)


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
    campos = dict(valores)
    servicos = set(campos.pop("servicos", ()))
    _validar_tipo_ativo(db, campos["id_tipo_unidade"])
    _validar_servicos_ativos(db, servicos)
    registro = UnidadeSaude(**campos)
    _inserir(db, registro)
    cadastro_repo.incluir_servicos(db, registro.id_unidade, servicos)
    db.refresh(registro)
    _auditar(
        db,
        Evento.CATALOG_CREATED,
        UNIDADES,
        registro.id_unidade,
        autor,
        ctx,
        extra={"servicos_adicionados": sorted(servicos)} if servicos else None,
    )
    return registro


def criar_servico(
    db: Session, valores: dict[str, Any], autor: bytes, ctx: ContextoRequisicao
) -> ServicoSaude:
    campos = dict(valores)
    cids = {bytes.fromhex(c) for c in campos.pop("cids", ())}
    _validar_cids_ativos(db, cids)
    registro = ServicoSaude(**campos)
    _inserir(db, registro)
    cadastro_repo.incluir_cids_no_servico(db, registro.id_servico, cids)
    db.refresh(registro)
    extra = {"cids_adicionados": cadastro_repo.codigos_dos_cids(db, cids)} if cids else None
    _auditar(db, Evento.CATALOG_CREATED, SERVICOS, registro.id_servico, autor, ctx, extra=extra)
    return registro


def atualizar_servico(
    db: Session,
    chave: int,
    alteracoes: dict[str, Any],
    autor: bytes,
    ctx: ContextoRequisicao,
) -> ServicoSaude | None:
    atual = cadastro_repo.buscar(db, ServicoSaude, chave, travar=True)
    if atual is None:
        return None
    campos = dict(alteracoes)
    extra = None
    if "cids" in campos:
        extra = _aplicar_cids_do_servico(db, chave, {bytes.fromhex(c) for c in campos.pop("cids")})
    if not campos and extra is None:
        return atual  # só CIDs, e nada mudou: sem evento
    return atualizar(db, SERVICOS, chave, campos, autor, ctx, extra=extra)


def criar_agenda(
    db: Session, valores: dict[str, Any], autor: bytes, ctx: ContextoRequisicao
) -> AgendaServico:
    _validar_agenda(db, valores, exceto=None)
    registro = AgendaServico(**valores)
    _inserir(db, registro)
    _auditar(db, Evento.CATALOG_CREATED, AGENDAS, registro.id_agenda, autor, ctx)
    return registro


def atualizar_agenda(
    db: Session,
    chave: int,
    alteracoes: dict[str, Any],
    autor: bytes,
    ctx: ContextoRequisicao,
) -> AgendaServico | None:
    """Valida o resultado final: os campos enviados somados aos que já estão gravados."""
    atual = cadastro_repo.buscar(db, AgendaServico, chave, travar=True)
    if atual is None:
        return None
    final = {
        campo: alteracoes.get(campo, getattr(atual, campo))
        for campo in (
            "id_unidade",
            "id_servico",
            "dia_semana",
            "hora_inicio",
            "hora_fim",
            "duracao_minutos",
        )
    }
    if final["hora_inicio"] >= final["hora_fim"]:
        raise AgendaInvalida
    _validar_agenda(db, final, exceto=chave)
    return atualizar(db, AGENDAS, chave, alteracoes, autor, ctx)


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
    """Só valida tipo e serviços novos: o que já está inativo não impede editar o resto."""
    atual = cadastro_repo.buscar(db, UnidadeSaude, chave, travar=True)
    if atual is None:
        return None
    campos = dict(alteracoes)
    novo_tipo = campos.get("id_tipo_unidade", atual.id_tipo_unidade)
    if novo_tipo != atual.id_tipo_unidade:
        _validar_tipo_ativo(db, novo_tipo)
    extra = None
    if "servicos" in campos:
        extra = _aplicar_servicos(db, chave, set(campos.pop("servicos")))
    if not campos and extra is None:
        return atual  # só serviços, e nada mudou: sem evento
    return atualizar(db, UNIDADES, chave, campos, autor, ctx, extra=extra)


def atualizar[R: Registro](
    db: Session,
    catalogo: Catalogo[R],
    chave: Chave,
    alteracoes: dict[str, Any],
    autor: bytes,
    ctx: ContextoRequisicao,
    *,
    extra: dict[str, Any] | None = None,
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
        extra=extra,
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


def _validar_servicos_ativos(db: Session, ids: set[int]) -> None:
    if ids and cadastro_repo.servicos_ativos_entre(db, ids) != ids:
        raise ServicoInvalido


def _aplicar_servicos(db: Session, id_unidade: int, desejados: set[int]) -> dict[str, Any] | None:
    """Deixa a unidade exatamente com esses serviços; devolve o que mudou, para o log."""
    atuais = cadastro_repo.ids_de_servicos_da_unidade(db, id_unidade)
    adicionados, removidos = desejados - atuais, atuais - desejados
    if not adicionados and not removidos:
        return None
    _validar_servicos_ativos(db, adicionados)
    cadastro_repo.incluir_servicos(db, id_unidade, adicionados)
    if removidos:
        cadastro_repo.remover_servicos(db, id_unidade, removidos)
    return {"servicos_adicionados": sorted(adicionados), "servicos_removidos": sorted(removidos)}


def _validar_cids_ativos(db: Session, hashes: set[bytes]) -> None:
    if hashes and cadastro_repo.hashes_de_cids_ativos_entre(db, hashes) != hashes:
        raise CidInvalido


def _aplicar_cids(db: Session, id_tipo_oci: int, desejados: set[bytes]) -> dict[str, Any] | None:
    """Deixa o tipo exatamente com esses CIDs; devolve os códigos que mudaram, para o log."""
    atuais = cadastro_repo.hashes_de_cids_do_tipo(db, id_tipo_oci)
    adicionados, removidos = desejados - atuais, atuais - desejados
    if not adicionados and not removidos:
        return None
    _validar_cids_ativos(db, adicionados)
    cadastro_repo.incluir_cids(db, id_tipo_oci, adicionados)
    if removidos:
        cadastro_repo.remover_cids(db, id_tipo_oci, removidos)
    return {
        "cids_adicionados": cadastro_repo.codigos_dos_cids(db, adicionados),
        "cids_removidos": cadastro_repo.codigos_dos_cids(db, removidos),
    }


def _aplicar_cids_do_servico(
    db: Session, id_servico: int, desejados: set[bytes]
) -> dict[str, Any] | None:
    atuais = cadastro_repo.hashes_de_cids_do_servico(db, id_servico)
    adicionados, removidos = desejados - atuais, atuais - desejados
    if not adicionados and not removidos:
        return None
    _validar_cids_ativos(db, adicionados)
    cadastro_repo.incluir_cids_no_servico(db, id_servico, adicionados)
    if removidos:
        cadastro_repo.remover_cids_do_servico(db, id_servico, removidos)
    return {
        "cids_adicionados": cadastro_repo.codigos_dos_cids(db, adicionados),
        "cids_removidos": cadastro_repo.codigos_dos_cids(db, removidos),
    }


def _validar_agenda(db: Session, valores: dict[str, Any], *, exceto: int | None) -> None:
    unidade = cadastro_repo.buscar(db, UnidadeSaude, valores["id_unidade"])
    if unidade is None or unidade.status != "ativo":
        raise UnidadeInvalida
    if not cadastro_repo.servico_na_unidade(db, valores["id_unidade"], valores["id_servico"]):
        raise ServicoInvalido
    minutos = (
        valores["hora_fim"].hour * 60
        + valores["hora_fim"].minute
        - valores["hora_inicio"].hour * 60
        - valores["hora_inicio"].minute
    )
    if minutos < valores["duracao_minutos"]:
        raise AgendaInvalida
    for outra in agenda_repo.outras_agendas_no_dia(
        db, valores["id_unidade"], valores["id_servico"], valores["dia_semana"], exceto
    ):
        if valores["hora_inicio"] < outra.hora_fim and outra.hora_inicio < valores["hora_fim"]:
            raise AgendaSobreposta


def _garantir_sem_uso(db: Session, registro: Registro) -> None:
    # OCI em andamento depende destes cadastros (ADR-0025).
    if isinstance(registro, TipoOci) and cadastro_repo.ocis_abertas_do_tipo(
        db, registro.id_tipo_oci
    ):
        raise CadastroEmUso("Há OCIs abertas deste tipo: encerre-as antes de inativar.")
    if isinstance(registro, Cid) and cadastro_repo.servicos_ativos_com_cid(db, registro.cid_hash):
        raise CadastroEmUso("Há serviços ativos com este CID: remova-o deles antes de inativar.")
    if isinstance(registro, Cid) and cadastro_repo.ocis_abertas_com_cid(db, registro.cid_hash):
        raise CadastroEmUso("Há OCIs abertas com este CID: encerre-as antes de inativar.")
    if isinstance(registro, UnidadeSaude) and cadastro_repo.etapas_agendadas_na_unidade(
        db, registro.id_unidade
    ):
        raise CadastroEmUso("Há etapas agendadas nesta unidade: encerre-as antes de inativar.")
    if isinstance(registro, ServicoSaude) and cadastro_repo.etapas_agendadas_com_servico(
        db, registro.id_servico
    ):
        raise CadastroEmUso("Há etapas agendadas com este serviço: encerre-as antes de inativar.")
    if (
        isinstance(registro, Cid)
        and cadastro_repo.tipos_oci_ativos_com_cid(db, registro.cid_hash) > 0
    ):
        raise CadastroEmUso(
            "Há tipos de OCI ativos com este CID: remova-o deles antes de inativar."
        )
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
    if (
        isinstance(registro, ServicoSaude)
        and cadastro_repo.unidades_ativas_com_servico(db, registro.id_servico) > 0
    ):
        raise CadastroEmUso(
            "Há unidades ativas com este serviço: remova-o delas antes de inativar."
        )


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
    if isinstance(registro, TipoOci):
        return registro.id_tipo_oci
    if isinstance(registro, AgendaServico):
        return registro.id_agenda
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
    extra: dict[str, Any] | None = None,
) -> None:
    resumo: dict[str, Any] = {"recurso": catalogo.recurso, "id": identificador}
    if campos is not None:
        resumo["campos"] = campos
    if extra:
        resumo.update(extra)
    auditoria.registrar(db, evento, ctx, cpf_usuario_hash=autor, resumo=resumo)
