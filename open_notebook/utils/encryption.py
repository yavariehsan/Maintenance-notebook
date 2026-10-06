"""
Field-level encryption for sensitive data using API keys.

This module provides encryption/decryption for API keys stored in the database.
Fernet uses AES-128-CBC with HMAC-SHA256 for authenticated encryption.

OPEN_NOTEBOOK_ENCRYPTION_KEY accepts **any string**. A Fernet key is derived
from it via SHA-256, so users can set a simple passphrase like
``OPEN_NOTEBOOK_ENCRYPTION_KEY=my-secret`` and it will work.

Usage:
    # Encrypt before storing
    encrypted = encrypt_value(api_key)

    # Decrypt when reading
    decrypted = decrypt_value(encrypted)
"""

import base64
import hashlib
import os
import re
import secrets
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from loguru import logger


def get_secret_from_env(var_name: str) -> Optional[str]:
    """
    Get a secret from environment, supporting Docker secrets pattern.

    Checks for VAR_FILE first (Docker secrets), then falls back to VAR.

    Args:
        var_name: Base name of the environment variable (e.g., "OPEN_NOTEBOOK_ENCRYPTION_KEY")

    Returns:
        The secret value, or None if not configured.
    """
    # Check for _FILE variant first (Docker secrets)
    file_path = os.environ.get(f"{var_name}_FILE")
    if file_path:
        try:
            path = Path(file_path)
            if path.exists() and path.is_file():
                # Pin UTF-8 explicitly: the default locale encoding mangles
                # non-ASCII secrets (POSIX/ASCII locales raise, Windows
                # code pages silently mojibake them), which breaks or
                # silently disables password auth. Secret files are UTF-8.
                secret = path.read_text(encoding="utf-8").strip()
                if secret:
                    logger.debug(f"Loaded {var_name} from file: {file_path}")
                    return secret
                else:
                    logger.warning(f"{var_name}_FILE points to empty file: {file_path}")
            else:
                logger.warning(f"{var_name}_FILE path does not exist: {file_path}")
        except Exception as e:
            logger.error(f"Failed to read {var_name} from file {file_path}: {e}")

    # Fall back to direct environment variable
    return os.environ.get(var_name)


def _get_or_create_encryption_key() -> str:
    """
    Get encryption key from environment, requires explicit configuration.

    Priority:
    1. OPEN_NOTEBOOK_ENCRYPTION_KEY_FILE (Docker secrets)
    2. OPEN_NOTEBOOK_ENCRYPTION_KEY (environment variable)

    For production deployments, you MUST set OPEN_NOTEBOOK_ENCRYPTION_KEY explicitly!

    Returns:
        Encryption key string.

    Raises:
        ValueError: If no encryption key is configured.
    """
    # First check environment/Docker secrets
    key = get_secret_from_env("OPEN_NOTEBOOK_ENCRYPTION_KEY")
    if key:
        return key

    raise ValueError(
        "OPEN_NOTEBOOK_ENCRYPTION_KEY is not set. "
        "Set this environment variable to any secret string to enable "
        "encrypted storage of API keys in the database."
    )


# Lazy-loaded encryption key: initialized on first use, not at import time.
# This prevents the entire app from crashing if the key is not yet configured
# when other modules import from this file.
_ENCRYPTION_KEY: Optional[str] = None


def _get_encryption_key() -> str:
    """Get the encryption key, initializing lazily on first call."""
    global _ENCRYPTION_KEY
    if _ENCRYPTION_KEY is None:
        _ENCRYPTION_KEY = _get_or_create_encryption_key()
    return _ENCRYPTION_KEY


def _ensure_fernet_key(key: str) -> str:
    """
    Derive a valid Fernet key from an arbitrary string via SHA-256.

    Any string is accepted as input. The key is derived by hashing it with
    SHA-256 and encoding the result as URL-safe base64.
    """
    derived = hashlib.sha256(key.encode()).digest()
    return base64.urlsafe_b64encode(derived).decode()


def get_fernet() -> Fernet:
    """
    Get Fernet instance with the configured encryption key.

    Returns:
        Fernet instance.

    Raises:
        ValueError: If encryption key is not configured.
    """
    return Fernet(_ensure_fernet_key(_get_encryption_key()).encode())


def encrypt_value(value: str) -> str:
    """
    Encrypt a string value using the current versioned scheme (PBKDF2).

    New writes always use the ``pbkdf2v2:`` envelope carrying the active
    key id. Legacy reads keep working through :func:`decrypt_value`.

    Args:
        value: The plain text string to encrypt.

    Returns:
        Versioned encrypted string.

    Raises:
        ValueError: If encryption is not configured.
    """
    keys = get_configured_keys()
    active_id = next(iter(keys))
    return encrypt_pbkdf2v2_value(value, keys[active_id], active_id)


