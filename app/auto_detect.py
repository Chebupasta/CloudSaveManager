"""
Логика автоматического определения:
  1) какой процесс отслеживать (пользователь просто выбирает игру из
     списка запущенных программ — не нужно знать/вводить имя .exe);
  2) где лежит файл или папка сохранения (эвристический поиск по типовым
     папкам + анализ недавно изменённых файлов — не нужно знать путь).

Модуль не зависит от PyQt, чтобы его было легко тестировать отдельно.
Обёртка для запуска поиска в фоновом потоке — в app/ui/auto_detect_dialogs.py.
"""
import os
import re
import sys
import time
from typing import List, Dict, Set, Callable, Optional, Tuple

import psutil

# Процессы, которые почти наверняка не являются игрой — не показываем их
# в списке выбора, чтобы не заставлять пользователя искать иголку в стоге сена.
_PROCESS_BLOCKLIST = {
    'system', 'system idle process', 'registry', 'idle',
    'svchost.exe', 'explorer.exe', 'dwm.exe', 'csrss.exe', 'wininit.exe',
    'winlogon.exe', 'services.exe', 'lsass.exe', 'smss.exe', 'taskhostw.exe',
    'runtimebroker.exe', 'searchindexer.exe', 'searchapp.exe', 'conhost.exe',
    'ctfmon.exe', 'dllhost.exe', 'fontdrvhost.exe', 'sihost.exe',
    'startmenuexperiencehost.exe', 'shellexperiencehost.exe',
    'applicationframehost.exe', 'backgroundtaskhost.exe',
    'securityhealthservice.exe', 'securityhealthsystray.exe', 'wmiprvse.exe',
    'spoolsv.exe', 'audiodg.exe', 'lsaiso.exe', 'memcompression.exe',
    'systemsettings.exe', 'textinputhost.exe', 'crashpad_handler.exe',
    'cloudsavemanager.exe', 'python.exe', 'python3.exe', 'pythonw.exe',
    'systemd', 'bash', 'sh', 'kthreadd', 'kworker',
}

# Папки, которые почти никогда не содержат сохранения игр — пропускаем их
# при поиске, чтобы не тратить время и не засорять результаты.
_SKIP_DIR_NAMES = {
    'cache', 'gpucache', 'code cache', 'crashpad', 'crash reports',
    'temp', 'tmp', 'logs', 'log', 'webcache', 'service worker',
    '.git', 'node_modules', '__pycache__', 'crashdumps', 'update',
    'updater', 'installer', 'redist', 'directx', 'vcredist',
}

_ENGINE_TOKENS = {
    'win64', 'win32', 'x64', 'x86', 'shipping', 'retail', 'final',
    'release', 'debug', 'client', 'server', 'launcher', 'app', 'exe',
}

_GENERIC_DIR_NAMES = {
    'binaries', 'win64', 'win32', 'x64', 'x86', 'shipping', 'retail',
    'bin', 'game', 'content', 'engine', 'steamapps', 'common',
    'program files', 'program files (x86)', 'steamlibrary',
}


def list_running_processes() -> List[Dict]:
    """Возвращает список уникальных запущенных программ:
    [{'name', 'exe', 'create_time'}]. Системные и заведомо неигровые
    процессы отфильтрованы. create_time (unix-время запуска) используется,
    чтобы потом искать только файлы, изменённые ПОСЛЕ старта игры, а не
    вслепую за последние несколько часов."""
    own_pid = os.getpid()
    seen = {}
    for proc in psutil.process_iter(attrs=['pid', 'name', 'exe', 'create_time']):
        try:
            if proc.info['pid'] == own_pid:
                continue
            name = proc.info.get('name') or ''
            if not name or name.lower() in _PROCESS_BLOCKLIST:
                continue
            exe = proc.info.get('exe') or ''
            key = (name.lower(), exe)
            if key not in seen:
                seen[key] = {'name': name, 'exe': exe, 'create_time': proc.info.get('create_time')}
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return sorted(seen.values(), key=lambda p: p['name'].lower())


