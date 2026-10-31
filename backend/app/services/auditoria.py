"""Registro de eventos no log WORM. Nunca recebe dado sensível em claro (só hashes e metadados)."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy.orm import Session

from app.repositories import log as log_repo


class Evento(StrEnum):
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILURE = "login_failure"
    ACCOUNT_LOCKED = "account_locked"
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    USER_DEACTIVATED = "user_deactivated"
    USER_REACTIVATED = "user_reactivated"
    MFA_ENROLLED = "mfa_enrolled"
    MFA_SUCCESS = "mfa_success"
    MFA_FAILURE = "mfa_failure"
    MFA_RECOVERY_USED = "mfa_recovery_used"
    RECOVERY_CODES_GENERATED = "recovery_codes_generated"
    SESSION_CREATED = "session_created"
    LOGOUT = "logout"
    # Nome de evento, não senha (falso positivo de S105/B105).
    PASSWORD_CHANGE = "password_change"  # noqa: S105  # nosec B105
    ACCESS_RESET = "access_reset"
    CATALOG_CREATED = "catalog_created"
    CATALOG_IMPORTED = "catalog_imported"
    CATALOG_UPDATED = "catalog_updated"
    CATALOG_DEACTIVATED = "catalog_deactivated"
    CATALOG_REACTIVATED = "catalog_reactivated"
    LOG_CHAIN_VERIFIED = "log_chain_verified"
    LOG_CHAIN_BROKEN = "log_chain_broken"
    LOG_CHECKPOINT_CREATED = "log_checkpoint_created"
    LOG_READ = "log_read"
    ACCESS_DENIED = "access_denied"
    ROLE_CHANGE = "role_change"
    SENSITIVE_DATA_ACCESS = "sensitive_data_access"
    OCI_CREATED = "oci_created"
    OCI_UPDATED = "oci_updated"
    OCI_CONCLUDED = "oci_concluded"
    OCI_CANCELED = "oci_canceled"
    OCI_DASHBOARD_READ = "oci_dashboard_read"
    NAVIGATION_CREATED = "navigation_created"
    NAVIGATION_UPDATED = "navigation_updated"
    NAVIGATION_RESCHEDULED = "navigation_rescheduled"
    PATIENT_CREATED = "patient_created"
    PATIENT_UPDATED = "patient_updated"
    PATIENT_DEACTIVATED = "patient_deactivated"
    PATIENT_REACTIVATED = "patient_reactivated"
    PATIENT_SEARCH = "patient_search"
    RATE_LIMITED = "rate_limited"
    CSRF_REJECTED = "csrf_rejected"


@dataclass(frozen=True)
class ContextoRequisicao:
    ip: str | None = None
    request_id: str | None = None


def registrar(
    db: Session,
    evento: Evento,
    ctx: ContextoRequisicao,
    *,
    cpf_usuario_hash: bytes | None = None,
    cpf_paciente_hash: bytes | None = None,
    id_oci: int | None = None,
    resumo: dict[str, Any] | None = None,
) -> None:
    log_repo.registrar(
        db,
        acao=evento.value,
        cpf_usuario_hash=cpf_usuario_hash,
        cpf_paciente_hash=cpf_paciente_hash,
        id_oci=id_oci,
        ip_origem=ctx.ip,
        request_id=ctx.request_id,
        resumo=resumo,
    )