def looks_like_fernet_token(s: str) -> bool:
    """
    Check if string looks like a Fernet encrypted token.

    Fernet tokens are versioned (1 byte) + timestamp (8 bytes) + IV (16 bytes)
    + ciphertext (variable, multiple of 16 with PKCS7 padding) + HMAC (32 bytes).
    Minimum decoded size is 73 bytes (1+8+16+16+32) for the smallest payload.
    """
    if len(s) < 100:  # Base64 of 73 bytes = ~100 chars minimum
        return False
    try:
        decoded = base64.urlsafe_b64decode(s)
        # Fernet: version(1) + timestamp(8) + IV(16) + ciphertext(>=16) + HMAC(32)
        # Minimum 73 bytes, ciphertext must be multiple of 16 (AES block size)
        if len(decoded) < 73:
            return False
        ciphertext_len = len(decoded) - 1 - 8 - 16 - 32
        return ciphertext_len > 0 and ciphertext_len % 16 == 0
    except Exception:
        return False


def decrypt_value(value: str) -> str:
    """
    Decrypt a credential string value with strict version dispatch.

    Dispatch order (never guessed):

    1. Exact ``pbkdf2v2:`` prefix -> PBKDF2 path with exact key-id lookup.
       Unknown ids and wrong secrets raise; other keys are never tried.
    2. Exact ``pbkdf2v1:`` prefix -> PBKDF2 path over configured keys in
       deterministic order (v1 carries no identity; active first).
    3. Any other ``<name>v<digits>:``-shaped prefix -> unsupported
       version, controlled failure (prevents downgrade/confusion).
    4. Otherwise the legacy rules apply unchanged: Fernet/SHA-256
       decryption tried over configured keys in order, with plaintext
       passthrough for values that are not Fernet tokens at all.

    Args:
        value: The encrypted string (or plain text for legacy data).

    Returns:
        Decrypted plain text string, or original value if not encrypted.

    Raises:
        ValueError: If encryption is not configured, if decryption fails
            for versioned/encrypted data (e.g. wrong key), or if the
            version is unknown.
    """
    if is_pbkdf2v2_token(value):
        return decrypt_pbkdf2v2_value(value, get_configured_keys())
    if is_pbkdf2_token(value):
        return _decrypt_v1_with_keys(value, get_configured_keys())
    if _VERSIONED_PREFIX_RE.match(value or ""):
        raise ValueError(
            "Unsupported credential encryption version. The credential "
            "was written by a newer version and cannot be decrypted here."
        )
    return _decrypt_legacy_with_keys(value, get_configured_keys())


# --- Versioned PBKDF2 envelope (fork-native `pbkdf2v1:` format) -------------
#
# Layout (all ASCII, colon-separated, exactly four fields):
#
#     pbkdf2v1:<iterations>:<salt_b64>:<fernet_token>
#
# - ``pbkdf2v1``: format version. Dispatch is by exact prefix match.
# - ``iterations``: PBKDF2 iteration count, embedded so future runs may raise
#   it under review without breaking readers.
# - ``salt_b64``: standard-base64, cryptographically random per record
#   (``PBKDF2_SALT_BYTES``).
# - ``fernet_token``: standard Fernet token (AES-128-CBC + HMAC-SHA256)
#   whose key is ``base64url(PBKDF2-HMAC-SHA256(master_utf8, salt,
#   iterations, dklen=32))``. Authenticated encryption is preserved; PBKDF2
#   supplies the password-based work factor the legacy SHA-256 step lacks.
#
# Unknown ``<name>v<digits>:`` prefixes fail closed (never legacy, never
# plaintext) to prevent downgrade/confusion.

PBKDF2_VERSION = "pbkdf2v1"
PBKDF2_PREFIX = "pbkdf2v1:"
PBKDF2_ITERATIONS = 600_000
PBKDF2_SALT_BYTES = 16
PBKDF2_HASH_NAME = "sha256"

# Fork-native multi-key envelope: same construction as v1 plus an explicit
# key identifier so reads never guess among configured keys:
#     pbkdf2v2:<key_id>:<iterations>:<salt_b64>:<fernet_token>
PBKDF2V2_VERSION = "pbkdf2v2"
PBKDF2V2_PREFIX = "pbkdf2v2:"

ACTIVE_KEY_ID_ENV = "OPEN_NOTEBOOK_ENCRYPTION_KEY_ID"
PREVIOUS_KEYS_ENV = "OPEN_NOTEBOOK_ENCRYPTION_PREVIOUS_KEYS"
DEFAULT_ACTIVE_KEY_ID = "default"

_VERSIONED_PREFIX_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*v[0-9]+:")


