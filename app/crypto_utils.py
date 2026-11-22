"""
Необязательное шифрование сохранений перед выгрузкой в облако (AES-256-GCM,
ключ из пароля через scrypt). Формат файла: MAGIC | salt(16) | nonce(12) | шифртекст+тег.
Пароль хранится только у вас (в защищённом хранилище системы) и в облако не попадает —
потеряв его, расшифровать облачные копии нельзя.
"""
import secrets

MAGIC = b'CSMENC1\0'
SALT_LEN, NONCE_LEN = 16, 12
_SCRYPT_N = 2 ** 15


class CryptoError(Exception):
    """Неверный пароль, повреждённый файл или недоступное шифрование."""


def _load():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
        return AESGCM, Scrypt
    except ImportError as e:
        raise CryptoError('Для шифрования нужен пакет cryptography (pip install cryptography).') from e


def _key(passphrase: str, salt: bytes, scrypt_cls) -> bytes:
    return scrypt_cls(salt=salt, length=32, n=_SCRYPT_N, r=8, p=1).derive(passphrase.encode('utf-8'))


def is_encrypted(path: str) -> bool:
    try:
        with open(path, 'rb') as f:
            return f.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def encrypt_file(src: str, dst: str, passphrase: str) -> None:
    if not passphrase:
        raise CryptoError('Не задан пароль шифрования.')
    aesgcm_cls, scrypt_cls = _load()
    salt, nonce = secrets.token_bytes(SALT_LEN), secrets.token_bytes(NONCE_LEN)
    with open(src, 'rb') as f:
        data = f.read()
    blob = aesgcm_cls(_key(passphrase, salt, scrypt_cls)).encrypt(nonce, data, MAGIC)
    with open(dst, 'wb') as f:
        f.write(MAGIC + salt + nonce + blob)


def decrypt_file(src: str, dst: str, passphrase: str) -> None:
    if not passphrase:
        raise CryptoError('Облачная копия зашифрована — задайте пароль шифрования в аккаунте.')
    aesgcm_cls, scrypt_cls = _load()
    with open(src, 'rb') as f:
        raw = f.read()
    if not raw.startswith(MAGIC) or len(raw) < len(MAGIC) + SALT_LEN + NONCE_LEN + 16:
        raise CryptoError('Файл не является зашифрованным сохранением или повреждён.')
    off = len(MAGIC)
    salt, nonce, blob = raw[off:off + SALT_LEN], raw[off + SALT_LEN:off + SALT_LEN + NONCE_LEN], raw[off + SALT_LEN + NONCE_LEN:]
    try:
        data = aesgcm_cls(_key(passphrase, salt, scrypt_cls)).decrypt(nonce, blob, MAGIC)
    except Exception as e:  # InvalidTag: неверный пароль либо файл изменён
        raise CryptoError('Не удалось расшифровать: неверный пароль или файл повреждён.') from e
    with open(dst, 'wb') as f:
        f.write(data)