def _normalize(text: str) -> str:
    return re.sub(r'[^a-z0-9]', '', text.lower())


def guess_candidate_names(exe_path: str = '', extra_text: str = '') -> Set[str]:
    """Собирает набор возможных "имён" игры на основе пути к exe-файлу и/или
    произвольного текста (например, названия игры, введённого пользователем),
    чтобы затем искать похожие по названию папки на диске."""
    candidates: Set[str] = set()

    if exe_path:
        stem = os.path.splitext(os.path.basename(exe_path))[0]
        if stem:
            candidates.add(stem)
        words = [w for w in re.findall(r'[A-Za-z0-9]+', stem) if w.lower() not in _ENGINE_TOKENS]
        if words:
            candidates.add(''.join(words))

        parts = [p for p in os.path.normpath(exe_path).split(os.sep) if p]
        for part in reversed(parts[:-1][-5:]):
            if part.lower() not in _GENERIC_DIR_NAMES and not re.match(r'^[0-9a-fA-F]{8,}$', part):
                candidates.add(part)

    if extra_text:
        words = re.findall(r'[A-Za-z0-9А-Яа-яЁё]+', extra_text)
        if words:
            candidates.add(''.join(words))
            candidates.add(extra_text.strip())

    return {c for c in candidates if c and len(_normalize(c)) >= 3}


def _prettify(word: str) -> str:
    pretty = re.sub(r'(?<=[a-zа-я0-9])(?=[A-ZА-Я])', ' ', word).replace('_', ' ').replace('-', ' ')
    return ' '.join(pretty.split())


def guess_pretty_name(exe_path: str) -> str:
    """Пытается предположить человекочитаемое название игры по пути к exe.
    В первую очередь доверяем имени самого exe-файла (самый надёжный
    признак), и только потом — родительским папкам, чтобы случайные
    промежуточные каталоги (например, временные) не портили угадывание."""
    if not exe_path:
        return ''
    stem = os.path.splitext(os.path.basename(exe_path))[0]
    words = [w for w in re.findall(r'[A-Za-z0-9]+', stem) if w.lower() not in _ENGINE_TOKENS]
    if words:
        return _prettify(''.join(words))

    parts = [p for p in os.path.normpath(exe_path).split(os.sep) if p]
    for part in reversed(parts[:-1][-3:]):
        if part.lower() not in _GENERIC_DIR_NAMES and not re.match(r'^[0-9a-fA-F]{8,}$', part) \
                and len(_normalize(part)) >= 3:
            return _prettify(part)
    return ''


def _platform_root_map() -> Dict[str, str]:
    """Типовые "портируемые" корни (те же ключи имеют смысл на любом
    компьютере пользователя, в отличие от пути к exe конкретной
    установки) — используются и для поиска, и для восстановления
    запомненных путей (learned_paths.py)."""
    mapping: Dict[str, str] = {}
    if sys.platform.startswith('win'):
        appdata = os.getenv('APPDATA')
        localappdata = os.getenv('LOCALAPPDATA')
        userprofile = os.getenv('USERPROFILE') or os.path.expanduser('~')
        if appdata:
            mapping['appdata'] = appdata
        if localappdata:
            mapping['localappdata'] = localappdata
            mapping['locallow'] = os.path.join(os.path.dirname(localappdata), 'LocalLow')
        docs = os.path.join(userprofile, 'Documents')
        mapping['documents'] = docs
        mapping['my_games'] = os.path.join(docs, 'My Games')
        mapping['saved_games'] = os.path.join(userprofile, 'Saved Games')
    else:
        home = os.path.expanduser('~')
        mapping['linux_config'] = os.path.join(home, '.config')
        mapping['linux_share'] = os.path.join(home, '.local/share')
    return mapping


def resolve_root(root_key: str) -> Optional[str]:
    """Абсолютный путь для данного ключа корня на ЭТОМ компьютере —
    используется при восстановлении запомненного (learned) пути."""
    return _platform_root_map().get(root_key)


