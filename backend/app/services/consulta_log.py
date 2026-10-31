"""Consulta do log de auditoria (RF-04, ADR-0015): somente leitura, e a leitura é auditada.

O log guarda só hashes. Para quem tem log:ver_cpf (Administrador, ADR-0017), o CPF vem dos
cadastros de usuário e paciente, decifrado na hora de responder (ADR-0016), e nunca é gravado no
log; o Auditor vê só o hash truncado. Hash sem cadastro (ex.: login com CPF que não
existe) continua aparecendo como hash truncado. A integridade exibida é a da última verificação
feita pelo container `tarefas`; a API não recalcula a cadeia nem recebe a chave dos checkpoints
(ADR-0010).
"""

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.cpf import formatar_cpf
from app.core.crypto import ErroCriptografia, FinalidadeHash, hash_busca
from app.models import Log
from app.repositories import log as log_repo
from app.repositories import paciente as paciente_repo
from app.repositories import usuario as usuario_repo
from app.services import auditoria, autorizacao, paciente, usuario
from app.services.auditoria import ContextoRequisicao, Evento
from app.services.autorizacao import Permissao

TAMANHO_PAGINA = 50  # fixo: o cliente não escolhe quantos registros ler por requisição
_TAMANHO_HASH = 12


@dataclass(frozen=True)
class Filtros:
    de: datetime | None = None
    ate: datetime | None = None
    acao: str | None = None
    cpf: str | None = field(default=None, repr=False)
    antes: int | None = None


@dataclass(frozen=True)
class ItemLog:
    seq: int
    data_hora: datetime
    acao: str
    ip_origem: str | None
    request_id: str | None
    usuario: str | None
    paciente: str | None
    usuario_cpf: str | None = field(repr=False)
    paciente_cpf: str | None = field(repr=False)
    id_oci: int | None
    pacientes_lista: list[str] = field(repr=False)  # eventos de lista: CPF ou hash de cada um
    hash: str
    resumo: dict[str, Any]


@dataclass(frozen=True)
class PaginaLog:
    itens: list[ItemLog]
    proximo: int | None


@dataclass(frozen=True)
class Integridade:
    total_registros: int
    verificada_em: datetime | None
    integra: bool | None  # None: ainda não houve verificação
    checkpoint_em: datetime | None
    checkpoint_seq: int | None


def acoes() -> list[str]:
    return sorted(evento.value for evento in Evento)


def consultar(
    db: Session, settings: Settings, filtros: Filtros, autor: bytes, ctx: ContextoRequisicao
) -> PaginaLog:
    cpf_hash = (
        None
        if filtros.cpf is None
        else hash_busca(settings.chave_hmac, FinalidadeHash.CPF, filtros.cpf)
    )
    linhas = log_repo.consultar(
        db,
        limite=TAMANHO_PAGINA + 1,
        antes=filtros.antes,
        de=filtros.de,
        ate=filtros.ate,
        acao=filtros.acao,
        cpf_usuario_hash=cpf_hash,
    )
    pagina = linhas[:TAMANHO_PAGINA]
    revelar = autorizacao.tem_permissao(db, autor, Permissao.LOG_VER_CPF)
    cpfs_usuarios = _cpfs_de_usuarios(db, settings, pagina) if revelar else {}
    listados = _pacientes_listados(db, pagina)
    cpfs_pacientes = _cpfs_de_pacientes(db, settings, pagina, listados) if revelar else {}
    resumo = _resumo_da_leitura(filtros, cpf_hash, pagina)
    resumo["cpfs_exibidos"] = len(cpfs_usuarios) + len(cpfs_pacientes)
    auditoria.registrar(db, Evento.LOG_READ, ctx, cpf_usuario_hash=autor, resumo=resumo)
    return PaginaLog(
        itens=[_item(linha, cpfs_usuarios, cpfs_pacientes, listados) for linha in pagina],
        proximo=pagina[-1].seq_cadeia if len(linhas) > TAMANHO_PAGINA else None,
    )


def integridade(db: Session) -> Integridade:
    verificacao = log_repo.ultimo_evento(
        db, (Evento.LOG_CHAIN_VERIFIED.value, Evento.LOG_CHAIN_BROKEN.value)
    )
    checkpoint = log_repo.ultimo_checkpoint(db)
    return Integridade(
        total_registros=log_repo.total_registros(db),
        verificada_em=verificacao.data_hora if verificacao else None,
        integra=verificacao.acao == Evento.LOG_CHAIN_VERIFIED.value if verificacao else None,
        checkpoint_em=checkpoint.criado_em if checkpoint else None,
        checkpoint_seq=checkpoint.seq_cadeia if checkpoint else None,
    )


