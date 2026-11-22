"""
Локальное резервное копирование сохранений перед их перезаписью
(например, перед загрузкой версии из облака поверх локального файла).

Для файлов делается простая копия, для папок — zip-архив.
Хранится не более N (настройка «резервных копий на слот») последних копий на слот.
"""
import glob
import os
import re
import shutil
import zipfile
from datetime import datetime
from typing import List, Dict, Tuple

from app.constants import RUNTIME, get_backups_dir


def _safe_name(text: str) -> str:
    return ''.join(c if c.isalnum() or c in ('-', '_') else '_' for c in text)


def backup_path_for(game_id: str, slot_id: str) -> str:
    folder = os.path.join(get_backups_dir(), _safe_name(game_id), _safe_name(slot_id))
    os.makedirs(folder, exist_ok=True)
    return folder


def _write_copy(source_path: str, dest_base: str, is_directory: bool) -> str:
    """Копирует файл (как есть) или папку (zip) в dest_base + расширение."""
    if is_directory:
        dest = dest_base + '.zip'
        with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, _dirs, files in os.walk(source_path):
                for name in files:
                    full = os.path.join(root, name)
                    zf.write(full, os.path.relpath(full, source_path))
        return dest
    dest = dest_base + os.path.splitext(source_path)[1]
    shutil.copyfile(source_path, dest)
    return dest


def _stamp() -> str:
    # микросекунды: быстрые повторные копии не перезаписывают друг друга
    return datetime.now().strftime('%Y%m%d_%H%M%S_%f')


def make_local_backup(game_id: str, slot_id: str, source_path: str, is_directory: bool) -> str:
    """Создаёт резервную копию перед перезаписью. Возвращает путь к копии
    (или пустую строку, если исходный файл/папка не существует)."""
    if not source_path or not os.path.exists(source_path):
        return ''
    folder = backup_path_for(game_id, slot_id)
    dest = _write_copy(source_path, os.path.join(folder, f'backup_{_stamp()}'), is_directory)
    _trim_old_backups(folder)
    return dest


def make_snapshot(game_id: str, slot_id: str, source_path: str, is_directory: bool,
                  label: str = '', auto: bool = False) -> str:
    """Снимок сохранения. Именной (label) хранится, пока вы его не удалите; автоматический
    (auto) — ограниченное число последних; обычные копии перед заменой — как раньше."""
    if not source_path or not os.path.exists(source_path):
        return ''
    folder = backup_path_for(game_id, slot_id)
    tag = '__auto' if auto else f'__s_{_safe_name(label.strip())[:40] or "снимок"}'
    dest = _write_copy(source_path, os.path.join(folder, f'backup_{_stamp()}{tag}'), is_directory)
    _trim_old_backups(folder)
    return dest


def delete_backup(path: str) -> bool:
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def delete_backups(paths) -> int:
    """Массовое удаление копий; возвращает число реально удалённых."""
    return sum(1 for p in paths if delete_backup(p))


def store_cloud_copy(game_id: str, slot_id: str, src_file: str, is_directory: bool) -> str:
    """Сохраняет скачанную из облака версию (перед тем как её перезапишет новая
    выгрузка) в локальные резервные копии. Для папок облачный файл — zip,
    поэтому формат совпадает с копиями папок и восстанавливается так же."""
    if not src_file or not os.path.isfile(src_file):
        return ''
    folder = backup_path_for(game_id, slot_id)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    ext = '.zip' if is_directory else os.path.splitext(src_file)[1]
    dest = os.path.join(folder, f'backup_{ts}_cloud{ext}')
    shutil.copyfile(src_file, dest)
    _trim_old_backups(folder)
    return dest


def _kind(path: str) -> str:
    name = os.path.basename(path)
    if '__s_' in name:
        return 'named'
    if '__auto' in name:
        return 'auto'
    return 'regular'


def _trim_old_backups(folder: str):
    """Обычные копии и автоснимки обрезаются каждый по своему лимиту; именные снимки не трогаем."""
    files = sorted(glob.glob(os.path.join(folder, 'backup_*')))  # имя содержит время
    for kind, limit in (('regular', RUNTIME['max_backups']), ('auto', RUNTIME.get('max_auto_snapshots', 10))):
        group = [f for f in files if _kind(f) == kind]
        while len(group) > limit:
            try:
                os.remove(group.pop(0))
            except OSError:
                pass


def _ts_from_name(path: str):
    m = re.search(r'backup_(\d{8}_\d{6})', os.path.basename(path))
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), '%Y%m%d_%H%M%S').timestamp()
    except ValueError:
        return None


def _label(path: str) -> str:
    m = re.search(r'__s_(.+?)(?:\.[^.]+)?$', os.path.basename(path))
    return m.group(1).replace('_', ' ') if m else ''


def list_backups(game_id: str, slot_id: str) -> List[Dict]:
    """Список локальных резервных копий слота, новые сверху."""
    folder = backup_path_for(game_id, slot_id)
    items = []
    for path in glob.glob(os.path.join(folder, 'backup_*')):
        try:
            stat = os.stat(path)
        except OSError:
            continue
        items.append({
            'path': path,
            'mtime': _ts_from_name(path) or stat.st_mtime,
            'size': stat.st_size,
            'is_zip': path.lower().endswith('.zip'),
            'kind': _kind(path),
            'label': _label(path),
        })
    items.sort(key=lambda i: os.path.basename(i['path']), reverse=True)
    # разница размера с предыдущей (более старой) копией; у самой старой — None
    for i, item in enumerate(items):
        older = items[i + 1] if i + 1 < len(items) else None
        item['delta_size'] = item['size'] - older['size'] if older else None
        item['delta_seconds'] = item['mtime'] - older['mtime'] if older else None
    return items


def restore_backup(backup_path: str, target_path: str, is_directory: bool,
                    game_id: str, slot_id: str) -> Tuple[bool, str]:
    """Восстанавливает локальный файл/папку из резервной копии.
    Перед восстановлением на всякий случай бэкапит и ТЕКУЩЕЕ состояние —
    так возврат к старой копии тоже можно отменить."""
    if not os.path.isfile(backup_path):
        return False, 'Файл резервной копии не найден.'
    if not target_path:
        return False, 'Не указан путь, куда восстанавливать.'

    # Бэкап текущего состояния перед восстановлением старой копии
    if os.path.exists(target_path):
        make_local_backup(game_id, slot_id, target_path, is_directory)

    try:
        if is_directory:
            if os.path.isdir(target_path):
                shutil.rmtree(target_path)
            os.makedirs(target_path, exist_ok=True)
            from app.zip_utils import safe_extract
            safe_extract(backup_path, target_path)
        else:
            os.makedirs(os.path.dirname(target_path) or '.', exist_ok=True)
            shutil.copy2(backup_path, target_path)
    except (OSError, zipfile.BadZipFile) as e:
        return False, f'Не удалось восстановить резервную копию: {e}'

    return True, 'Резервная копия восстановлена. Не забудьте выгрузить её в облако, если нужно.'
