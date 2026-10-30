from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.models import Cid, ServicoSaude, UnidadeSaude, Usuario

type Registro = UnidadeSaude | ServicoSaude | Cid
type Chave = int | bytes
type Ordem = ColumnElement[Any] | InstrumentedAttribute[str]


def listar[R: Registro](
    db: Session,
    modelo: type[R],
    *,
    ordem: Ordem,
    colunas_busca: Sequence[InstrumentedAttribute[str]],
    busca: str | None,
    limite: int,
    deslocamento: int,
) -> list[R]:
    consulta = select(modelo).order_by(ordem).limit(limite).offset(deslocamento)
    if busca:
        # autoescape: % e _ digitados são texto, não curinga.
        consulta = consulta.where(
            or_(*(coluna.icontains(busca, autoescape=True) for coluna in colunas_busca))
        )
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


def unidades_ativas(db: Session, limite: int) -> list[UnidadeSaude]:
    consulta = (
        select(UnidadeSaude)
        .where(UnidadeSaude.status == "ativo")
        .order_by(func.lower(UnidadeSaude.nome))
        .limit(limite)
    )
    return list(db.scalars(consulta))


def usuarios_ativos_na_unidade(db: Session, id_unidade: int) -> int:
    consulta = (
        select(func.count())
        .select_from(Usuario)
        .where(Usuario.id_unidade == id_unidade, Usuario.status == "ativo")
    )
    return int(db.scalar(consulta) or 0)
