from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Grupo, GrupoPapel, Papel, PapelPermissao, Permissao, UsuarioGrupo


def permissoes(db: Session, cpf_hash: bytes) -> frozenset[str]:
    """Permissões efetivas: usuário -> grupos -> papéis -> permissões, todos ativos."""
    consulta = (
        select(Permissao.permissao)
        .join(PapelPermissao, PapelPermissao.fk_permissao_id_permissao == Permissao.id_permissao)
        .join(Papel, Papel.id_papel == PapelPermissao.fk_papel_id_papel)
        .join(GrupoPapel, GrupoPapel.fk_papel_id_papel == Papel.id_papel)
        .join(Grupo, Grupo.id_grupo == GrupoPapel.fk_grupo_id_grupo)
        .join(UsuarioGrupo, UsuarioGrupo.fk_grupo_id_grupo == Grupo.id_grupo)
        .where(
            UsuarioGrupo.fk_usuario_cpf_hash == cpf_hash,
            Permissao.status == "ativo",
            Papel.status == "ativo",
            Grupo.status == "ativo",
        )
        .distinct()
    )
    return frozenset(db.scalars(consulta))


def buscar_grupo(db: Session, nome: str) -> Grupo | None:
    return db.scalars(select(Grupo).where(Grupo.grupo == nome)).one_or_none()


def nomes_dos_grupos(db: Session) -> list[str]:
    return list(db.scalars(select(Grupo.grupo).order_by(Grupo.id_grupo)))


def adicionar_ao_grupo(db: Session, cpf_hash: bytes, id_grupo: int) -> bool:
    """Devolve False se o usuário já estava no grupo."""
    resultado = db.execute(
        insert(UsuarioGrupo)
        .values(fk_usuario_cpf_hash=cpf_hash, fk_grupo_id_grupo=id_grupo)
        .on_conflict_do_nothing()
        .returning(UsuarioGrupo.fk_grupo_id_grupo)
    )
    return resultado.first() is not None


def remover_do_grupo(db: Session, cpf_hash: bytes, id_grupo: int) -> bool:
    resultado = db.execute(
        delete(UsuarioGrupo)
        .where(
            UsuarioGrupo.fk_usuario_cpf_hash == cpf_hash,
            UsuarioGrupo.fk_grupo_id_grupo == id_grupo,
        )
        .returning(UsuarioGrupo.fk_grupo_id_grupo)
    )
    return resultado.first() is not None
