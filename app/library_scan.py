"""
Поиск установленных игр: Steam (все библиотеки), Epic Games Store, GOG Galaxy (Windows).
Для каждой найденной игры определяется исполняемый файл (для слежения за процессом)
и, по базе путей Ludusavi, существующие на диске пути сохранений — чтобы добавить
сразу много игр одним нажатием.
"""
import glob
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app import manifest
from app.models import GameProfile, SaveSlot

_SKIP_NAMES = re.compile(r'^(proton\b|steam linux runtime|steamworks|steam controller|steamvr\b)', re.I)
_SKIP_EXE = re.compile(r'(unins|setup|install|crash|redist|vc_?redist|dxsetup|dotnet|ue4prereq|'
                       r'easyanticheat|eac|battleye|helper|updater|report|support|cef|webhelper)', re.I)


@dataclass
class FoundGame:
    name: str
    store: str                     # 'Steam' | 'Epic' | 'GOG'
    install_dir: str = ''
    exe_path: str = ''
    exe_candidates: List[str] = field(default_factory=list)   # другие вероятные .exe (выбор в окне сканера)
    launch: str = ''               # steam://rungameid/ID, epic-ссылка или путь к exe
    app_id: str = ''
    saves: List[Dict] = field(default_factory=list)   # кандидаты путей сохранений


def _read(path: str) -> str:
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    except OSError:
        return ''


def _norm(text: str) -> str:
    return re.sub(r'[^a-z0-9а-яё]', '', text.lower())


def exe_candidates(install_dir: str, game_name: str = '', depth: int = 2, limit: int = 8) -> List[str]:
    """Вероятные главные .exe игры, лучшие первыми.
    Оценка: совпадение имени файла с названием игры/папки (самый сильный признак), затем размер;
    файлы глубже в дереве и «Shipping»-обёртки ниже по рангу, служебные (setup, crash, eac...) отброшены."""
    if not install_dir or not os.path.isdir(install_dir):
        return []
    wanted = {n for n in (_norm(game_name), _norm(os.path.basename(install_dir.rstrip('\\/')))) if n}
    base_depth = install_dir.rstrip(os.sep).count(os.sep)
    scored = []
    for root, dirs, files in os.walk(install_dir):
        level = root.count(os.sep) - base_depth
        if level >= depth:
            dirs[:] = []
        for name in files:
            if not name.lower().endswith('.exe') or _SKIP_EXE.search(name):
                continue
            full = os.path.join(root, name)
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            stem = _norm(os.path.splitext(name)[0])
            score = 0.0
            if stem and any(stem == w or (len(stem) >= 4 and (stem in w or w in stem)) for w in wanted):
                score += 100
            score += min(size / (1024 * 1024), 500) / 5      # до +100 за размер (500 МБ)
            score -= level * 15
            if 'shipping' in stem:
                score += 5            # UE: реальный процесс игры, а не пускатель в корне
            scored.append((score, full))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [path for _score, path in scored[:limit]]


def guess_exe(install_dir: str, depth: int = 2, game_name: str = '') -> str:
    """Главный .exe игры (лучший из exe_candidates) или пустая строка."""
    cands = exe_candidates(install_dir, game_name, depth, limit=1)
    return cands[0] if cands else ''


# ---------- Steam ----------

def steam_roots() -> List[str]:
    roots = []
    if sys.platform.startswith('win'):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as key:
                roots.append(winreg.QueryValueEx(key, 'SteamPath')[0])
        except (ImportError, OSError):
            pass
        roots += [r'C:\Program Files (x86)\Steam', r'C:\Program Files\Steam']
    else:
        home = os.path.expanduser('~')
        roots += [os.path.join(home, '.steam', 'steam'), os.path.join(home, '.local', 'share', 'Steam'),
                  os.path.join(home, '.var', 'app', 'com.valvesoftware.Steam', '.local', 'share', 'Steam')]
    return [r for r in dict.fromkeys(os.path.normpath(r) for r in roots) if os.path.isdir(r)]


def steam_libraries(root: str) -> List[str]:
    libs = [root]
    text = _read(os.path.join(root, 'steamapps', 'libraryfolders.vdf'))
    for m in re.finditer(r'"path"\s+"([^"]+)"', text):
        libs.append(m.group(1).replace('\\\\', '\\'))
    return [l for l in dict.fromkeys(os.path.normpath(l) for l in libs) if os.path.isdir(os.path.join(l, 'steamapps'))]


