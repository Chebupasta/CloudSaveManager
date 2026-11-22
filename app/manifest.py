"""
База путей сохранений игр из открытого манифеста Ludusavi
(https://github.com/mtkennerly/ludusavi-manifest). Манифест большой (~17 МБ YAML),
поэтому один раз скачивается и сжимается в компактный индекс (только пути
сохранений для текущей ОС и Steam App ID); дальше поиск идёт по индексу локально.
"""
import glob
import json
import os
import re
import sys
import tempfile
import time
from typing import Callable, Dict, List, Optional, Set, Tuple

import requests

from app.constants import get_app_dir
from app.logger import log_action

MANIFEST_URL = 'https://raw.githubusercontent.com/mtkennerly/ludusavi-manifest/master/data/manifest.yaml'
MAX_AGE_DAYS = 30
CURRENT_OS = 'windows' if sys.platform.startswith('win') else ('mac' if sys.platform == 'darwin' else 'linux')

_index_cache: Dict[str, Dict] = {}
_norm_cache: Dict[str, str] = {}


def index_path() -> str:
    return os.path.join(get_app_dir(), 'save_paths_index.json')


def _normalize(text: str) -> str:
    return re.sub(r'[^a-z0-9а-яё]+', '', (text or '').lower())


def _os_ok(when) -> bool:
    if not when:
        return True
    return any((w or {}).get('os') in (None, CURRENT_OS) for w in when)


def build_index(raw: Dict) -> Dict[str, Dict]:
    """Сжимает манифест: имя игры -> {p: [шаблоны путей сохранений], s: steam id, i: [папки установки]}."""
    out = {}
    for name, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        paths = []
        for template, meta in (entry.get('files') or {}).items():
            meta = meta or {}
            if 'save' in (meta.get('tags') or []) and _os_ok(meta.get('when')):
                paths.append(template)
        steam = (entry.get('steam') or {}).get('id')
        if not paths and not steam:
            continue
        item = {'p': paths}
        if steam:
            item['s'] = steam
        install = list((entry.get('installDir') or {}).keys())
        if install:
            item['i'] = install
        out[name] = item
    return out


def index_is_fresh() -> bool:
    path = index_path()
    return os.path.isfile(path) and (time.time() - os.path.getmtime(path)) < MAX_AGE_DAYS * 86400


def update_index(progress: Optional[Callable[[int, str], None]] = None) -> Tuple[bool, str]:
    """Скачивает манифест и пересобирает индекс. Долгая операция (десятки секунд)."""
    def report(pct, text):
        if progress:
            progress(pct, text)

    tmp = tempfile.NamedTemporaryFile(suffix='.yaml', delete=False)
    tmp.close()
    try:
        report(0, 'Скачивание базы путей сохранений...')
        with requests.get(MANIFEST_URL, stream=True, timeout=30) as r:
            if r.status_code != 200:
                return False, f'Не удалось скачать базу: HTTP {r.status_code}'
            total = int(r.headers.get('Content-Length') or 0)
            done = 0
            with open(tmp.name, 'wb') as f:
                for chunk in r.iter_content(chunk_size=262144):
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        report(int(60 * done / total), 'Скачивание базы путей сохранений...')
        report(65, 'Обработка базы (может занять около минуты)...')
        index = _parse_manifest_file(tmp.name, report)
        report(95, 'Сохранение индекса...')
        part = index_path() + '.part'
        with open(part, 'w', encoding='utf-8') as f:
            json.dump(index, f, ensure_ascii=False)
        os.replace(part, index_path())  # атомарно: недописанный индекс не появится
        _index_cache.clear()
        _norm_cache.clear()
        log_action('manifest', 'updated', f'{len(index)} игр')
        report(100, 'Готово')
        return True, f'База обновлена: {len(index)} игр.'
    except (requests.RequestException, OSError, ImportError, ValueError) as e:
        log_action('manifest', 'fail', str(e))
        return False, f'Не удалось обновить базу: {e}'
    finally:
        if os.path.exists(tmp.name):
            os.remove(tmp.name)


def _parse_manifest_file(path: str, report, throttle: bool = True) -> Dict[str, Dict]:
    """Разбирает большой YAML порциями (по ~300 игр) с короткими паузами между ними —
    так интерфейс не замирает, пока в фоне строится индекс."""
    import yaml
    loader = getattr(yaml, 'CSafeLoader', yaml.SafeLoader)
    size = max(1, os.path.getsize(path))
    index: Dict[str, Dict] = {}
    chunk: List[str] = []
    blocks = 0
    read_bytes = 0

    def flush():
        nonlocal chunk, blocks
        started = time.perf_counter()
        if chunk:
            data = yaml.load(''.join(chunk), Loader=loader)
            if isinstance(data, dict):
                index.update(build_index(data))
        chunk, blocks = [], 0
        # Работаем ~20% времени: фоновая подготовка базы не должна заметно грузить процессор
        time.sleep(max(0.01, (time.perf_counter() - started) * 4) if throttle else 0.01)

    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            read_bytes += len(line.encode('utf-8'))
            if line.startswith('---'):
                continue
            if line[:1] not in (' ', '\t', '\n', '\r', '#') and line.strip():
                if blocks >= 150:
                    flush()
                    report(65 + int(30 * read_bytes / size), 'Обработка базы...')
                blocks += 1
            chunk.append(line)
    flush()
    return index


