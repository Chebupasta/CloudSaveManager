"""
Утилиты для поиска файлов сохранений на диске.

Игры From Software (Dark Souls III, Elden Ring и т.д.) хранят сохранения
в подпапке, названной длинным числовым ID (Steam ID пользователя), поэтому
точный путь заранее неизвестен — нужно просканировать родительскую папку.
Этот модуль умеет собирать список кандидатов под Windows и Linux
(Steam Proton / нативный Wine) и на Mac.
"""
import os
import sys
from typing import List


def _windows_appdata_base(folder_name: str) -> List[str]:
    appdata = os.getenv('APPDATA')
    if not appdata:
        return []
    return [os.path.join(appdata, folder_name)]


def _proton_wine_bases(folder_name: str, steam_app_id: str) -> List[str]:
    """Возвращает возможные базовые папки для игр, запущенных через Steam
    Proton или обычный Wine на Linux/Mac."""
    home = os.path.expanduser('~')
    user = os.getenv('USER', os.getenv('USERNAME', 'steamuser'))
    bases = []
    if steam_app_id:
        bases += [
            os.path.join(home, '.steam/steam/steamapps/compatdata', steam_app_id,
                         'pfx/drive_c/users/steamuser/AppData/Roaming', folder_name),
            os.path.join(home, '.local/share/Steam/steamapps/compatdata', steam_app_id,
                         'pfx/drive_c/users/steamuser/AppData/Roaming', folder_name),
            os.path.join(home, '.var/app/com.valvesoftware.Steam/.local/share/Steam/'
                                'steamapps/compatdata', steam_app_id,
                         'pfx/drive_c/users/steamuser/AppData/Roaming', folder_name),
        ]
    bases.append(os.path.join(home, '.wine/drive_c/users', user, 'AppData/Roaming', folder_name))
    return bases


def find_slot_files(folder_name: str, filename: str, steam_app_id: str = '') -> List[str]:
    """Ищет файлы вида <base>/<folder_name>/<любой_id>/<filename>.

    folder_name — имя папки игры внутри AppData/Roaming (например 'DarkSoulsIII').
    filename — имя файла сохранения (например 'DS30000.sl2').
    steam_app_id — Steam App ID игры, нужен только для поиска в compatdata на Linux.

    Возвращает список найденных абсолютных путей (обычно один, но может
    быть несколько, если на одном компьютере несколько Steam-аккаунтов).
    """
    if sys.platform.startswith('win'):
        bases = _windows_appdata_base(folder_name)
    else:
        bases = _proton_wine_bases(folder_name, steam_app_id)

    found = []
    seen_real = set()
    for base in bases:
        if not os.path.isdir(base):
            continue
        try:
            entries = os.listdir(base)
        except OSError:
            continue
        for entry in entries:
            candidate = os.path.join(base, entry, filename)
            if os.path.isfile(candidate):
                real = os.path.realpath(candidate)
                if real not in seen_real:
                    seen_real.add(real)
                    found.append(candidate)
    return found


def expand_user_path(path: str) -> str:
    """Разворачивает переменные окружения и ~ в произвольном пути."""
    return os.path.normpath(os.path.expanduser(os.path.expandvars(path)))
