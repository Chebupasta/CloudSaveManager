"""
Общие константы приложения: пути к папке настроек, файлам конфигурации и т.д.
"""
import os
import sys

APP_NAME = 'CloudSaveManager'


def get_app_dir() -> str:
    """Возвращает (и создаёт) папку для хранения настроек приложения.

    Windows:  %APPDATA%\\CloudSaveManager
    Linux/Mac: ~/.config/CloudSaveManager
    """
    if sys.platform.startswith('win'):
        base = os.getenv('APPDATA') or os.path.expanduser('~')
    else:
        base = os.getenv('XDG_CONFIG_HOME') or os.path.join(os.path.expanduser('~'), '.config')
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def get_backups_dir() -> str:
    path = os.path.join(get_app_dir(), 'backups')
    os.makedirs(path, exist_ok=True)
    return path


def get_log_path() -> str:
    return os.path.join(get_app_dir(), 'log.txt')


GAMES_FILE = 'games.json'
ACCOUNTS_FILE = 'accounts.json'
SETTINGS_FILE = 'settings.json'
SECRETS_FALLBACK_FILE = 'secrets.json'

# Максимальный размер лог-файла в байтах перед обрезкой
MAX_LOG_SIZE = 2 * 1024 * 1024

# Сколько последних локальных резервных копий хранить на слот
MAX_BACKUPS_PER_SLOT = 5

# Интервал опроса процессов (сек.)
PROCESS_POLL_INTERVAL = 5

# Сколько секунд подождать после закрытия игры перед выгрузкой
# (чтобы игра успела дописать файл сохранения на диск)
UPLOAD_DELAY_AFTER_EXIT = 4

# Сколько опросов подряд процесс должен отсутствовать, чтобы игра считалась закрытой
EXIT_CONFIRM_POLLS = 2

# Паузы (секунды) перед повторами неудачной автовыгрузки
RETRY_DELAYS = (30, 120, 600, 1800)

# Файл сохранения должен не меняться столько секунд, чтобы его можно было выгрузить во время игры
PERIODIC_STABLE_SECONDS = 20

# Значения, которые зависят от настроек пользователя (обновляются при загрузке/сохранении настроек)
# max_auto_snapshot_mb: автоснимки не делаются для слотов больше этого размера (0 — без ограничения)
RUNTIME = {'max_backups': MAX_BACKUPS_PER_SLOT, 'max_auto_snapshots': 10, 'max_auto_snapshot_mb': 300}
