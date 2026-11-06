"""
master_key.py — where the secrets vault's master key(s) come from.

``PIPESETS_MASTER_KEY_PROVIDER`` picks the source (inferred from which variable is set when
it's empty):

  env       ``PIPESETS_MASTER_KEY`` — Fernet keys, comma-separated. Without it a key is
            generated once into ``.secrets_master_key`` in the data folder (local dev only).
  aws_kms   ``PIPESETS_MASTER_KEY_KMS`` — KMS ciphertext blobs (base64), comma-separated.
            Each is decrypted with KMS at startup, so the key never sits in plaintext in the
            environment or on disk. AWS credentials and region come from boto3's usual chain.
            Make one with ``python manage.py kms-wrap-key --key-id <arn or alias>``.
  vault     HashiCorp Vault KV: ``VAULT_ADDR``, ``VAULT_TOKEN`` (optional ``VAULT_NAMESPACE``),
            ``PIPESETS_MASTER_KEY_VAULT_PATH`` (API path, e.g. ``secret/data/pipesets`` for
            KV v2) and ``PIPESETS_MASTER_KEY_VAULT_FIELD`` (default ``master_key``). The field
            holds Fernet keys, comma-separated.

Whatever the source, the first key encrypts and all of them decrypt, so rotation works the
same way: prepend a new key and run ``python manage.py rotate-secrets``.
A source that is configured but unreachable fails loudly — never falls back to another key.
"""

import base64
import logging
import os
from typing import List, Optional

import httpx
from cryptography.fernet import Fernet

from paths import data_path

logger = logging.getLogger("pipesets-ai-backend")

PROVIDERS = ("env", "aws_kms", "vault")
_KEY_FILE = data_path(".secrets_master_key")


class MasterKeyError(RuntimeError):
    pass


def _split(value: str) -> List[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def provider() -> str:
    name = os.getenv("PIPESETS_MASTER_KEY_PROVIDER", "").strip().lower()
    if not name:
        if os.getenv("PIPESETS_MASTER_KEY_KMS", "").strip():
            return "aws_kms"
        if os.getenv("PIPESETS_MASTER_KEY_VAULT_PATH", "").strip():
            return "vault"
        return "env"
    if name not in PROVIDERS:
        raise MasterKeyError(f"Unknown PIPESETS_MASTER_KEY_PROVIDER '{name}' (use one of: {', '.join(PROVIDERS)}).")
    return name


def load_keys() -> List[bytes]:
    """The master keys, primary first."""
    name = provider()
    keys = {"env": _from_env, "aws_kms": _from_kms, "vault": _from_vault}[name]()
    if not keys:
        raise MasterKeyError(f"The '{name}' master key provider returned no keys.")
    for k in keys:
        try:
            Fernet(k)
        except ValueError as e:
            raise MasterKeyError(f"A master key from '{name}' is not a valid Fernet key.") from e
    return keys


# ── env / local file ──────────────────────────────────────────────────────────

def _from_env() -> List[bytes]:
    env = os.getenv("PIPESETS_MASTER_KEY", "").strip()
    if env:
        return [k.encode() for k in _split(env)]
    if not os.path.exists(_KEY_FILE):
        logger.warning("PIPESETS_MASTER_KEY is not set; generating a local key at %s", _KEY_FILE)
        fd = os.open(_KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(Fernet.generate_key())
    with open(_KEY_FILE, "rb") as f:
        return [f.read().strip()]


# ── AWS KMS ───────────────────────────────────────────────────────────────────

def _kms_client():
    import boto3  # lazy: only deployments using KMS need AWS credentials
    return boto3.client("kms")


def _as_fernet_key(plaintext: bytes) -> bytes:
    """KMS data keys are 32 raw bytes; a wrapped existing key is already base64 text."""
    return base64.urlsafe_b64encode(plaintext) if len(plaintext) == 32 else plaintext.strip()


def _from_kms() -> List[bytes]:
    blobs = _split(os.getenv("PIPESETS_MASTER_KEY_KMS", ""))
    if not blobs:
        raise MasterKeyError("PIPESETS_MASTER_KEY_KMS is empty — set it to the output of `manage.py kms-wrap-key`.")
    client = _kms_client()
    keys = []
    for blob in blobs:
        try:
            out = client.decrypt(CiphertextBlob=base64.b64decode(blob))
        except Exception as e:
            raise MasterKeyError(f"KMS could not decrypt the master key: {type(e).__name__}: {e}") from e
        keys.append(_as_fernet_key(out["Plaintext"]))
    return keys


def kms_wrap(key_id: str, fernet_key: Optional[str] = None) -> str:
    """Base64 KMS ciphertext for PIPESETS_MASTER_KEY_KMS: ``fernet_key`` encrypted under
    ``key_id``, or a fresh 256-bit data key when none is given."""
    client = _kms_client()
    if fernet_key:
        Fernet(fernet_key.encode())  # refuse to wrap something that isn't a key
        blob = client.encrypt(KeyId=key_id, Plaintext=fernet_key.encode())["CiphertextBlob"]
    else:
        blob = client.generate_data_key(KeyId=key_id, KeySpec="AES_256")["CiphertextBlob"]
    return base64.b64encode(blob).decode("ascii")


# ── HashiCorp Vault ───────────────────────────────────────────────────────────

def _from_vault() -> List[bytes]:
    addr = os.getenv("VAULT_ADDR", "").strip().rstrip("/")
    token = os.getenv("VAULT_TOKEN", "").strip()
    path = os.getenv("PIPESETS_MASTER_KEY_VAULT_PATH", "").strip().strip("/")
    field = os.getenv("PIPESETS_MASTER_KEY_VAULT_FIELD", "master_key").strip()
    if not (addr and token and path):
        raise MasterKeyError("The vault master key provider needs VAULT_ADDR, VAULT_TOKEN and "
                             "PIPESETS_MASTER_KEY_VAULT_PATH.")
    headers = {"X-Vault-Token": token}
    if os.getenv("VAULT_NAMESPACE", "").strip():
        headers["X-Vault-Namespace"] = os.getenv("VAULT_NAMESPACE", "").strip()
    try:
        r = httpx.get(f"{addr}/v1/{path}", headers=headers, timeout=10.0)
    except httpx.HTTPError as e:
        raise MasterKeyError(f"Vault is unreachable at {addr}: {type(e).__name__}") from e
    if r.status_code != 200:
        raise MasterKeyError(f"Vault returned HTTP {r.status_code} for {path}.")
    data = (r.json() or {}).get("data") or {}
    if isinstance(data.get("data"), dict):  # KV v2 nests the secret under data.data
        data = data["data"]
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise MasterKeyError(f"Vault secret {path} has no '{field}' field.")
    return [k.encode() for k in _split(value)]
