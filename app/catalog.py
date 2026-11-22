"""
Каталог игр в облаке. Рядом с сохранениями лежит маленький файл `_catalog.json` —
список игр с процессами, слотами и «переносимыми» путями (с %APPDATA% и т.п. вместо
имени пользователя). Второй компьютер, подключившись к тому же хранилищу, читает его
и сам добавляет игры, которых у него ещё нет; настройки игр с первого ПК переносятся.
"""
import datetime
import json
import os
import socket
import tempfile
from typing import Dict, List, Optional, Tuple

from app import crypto_utils, manifest, sync_manager
from app.crypto_utils import CryptoError
from app.logger import log_action
from app.models import GameProfile, SaveSlot

VERSION = 1


# ---------- переносимые пути ----------

def _roots() -> List[Tuple[str, str]]:
    """(токен, путь) от более длинных/специфичных к коротким."""
    home = os.path.expanduser('~')
    roots = [
        ('{LOCALAPPDATA}', os.environ.get('LOCALAPPDATA') or os.path.join(home, 'AppData', 'Local')),
        ('{APPDATA}', os.environ.get('APPDATA') or os.path.join(home, 'AppData', 'Roaming')),
        ('{DOCUMENTS}', os.path.join(home, 'Documents')),
        ('{XDG_DATA}', os.environ.get('XDG_DATA_HOME') or os.path.join(home, '.local', 'share')),
        ('{XDG_CONFIG}', os.environ.get('XDG_CONFIG_HOME') or os.path.join(home, '.config')),
        ('{HOME}', home),
    ]
    return sorted(roots, key=lambda r: len(r[1]), reverse=True)


def to_template(path: str) -> str:
    """Абсолютный путь -> шаблон без имени пользователя (разделители — «/»)."""
    if not path:
        return ''
    norm = os.path.normpath(path)
    for token, root in _roots():
        root_n = os.path.normpath(root)
        if os.path.normcase(norm) == os.path.normcase(root_n) or \
                os.path.normcase(norm).startswith(os.path.normcase(root_n) + os.sep):
            rest = norm[len(root_n):].lstrip('\\/')
            return (token + ('/' + rest.replace('\\', '/') if rest else ''))
    return norm.replace('\\', '/')


def from_template(template: str) -> str:
    if not template:
        return ''
    for token, root in _roots():
        if template.startswith(token):
            rest = template[len(token):].lstrip('/')
            return os.path.normpath(os.path.join(root, rest)) if rest else os.path.normpath(root)
    return os.path.normpath(template)


# ---------- запись/чтение каталога ----------

def is_safe_import_path(path: str) -> bool:
    """Путь из облачного каталога подставляется автоматически только если он внутри
    профиля пользователя, общих папок данных или библиотеки Steam — иначе подменённый
    каталог мог бы направить загрузку в произвольную папку системы."""
    if not path or sync_manager.is_dangerous_target(path):
        return False
    p = os.path.normcase(os.path.abspath(path))
    allowed = [os.path.expanduser('~'), os.environ.get('PUBLIC', ''), os.environ.get('PROGRAMDATA', '')]
    for root in allowed:
        if root:
            root_n = os.path.normcase(os.path.abspath(root))
            if p.startswith(root_n + os.sep):
                return True
    return (os.sep + 'steamapps' + os.sep) in p + os.sep


def build_entry(game: GameProfile) -> Dict:
    return {
        'name': game.name,
        'process_names': list(game.process_names),
        'auto_upload_on_exit': game.auto_upload_on_exit,
        'check_cloud_on_start': game.check_cloud_on_start,
        'periodic_upload_minutes': int(getattr(game, 'periodic_upload_minutes', 0) or 0),
        'prefix': game.remote_prefix or game.name,
        'launch': game.launch_command if '://' in game.launch_command else to_template(game.launch_command),
        'slots': [{'label': s.label, 'remote_name': s.remote_name, 'is_directory': s.is_directory,
                   'exclude': s.exclude_patterns, 'path': to_template(s.path)} for s in game.slots],
        'updated_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'device': socket.gethostname(),
    }


