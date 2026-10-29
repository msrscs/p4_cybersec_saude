"""Mapeamento ORM das tabelas do schema `app` (a estrutura é definida pelas migrations)."""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Identity, MetaData, SmallInteger, Text
from sqlalchemy.dialects.postgresql import BYTEA, INET, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(schema="app")


class Usuario(Base):
    __tablename__ = "usuario"

    cpf_hash: Mapped[bytes] = mapped_column(BYTEA, primary_key=True)
    email_hash: Mapped[bytes] = mapped_column(BYTEA, unique=True)
    cpf_cripto: Mapped[bytes] = mapped_column(BYTEA)
    nome_cripto: Mapped[bytes] = mapped_column(BYTEA)
    email_cripto: Mapped[bytes] = mapped_column(BYTEA)
    dek_cripto: Mapped[bytes] = mapped_column(BYTEA)
    kek_versao: Mapped[int] = mapped_column(SmallInteger)
    senha_hash: Mapped[str] = mapped_column(Text)
    totp_segredo_cripto: Mapped[bytes | None] = mapped_column(BYTEA)
    mfa_ativo: Mapped[bool] = mapped_column(default=False)
    id_unidade: Mapped[int | None]
    status: Mapped[str] = mapped_column(Text, default="ativo")
    falhas_login: Mapped[int] = mapped_column(default=0)
    bloqueios: Mapped[int] = mapped_column(SmallInteger, default=0)
    bloqueado_ate: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    criado_em: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default="now()")
    atualizado_em: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default="now()"
    )

    def __repr__(self) -> str:  # nunca expor campos, nem cifrados
        return "<Usuario>"


class Sessao(Base):
    __tablename__ = "sessao"

    token_hash: Mapped[bytes] = mapped_column(BYTEA, primary_key=True)
    cpf_hash: Mapped[bytes] = mapped_column(BYTEA)
    escopo: Mapped[str] = mapped_column(Text)
    expira_em: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    ip: Mapped[str | None] = mapped_column(INET)
    criado_em: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default="now()")

    def __repr__(self) -> str:
        return "<Sessao>"


class Log(Base):
    __tablename__ = "log"

    id_log: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    data_hora: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default="clock_timestamp()"
    )
    acao: Mapped[str] = mapped_column(Text)
    resumo_acessado: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    ip_origem: Mapped[str | None] = mapped_column(INET)
    request_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    geolocalizacao: Mapped[str | None] = mapped_column(Text)
    cpf_usuario_hash: Mapped[bytes | None] = mapped_column(BYTEA)
    cpf_paciente_hash: Mapped[bytes | None] = mapped_column(BYTEA)
    id_oci: Mapped[int | None] = mapped_column(BigInteger)
    prev_hash: Mapped[bytes | None] = mapped_column(BYTEA)
    hash_assinatura_worm: Mapped[bytes | None] = mapped_column(BYTEA)