def _cpfs_de_usuarios(db: Session, settings: Settings, pagina: list[Log]) -> dict[bytes, str]:
    hashes = {linha.cpf_usuario_hash for linha in pagina if linha.cpf_usuario_hash}
    registros = usuario_repo.buscar_varios(db, hashes) if hashes else []
    return _decifrar_cpfs(registros, lambda r: (r.cpf_hash, usuario.cpf_em_claro(settings, r)))


def _cpfs_de_pacientes(
    db: Session, settings: Settings, pagina: list[Log], listados: dict[uuid.UUID, bytes]
) -> dict[bytes, str]:
    hashes = {linha.cpf_paciente_hash for linha in pagina if linha.cpf_paciente_hash}
    hashes.update(listados.values())
    registros = paciente_repo.buscar_varios(db, hashes) if hashes else []
    return _decifrar_cpfs(registros, lambda r: (r.cpf_hash, paciente.cpf_em_claro(settings, r)))


def _ids_listados(linha: Log) -> list[uuid.UUID]:
    # Um evento de lista cobre vários pacientes: guarda os identificadores opacos no resumo, em
    # vez de um único cpf_paciente_hash (ADR-0018).
    if linha.acao != Evento.SENSITIVE_DATA_ACCESS.value:
        return []
    valores = linha.resumo_acessado.get("pacientes")
    if not isinstance(valores, list):
        return []
    ids = []
    for valor in valores:
        try:
            ids.append(uuid.UUID(str(valor)))
        except ValueError:
            continue
    return ids


def _pacientes_listados(db: Session, pagina: list[Log]) -> dict[uuid.UUID, bytes]:
    ids = {id_publico for linha in pagina for id_publico in _ids_listados(linha)}
    return paciente_repo.hashes_por_ids(db, ids) if ids else {}


def _decifrar_cpfs[T](
    registros: Iterable[T], decifrar: Callable[[T], tuple[bytes, str]]
) -> dict[bytes, str]:
    # Um cadastro adulterado não pode derrubar a tela de auditoria: a linha fica só com o hash.
    cpfs: dict[bytes, str] = {}
    for registro in registros:
        try:
            chave, cpf = decifrar(registro)
        except ErroCriptografia:
            continue
        cpfs[chave] = formatar_cpf(cpf)
    return cpfs


def _resumo_da_leitura(
    filtros: Filtros, cpf_hash: bytes | None, pagina: list[Log]
) -> dict[str, Any]:
    # Filtros e faixa da cadeia permitem saber o que foi visto; o CPF nunca vai para o log.
    resumo: dict[str, Any] = {"registros": len(pagina)}
    if pagina:
        resumo["seq_inicio"] = pagina[0].seq_cadeia
        resumo["seq_fim"] = pagina[-1].seq_cadeia
    if filtros.de is not None:
        resumo["de"] = filtros.de.isoformat()
    if filtros.ate is not None:
        resumo["ate"] = filtros.ate.isoformat()
    if filtros.acao is not None:
        resumo["acao"] = filtros.acao
    if cpf_hash is not None:
        resumo["usuario"] = _curto(cpf_hash)
    if filtros.antes is not None:
        resumo["antes"] = filtros.antes
    return resumo


def _item(
    linha: Log,
    usuarios: dict[bytes, str],
    pacientes: dict[bytes, str],
    listados: dict[uuid.UUID, bytes],
) -> ItemLog:
    hashes_listados = [listados[i] for i in _ids_listados(linha) if i in listados]
    return ItemLog(
        seq=linha.seq_cadeia,
        data_hora=linha.data_hora,
        acao=linha.acao,
        ip_origem=None if linha.ip_origem is None else str(linha.ip_origem),
        request_id=None if linha.request_id is None else str(linha.request_id),
        usuario=_curto(linha.cpf_usuario_hash),
        paciente=_curto(linha.cpf_paciente_hash),
        usuario_cpf=usuarios.get(linha.cpf_usuario_hash or b""),
        paciente_cpf=pacientes.get(linha.cpf_paciente_hash or b""),
        id_oci=linha.id_oci,
        pacientes_lista=[pacientes.get(h) or h.hex()[:_TAMANHO_HASH] for h in hashes_listados],
        hash=linha.hash_assinatura_worm.hex()[:_TAMANHO_HASH],
        resumo=linha.resumo_acessado,
    )


def _curto(valor: bytes | None) -> str | None:
    return None if valor is None else valor.hex()[:_TAMANHO_HASH]
