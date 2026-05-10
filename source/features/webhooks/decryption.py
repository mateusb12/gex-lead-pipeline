import base64
import json
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from source.shared.config import settings

GRUMMER_SECRET_PATH = Path("assets/grummer_secret.txt")


class DecryptionError(Exception):
    pass


class MissingGrummerSecretError(DecryptionError):
    pass


def decrypt_grummer_payload(*, iv_base64: str, ciphertext_base64: str) -> dict[str, Any]:
    key = _load_grummer_secret_key()

    try:
        iv = base64.b64decode(iv_base64, validate=True)
        ciphertext = base64.b64decode(ciphertext_base64, validate=True)
    except Exception as exc:
        raise DecryptionError("invalid base64 iv or ciphertext") from exc

    if len(key) != 32:
        raise DecryptionError("grummer secret must be 32 bytes for AES-256")

    if len(iv) != 16:
        raise DecryptionError("AES-CBC iv must be 16 bytes")

    try:
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        decryptor = cipher.decryptor()

        padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()

        unpadder = PKCS7(128).unpadder()
        plaintext = unpadder.update(padded_plaintext) + unpadder.finalize()

        decoded = plaintext.decode("utf-8")
        payload = json.loads(decoded)
    except Exception as exc:
        raise DecryptionError("failed to decrypt grummer payload") from exc

    if not isinstance(payload, dict):
        raise DecryptionError("decrypted grummer payload must be a JSON object")

    return payload


def _load_grummer_secret_key() -> bytes:
    secret_hex = settings.grummer_secret_hex

    if not secret_hex and GRUMMER_SECRET_PATH.exists():
        secret_hex = GRUMMER_SECRET_PATH.read_text(encoding="utf-8").strip()

    if not secret_hex:
        raise MissingGrummerSecretError(
            "GRUMMER_SECRET_HEX is not configured and assets/grummer_secret.txt was not found"
        )

    try:
        return bytes.fromhex(secret_hex.strip())
    except ValueError as exc:
        raise DecryptionError("grummer secret must be a valid hex string") from exc