def fetch(store, account) -> Tuple[Optional[Dict], Optional[str]]:
    """Скачивает каталог. (dict, None) | ({}, None) если каталога ещё нет | (None, ошибка)."""
    provider, err = sync_manager.provider_for_account(store, account)
    if err:
        return None, err
    tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False)
    tmp.close()
    try:
        ok, msg = provider.download_file(sync_manager.catalog_key(account), tmp.name)
        if not ok:
            return ({}, None) if msg == provider.NOT_FOUND else (None, msg)
        passphrase = sync_manager._passphrase(account)
        sync_manager._decrypt_if_needed(tmp.name, passphrase)
        with open(tmp.name, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return (data if isinstance(data, dict) else {}), None
    except (OSError, ValueError, CryptoError) as e:
        return None, f'Не удалось прочитать каталог игр: {e}'
    finally:
        if os.path.exists(tmp.name):
            os.remove(tmp.name)


def publish(store, account) -> Tuple[bool, str]:
    """Дописывает в облачный каталог игры этого ПК (чужие записи сохраняются)."""
    # Каталог публикуется из отдельного потока — снимаем снимок под тем же
    # замком, которым store меняет список игр.
    with store._lock:
        games = [g for g in store.games if g.account_id == account.id]
    if not games:
        return True, 'Нет игр для публикации.'
    catalog, err = fetch(store, account)
    if catalog is None:
        return False, err
    entries = catalog.get('games') if isinstance(catalog.get('games'), dict) else {}
    changed = False
    for game in games:
        key = sync_manager.game_cloud_key(game)
        new = build_entry(game)
        old = entries.get(key)
        # сравниваем без времени/устройства — не перезаписываем облако впустую
        strip = lambda e: {k: v for k, v in (e or {}).items() if k not in ('updated_at', 'device')}
        if strip(old) != strip(new):
            entries[key] = new
            changed = True
    if not changed:
        return True, 'Каталог игр актуален.'
    provider, err = sync_manager.provider_for_account(store, account)
    if err:
        return False, err
    payload = {'version': VERSION, 'games': entries}
    tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w', encoding='utf-8')
    enc = None
    try:
        json.dump(payload, tmp, ensure_ascii=False)
        tmp.close()
        upload_path = tmp.name
        passphrase = sync_manager._passphrase(account)
        if passphrase == '':
            return False, 'Включено шифрование, но не задан пароль.'
        if passphrase:
            enc = tmp.name + '.enc'
            crypto_utils.encrypt_file(tmp.name, enc, passphrase)
            upload_path = enc
        ok, msg = provider.upload_file(upload_path, sync_manager.catalog_key(account), message='catalog')
        log_action('catalog', 'publish_ok' if ok else 'publish_fail', msg if not ok else f'{len(entries)} игр')
        return ok, 'Каталог игр обновлён в облаке.' if ok else msg
    except (OSError, CryptoError) as e:
        return False, str(e)
    finally:
        for p in (tmp.name, enc):
            if p and os.path.exists(p):
                os.remove(p)


# ---------- импорт на втором компьютере ----------

def _resolve_slot_path(slot_entry: Dict, game_name: str, report: Optional[Dict] = None) -> str:
    """Локальный путь слота: шаблон с первого ПК -> если такого нет, ищем по базе путей."""
    path = from_template(slot_entry.get('path', ''))
    if not (path and os.path.exists(path)):
        try:
            for cand in manifest.find_candidates({game_name}):
                if bool(cand['is_dir']) == bool(slot_entry.get('is_directory')):
                    path = cand['path']
                    break
        except Exception:  # поиск по базе вспомогательный — не должен ломать импорт
            pass
    if path and not is_safe_import_path(path):
        # путь вне безопасных папок автоматически не подставляем — пользователь укажет сам
        log_action('catalog', 'unsafe_path_skipped', f'{game_name}: {path}')
        if report is not None:
            report['unsafe'] = report.get('unsafe', 0) + 1
        return ''
    return path


def _ignore_id(account_id: str, key: str) -> str:
    return f'{account_id}:{key}'


def remember_removed(store, game: GameProfile) -> None:
    """Игра удалена вручную — не добавлять её снова из каталога."""
    if game.account_id:
        entry = _ignore_id(game.account_id, sync_manager.game_cloud_key(game))
        if entry not in store.settings.ignored_catalog:
            store.settings.ignored_catalog.append(entry)
            store.save_settings()


def import_new(store, account, include_ignored: bool = False,
               progress=None, report: Optional[Dict] = None) -> Tuple[List[GameProfile], Optional[str]]:
    """Добавляет игры из облачного каталога, которых нет на этом ПК.
    Возвращает (созданные игры, ошибка)."""
    catalog, err = fetch(store, account)
    if catalog is None:
        return [], err
    entries = catalog.get('games') if isinstance(catalog.get('games'), dict) else {}
    with store._lock:
        local_keys = {sync_manager.game_cloud_key(g) for g in store.games if g.account_id == account.id}
    created: List[GameProfile] = []
    for i, (key, entry) in enumerate(sorted(entries.items())):
        if key in local_keys:
            continue
        ignored = _ignore_id(account.id, key)
        if ignored in store.settings.ignored_catalog:
            if not include_ignored:
                continue
            store.settings.ignored_catalog.remove(ignored)
        name = entry.get('name') or key
        game = GameProfile(
            name=name, process_names=list(entry.get('process_names') or []), account_id=account.id,
            remote_prefix=entry.get('prefix') or name,
            auto_upload_on_exit=bool(entry.get('auto_upload_on_exit', True)),
            check_cloud_on_start=bool(entry.get('check_cloud_on_start', True)),
            periodic_upload_minutes=int(entry.get('periodic_upload_minutes') or 0))
        launch = entry.get('launch') or ''
        game.launch_command = launch if '://' in launch else (from_template(launch) if launch else '')
        if game.launch_command and '://' not in game.launch_command and not os.path.exists(game.launch_command):
            game.launch_command = ''  # такого файла на этом ПК нет
        game.slots = [SaveSlot(label=s.get('label') or 'Сохранение', remote_name=s.get('remote_name') or 'save.dat',
                               is_directory=bool(s.get('is_directory')), exclude_patterns=s.get('exclude') or '',
                               path=_resolve_slot_path(s, name, report)) for s in entry.get('slots', [])]
        store.add_game(game)
        created.append(game)
        log_action('catalog', 'imported', f'{name} из {entry.get("device", "?")}')
        if progress:
            progress(int(100 * (i + 1) / max(1, len(entries))), f'Добавлено: {name}')
    if created:
        store.save_settings()  # список игнорируемых мог измениться
    return created, None


def download_missing(store, games: List[GameProfile], progress=None) -> int:
    """Скачивает из облака сохранения для слотов, которых локально нет (перезаписывать
    нечего — безопасно). Возвращает число скачанных слотов."""
    done = 0
    for game in games:
        for slot in game.slots:
            if not slot.path or os.path.exists(slot.path):
                continue
            if progress:
                progress(0, f'Скачивание: {game.name} / {slot.label}')
            ok, _msg = sync_manager.download_slot(store, game, slot)
            done += 1 if ok else 0
    return done


def sync_account(store, account, include_ignored: bool = False, progress=None) -> Tuple[List[GameProfile], str]:
    """Полный цикл для аккаунта: подхватить чужие игры -> докачать недостающие
    сохранения -> опубликовать свои игры. Возвращает (новые игры, сообщение)."""
    report: Dict = {}
    created, err = import_new(store, account, include_ignored, progress, report)
    if err:
        return [], err
    note = ''
    if report.get('unsafe'):
        note += f' Слотов с путём вне безопасных папок: {report["unsafe"]} — укажите путь вручную.'
    if created and store.settings.auto_download_imported:
        n = download_missing(store, created, progress)
        note += f' Скачано сохранений: {n}.'
    ok, msg = publish(store, account)
    if not ok:
        note += f' (Каталог не обновлён: {msg})'
    if created:
        return created, f'Добавлено игр из облака: {len(created)}.{note}'
    return [], f'Новых игр в облаке нет.{note}'
