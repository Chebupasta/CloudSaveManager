"""
Пресеты путей сохранений для эмуляторов (Yuzu/Ryujinx/RPCS3/PCSX2/Dolphin/RetroArch).

Модуль только ищет папки-кандидаты на диске и ничего не пишет. Пути собраны
по стандартным (не портативным) установкам и НЕ проверялись на реальных ПК:
у портативных сборок данные лежат рядом с программой, их можно указать вручную
через параметр ``extra_roots``.

Каждый шаблон — путь относительно «корня» (AppData/Documents/домашняя папка и т.п.).
Корни берутся из переменных окружения, поэтому в тестах их легко подменить.
"""
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, Iterable, List


@dataclass(frozen=True)
class EmulatorPreset:
    key: str
    name: str
    process_names: List[str]
    # (имя корня, относительный путь). Имена корней: appdata, documents, home,
    # xdg_data, xdg_config.
    save_dirs: List[tuple] = field(default_factory=list)
    note: str = ''


EMULATORS: Dict[str, EmulatorPreset] = {
    'yuzu': EmulatorPreset(
        'yuzu', 'Yuzu', ['yuzu.exe'],
        [('appdata', 'yuzu/nand/user/save'), ('xdg_data', 'yuzu/nand/user/save')],
        'Проект закрыт; у форков (Suyu, Sudachi и др.) папки другие — добавьте вручную.'),
    'ryujinx': EmulatorPreset(
        'ryujinx', 'Ryujinx', ['Ryujinx.exe', 'Ryujinx'],
        [('appdata', 'Ryujinx/bis/user/save'), ('xdg_config', 'Ryujinx/bis/user/save')],
        'Сохранения лежат в папках с числовыми ID — выгружайте всю папку save.'),
    'rpcs3': EmulatorPreset(
        'rpcs3', 'RPCS3', ['rpcs3.exe', 'rpcs3'],
        [('appdata', 'rpcs3/dev_hdd0/home/00000001/savedata'),
         ('xdg_config', 'rpcs3/dev_hdd0/home/00000001/savedata')],
        'Часто RPCS3 портативный — тогда укажите его папку через extra_roots.'),
    'pcsx2': EmulatorPreset(
        'pcsx2', 'PCSX2', ['pcsx2-qt.exe', 'pcsx2.exe', 'pcsx2-qt'],
        [('documents', 'PCSX2/memcards'), ('documents', 'PCSX2/sstates'),
         ('xdg_config', 'PCSX2/memcards'), ('xdg_config', 'PCSX2/sstates')]),
    'dolphin': EmulatorPreset(
        'dolphin', 'Dolphin', ['Dolphin.exe', 'dolphin-emu'],
        [('documents', 'Dolphin Emulator/GC'), ('documents', 'Dolphin Emulator/Wii'),
         ('appdata', 'Dolphin Emulator/GC'), ('appdata', 'Dolphin Emulator/Wii'),
         ('xdg_data', 'dolphin-emu/GC'), ('xdg_data', 'dolphin-emu/Wii')]),
    'retroarch': EmulatorPreset(
        'retroarch', 'RetroArch', ['retroarch.exe', 'retroarch'],
        [('appdata', 'RetroArch/saves'), ('appdata', 'RetroArch/states'),
         ('xdg_config', 'retroarch/saves'), ('xdg_config', 'retroarch/states')],
        'В настройках RetroArch папки сохранений можно переназначить.'),
}


def _roots() -> Dict[str, str]:
    home = os.path.expanduser('~')
    roots = {
        'home': home,
        'documents': os.path.join(home, 'Documents'),
        'xdg_data': os.getenv('XDG_DATA_HOME') or os.path.join(home, '.local', 'share'),
        'xdg_config': os.getenv('XDG_CONFIG_HOME') or os.path.join(home, '.config'),
    }
    appdata = os.getenv('APPDATA')
    if appdata:
        roots['appdata'] = appdata
    if sys.platform.startswith('win'):
        # Windows: «Документы» может быть перенесена; USERPROFILE надёжнее ~ в тестах
        prof = os.getenv('USERPROFILE')
        if prof:
            roots['documents'] = os.path.join(prof, 'Documents')
    return roots


def find_emulator_saves(key: str, extra_roots: Iterable[str] = ()) -> List[str]:
    """Возвращает существующие папки сохранений эмулятора ``key``.

    ``extra_roots`` — папки портативных установок: шаблоны применяются и к ним
    (например, ``D:/Emu/rpcs3`` + ``dev_hdd0/home/00000001/savedata``).
    Неизвестный ключ — пустой список. Дубликаты (через симлинки) убираются.
    """
    preset = EMULATORS.get(key)
    if preset is None:
        return []
    roots = _roots()
    bases: List[str] = []
    for root_name, rel in preset.save_dirs:
        root = roots.get(root_name)
        if root:
            bases.append(os.path.join(root, *rel.split('/')))
    for extra in extra_roots:
        if not extra:
            continue
        for _root_name, rel in preset.save_dirs:
            parts = rel.split('/')
            # у портативной сборки нет верхней папки программы: отбрасываем первый сегмент
            bases.append(os.path.join(extra, *parts[1:]) if len(parts) > 1 else extra)
            bases.append(os.path.join(extra, *parts))
    found: List[str] = []
    seen = set()
    for base in bases:
        if os.path.isdir(base):
            real = os.path.realpath(base)
            if real not in seen:
                seen.add(real)
                found.append(base)
    return found


def find_all_emulator_saves(extra_roots: Iterable[str] = ()) -> Dict[str, List[str]]:
    """Для каждого известного эмулятора — найденные папки (только непустые результаты)."""
    result = {}
    for key in EMULATORS:
        paths = find_emulator_saves(key, extra_roots)
        if paths:
            result[key] = paths
    return result