def load_index() -> Dict[str, Dict]:
    if _index_cache:
        return _index_cache
    path = index_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    _index_cache.update(data)
    return _index_cache


def lookup(names: Set[str], limit: int = 3) -> List[Tuple[str, Dict]]:
    """Ищет игры в индексе по набору возможных названий (точное совпадение
    нормализованных имён, затем близкое вхождение)."""
    index = load_index()
    if not index or not names:
        return []
    targets = {_normalize(n) for n in names if _normalize(n)}
    targets = {t for t in targets if len(t) >= 4}
    if not _norm_cache:
        for name, item in index.items():
            _norm_cache[name] = _normalize(name)
    exact, near = [], []
    for name, item in index.items():
        keys = {_norm_cache[name]} | {_normalize(i) for i in item.get('i', [])}
        if keys & targets:
            exact.append((name, item))
        elif any(len(k) >= 6 and any((t in k or k in t) and abs(len(k) - len(t)) <= 6 for t in targets)
                 for k in keys):
            near.append((name, item))
    return (exact + near)[:limit]


def _placeholders(base_dirs: List[str]) -> Dict[str, List[str]]:
    home = os.path.expanduser('~')
    appdata = os.environ.get('APPDATA') or os.path.join(home, 'AppData', 'Roaming')
    local = os.environ.get('LOCALAPPDATA') or os.path.join(home, 'AppData', 'Local')
    docs = os.path.join(home, 'Documents')
    return {
        '<home>': [home],
        '<winAppData>': [appdata],
        '<winLocalAppData>': [local],
        '<winLocalAppDataLow>': [os.path.join(os.path.dirname(local), 'LocalLow')],
        '<winDocuments>': [docs],
        '<winPublic>': [os.environ.get('PUBLIC') or 'C:/Users/Public'],
        '<winProgramData>': [os.environ.get('PROGRAMDATA') or 'C:/ProgramData'],
        '<xdgData>': [os.environ.get('XDG_DATA_HOME') or os.path.join(home, '.local', 'share')],
        '<xdgConfig>': [os.environ.get('XDG_CONFIG_HOME') or os.path.join(home, '.config')],
        '<osUserName>': [os.environ.get('USERNAME') or os.environ.get('USER') or '*'],
        '<storeUserId>': ['*'],
        '<storeGameId>': ['*'],
        '<base>': base_dirs or [],
        '<root>': [],
        '<game>': [],
    }


def expand(template: str, base_dirs: Optional[List[str]] = None, install_names: Optional[List[str]] = None,
           roots: Optional[List[str]] = None) -> List[str]:
    """Подставляет плейсхолдеры Ludusavi и раскрывает маски: возвращает существующие пути."""
    ph = _placeholders(base_dirs or [])
    ph['<root>'] = roots or []
    ph['<game>'] = install_names or []
    results = [template]
    for token, values in ph.items():
        if token not in template:
            continue
        results = [r.replace(token, v) for r in results for v in values]
    found = []
    for pattern in results:
        if '<' in pattern and '>' in pattern:
            continue  # остались неизвестные плейсхолдеры
        found.extend(glob.glob(pattern.replace('\\', '/')))
    return list(dict.fromkeys(os.path.normpath(p) for p in found if os.path.exists(p)))


def _ancestors(exe_path: str, depth: int = 4) -> Tuple[List[str], List[str]]:
    base_dirs, roots = [], []
    if not exe_path:
        return base_dirs, roots
    cur = os.path.dirname(os.path.abspath(exe_path))
    for _ in range(depth):
        base_dirs.append(cur)
        if os.path.basename(cur).lower() == 'common' and os.path.basename(os.path.dirname(cur)).lower() == 'steamapps':
            roots.append(os.path.dirname(os.path.dirname(cur)))
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return base_dirs, roots


def find_candidates(names: Set[str], exe_path: str = '') -> List[Dict]:
    """Кандидаты пути к сохранению из базы. Формат совместим с auto_detect."""
    base_dirs, roots = _ancestors(exe_path)
    out = []
    for game_name, item in lookup(names):
        for template in item.get('p', []):
            for path in expand(template, base_dirs, item.get('i', []), roots):
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    mtime = 0
                out.append({'path': path, 'mtime': mtime, 'is_dir': os.path.isdir(path),
                            'reason': f'база путей: {game_name}', 'root_key': 'manifest',
                            'relative': os.path.basename(path)})
    return out


def steam_id_for(names: Set[str]) -> Optional[str]:
    for _name, item in lookup(names, limit=1):
        if item.get('s'):
            return str(item['s'])
    return None