def common_search_roots(exe_path: str = '') -> List[Tuple[str, str]]:
    """Список типовых папок, где игры хранят сохранения, как пары
    (ключ_корня, абсолютный_путь). Ключ нужен, чтобы потом можно было
    запомнить находку в привязке не к конкретному пути на диске (он у
    каждого пользователя свой), а к тому, ЧТО это за папка — и затем
    воссоздать её на любом компьютере."""
    roots: List[Tuple[str, str]] = []
    for key, path in _platform_root_map().items():
        if os.path.isdir(path):
            roots.append((key, path))

    if sys.platform.startswith('linux'):
        home = os.path.expanduser('~')
        for base in (os.path.join(home, '.steam/steam/steamapps/compatdata'),
                     os.path.join(home, '.local/share/Steam/steamapps/compatdata')):
            if os.path.isdir(base):
                roots.append(('steam_compat', base))

    if exe_path:
        exe_dir = os.path.dirname(exe_path)
        if os.path.isdir(exe_dir):
            roots.append(('exe_dir', exe_dir))
            parent = os.path.dirname(exe_dir)
            if os.path.isdir(parent):
                roots.append(('exe_parent', parent))

    seen = set()
    unique_roots = []
    for key, path in roots:
        real = os.path.realpath(path)
        if real not in seen:
            seen.add(real)
            unique_roots.append((key, path))
    return unique_roots


def classify_path(path: str) -> Optional[Tuple[str, str]]:
    """Если path лежит внутри одного из типовых портируемых корней,
    возвращает (ключ_корня, относительный_путь) — используется, чтобы
    запомнить путь, выбранный пользователем вручную или через поиск,
    для последующего мгновенного распознавания той же игры."""
    if not path:
        return None
    path_real = os.path.realpath(path)
    for key, root_path in _platform_root_map().items():
        if not os.path.isdir(root_path):
            continue
        root_real = os.path.realpath(root_path)
        try:
            rel = os.path.relpath(path_real, root_real)
        except ValueError:
            continue  # разные диски на Windows
        if rel != '.' and not rel.startswith('..'):
            return key, rel
    return None


def _iter_dirs(root: str, max_depth: int, should_stop: Callable[[], bool]):
    """Обходит подпапки root до глубины max_depth, отдавая (путь, глубина)."""
    stack = [(root, 0)]
    while stack:
        if should_stop():
            return
        path, depth = stack.pop()
        if depth >= max_depth:
            continue
        try:
            with os.scandir(path) as it:
                entries = list(it)
        except (PermissionError, FileNotFoundError, NotADirectoryError, OSError):
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name.lower() in _SKIP_DIR_NAMES or entry.name.startswith('.'):
                        continue
                    yield entry.path, depth + 1
                    stack.append((entry.path, depth + 1))
            except OSError:
                continue


def find_by_name(candidate_names: Set[str], roots: List[Tuple[str, str]], max_depth: int = 2,
                  time_budget: float = 4.0, should_stop: Callable[[], bool] = lambda: False) -> List[Dict]:
    """Ищет папки, чьё имя похоже на одно из candidate_names.
    roots — список (ключ_корня, путь), см. common_search_roots()."""
    if not candidate_names:
        return []
    norm_candidates = {_normalize(c) for c in candidate_names}
    norm_candidates = {c for c in norm_candidates if len(c) >= 3}
    if not norm_candidates:
        return []

    start = time.monotonic()
    matches = []
    for root_key, root_path in roots:
        if time.monotonic() - start > time_budget or should_stop():
            break
        for dirpath, _depth in _iter_dirs(root_path, max_depth, should_stop):
            if time.monotonic() - start > time_budget or should_stop():
                break
            norm_base = _normalize(os.path.basename(dirpath))
            if not norm_base:
                continue
            if any(norm_base == nc or norm_base in nc or nc in norm_base for nc in norm_candidates):
                mtime = _latest_mtime(dirpath, limit=300, should_stop=should_stop)
                matches.append({'path': dirpath, 'mtime': mtime, 'is_dir': True, 'reason': 'по названию',
                                 'root_key': root_key, 'relative': os.path.relpath(dirpath, root_path)})

    return _dedupe_sorted(matches)