def _derive_pbkdf2_fernet_key(
    master_secret: str, salt: bytes, iterations: int
) -> bytes:
    """Derive a Fernet-ready key via PBKDF2-HMAC-SHA256 (UTF-8 master)."""
    raw = hashlib.pbkdf2_hmac(
        PBKDF2_HASH_NAME,
        master_secret.encode("utf-8"),
        salt,
        iterations,
        dklen=32,
    )
    return base64.urlsafe_b64encode(raw)


def encrypt_pbkdf2_value(value: str, master_secret: str) -> str:
    """Encrypt with a fresh random salt under the ``pbkdf2v1:`` envelope."""
    salt = secrets.token_bytes(PBKDF2_SALT_BYTES)
    fernet = Fernet(
        _derive_pbkdf2_fernet_key(master_secret, salt, PBKDF2_ITERATIONS)
    )
    token = fernet.encrypt(value.encode("utf-8")).decode("utf-8")
    salt_b64 = base64.b64encode(salt).decode("ascii")
    return f"{PBKDF2_PREFIX}{PBKDF2_ITERATIONS}:{salt_b64}:{token}"


def is_pbkdf2_token(value: object) -> bool:
    """Exact-prefix check for the ``pbkdf2v1:`` envelope."""
    return isinstance(value, str) and value.startswith(PBKDF2_PREFIX)


def is_pbkdf2v2_token(value: object) -> bool:
    """Exact-prefix check for the ``pbkdf2v2:`` envelope."""
    return isinstance(value, str) and value.startswith(PBKDF2V2_PREFIX)


def get_active_key_id() -> str:
    """Configured active key id (``OPEN_NOTEBOOK_ENCRYPTION_KEY_ID``).

    Blank/unset means the ``"default"`` single-key deployment. Colons are
    rejected: they collide with the envelope delimiter.
    """
    raw = get_secret_from_env(ACTIVE_KEY_ID_ENV)
    key_id = (raw or "").strip() or DEFAULT_ACTIVE_KEY_ID
    if ":" in key_id:
        raise ValueError(
            "Invalid encryption key id: identifiers must not contain ':'."
        )
    return key_id


def get_configured_keys() -> "dict[str, str]":
    """All configured master secrets, active first, in deterministic order.

    Active secret comes from ``OPEN_NOTEBOOK_ENCRYPTION_KEY``; previous
    secrets from ``OPEN_NOTEBOOK_ENCRYPTION_PREVIOUS_KEYS`` as a JSON
    object mapping key id to secret. Duplicate ids (including a clash
    with the active id) and malformed values raise ValueError. Secret
    values never appear in error messages.
    """
    import json

    active_secret = get_secret_from_env("OPEN_NOTEBOOK_ENCRYPTION_KEY")
    if not active_secret:
        raise ValueError(
            "Encryption key not configured. "
            "Set OPEN_NOTEBOOK_ENCRYPTION_KEY to enable encrypted storage."
        )
    active_id = get_active_key_id()
    keys: "dict[str, str]" = {active_id: active_secret}
    raw_previous = get_secret_from_env(PREVIOUS_KEYS_ENV)
    if raw_previous:
        try:
            parsed = json.loads(raw_previous)
        except Exception:
            raise ValueError(
                f"{PREVIOUS_KEYS_ENV} must be a JSON object mapping "
                "key id to secret."
            )
        if not isinstance(parsed, dict):
            raise ValueError(
                f"{PREVIOUS_KEYS_ENV} must be a JSON object mapping "
                "key id to secret."
            )
        for key_id, secret in parsed.items():
            clean_id = str(key_id).strip()
            if not clean_id or ":" in clean_id or not secret:
                raise ValueError(
                    "Invalid previous-key entry: ids must be non-blank "
                    "without ':' and secrets non-empty."
                )
            if clean_id in keys:
                raise ValueError(
                    f"Duplicate encryption key id: '{clean_id}' is already "
                    "configured."
                )
            keys[clean_id] = secret
    return keys


def _parse_envelope_fields(
    token: str, version: str, expected_fields: int
) -> "list[str]":
    """Split and validate a versioned envelope's shape (never decrypts)."""
    parts = token.split(":")
    if len(parts) != expected_fields or parts[0] != version:
        raise ValueError("Malformed versioned credential envelope.")
    return parts


def _parse_iterations(raw: str) -> int:
    try:
        iterations = int(raw)
    except (TypeError, ValueError):
        raise ValueError("Malformed versioned credential envelope.")
    if iterations <= 0:
        raise ValueError("Malformed versioned credential envelope.")
    return iterations


