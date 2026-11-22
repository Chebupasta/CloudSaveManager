"""
Хранение чувствительных данных (токены, пароли) отдельно от основного
конфига. По возможности используется системное хранилище паролей через
пакет `keyring` (Windows Credential Manager / macOS Keychain / Secret
Service на Linux). Если `keyring` недоступен или недоступен бэкенд —
используется резервный локальный JSON-файл в папке настроек приложения
(как и в исходной версии программы, где токен GitHub хранился в
`.github_creds`).
"""
import json
import os

from app.constants import get_app_dir, SECRETS_FALLBACK_FILE

SERVICE_NAME = 'CloudSaveManager'

try:
    import keyring
    from keyring.errors import KeyringError
    _KEYRING_AVAILABLE = True
except Exception:  # pragma: no cover - keyring может отсутствовать
    keyring = None
    KeyringError = Exception
    _KEYRING_AVAILABLE = False


def _fallback_path() -> str:
    return os.path.join(get_app_dir(), SECRETS_FALLBACK_FILE)


def _load_fallback() -> dict:
    path = _fallback_path()
    if os.path.isfile(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_fallback(data: dict):
    path = _fallback_path()
    # Сразу создаём файл с правами 0600, чтобы секреты не были читаемы другими
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_secure_backend_available() -> bool:
    """True, если чувствительные данные хранятся в системном хранилище,
    а не в обычном файле на диске."""
    if not _KEYRING_AVAILABLE:
        return False
    try:
        backend = keyring.get_keyring()
        # keyring использует "fail" бэкенд, если не нашёл подходящий
        module = backend.__class__.__module__.lower()
        return 'fail' not in module and 'null' not in module
    except Exception:
        return False


def set_secret(account_id: str, value: str):
    if _KEYRING_AVAILABLE and is_secure_backend_available():
        try:
            keyring.set_password(SERVICE_NAME, account_id, value)
            return
        except KeyringError:
            pass
    data = _load_fallback()
    data[account_id] = value
    _save_fallback(data)


def get_secret(account_id: str) -> str:
    if _KEYRING_AVAILABLE and is_secure_backend_available():
        try:
            value = keyring.get_password(SERVICE_NAME, account_id)
            if value is not None:
                return value
        except KeyringError:
            pass
    data = _load_fallback()
    return data.get(account_id, '')


def delete_secret(account_id: str):
    if _KEYRING_AVAILABLE and is_secure_backend_available():
        try:
            keyring.delete_password(SERVICE_NAME, account_id)
        except KeyringError:
            pass
    data = _load_fallback()
    if account_id in data:
        del data[account_id]
        _save_fallback(data)