def find_recent(roots: List[Tuple[str, str]], since_minutes: int = 240, max_depth: int = 3,
                 time_budget: float = 5.0, top_n: int = 20,
                 should_stop: Callable[[], bool] = lambda: False) -> List[Dict]:
    """Ищет недавно изменённые файлы/папки в типовых местах — полезно, если
    поиск по названию ничего не нашёл: сохранение почти всегда будет одним
    из самых недавно изменённых файлов сразу после игровой сессии.
    roots — список (ключ_корня, путь), см. common_search_roots()."""
    cutoff = time.time() - since_minutes * 60
    start = time.monotonic()
    containers: Dict[str, Dict] = {}   # abs_path -> {'mtime','root_key','root_path'}
    lone_files: Dict[str, Dict] = {}

    for root_key, root_path in roots:
        if time.monotonic() - start > time_budget or should_stop():
            break
        try:
            with os.scandir(root_path) as it:
                for entry in it:
                    if should_stop():
                        break
                    try:
                        if entry.is_file(follow_symlinks=False):
                            st = entry.stat()
                            if st.st_mtime >= cutoff:
                                lone_files[entry.path] = {'mtime': st.st_mtime, 'root_key': root_key,
                                                           'root_path': root_path}
                    except OSError:
                        continue
        except OSError:
            pass

        for dirpath, depth in _iter_dirs(root_path, max_depth, should_stop):
            if time.monotonic() - start > time_budget or should_stop():
                break
            rel = os.path.relpath(dirpath, root_path)
            container = os.path.join(root_path, rel.split(os.sep)[0])
            try:
                with os.scandir(dirpath) as it:
                    for entry in it:
                        try:
                            if entry.is_file(follow_symlinks=False):
                                st = entry.stat()
                                if st.st_mtime >= cutoff:
                                    prev = containers.get(container)
                                    if not prev or st.st_mtime > prev['mtime']:
                                        containers[container] = {'mtime': st.st_mtime, 'root_key': root_key,
                                                                  'root_path': root_path}
                        except OSError:
                            continue
            except OSError:
                continue

    results = [{'path': p, 'mtime': info['mtime'], 'is_dir': True, 'reason': 'недавно изменено',
                'root_key': info['root_key'], 'relative': os.path.relpath(p, info['root_path'])}
               for p, info in containers.items()]
    results += [{'path': p, 'mtime': info['mtime'], 'is_dir': False, 'reason': 'недавно изменено',
                 'root_key': info['root_key'], 'relative': os.path.relpath(p, info['root_path'])}
                for p, info in lone_files.items()]
    results.sort(key=lambda r: r['mtime'], reverse=True)
    return results[:top_n]


def _latest_mtime(path: str, limit: int = 300, should_stop: Callable[[], bool] = lambda: False) -> float:
    latest = 0.0
    count = 0
    try:
        latest = max(latest, os.path.getmtime(path))
    except OSError:
        pass
    for dirpath, dirnames, filenames in os.walk(path):
        if should_stop():
            break
        dirnames[:] = [d for d in dirnames if d.lower() not in _SKIP_DIR_NAMES]
        for name in filenames:
            count += 1
            if count > limit:
                return latest
            try:
                latest = max(latest, os.path.getmtime(os.path.join(dirpath, name)))
            except OSError:
                continue
    return latest


def _dedupe_sorted(items: List[Dict]) -> List[Dict]:
    seen = set()
    result = []
    for item in sorted(items, key=lambda i: i['mtime'] or 0, reverse=True):
        real = os.path.realpath(item['path'])
        if real in seen:
            continue
        seen.add(real)
        result.append(item)
    return result


def merge_results(name_matches: List[Dict], recent_matches: List[Dict], limit: int = 25) -> List[Dict]:
    """Объединяет находки по названию (приоритет) и по недавним изменениям,
    убирая дубликаты."""
    seen = set()
    merged = []
    for item in list(name_matches) + list(recent_matches):
        real = os.path.realpath(item['path'])
        if real in seen:
            continue
        seen.add(real)
        merged.append(item)
    return merged[:limit]
