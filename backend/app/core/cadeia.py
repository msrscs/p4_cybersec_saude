"""Hash encadeado do log de auditoria e assinatura dos checkpoints (ADR-0010).

Reimplementa em Python a serialização da função `app.log_calcular_hash` (migration 0005),
para que a verificação não dependa do código que está dentro do banco. Só SHA-256 e
HMAC-SHA256 da biblioteca padrão; nenhuma primitiva própria.

Serialização: cada parte com prefixo de 4 bytes (big-endian) com o tamanho; NULL é
representado por 0xFFFFFFFF sem dados (distingue NULL de texto vazio).
"""

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

TAMANHO_HASH = 32
GENESIS = bytes(TAMANHO_HASH)
_NULO = b"\xff\xff\xff\xff"
_DOMINIO_LOG = "cybersec-saude/log/v1"
_DOMINIO_CHECKPOINT = "cybersec-saude/log_checkpoint/v1"
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class RegistroCadeia:
    """Campos do log que entram no hash, no formato em que o banco os converte para texto.

    `ip_origem`, `request_id` e `resumo` vêm do banco já como `::text` (inet, uuid, jsonb).
    """

    seq_cadeia: int
    id_log: int
    data_hora: datetime
    acao: str
    resumo: str
    ip_origem: str | None
    request_id: str | None
    geolocalizacao: str | None
    cpf_usuario_hash: bytes | None
    cpf_paciente_hash: bytes | None
    id_oci: int | None
    prev_hash: bytes
    hash_assinatura_worm: bytes


def _parte(valor: bytes | None) -> bytes:
    if valor is None:
        return _NULO
    return len(valor).to_bytes(4, "big") + valor


def _texto(valor: str | int | None) -> bytes:
    return _parte(None if valor is None else str(valor).encode("utf-8"))


def microssegundos(momento: datetime) -> int:
    """Microssegundos desde a época, em aritmética inteira (igual a extract(epoch)*1e6)."""
    return (momento - _EPOCH) // timedelta(microseconds=1)


def hash_registro(prev_hash: bytes, r: RegistroCadeia) -> bytes:
    mensagem = b"".join(
        (
            _texto(_DOMINIO_LOG),
            _parte(prev_hash),
            _texto(r.seq_cadeia),
            _texto(r.id_log),
            _texto(microssegundos(r.data_hora)),
            _texto(r.acao),
            _texto(r.resumo),
            _texto(r.ip_origem),
            _texto(r.request_id),
            _texto(r.geolocalizacao),
            _parte(r.cpf_usuario_hash),
            _parte(r.cpf_paciente_hash),
            _texto(r.id_oci),
        )
    )
    return hashlib.sha256(mensagem).digest()


def assinar_checkpoint(chave: bytes, seq_cadeia: int, hash_cadeia: bytes) -> bytes:
    mensagem = _texto(_DOMINIO_CHECKPOINT) + _texto(seq_cadeia) + _parte(hash_cadeia)
    return hmac.new(chave, mensagem, hashlib.sha256).digest()


def checkpoint_valido(chave: bytes, seq_cadeia: int, hash_cadeia: bytes, assinatura: bytes) -> bool:
    return hmac.compare_digest(assinar_checkpoint(chave, seq_cadeia, hash_cadeia), assinatura)


@dataclass(frozen=True)
class Ancora:
    """Último ponto conhecido da cadeia, guardado fora do sistema (`seq:hash_hex`)."""

    seq_cadeia: int
    hash_cadeia: bytes

    @classmethod
    def de_texto(cls, texto: str) -> Ancora:
        seq_txt, sep, hash_hex = texto.strip().partition(":")
        try:
            seq = int(seq_txt)
            hash_cadeia = bytes.fromhex(hash_hex)
        except ValueError:
            raise ValueError("Âncora deve ter o formato seq:hash_hex.") from None
        if not sep or seq <= 0 or len(hash_cadeia) != TAMANHO_HASH:
            raise ValueError("Âncora deve ter o formato seq:hash_hex.")
        return cls(seq, hash_cadeia)

    def __str__(self) -> str:
        return f"{self.seq_cadeia}:{self.hash_cadeia.hex()}"