def _parse_salt(raw: str) -> bytes:
    try:
        salt = base64.b64decode(raw)
    except Exception:
        raise ValueError("Malformed versioned credential envelope.")
    if len(salt) < PBKDF2_SALT_BYTES:
        raise ValueError("Malformed versioned credential envelope.")
    return salt


def _decrypt_fernet_token(
    fernet_token: str, master_secret: str, salt: bytes, iterations: int
) -> str:
    """Fernet-decrypt one envelope payload. Wrong keys raise ValueError."""
    try:
        fernet = Fernet(
            _derive_pbkdf2_fernet_key(master_secret, salt, iterations)
        )
        return fernet.decrypt(fernet_token.encode("utf-8")).decode("utf-8")
    except InvalidToken as e:
        raise ValueError(
            "Decryption failed: versioned credential could not be "
            "decrypted. Check OPEN_NOTEBOOK_ENCRYPTION_KEY configuration."
        ) from e


def decrypt_pbkdf2_value(token: str, master_secret: str) -> str:
    """Decrypt a ``pbkdf2v1:`` envelope. Any defect raises ValueError."""
    parts = _parse_envelope_fields(token, PBKDF2_VERSION, 4)
    iterations = _parse_iterations(parts[1])
    salt = _parse_salt(parts[2])
    try:
        return _decrypt_fernet_token(parts[3], master_secret, salt, iterations)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(
            f"Decryption failed for versioned credential: {str(e)}"
        ) from e


def encrypt_pbkdf2v2_value(
    value: str, master_secret: str, key_id: str
) -> str:
    """Encrypt under the ``pbkdf2v2:`` envelope with an explicit key id."""
    if not key_id or ":" in key_id:
        raise ValueError("Key id must be non-blank and contain no ':'.")
    salt = secrets.token_bytes(PBKDF2_SALT_BYTES)
    fernet = Fernet(
        _derive_pbkdf2_fernet_key(master_secret, salt, PBKDF2_ITERATIONS)
    )
    token = fernet.encrypt(value.encode("utf-8")).decode("utf-8")
    salt_b64 = base64.b64encode(salt).decode("ascii")
    return f"{PBKDF2V2_PREFIX}{key_id}:{PBKDF2_ITERATIONS}:{salt_b64}:{token}"


def decrypt_pbkdf2v2_value(
    token: str, keys: "dict[str, str]"
) -> str:
    """Decrypt a ``pbkdf2v2:`` envelope via exact key-id lookup.

    No fallback: an unknown key id or wrong secret raises ValueError, and
    other configured keys are never attempted.
    """
    parts = _parse_envelope_fields(token, PBKDF2V2_VERSION, 5)
    key_id = parts[1]
    if not key_id or key_id not in keys:
        raise ValueError(
            f"Unknown encryption key id: '{key_id}'. Configure the "
            "matching previous key to decrypt this credential."
        )
    iterations = _parse_iterations(parts[2])
    salt = _parse_salt(parts[3])
    try:
        return _decrypt_fernet_token(parts[4], keys[key_id], salt, iterations)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(
            f"Decryption failed for versioned credential: {str(e)}"
        ) from e


def _decrypt_v1_with_keys(token: str, keys: "dict[str, str]") -> str:
    """Decrypt a ``pbkdf2v1:`` envelope against configured keys in order.

    v1 carries no key identity, so candidates are attempted deterministically
    (active first, then previous in configured order). Structural defects
    fail immediately; only wrong-key results advance to the next candidate.
    """
    parts = _parse_envelope_fields(token, PBKDF2_VERSION, 4)
    iterations = _parse_iterations(parts[1])
    salt = _parse_salt(parts[2])
    for candidate in keys.values():
        try:
            return _decrypt_fernet_token(parts[3], candidate, salt, iterations)
        except ValueError:
            continue
    raise ValueError(
        "Decryption failed: none of the configured keys decrypted "
        "the pbkdf2v1 credential. Check OPEN_NOTEBOOK_ENCRYPTION_KEY "
        "and previous-keys configuration."
    )


def _decrypt_legacy_with_keys(value: str, keys: "dict[str, str]") -> str:
    """Legacy Fernet/SHA-256 decrypt across configured keys in order.

    Non-Fernet-shaped input is key-independent: the historic plaintext
    passthrough applies on first inspection. Fernet-shaped input that no
    configured key opens raises wrong-key ValueError.
    """
    if not looks_like_fernet_token(value):
        return value
    for candidate in keys.values():
        fernet = Fernet(_ensure_fernet_key(candidate).encode())
        try:
            return fernet.decrypt(value.encode()).decode()
        except InvalidToken:
            continue
    raise ValueError(
        "Decryption failed: data appears to be encrypted but key is "
        "incorrect. Check OPEN_NOTEBOOK_ENCRYPTION_KEY configuration."
    )
