from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.models import (
    Cid,
    Oci,
    OciNavegacao,
    ServicoSaude,
    TipoOci,
    TipoOciCid,
    TipoUnidade,
    UnidadeSaude,
    UnidadeServico,
    Usuario,
)

type Registro = TipoUnidade | UnidadeSaude | ServicoSaude | Cid | TipoOci
type Chave = int | bytes
type Ordem = ColumnElement[Any] | InstrumentedAttribute[str]


def listar[R: Registro](
    db: Session,
    modelo: type[R],
    *,
    ordem: Ordem,
    condicao: ColumnElement[bool] | None,
    limite: int,
    deslocamento: int,
) -> list[R]:
    consulta = select(modelo).order_by(ordem).limit(limite).offset(deslocamento)
    if condicao is not None:
        consulta = consulta.where(condicao)
    return list(db.scalars(consulta))


def buscar[R: Registro](
    db: Session, modelo: type[R], chave: Chave, *, travar: bool = False
) -> R | None:
    return db.get(modelo, chave, with_for_update=travar or None)


def inserir(db: Session, registro: Registro) -> None:
    db.add(registro)
    db.flush()


def inserir_cids_novos(db: Session, linhas: Sequence[dict[str, Any]]) -> int:
    """Insere o que ainda não existe, sem alterar o que existe. Devolve quantos entraram."""
    comando = insert(Cid).values(list(linhas)).on_conflict_do_nothing().returning(Cid.cid_hash)
    return len(db.execute(comando).all())


def ativos[R: TipoUnidade | UnidadeSaude | ServicoSaude](
    db: Session, modelo: type[R], limite: int
) -> list[R]:
    """Para as comboboxes: só registros ativos, em ordem de nome."""
    consulta = (
        select(modelo)
        .where(modelo.status == "ativo")
        .order_by(func.lower(modelo.nome))
        .limit(limite)
    )
    return list(db.scalars(consulta))


def cids_ativos(db: Session, condicao: ColumnElement[bool], limite: int) -> list[Cid]:
    consulta = select(Cid).where(Cid.status == "ativo", condicao).order_by(Cid.cid).limit(limite)
    return list(db.scalars(consulta))


def hashes_de_cids_do_tipo(db: Session, id_tipo_oci: int) -> set[bytes]:
    consulta = select(TipoOciCid.fk_cid_cid_hash).where(
        TipoOciCid.fk_tipo_oci_tipo_oci_id == id_tipo_oci
    )
    return set(db.scalars(consulta))


def incluir_cids(db: Session, id_tipo_oci: int, hashes: Iterable[bytes]) -> None:
    linhas = [{"fk_tipo_oci_tipo_oci_id": id_tipo_oci, "fk_cid_cid_hash": h} for h in hashes]
    if linhas:
        db.execute(insert(TipoOciCid).values(linhas).on_conflict_do_nothing())


def remover_cids(db: Session, id_tipo_oci: int, hashes: Iterable[bytes]) -> None:
    db.execute(
        delete(TipoOciCid).where(
            TipoOciCid.fk_tipo_oci_tipo_oci_id == id_tipo_oci,
            TipoOciCid.fk_cid_cid_hash.in_(list(hashes)),
        )
    )


def hashes_de_cids_ativos_entre(db: Session, hashes: Iterable[bytes]) -> set[bytes]:
    consulta = select(Cid.cid_hash).where(Cid.cid_hash.in_(list(hashes)), Cid.status == "ativo")
    return set(db.scalars(consulta))


def codigos_dos_cids(db: Session, hashes: Iterable[bytes]) -> list[str]:
    return list(db.scalars(select(Cid.cid).where(Cid.cid_hash.in_(list(hashes))).order_by(Cid.cid)))


def tipos_oci_ativos_com_cid(db: Session, cid_hash: bytes) -> int:
    consulta = (
        select(func.count())
        .select_from(TipoOciCid)
        .join(TipoOci, TipoOci.id_tipo_oci == TipoOciCid.fk_tipo_oci_tipo_oci_id)
        .where(TipoOciCid.fk_cid_cid_hash == cid_hash, TipoOci.status == "ativo")
    )
    return int(db.scalar(consulta) or 0)


