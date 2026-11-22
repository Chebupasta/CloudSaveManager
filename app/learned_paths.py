"""
Локальная "память" программы о том, где лежат сохранения уже
настроенных игр — ключ: имя процесса (.exe).

Встроенные пресеты (app/presets.py) дают точный путь только для пары
известных игр (Dark Souls III, Elden Ring). Для любой другой игры путь
находится эвристическим поиском (app/auto_detect.py) — то есть угадыванием
по названию папок и недавним изменениям. Чтобы не гадать заново при
каждом добавлении/переустановке, как только путь подтверждён (неважно,
через автопоиск или выбран вручную), программа запоминает его — не как
абсолютный путь (он у каждого пользователя свой), а как пару
"тип типовой папки" + "относительный путь внутри неё". Это позволяет
восстановить точный путь на любом компьютере того же пользователя, и по
сути превращает каждую успешно настроенную игру в маленький личный
пресет, растущий вместе с библиотекой игр.
"""
import json
import os
from typing import Dict, Optional

from app import auto_detect
from app.constants import get_app_dir

LEARNED_FILE = 'learned_paths.json'

# Эти "корни" не переносимы между компьютерами/переустановками (путь к
# exe конкретной установки), поэтому запоминать их бессмысленно.
_NON_PORTABLE_ROOTS = {'exe_dir', 'exe_parent'}


def _path() -> str:
    return os.path.join(get_app_dir(), LEARNED_FILE)


def _load() -> Dict:
    p = _path()
    if os.path.isfile(p):
        try:
            with open(p, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save(data: Dict):
    with open(_path(), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _key(process_name: str, discriminator: str = '') -> str:
    """Ключ: процесс + идентификатор слота. Без идентификатора второй слот
    с тем же .exe перезаписывал путь первого."""
    key = process_name.strip().lower()
    if discriminator:
        key += '|' + discriminator.strip().lower()
    return key


def remember(process_name: str, root_key: str, relative: str, is_directory: bool,
             discriminator: str = ''):
    """Запоминает успешно найденный/подтверждённый путь для процесса и слота."""
    if not process_name or not relative or root_key in _NON_PORTABLE_ROOTS:
        return
    data = _load()
    entry = {
        'root_key': root_key,
        'relative': relative,
        'is_directory': is_directory,
    }
    data[_key(process_name, discriminator)] = entry
    # Простой ключ оставляем для совместимости со старыми вызовами без
    # идентификатора слота — но не перезаписываем его вторым слотом.
    if discriminator:
        data.setdefault(_key(process_name), entry)
    _save(data)


def recall(process_name: str, discriminator: str = '') -> Optional[Dict]:
    """Возвращает запомненную запись как есть (без проверки, существует
    ли путь на диске прямо сейчас)."""
    if not process_name:
        return None
    data = _load()
    return (data.get(_key(process_name, discriminator)) if discriminator else None) or \
        data.get(_key(process_name))


def try_resolve(process_name: str, discriminator: str = '') -> Optional[Dict]:
    """Восстанавливает абсолютный путь из запомненных данных на ЭТОМ
    компьютере и проверяет, что он всё ещё существует. Возвращает None,
    если для процесса ничего не запомнено, либо путь больше не существует
    (например, игру переустановили в другое место, или это была
    случайная находка эвристики, а не настоящее сохранение)."""
    entry = recall(process_name, discriminator)
    if not entry:
        return None
    root_path = auto_detect.resolve_root(entry.get('root_key', ''))
    if not root_path:
        return None
    full_path = os.path.normpath(os.path.join(root_path, entry['relative']))
    is_dir = bool(entry.get('is_directory'))
    exists = os.path.isdir(full_path) if is_dir else os.path.isfile(full_path)
    if not exists:
        return None
    try:
        mtime = os.path.getmtime(full_path)
    except OSError:
        mtime = 0
    return {
        'path': full_path,
        'is_dir': is_dir,
        'reason': 'уже находили для этого процесса ранее',
        'mtime': mtime,
    }


def forget(process_name: str, discriminator: str = ''):
    data = _load()
    for key in (_key(process_name, discriminator), _key(process_name)):
        if key in data:
            del data[key]
    _save(data)
