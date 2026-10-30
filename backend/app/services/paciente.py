"""Cadastro de pacientes (RF-03): dados pessoais só cifrados (ADR-0004), CPF imutável.

Toda leitura de dados do paciente é auditada (sensitive_data_access) com o cpf_paciente_hash;
nenhum dado em claro vai para o log. A exclusão é lógica (status), ver ADR-0011.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.crypto import (
    DekCifrada,
    FinalidadeHash,
    abrir_dek,
    cifrar_campo,
    decifrar_campo,
    gerar_dek,
    hash_busca,
)
from app.models import Paciente
from app.repositories import paciente as paciente_repo
from app.services import auditoria
from app.services.auditoria import ContextoRequisicao, Evento

_TABELA = "paciente"
TAMANHO_PAGINA = 20  # fixo: o cliente não escolhe quantos registros decifrar por requisição


class ErroCadastroPaciente(Exception):
    def __init__(self) -> None:
        super().__init__("Não foi possível cadastrar o paciente.")


class PacienteInativo(Exception):
    pass


@dataclass(frozen=True)
class NovoPaciente:
    cpf: str  # só dígitos, já validado
    nome: str = field(repr=False)
    data_nascimento: date = field(repr=False)
    email: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class DadosPaciente:
    id_publico: uuid.UUID
    cpf: str = field(repr=False)
    nome: str = field(repr=False)
    data_nascimento: date = field(repr=False)
    email: str | None = field(repr=False)
    status: str
    criado_em: datetime
    atualizado_em: datetime


@dataclass(frozen=True)
class ResumoPaciente:
    """Só o necessário para reconhecer o paciente na lista (minimização, ADR-0014)."""

    id_publico: uuid.UUID
    cpf: str = field(repr=False)
    nome: str = field(repr=False)
    status: str


@dataclass(frozen=True)
class PaginaPacientes:
    itens: list[ResumoPaciente]
    proximo: uuid.UUID | None


@dataclass(frozen=True)
class Alteracoes:
    """Só os campos enviados; email=None em `campos` significa remover o e-mail."""

    campos: frozenset[str]  # subconjunto de {nome, data_nascimento, email}
    nome: str | None = field(default=None, repr=False)
    data_nascimento: date | None = field(default=None, repr=False)
    email: str | None = field(default=None, repr=False)


def cadastrar(
    db: Session,
    settings: Settings,
    dados: NovoPaciente,
    autor: bytes,
    ctx: ContextoRequisicao,
) -> DadosPaciente:
    cpf_hash = hash_busca(settings.chave_hmac, FinalidadeHash.CPF, dados.cpf)
    if paciente_repo.existe(db, cpf_hash):
        raise ErroCadastroPaciente
    dek, dek_cifrada = gerar_dek(settings.keyring)
    paciente = Paciente(
        cpf_hash=cpf_hash,
        id_publico=uuid.uuid4(),
        cpf_cripto=_cifrar(dek, cpf_hash, "cpf_cripto", dados.cpf),
        nome_cripto=_cifrar(dek, cpf_hash, "nome_cripto", dados.nome),
        data_nascimento_cripto=_cifrar(
            dek, cpf_hash, "data_nascimento_cripto", dados.data_nascimento.isoformat()
        ),
        email_cripto=_cifrar_opcional(dek, cpf_hash, "email_cripto", dados.email),
        dek_cripto=dek_cifrada.dek_cripto,
        kek_versao=dek_cifrada.kek_versao,
    )
    try:
        with db.begin_nested():
            paciente_repo.inserir(db, paciente)
    except IntegrityError:
        raise ErroCadastroPaciente from None
    db.refresh(paciente)
    auditoria.registrar(
        db, Evento.PATIENT_CREATED, ctx, cpf_usuario_hash=autor, cpf_paciente_hash=cpf_hash
    )
    return _decifrar(settings, paciente)


def buscar_por_cpf(
    db: Session, settings: Settings, cpf: str, autor: bytes, ctx: ContextoRequisicao
) -> DadosPaciente | None:
    cpf_hash = hash_busca(settings.chave_hmac, FinalidadeHash.CPF, cpf)
    paciente = paciente_repo.buscar_por_cpf_hash(db, cpf_hash)
    auditoria.registrar(
        db,
        Evento.PATIENT_SEARCH,
        ctx,
        cpf_usuario_hash=autor,
        cpf_paciente_hash=cpf_hash,
        resumo={"encontrado": paciente is not None},
    )
    if paciente is None:
        return None
    return _ler(db, settings, paciente, autor, ctx, origem="busca")


def obter(
    db: Session, settings: Settings, id_publico: uuid.UUID, autor: bytes, ctx: ContextoRequisicao
) -> DadosPaciente | None:
    paciente = paciente_repo.buscar_por_id(db, id_publico)
    if paciente is None:
        return None
    return _ler(db, settings, paciente, autor, ctx, origem="consulta")


def listar(
    db: Session,
    settings: Settings,
    depois: uuid.UUID | None,
    autor: bytes,
    ctx: ContextoRequisicao,
) -> PaginaPacientes:
    """Uma página da lista. Decifra só nome e CPF, e audita quais pacientes foram exibidos."""
    referencia = None
    if depois is not None:
        referencia = paciente_repo.buscar_por_id(db, depois)
        if referencia is None:  # cursor que não veio desta API
            return PaginaPacientes(itens=[], proximo=None)
    linhas = paciente_repo.listar(db, limite=TAMANHO_PAGINA + 1, depois=referencia)
    pagina = linhas[:TAMANHO_PAGINA]
    auditoria.registrar(
        db,
        Evento.SENSITIVE_DATA_ACCESS,
        ctx,
        cpf_usuario_hash=autor,
        resumo={
            "recurso": _TABELA,
            "origem": "lista",
            "pacientes": [str(p.id_publico) for p in pagina],
        },
    )
    return PaginaPacientes(
        itens=[_resumir(settings, p) for p in pagina],
        proximo=pagina[-1].id_publico if len(linhas) > TAMANHO_PAGINA else None,
    )


def atualizar(
    db: Session,
    settings: Settings,
    id_publico: uuid.UUID,
    alteracoes: Alteracoes,
    autor: bytes,
    ctx: ContextoRequisicao,
) -> DadosPaciente | None:
    paciente = paciente_repo.buscar_por_id(db, id_publico, travar=True)
    if paciente is None:
        return None
    if paciente.status != "ativo":
        raise PacienteInativo
    dek = _dek(settings, paciente)
    chave = paciente.cpf_hash
    if "nome" in alteracoes.campos and alteracoes.nome is not None:
        paciente.nome_cripto = _cifrar(dek, chave, "nome_cripto", alteracoes.nome)
    if "data_nascimento" in alteracoes.campos and alteracoes.data_nascimento is not None:
        paciente.data_nascimento_cripto = _cifrar(
            dek, chave, "data_nascimento_cripto", alteracoes.data_nascimento.isoformat()
        )
    if "email" in alteracoes.campos:
        paciente.email_cripto = _cifrar_opcional(dek, chave, "email_cripto", alteracoes.email)
    db.flush()
    db.refresh(paciente)
    auditoria.registrar(
        db,
        Evento.PATIENT_UPDATED,
        ctx,
        cpf_usuario_hash=autor,
        cpf_paciente_hash=chave,
        resumo={"campos": sorted(alteracoes.campos)},
    )
    return _decifrar(settings, paciente)


def alterar_status(
    db: Session, id_publico: uuid.UUID, *, ativo: bool, autor: bytes, ctx: ContextoRequisicao
) -> bool:
    """Inativa ou reativa. Devolve False se o paciente não existe; sem mudança não audita."""
    paciente = paciente_repo.buscar_por_id(db, id_publico, travar=True)
    if paciente is None:
        return False
    novo = "ativo" if ativo else "inativo"
    if paciente.status != novo:
        paciente.status = novo
        db.flush()
        evento = Evento.PATIENT_REACTIVATED if ativo else Evento.PATIENT_DEACTIVATED
        auditoria.registrar(
            db, evento, ctx, cpf_usuario_hash=autor, cpf_paciente_hash=paciente.cpf_hash
        )
    return True


# --- Apoio -------------------------------------------------------------------------------


def _ler(
    db: Session,
    settings: Settings,
    paciente: Paciente,
    autor: bytes,
    ctx: ContextoRequisicao,
    *,
    origem: str,
) -> DadosPaciente:
    dados = _decifrar(settings, paciente)
    auditoria.registrar(
        db,
        Evento.SENSITIVE_DATA_ACCESS,
        ctx,
        cpf_usuario_hash=autor,
        cpf_paciente_hash=paciente.cpf_hash,
        resumo={"recurso": _TABELA, "origem": origem},
    )
    return dados


def _dek(settings: Settings, paciente: Paciente) -> bytes:
    return abrir_dek(settings.keyring, DekCifrada(paciente.dek_cripto, paciente.kek_versao))


def _cifrar(dek: bytes, cpf_hash: bytes, coluna: str, valor: str) -> bytes:
    return cifrar_campo(dek, valor, tabela=_TABELA, coluna=coluna, id_registro=cpf_hash)


def _cifrar_opcional(dek: bytes, cpf_hash: bytes, coluna: str, valor: str | None) -> bytes | None:
    return None if valor is None else _cifrar(dek, cpf_hash, coluna, valor)


def _resumir(settings: Settings, paciente: Paciente) -> ResumoPaciente:
    dek = _dek(settings, paciente)
    chave = paciente.cpf_hash
    return ResumoPaciente(
        id_publico=paciente.id_publico,
        cpf=decifrar_campo(
            dek, paciente.cpf_cripto, tabela=_TABELA, coluna="cpf_cripto", id_registro=chave
        ),
        nome=decifrar_campo(
            dek, paciente.nome_cripto, tabela=_TABELA, coluna="nome_cripto", id_registro=chave
        ),
        status=paciente.status,
    )


def _decifrar(settings: Settings, paciente: Paciente) -> DadosPaciente:
    dek = _dek(settings, paciente)

    def campo(blob: bytes, coluna: str) -> str:
        return decifrar_campo(
            dek, blob, tabela=_TABELA, coluna=coluna, id_registro=paciente.cpf_hash
        )

    return DadosPaciente(
        id_publico=paciente.id_publico,
        cpf=campo(paciente.cpf_cripto, "cpf_cripto"),
        nome=campo(paciente.nome_cripto, "nome_cripto"),
        data_nascimento=date.fromisoformat(
            campo(paciente.data_nascimento_cripto, "data_nascimento_cripto")
        ),
        email=None
        if paciente.email_cripto is None
        else campo(paciente.email_cripto, "email_cripto"),
        status=paciente.status,
        criado_em=paciente.criado_em,
        atualizado_em=paciente.atualizado_em,
    )
