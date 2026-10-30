from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import LimiteRequisicao


def incrementar(db: Session, grupo: str, ip: str, janela: datetime) -> int:
    """Soma 1 ao contador da janela (cria se não existir) e devolve o total, atomicamente."""
    comando = (
        insert(LimiteRequisicao)
        .values(grupo=grupo, ip=ip, janela=janela, total=1)
        .on_conflict_do_update(
            index_elements=[LimiteRequisicao.grupo, LimiteRequisicao.ip, LimiteRequisicao.janela],
            set_={"total": LimiteRequisicao.total + 1},
        )
        .returning(LimiteRequisicao.total)
    )
    return int(db.execute(comando).scalar_one())


def remover_vencidos(db: Session, antes_de: datetime) -> int:
    resultado = db.execute(delete(LimiteRequisicao).where(LimiteRequisicao.janela < antes_de))
    return int(resultado.rowcount)  # type: ignore[attr-defined]
