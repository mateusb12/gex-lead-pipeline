import base64
import json

import pytest
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


def test_validate_grummer_secret_config_passa_com_env_hex_valido(monkeypatch):
    monkeypatch.setattr(decryption.settings, "grummer_secret_hex", "00" * 32)

    decryption.validate_grummer_secret_config()


def test_validate_grummer_secret_config_passa_lendo_arquivo_quando_env_vazio(monkeypatch, tmp_path):
    secret_path = tmp_path / "grummer_secret.txt"
    secret_path.write_text("11" * 32, encoding="utf-8")

    monkeypatch.setattr(decryption.settings, "grummer_secret_hex", "")
    monkeypatch.setattr(decryption, "GRUMMER_SECRET_PATH", secret_path)

    decryption.validate_grummer_secret_config()


def test_validate_grummer_secret_config_falha_sem_env_nem_arquivo(monkeypatch, tmp_path):
    monkeypatch.setattr(decryption.settings, "grummer_secret_hex", "")
    monkeypatch.setattr(decryption, "GRUMMER_SECRET_PATH", tmp_path / "missing.txt")

    with pytest.raises(
        decryption.MissingGrummerSecretError,
        match="GRUMMER_SECRET_HEX is not configured and assets/grummer_secret.txt was not found",
    ):
        decryption.validate_grummer_secret_config()


def test_validate_grummer_secret_config_falha_com_hex_invalido(monkeypatch):
    monkeypatch.setattr(decryption.settings, "grummer_secret_hex", "not-hex")

    with pytest.raises(decryption.DecryptionError, match="grummer secret must be a valid hex string"):
        decryption.validate_grummer_secret_config()


def test_validate_grummer_secret_config_falha_com_tamanho_diferente_de_32_bytes(monkeypatch):
    monkeypatch.setattr(decryption.settings, "grummer_secret_hex", "00" * 31)

    with pytest.raises(decryption.DecryptionError, match="grummer secret must be 32 bytes for AES-256"):
        decryption.validate_grummer_secret_config()