def ativos_tipo_oci(db: Session, limite: int) -> list[TipoOci]:
    consulta = (
        select(TipoOci)
        .where(TipoOci.status == "ativo")
        .order_by(func.lower(TipoOci.tipo_oci))
        .limit(limite)
    )
    return list(db.scalars(consulta))


def ocis_abertas_do_tipo(db: Session, id_tipo_oci: int) -> int:
    consulta = select(func.count()).where(Oci.id_tipo_oci == id_tipo_oci, Oci.status == "aberta")
    return int(db.scalar(consulta) or 0)


def ocis_abertas_com_cid(db: Session, cid_hash: bytes) -> int:
    consulta = select(func.count()).where(Oci.cid_hash == cid_hash, Oci.status == "aberta")
    return int(db.scalar(consulta) or 0)


def etapas_agendadas_na_unidade(db: Session, id_unidade: int) -> int:
    consulta = (
        select(func.count())
        .select_from(OciNavegacao)
        .join(Oci, Oci.id_oci == OciNavegacao.id_oci)
        .where(
            OciNavegacao.id_unidade == id_unidade,
            OciNavegacao.status == "agendado",
            Oci.status == "aberta",
        )
    )
    return int(db.scalar(consulta) or 0)


def etapas_agendadas_com_servico(db: Session, id_servico: int) -> int:
    consulta = (
        select(func.count())
        .select_from(OciNavegacao)
        .join(Oci, Oci.id_oci == OciNavegacao.id_oci)
        .where(
            OciNavegacao.id_servico == id_servico,
            OciNavegacao.status == "agendado",
            Oci.status == "aberta",
        )
    )
    return int(db.scalar(consulta) or 0)


def ids_de_servicos_da_unidade(db: Session, id_unidade: int) -> set[int]:
    consulta = select(UnidadeServico.fk_servico_saude_id_servico).where(
        UnidadeServico.fk_unidade_saude_id_unidade == id_unidade
    )
    return set(db.scalars(consulta))


def incluir_servicos(db: Session, id_unidade: int, ids: Iterable[int]) -> None:
    linhas = [
        {"fk_unidade_saude_id_unidade": id_unidade, "fk_servico_saude_id_servico": i} for i in ids
    ]
    if linhas:
        db.execute(insert(UnidadeServico).values(linhas).on_conflict_do_nothing())


def remover_servicos(db: Session, id_unidade: int, ids: Iterable[int]) -> None:
    db.execute(
        delete(UnidadeServico).where(
            UnidadeServico.fk_unidade_saude_id_unidade == id_unidade,
            UnidadeServico.fk_servico_saude_id_servico.in_(list(ids)),
        )
    )


def servicos_ativos_entre(db: Session, ids: Iterable[int]) -> set[int]:
    consulta = select(ServicoSaude.id_servico).where(
        ServicoSaude.id_servico.in_(list(ids)), ServicoSaude.status == "ativo"
    )
    return set(db.scalars(consulta))


def unidades_ativas_com_servico(db: Session, id_servico: int) -> int:
    consulta = (
        select(func.count())
        .select_from(UnidadeServico)
        .join(
            UnidadeSaude,
            UnidadeSaude.id_unidade == UnidadeServico.fk_unidade_saude_id_unidade,
        )
        .where(
            UnidadeServico.fk_servico_saude_id_servico == id_servico,
            UnidadeSaude.status == "ativo",
        )
    )
    return int(db.scalar(consulta) or 0)


def unidades_ativas_do_tipo(db: Session, id_tipo_unidade: int) -> int:
    consulta = (
        select(func.count())
        .select_from(UnidadeSaude)
        .where(UnidadeSaude.id_tipo_unidade == id_tipo_unidade, UnidadeSaude.status == "ativo")
    )
    return int(db.scalar(consulta) or 0)


def nomes_das_unidades(db: Session, ids: Iterable[int]) -> dict[int, str]:
    consulta = select(UnidadeSaude.id_unidade, UnidadeSaude.nome).where(
        UnidadeSaude.id_unidade.in_(list(ids))
    )
    return {id_unidade: nome for id_unidade, nome in db.execute(consulta)}


def usuarios_ativos_na_unidade(db: Session, id_unidade: int) -> int:
    consulta = (
        select(func.count())
        .select_from(Usuario)
        .where(Usuario.id_unidade == id_unidade, Usuario.status == "ativo")
    )
    return int(db.scalar(consulta) or 0)