def scan_steam(roots: Optional[List[str]] = None) -> List[FoundGame]:
    found, seen = [], set()
    for root in (roots if roots is not None else steam_roots()):
        for lib in steam_libraries(root):
            steamapps = os.path.join(lib, 'steamapps')
            for acf in glob.glob(os.path.join(steamapps, 'appmanifest_*.acf')):
                text = _read(acf)
                name = re.search(r'"name"\s+"([^"]+)"', text)
                inst = re.search(r'"installdir"\s+"([^"]+)"', text)
                appid = re.search(r'"appid"\s+"(\d+)"', text)
                if not (name and inst and appid) or _SKIP_NAMES.match(name.group(1)) or appid.group(1) in seen:
                    continue
                seen.add(appid.group(1))
                install = os.path.join(steamapps, 'common', inst.group(1))
                if not os.path.isdir(install):
                    continue
                found.append(FoundGame(name=name.group(1), store='Steam', install_dir=install,
                                       exe_path=guess_exe(install, game_name=name.group(1)), app_id=appid.group(1),
                                       launch=f'steam://rungameid/{appid.group(1)}'))
    return found


# ---------- Epic ----------

def scan_epic(manifests_dir: Optional[str] = None) -> List[FoundGame]:
    folder = manifests_dir or os.path.join(os.environ.get('PROGRAMDATA', r'C:\ProgramData'),
                                           'Epic', 'EpicGamesLauncher', 'Data', 'Manifests')
    found = []
    for item in glob.glob(os.path.join(folder, '*.item')):
        try:
            data = json.loads(_read(item))
        except ValueError:
            continue
        name, install = data.get('DisplayName'), data.get('InstallLocation')
        if not name or not install or not os.path.isdir(install):
            continue
        exe = os.path.join(install, data.get('LaunchExecutable') or '')
        exe = exe if os.path.isfile(exe) else guess_exe(install, game_name=name)
        ns, cat, app = data.get('CatalogNamespace'), data.get('CatalogItemId'), data.get('AppName')
        launch = (f'com.epicgames.launcher://apps/{ns}%3A{cat}%3A{app}?action=launch&silent=true'
                  if ns and cat and app else exe)
        found.append(FoundGame(name=name, store='Epic', install_dir=install, exe_path=exe, launch=launch,
                               app_id=app or ''))
    return found


# ---------- GOG (реестр Windows) ----------

def scan_gog() -> List[FoundGame]:
    if not sys.platform.startswith('win'):
        return []
    found = []
    try:
        import winreg
        base = r'SOFTWARE\WOW6432Node\GOG.com\Games'
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                with winreg.OpenKey(root, winreg.EnumKey(root, i)) as key:
                    def val(n):
                        try:
                            return winreg.QueryValueEx(key, n)[0]
                        except OSError:
                            return ''
                    name, exe, path = val('gameName'), val('exe'), val('path')
                    if name and path and os.path.isdir(path):
                        exe = exe if exe and os.path.isfile(exe) else guess_exe(path, game_name=name)
                        found.append(FoundGame(name=name, store='GOG', install_dir=path, exe_path=exe,
                                               launch=exe, app_id=str(val('gameID'))))
    except (ImportError, OSError):
        pass
    return found


# ---------- общий поиск и сопоставление с базой путей ----------

def match_saves(game: FoundGame, limit: int = 3) -> List[Dict]:
    names = {game.name}
    if game.install_dir:
        names.add(os.path.basename(game.install_dir.rstrip('\\/')))
    try:
        cands = manifest.find_candidates(names, game.exe_path or game.install_dir)
    except Exception:  # база вспомогательная — поиск игр не должен из-за неё падать
        cands = []
    return cands[:limit]


def scan_all(progress=None) -> List[FoundGame]:
    """Steam + Epic + GOG; каждой игре подбираются пути сохранений. progress(текст)."""
    games: List[FoundGame] = []
    for label, fn in (('Steam', scan_steam), ('Epic Games', scan_epic), ('GOG', scan_gog)):
        if progress:
            progress(f'Поиск: {label}...')
        games.extend(fn())
    for i, g in enumerate(games):
        if progress and i % 10 == 0:
            progress(f'Поиск сохранений: {i}/{len(games)}...')
        g.saves = match_saves(g)
        g.exe_candidates = exe_candidates(g.install_dir, g.name) if g.install_dir else []
    games.sort(key=lambda g: (not g.saves, g.name.lower()))
    return games


def to_profile(found: FoundGame, account_id: str = '') -> GameProfile:
    """Профиль игры из найденной: процесс, команда запуска и слоты по найденным путям."""
    game = GameProfile(name=found.name, account_id=account_id, launch_command=found.launch)
    if found.exe_path:
        game.process_names = [os.path.basename(found.exe_path)]
        game.hint_exe_path = found.exe_path
    for i, cand in enumerate(found.saves):
        is_dir = bool(cand['is_dir'])
        label = os.path.basename(cand['path'].rstrip('\\/')) or 'Сохранение'
        game.slots.append(SaveSlot(label=label, path=cand['path'], is_directory=is_dir,
                                   # Индекс нужен и для файлов: два сохранения с
                                   # одинаковым именем (settings.json) иначе
                                   # перезаписывали бы друг друга в облаке.
                                   remote_name=(f'slot{i + 1}.zip' if is_dir else
                                                f'slot{i + 1}_{os.path.basename(cand["path"])}')))
    return game
