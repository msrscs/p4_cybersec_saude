import uuid
from datetime import datetime

from sqlalchemy import exists, func, literal, select, tuple_
from sqlalchemy.orm import Session

from app.models import Cid, Oci, OciNavegacao, ServicoSaude, TipoOciCid, UnidadeServico


def inserir(db: Session, oci: Oci) -> None:
    db.add(oci)
    db.flush()


def inserir_navegacao(db: Session, navegacao: OciNavegacao) -> None:
    db.add(navegacao)
    db.flush()


def buscar_por_id(db: Session, id_publico: uuid.UUID, *, travar: bool = False) -> Oci | None:
    consulta = select(Oci).where(Oci.id_publico == id_publico)
    if travar:
        consulta = consulta.with_for_update(of=Oci)
    return db.scalars(consulta).one_or_none()


def buscar_navegacao(db: Session, id_oci: int, id_navegacao: int) -> OciNavegacao | None:
    consulta = select(OciNavegacao).where(
        OciNavegacao.id_oci_navegacao == id_navegacao, OciNavegacao.id_oci == id_oci
    )
    return db.scalars(consulta.with_for_update(of=OciNavegacao)).one_or_none()


def esta_na_unidade(db: Session, id_oci: int, id_unidade: int) -> bool:
    consulta = select(OciNavegacao.id_oci_navegacao).where(
        OciNavegacao.id_oci == id_oci, OciNavegacao.id_unidade == id_unidade
    )
    return db.scalars(consulta.limit(1)).first() is not None


def listar(
    db: Session,
    *,
    limite: int,
    depois: Oci | None = None,
    unidade_do_alcance: int | None = None,
    status: str | None = None,
    id_tipo_oci: int | None = None,
    id_unidade: int | None = None,
    cpf_paciente_hash: bytes | None = None,
    atrasadas_em: datetime | None = None,
) -> list[Oci]:
    """Mais recentes primeiro. `unidade_do_alcance`: só OCIs com navegação naquela unidade."""
    consulta = select(Oci).order_by(Oci.data_criacao.desc(), Oci.id_publico.desc()).limit(limite)
    if depois is not None:
        consulta = consulta.where(
            tuple_(Oci.data_criacao, Oci.id_publico)
            < tuple_(literal(depois.data_criacao), literal(depois.id_publico))
        )
    for unidade in (unidade_do_alcance, id_unidade):
        if unidade is not None:
            consulta = consulta.where(
                exists().where(
                    OciNavegacao.id_oci == Oci.id_oci, OciNavegacao.id_unidade == unidade
                )
            )
    if status is not None:
        consulta = consulta.where(Oci.status == status)
    if id_tipo_oci is not None:
        consulta = consulta.where(Oci.id_tipo_oci == id_tipo_oci)
    if cpf_paciente_hash is not None:
        consulta = consulta.where(Oci.cpf_paciente_hash == cpf_paciente_hash)
    if atrasadas_em is not None:
        consulta = consulta.where(Oci.status == "aberta", Oci.prazo_em < atrasadas_em)
    return list(db.scalars(consulta))


def cid_do_tipo(db: Session, id_tipo_oci: int, cid_hash: bytes) -> bool:
    """O CID precisa estar ativo e vinculado ao tipo de OCI."""
    consulta = (
        select(TipoOciCid.fk_cid_cid_hash)
        .join(Cid, Cid.cid_hash == TipoOciCid.fk_cid_cid_hash)
        .where(
            TipoOciCid.fk_tipo_oci_tipo_oci_id == id_tipo_oci,
            TipoOciCid.fk_cid_cid_hash == cid_hash,
            Cid.status == "ativo",
        )
    )
    return db.scalars(consulta.limit(1)).first() is not None


def cids_ativos_do_tipo(db: Session, id_tipo_oci: int) -> list[Cid]:
    consulta = (
        select(Cid)
        .join(TipoOciCid, TipoOciCid.fk_cid_cid_hash == Cid.cid_hash)
        .where(TipoOciCid.fk_tipo_oci_tipo_oci_id == id_tipo_oci, Cid.status == "ativo")
        .order_by(Cid.cid)
    )
    return list(db.scalars(consulta))


def servicos_ativos_da_unidade(db: Session, id_unidade: int) -> list[ServicoSaude]:
    consulta = (
        select(ServicoSaude)
        .join(UnidadeServico, UnidadeServico.fk_servico_saude_id_servico == ServicoSaude.id_servico)
        .where(
            UnidadeServico.fk_unidade_saude_id_unidade == id_unidade,
            ServicoSaude.status == "ativo",
        )
        .order_by(func.lower(ServicoSaude.nome))
    )
    return list(db.scalars(consulta))


def abertas_do_paciente(db: Session, cpf_paciente_hash: bytes) -> int:
    consulta = (
        select(func.count())
        .select_from(Oci)
        .where(Oci.cpf_paciente_hash == cpf_paciente_hash, Oci.status == "aberta")
    )
    return int(db.scalar(consulta) or 0)
