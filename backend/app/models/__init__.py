"""Mapeamento ORM das tabelas do schema `app` (a estrutura é definida pelas migrations)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    FetchedValue,
    ForeignKey,
    Identity,
    MetaData,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import BYTEA, INET, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    metadata = MetaData(schema="app")


class Usuario(Base):
    __tablename__ = "usuario"

    cpf_hash: Mapped[bytes] = mapped_column(BYTEA, primary_key=True)
    id_publico: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, default=uuid.uuid4
    )
    email_hash: Mapped[bytes] = mapped_column(BYTEA, unique=True)
    cpf_cripto: Mapped[bytes] = mapped_column(BYTEA)
    nome_cripto: Mapped[bytes] = mapped_column(BYTEA)
    email_cripto: Mapped[bytes] = mapped_column(BYTEA)
    dek_cripto: Mapped[bytes] = mapped_column(BYTEA)
    kek_versao: Mapped[int] = mapped_column(SmallInteger)
    senha_hash: Mapped[str] = mapped_column(Text)
    totp_segredo_cripto: Mapped[bytes | None] = mapped_column(BYTEA)
    totp_ultimo_passo: Mapped[int | None] = mapped_column(BigInteger)
    mfa_ativo: Mapped[bool] = mapped_column(default=False)
    troca_senha_obrigatoria: Mapped[bool] = mapped_column(default=False)
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
    tentativas: Mapped[int] = mapped_column(SmallInteger, default=0)
    ultimo_uso: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    expira_absoluta: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    criado_em: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default="now()")

    def __repr__(self) -> str:
        return "<Sessao>"


class CodigoRecuperacao(Base):
    __tablename__ = "mfa_codigo_recuperacao"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    cpf_hash: Mapped[bytes] = mapped_column(BYTEA)
    codigo_hash: Mapped[bytes] = mapped_column(BYTEA, unique=True)
    criado_em: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default="now()")
    usado_em: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    invalidado_em: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    def __repr__(self) -> str:
        return "<CodigoRecuperacao>"


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
    # Preenchidos pela trigger app.log_encadear (ADR-0010); a aplicação nunca os define.
    seq_cadeia: Mapped[int] = mapped_column(BigInteger, server_default=FetchedValue())
    prev_hash: Mapped[bytes] = mapped_column(BYTEA, server_default=FetchedValue())
    hash_assinatura_worm: Mapped[bytes] = mapped_column(BYTEA, server_default=FetchedValue())


class LogCheckpoint(Base):
    __tablename__ = "log_checkpoint"

    id_checkpoint: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    criado_em: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default="clock_timestamp()"
    )
    seq_cadeia: Mapped[int] = mapped_column(BigInteger)
    hash_cadeia: Mapped[bytes] = mapped_column(BYTEA)
    assinatura: Mapped[bytes] = mapped_column(BYTEA)

    def __repr__(self) -> str:
        return "<LogCheckpoint>"


# --- RBAC (RF-05/06/07/13). Estrutura e papéis iniciais definidos na migration 0006. ---


class Papel(Base):
    __tablename__ = "papel"

    id_papel: Mapped[int] = mapped_column(SmallInteger, Identity(always=True), primary_key=True)
    papel: Mapped[str] = mapped_column(Text, unique=True)
    descricao: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(Text, default="ativo")


class Permissao(Base):
    __tablename__ = "permissao"

    id_permissao: Mapped[int] = mapped_column(SmallInteger, Identity(always=True), primary_key=True)
    permissao: Mapped[str] = mapped_column(Text, unique=True)
    descricao: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(Text, default="ativo")


class Grupo(Base):
    __tablename__ = "grupo"

    id_grupo: Mapped[int] = mapped_column(SmallInteger, Identity(always=True), primary_key=True)
    grupo: Mapped[str] = mapped_column(Text, unique=True)
    status: Mapped[str] = mapped_column(Text, default="ativo")


class PapelPermissao(Base):
    __tablename__ = "papel_permissao"

    fk_papel_id_papel: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey(Papel.id_papel), primary_key=True
    )
    fk_permissao_id_permissao: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey(Permissao.id_permissao), primary_key=True
    )


class GrupoPapel(Base):
    __tablename__ = "grupo_papel"

    fk_grupo_id_grupo: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey(Grupo.id_grupo), primary_key=True
    )
    fk_papel_id_papel: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey(Papel.id_papel), primary_key=True
    )


class UsuarioGrupo(Base):
    __tablename__ = "usuario_grupo"

    fk_usuario_cpf_hash: Mapped[bytes] = mapped_column(
        BYTEA, ForeignKey(Usuario.cpf_hash), primary_key=True
    )
    fk_grupo_id_grupo: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey(Grupo.id_grupo), primary_key=True
    )


class Paciente(Base):
    __tablename__ = "paciente"

    cpf_hash: Mapped[bytes] = mapped_column(BYTEA, primary_key=True)
    id_publico: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    cpf_cripto: Mapped[bytes] = mapped_column(BYTEA)
    nome_cripto: Mapped[bytes] = mapped_column(BYTEA)
    data_nascimento_cripto: Mapped[bytes] = mapped_column(BYTEA)
    email_cripto: Mapped[bytes | None] = mapped_column(BYTEA)
    dek_cripto: Mapped[bytes] = mapped_column(BYTEA)
    kek_versao: Mapped[int] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(Text, default="ativo")
    criado_em: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default="now()")
    atualizado_em: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default="now()", server_onupdate=FetchedValue()
    )

    def __repr__(self) -> str:  # nunca expor campos, nem cifrados
        return "<Paciente>"


class LimiteRequisicao(Base):
    __tablename__ = "limite_requisicao"

    grupo: Mapped[str] = mapped_column(Text, primary_key=True)
    ip: Mapped[str] = mapped_column(INET, primary_key=True)
    janela: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), primary_key=True)
    total: Mapped[int] = mapped_column(default=1)


# --- Cadastros de catálogo (RF-09/10/11). Dados públicos: sem cifragem.


class TipoUnidade(Base):
    __tablename__ = "tipo_unidade"

    id_tipo_unidade: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    nome: Mapped[str] = mapped_column(Text)
    descricao: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(Text, default="ativo")


class ServicoSaude(Base):
    __tablename__ = "servico_saude"

    id_servico: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    nome: Mapped[str] = mapped_column(Text)
    descricao: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(Text, default="ativo")


class UnidadeServico(Base):
    __tablename__ = "unidade_saude_servico_saude"

    fk_unidade_saude_id_unidade: Mapped[int] = mapped_column(
        ForeignKey("app.unidade_saude.id_unidade"), primary_key=True
    )
    fk_servico_saude_id_servico: Mapped[int] = mapped_column(
        ForeignKey(ServicoSaude.id_servico), primary_key=True
    )


class UnidadeSaude(Base):
    __tablename__ = "unidade_saude"

    id_unidade: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    id_tipo_unidade: Mapped[int] = mapped_column(ForeignKey(TipoUnidade.id_tipo_unidade))
    tipo: Mapped[TipoUnidade] = relationship(lazy="selectin")
    # Só leitura: os vínculos mudam pelo repositório, para cada mudança ser auditada.
    servicos: Mapped[list[ServicoSaude]] = relationship(
        secondary=UnidadeServico.__table__,
        viewonly=True,
        lazy="selectin",
        order_by=func.lower(ServicoSaude.nome),
    )
    nome: Mapped[str] = mapped_column(Text)
    endereco: Mapped[str] = mapped_column(Text)
    telefone: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="ativo")


class Cid(Base):
    __tablename__ = "cid"

    cid_hash: Mapped[bytes] = mapped_column(BYTEA, primary_key=True)
    cid: Mapped[str] = mapped_column(Text, unique=True)
    descricao: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="ativo")


class TipoOciCid(Base):
    __tablename__ = "tipo_oci_cid"

    fk_tipo_oci_tipo_oci_id: Mapped[int] = mapped_column(
        ForeignKey("app.tipo_oci.id_tipo_oci"), primary_key=True
    )
    fk_cid_cid_hash: Mapped[bytes] = mapped_column(ForeignKey(Cid.cid_hash), primary_key=True)


class TipoOci(Base):
    __tablename__ = "tipo_oci"

    id_tipo_oci: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    tipo_oci: Mapped[str] = mapped_column(Text)
    prazo_diagnostico: Mapped[int]
    status: Mapped[str] = mapped_column(Text, default="ativo")
    # Só leitura: os vínculos mudam pelo repositório, para cada mudança ser auditada.
    cids: Mapped[list[Cid]] = relationship(
        secondary=TipoOciCid.__table__, viewonly=True, lazy="selectin", order_by=Cid.cid
    )


# --- OCI e navegação (RF-12). O vínculo paciente x CID é dado de saúde: ver ADR-0025.


class OciNavegacao(Base):
    __tablename__ = "oci_navegacao"

    id_oci_navegacao: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )
    id_oci: Mapped[int] = mapped_column(BigInteger, ForeignKey("app.oci.id_oci"))
    id_unidade: Mapped[int] = mapped_column(ForeignKey(UnidadeSaude.id_unidade))
    id_servico: Mapped[int] = mapped_column(ForeignKey(ServicoSaude.id_servico))
    data_hora: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    status: Mapped[str] = mapped_column(Text, default="agendado")
    unidade: Mapped[UnidadeSaude] = relationship(lazy="selectin")
    servico: Mapped[ServicoSaude] = relationship(lazy="selectin")


class Oci(Base):
    __tablename__ = "oci"

    id_oci: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    id_publico: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    id_tipo_oci: Mapped[int] = mapped_column(ForeignKey(TipoOci.id_tipo_oci))
    cpf_paciente_hash: Mapped[bytes] = mapped_column(BYTEA, ForeignKey(Paciente.cpf_hash))
    cid_hash: Mapped[bytes] = mapped_column(BYTEA, ForeignKey(Cid.cid_hash))
    data_criacao: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=FetchedValue()
    )
    prazo_em: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    resultado_cripto: Mapped[bytes | None] = mapped_column(BYTEA)
    dek_cripto: Mapped[bytes | None] = mapped_column(BYTEA)
    kek_versao: Mapped[int | None] = mapped_column(SmallInteger)
    resultado_cid_hash: Mapped[bytes | None] = mapped_column(BYTEA, ForeignKey(Cid.cid_hash))
    status: Mapped[str] = mapped_column(Text, default="aberta")
    tipo: Mapped[TipoOci] = relationship(lazy="selectin")
    cid: Mapped[Cid] = relationship(foreign_keys=[cid_hash], lazy="selectin")
    resultado_cid: Mapped[Cid | None] = relationship(
        foreign_keys=[resultado_cid_hash], lazy="selectin"
    )
    navegacoes: Mapped[list[OciNavegacao]] = relationship(
        lazy="selectin", order_by=OciNavegacao.data_hora
    )

    def __repr__(self) -> str:  # nunca expor campos, nem cifrados
        return "<Oci>"
