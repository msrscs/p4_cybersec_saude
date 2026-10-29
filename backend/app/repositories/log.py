from typing import Any

from sqlalchemy.orm import Session

from app.models import Log


def registrar(
    db: Session,
    *,
    acao: str,
    cpf_usuario_hash: bytes | None = None,
    ip_origem: str | None = None,
    request_id: str | None = None,
    resumo: dict[str, Any] | None = None,
) -> None:
    db.add(
        Log(
            acao=acao,
            cpf_usuario_hash=cpf_usuario_hash,
            ip_origem=ip_origem,
            request_id=request_id,
            resumo_acessado=resumo or {},
        )
    )
    db.flush()
