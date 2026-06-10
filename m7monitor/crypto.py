from datetime import datetime
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def aes_cbc_encrypt(key: bytes, data: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.CBC(bytes(16)), backend=default_backend())
    encryptor = cipher.encryptor()
    return encryptor.update(data) + encryptor.finalize()


def aes_ecb_encrypt(key: bytes, data: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
    encryptor = cipher.encryptor()
    return encryptor.update(data) + encryptor.finalize()


def watch_date_bytes(date: datetime) -> bytes:
    from datetime import timezone
    utc = date.astimezone(timezone.utc)
    return (
        utc.year.to_bytes(2, "little")
        + bytes([utc.month, utc.day, utc.hour, utc.minute, utc.second])
    )
