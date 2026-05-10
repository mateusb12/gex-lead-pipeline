import base64
import json

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from source.features.webhooks import decryption


def test_decriptar_payload_grummer_com_aes_cbc_e_pkcs7(monkeypatch):
    key = bytes.fromhex("00" * 32)
    iv = bytes.fromhex("11" * 16)

    payload = {
        "transaction_id": "ORD-TEST-CRYPT-001",
        "event": "order.approved",
    }

    plaintext = json.dumps(payload).encode("utf-8")

    padder = PKCS7(128).padder()
    padded_plaintext = padder.update(plaintext) + padder.finalize()

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded_plaintext) + encryptor.finalize()

    monkeypatch.setattr(decryption.settings, "grummer_secret_hex", key.hex())

    result = decryption.decrypt_grummer_payload(
        iv_base64=base64.b64encode(iv).decode("ascii"),
        ciphertext_base64=base64.b64encode(ciphertext).decode("ascii"),
    )

    assert result == payload
