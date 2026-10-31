"""OCI e navegação (RF-12, ADR-0025): o vínculo entre paciente e CID é dado de saúde.

Alcance por unidade em cada operação: sem oci:todas_unidades, o usuário só alcança OCIs com alguma
navegação na própria unidade, e só marca a navegação da própria unidade. Fora do alcance, a OCI é
tratada como inexistente e a tentativa fica no log. O resultado é cifrado (envelope por registro),
e nenhum dado clínico vai para o log: só quem fez, sobre qual paciente e OCI, e os campos alterados.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.crypto import (
    DekCifrada,
    ErroCriptografia,
    FinalidadeHash,
    abrir_dek,
    cifrar_campo,
    decifrar_campo,
    gerar_dek,
    hash_busca,
)
from app.models import Cid, Oci, OciNavegacao, Paciente, ServicoSaude, TipoOci, UnidadeSaude
from app.repositories import cadastro as cadastro_repo
from app.repositories import oci as oci_repo
from app.repositories import paciente as paciente_repo
from app.repositories import usuario as usuario_repo
from app.services import auditoria, autorizacao
from app.services import paciente as paciente_service
from app.services.auditoria import ContextoRequisicao, Evento
from app.services.autorizacao import Permissao
from app.services.cadastro import CidInvalido, ServicoInvalido, TipoInvalido, UnidadeInvalida

TAMANHO_PAGINA = 20
_TABELA = "oci"
_SITUACOES_DA_NAVEGACAO = frozenset({"realizado", "faltou", "cancelado"})


class PacienteIndisponivel(Exception):
    def __init__(self) -> None:
        super().__init__("Paciente não encontrado ou inativo.")


class OciDuplicada(Exception):
    def __init__(self) -> None:
        super().__init__("Este paciente já tem uma OCI aberta deste tipo.")


class OciEncerrada(Exception):
    def __init__(self) -> None:
        super().__init__("Esta OCI já foi encerrada.")


class NavegacaoEncerrada(Exception):
    def __init__(self) -> None:
        super().__init__("Esta etapa já foi encerrada: registre uma nova.")


class ForaDoAlcance(Exception):
    """Usuário sem alcance sobre a unidade: a rota responde 403 ou 404, sem detalhar."""


@dataclass(frozen=True)
class Alcance:
    todas_as_unidades: bool
    unidade: int | None  # None sem alcance global: o usuário não alcança nenhuma OCI

    def inclui(self, id_unidade: int) -> bool:
        return self.todas_as_unidades or self.unidade == id_unidade


@dataclass(frozen=True)
class FiltrosOci:
    status: str | None = None
    id_tipo_oci: int | None = None
    id_unidade: int | None = None
    cpf: str | None = field(default=None, repr=False)
    atrasadas: bool = False


@dataclass(frozen=True)
class NovaOci:
    cpf: str = field(repr=False)
    id_tipo_oci: int
    cid_hash: bytes
    id_unidade: int
    id_servico: int
    data_hora: datetime


@dataclass(frozen=True)
class DadosPessoais:
    id_publico: uuid.UUID
    nome: str | None = field(repr=False)
    cpf: str | None = field(repr=False)


@dataclass(frozen=True)
class PaginaOci:
    itens: list[tuple[Oci, DadosPessoais]]
    proximo: uuid.UUID | None


@dataclass(frozen=True)
class DetalheOci:
    oci: Oci
    paciente: DadosPessoais
    resultado: str | None = field(repr=False)
    alcance: Alcance


def alcance_de(db: Session, autor: bytes) -> Alcance:
    """Lido a cada requisição: uma mudança de grupo ou unidade vale na hora."""
    if autorizacao.tem_permissao(db, autor, Permissao.OCI_TODAS_UNIDADES):
        return Alcance(todas_as_unidades=True, unidade=None)
    usuario = usuario_repo.buscar(db, autor)
    return Alcance(todas_as_unidades=False, unidade=usuario.id_unidade if usuario else None)


def opcoes_de_abertura(
    db: Session, autor: bytes
) -> tuple[list[TipoOci], list[UnidadeSaude], list[UnidadeSaude]]:
    """Tipos ativos, unidades ativas e as unidades em que o usuário pode abrir uma OCI."""
    alcance = alcance_de(db, autor)
    unidades = cadastro_repo.ativos(db, UnidadeSaude, 1000)
    return (
        cadastro_repo.ativos_tipo_oci(db, 1000),
        unidades,
        [u for u in unidades if alcance.inclui(u.id_unidade)],
    )


def cids_do_tipo(db: Session, id_tipo_oci: int) -> list[Cid]:
    return oci_repo.cids_ativos_do_tipo(db, id_tipo_oci)


def servicos_da_unidade(db: Session, id_unidade: int) -> list[ServicoSaude]:
    return oci_repo.servicos_ativos_da_unidade(db, id_unidade)


def abrir(
    db: Session,
    settings: Settings,
    dados: NovaOci,
    autor: bytes,
    ctx: ContextoRequisicao,
    agora: datetime,
) -> DetalheOci:
    """Abre a OCI com a primeira etapa; é essa etapa que define em qual unidade ela é vista."""
    alcance = alcance_de(db, autor)
    if not alcance.inclui(dados.id_unidade):
        _auditar_fora_do_alcance(db, autor, ctx, resumo={"id_unidade": dados.id_unidade})
        raise ForaDoAlcance
    cpf_hash = hash_busca(settings.chave_hmac, FinalidadeHash.CPF, dados.cpf)
    paciente = paciente_repo.buscar_por_cpf_hash(db, cpf_hash)
    if paciente is None or paciente.status != "ativo":
        raise PacienteIndisponivel
    tipo = cadastro_repo.buscar(db, TipoOci, dados.id_tipo_oci)
    if tipo is None or tipo.status != "ativo":
        raise TipoInvalido
    if not oci_repo.cid_do_tipo(db, tipo.id_tipo_oci, dados.cid_hash):
        raise CidInvalido
    _validar_etapa(db, dados.id_unidade, dados.id_servico)

    oci = Oci(
        id_publico=uuid.uuid4(),
        id_tipo_oci=tipo.id_tipo_oci,
        cpf_paciente_hash=cpf_hash,
        cid_hash=dados.cid_hash,
        prazo_em=agora + timedelta(days=tipo.prazo_diagnostico),
    )
    try:
        with db.begin_nested():
            oci_repo.inserir(db, oci)
    except IntegrityError:
        raise OciDuplicada from None
    oci_repo.inserir_navegacao(
        db,
        OciNavegacao(
            id_oci=oci.id_oci,
            id_unidade=dados.id_unidade,
            id_servico=dados.id_servico,
            data_hora=dados.data_hora,
        ),
    )
    db.refresh(oci)
    _auditar(db, Evento.OCI_CREATED, oci, autor, ctx)
    return _detalhe(settings, db, oci, alcance)


def listar(
    db: Session,
    settings: Settings,
    filtros: FiltrosOci,
    depois: uuid.UUID | None,
    autor: bytes,
    ctx: ContextoRequisicao,
    agora: datetime,
) -> PaginaOci:
    alcance = alcance_de(db, autor)
    if not alcance.todas_as_unidades and alcance.unidade is None:
        return PaginaOci(itens=[], proximo=None)  # sem unidade, não alcança nenhuma OCI
    referencia = None
    if depois is not None:
        referencia = oci_repo.buscar_por_id(db, depois)
        if referencia is None:  # cursor que não veio desta API
            return PaginaOci(itens=[], proximo=None)
    cpf_hash = (
        None
        if filtros.cpf is None
        else hash_busca(settings.chave_hmac, FinalidadeHash.CPF, filtros.cpf)
    )
    linhas = oci_repo.listar(
        db,
        limite=TAMANHO_PAGINA + 1,
        depois=referencia,
        unidade_do_alcance=None if alcance.todas_as_unidades else alcance.unidade,
        status=filtros.status,
        id_tipo_oci=filtros.id_tipo_oci,
        id_unidade=filtros.id_unidade,
        cpf_paciente_hash=cpf_hash,
        atrasadas_em=agora if filtros.atrasadas else None,
    )
    pagina = linhas[:TAMANHO_PAGINA]
    pacientes = {
        p.cpf_hash: p
        for p in paciente_repo.buscar_varios(db, {o.cpf_paciente_hash for o in pagina})
    }
    resumo: dict[str, object] = {
        "recurso": _TABELA,
        "origem": "lista",
        "ocis": [str(o.id_publico) for o in pagina],
    }
    if cpf_hash is not None:
        resumo["paciente"] = cpf_hash.hex()[:12]
    auditoria.registrar(
        db, Evento.SENSITIVE_DATA_ACCESS, ctx, cpf_usuario_hash=autor, resumo=resumo
    )
    return PaginaOci(
        itens=[(o, _dados_pessoais(settings, pacientes[o.cpf_paciente_hash])) for o in pagina],
        proximo=pagina[-1].id_publico if len(linhas) > TAMANHO_PAGINA else None,
    )


def obter(
    db: Session,
    settings: Settings,
    id_publico: uuid.UUID,
    autor: bytes,
    ctx: ContextoRequisicao,
) -> DetalheOci | None:
    oci, alcance = _alcancavel(db, id_publico, autor, ctx)
    if oci is None:
        return None
    _auditar(db, Evento.SENSITIVE_DATA_ACCESS, oci, autor, ctx, recurso=_TABELA, origem="consulta")
    return _detalhe(settings, db, oci, alcance)


def alterar_cid(
    db: Session,
    settings: Settings,
    id_publico: uuid.UUID,
    cid_hash: bytes,
    autor: bytes,
    ctx: ContextoRequisicao,
) -> DetalheOci | None:
    oci, alcance = _alcancavel(db, id_publico, autor, ctx, travar=True)
    if oci is None:
        return None
    _exigir_aberta(oci)
    if cid_hash != oci.cid_hash:
        if not oci_repo.cid_do_tipo(db, oci.id_tipo_oci, cid_hash):
            raise CidInvalido
        oci.cid_hash = cid_hash
        db.flush()
        db.refresh(oci)
        _auditar(db, Evento.OCI_UPDATED, oci, autor, ctx, campos=["cid"])
    return _detalhe(settings, db, oci, alcance)


def concluir(
    db: Session,
    settings: Settings,
    id_publico: uuid.UUID,
    resultado: str,
    resultado_cid_hash: bytes | None,
    autor: bytes,
    ctx: ContextoRequisicao,
) -> DetalheOci | None:
    oci, alcance = _alcancavel(db, id_publico, autor, ctx, travar=True)
    if oci is None:
        return None
    _exigir_aberta(oci)
    if resultado_cid_hash is not None and not cadastro_repo.hashes_de_cids_ativos_entre(
        db, {resultado_cid_hash}
    ):
        raise CidInvalido
    dek, dek_cifrada = gerar_dek(settings.keyring)
    oci.resultado_cripto = cifrar_campo(
        dek,
        resultado,
        tabela=_TABELA,
        coluna="resultado_cripto",
        id_registro=oci.id_publico.bytes,
    )
    oci.dek_cripto = dek_cifrada.dek_cripto
    oci.kek_versao = dek_cifrada.kek_versao
    oci.resultado_cid_hash = resultado_cid_hash
    oci.status = "concluida"
    db.flush()
    db.refresh(oci)
    _auditar(db, Evento.OCI_CONCLUDED, oci, autor, ctx)
    return _detalhe(settings, db, oci, alcance)


def cancelar(
    db: Session,
    settings: Settings,
    id_publico: uuid.UUID,
    autor: bytes,
    ctx: ContextoRequisicao,
) -> DetalheOci | None:
    """Exclusão lógica: o histórico da OCI e o log são preservados."""
    oci, alcance = _alcancavel(db, id_publico, autor, ctx, travar=True)
    if oci is None:
        return None
    _exigir_aberta(oci)
    oci.status = "cancelada"
    db.flush()
    db.refresh(oci)
    _auditar(db, Evento.OCI_CANCELED, oci, autor, ctx)
    return _detalhe(settings, db, oci, alcance)


def incluir_etapa(
    db: Session,
    settings: Settings,
    id_publico: uuid.UUID,
    id_unidade: int,
    id_servico: int,
    data_hora: datetime,
    autor: bytes,
    ctx: ContextoRequisicao,
) -> DetalheOci | None:
    """Encaminhar para outra unidade é o objetivo da navegação: ela passa a ver esta OCI."""
    oci, alcance = _alcancavel(db, id_publico, autor, ctx, travar=True)
    if oci is None:
        return None
    _exigir_aberta(oci)
    _validar_etapa(db, id_unidade, id_servico)
    oci_repo.inserir_navegacao(
        db,
        OciNavegacao(
            id_oci=oci.id_oci, id_unidade=id_unidade, id_servico=id_servico, data_hora=data_hora
        ),
    )
    db.refresh(oci)
    _auditar(
        db,
        Evento.NAVIGATION_CREATED,
        oci,
        autor,
        ctx,
        id_unidade=id_unidade,
        id_servico=id_servico,
    )
    return _detalhe(settings, db, oci, alcance)


def alterar_etapa(
    db: Session,
    settings: Settings,
    id_publico: uuid.UUID,
    id_navegacao: int,
    status: str | None,
    data_hora: datetime | None,
    autor: bytes,
    ctx: ContextoRequisicao,
) -> DetalheOci | None:
    """Só quem está na unidade da etapa a marca, e só enquanto ela está agendada."""
    oci, alcance = _alcancavel(db, id_publico, autor, ctx, travar=True)
    if oci is None:
        return None
    _exigir_aberta(oci)
    etapa = oci_repo.buscar_navegacao(db, oci.id_oci, id_navegacao)
    if etapa is None:
        return None
    if not alcance.inclui(etapa.id_unidade):
        _auditar_fora_do_alcance(db, autor, ctx, resumo={"id_oci": oci.id_oci})
        raise ForaDoAlcance
    if etapa.status != "agendado":
        raise NavegacaoEncerrada
    campos = []
    if status is not None:
        etapa.status = status
        campos.append("status")
    if data_hora is not None:
        etapa.data_hora = data_hora
        campos.append("data_hora")
    db.flush()
    db.refresh(oci)
    _auditar(
        db,
        Evento.NAVIGATION_UPDATED,
        oci,
        autor,
        ctx,
        campos=campos,
        id_navegacao=id_navegacao,
        status_etapa=etapa.status,
    )
    return _detalhe(settings, db, oci, alcance)


def pode_marcar(alcance: Alcance, etapa: OciNavegacao, oci: Oci) -> bool:
    return (
        oci.status == "aberta" and etapa.status == "agendado" and alcance.inclui(etapa.id_unidade)
    )


# --- Apoio -------------------------------------------------------------------------------


def _alcancavel(
    db: Session,
    id_publico: uuid.UUID,
    autor: bytes,
    ctx: ContextoRequisicao,
    *,
    travar: bool = False,
) -> tuple[Oci | None, Alcance]:
    alcance = alcance_de(db, autor)
    oci = oci_repo.buscar_por_id(db, id_publico, travar=travar)
    if oci is None:
        return None, alcance
    if alcance.todas_as_unidades or (
        alcance.unidade is not None and oci_repo.esta_na_unidade(db, oci.id_oci, alcance.unidade)
    ):
        return oci, alcance
    # Mesma resposta de OCI inexistente, mas a tentativa fica registrada.
    _auditar_fora_do_alcance(
        db, autor, ctx, resumo={"id_oci": oci.id_oci}, cpf_paciente_hash=oci.cpf_paciente_hash
    )
    return None, alcance


def _exigir_aberta(oci: Oci) -> None:
    if oci.status != "aberta":
        raise OciEncerrada


def _validar_etapa(db: Session, id_unidade: int, id_servico: int) -> None:
    unidade = cadastro_repo.buscar(db, UnidadeSaude, id_unidade)
    if unidade is None or unidade.status != "ativo":
        raise UnidadeInvalida
    if id_servico not in {
        s.id_servico for s in oci_repo.servicos_ativos_da_unidade(db, id_unidade)
    }:
        raise ServicoInvalido


def _dados_pessoais(settings: Settings, paciente: Paciente) -> DadosPessoais:
    try:
        resumo = paciente_service.resumir(settings, paciente)
    except ErroCriptografia:
        return DadosPessoais(id_publico=paciente.id_publico, nome=None, cpf=None)
    return DadosPessoais(id_publico=paciente.id_publico, nome=resumo.nome, cpf=resumo.cpf)


def _detalhe(settings: Settings, db: Session, oci: Oci, alcance: Alcance) -> DetalheOci:
    paciente = paciente_repo.buscar_por_cpf_hash(db, oci.cpf_paciente_hash)
    if paciente is None:  # pragma: no cover - garantido pela chave estrangeira
        raise PacienteIndisponivel
    return DetalheOci(
        oci=oci,
        paciente=_dados_pessoais(settings, paciente),
        resultado=_resultado(settings, oci),
        alcance=alcance,
    )


def _resultado(settings: Settings, oci: Oci) -> str | None:
    if oci.resultado_cripto is None or oci.dek_cripto is None or oci.kek_versao is None:
        return None
    dek = abrir_dek(settings.keyring, DekCifrada(oci.dek_cripto, oci.kek_versao))
    return decifrar_campo(
        dek,
        oci.resultado_cripto,
        tabela=_TABELA,
        coluna="resultado_cripto",
        id_registro=oci.id_publico.bytes,
    )


def _auditar(
    db: Session,
    evento: Evento,
    oci: Oci,
    autor: bytes,
    ctx: ContextoRequisicao,
    **resumo: object,
) -> None:
    auditoria.registrar(
        db,
        evento,
        ctx,
        cpf_usuario_hash=autor,
        cpf_paciente_hash=oci.cpf_paciente_hash,
        id_oci=oci.id_oci,
        resumo=resumo or None,
    )


def _auditar_fora_do_alcance(
    db: Session,
    autor: bytes,
    ctx: ContextoRequisicao,
    *,
    resumo: dict[str, object],
    cpf_paciente_hash: bytes | None = None,
) -> None:
    auditoria.registrar(
        db,
        Evento.ACCESS_DENIED,
        ctx,
        cpf_usuario_hash=autor,
        cpf_paciente_hash=cpf_paciente_hash,
        resumo={"motivo": "fora_da_unidade", **resumo},
    )
