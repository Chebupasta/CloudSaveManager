"""
Связующий слой между моделями (GameProfile/SaveSlot), облачными
провайдерами и локальными резервными копиями. Используется как ручными
кнопками "Выгрузить"/"Загрузить" в интерфейсе, так и автоматической
выгрузкой после закрытия игры — чтобы логика в обоих местах была одна.
"""
import datetime
import fnmatch
import hashlib
import json
import os
import re
import socket
import shutil
import tempfile
import threading
import time
import zipfile
from typing import Callable, Dict, Optional, Tuple

from app import crypto_utils, secrets_store
from app.crypto_utils import CryptoError
from app.backup import make_local_backup, store_cloud_copy
from app.cloud import create_provider
from app.cloud.base import CloudProvider
from app.logger import log_action
from app.models import GameProfile, SaveSlot
from app.store import ConfigStore


_BAD_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')


def _clean_segment(text: str) -> str:
    """Делает безопасное имя папки для облака (в т.ч. для Windows-путей
    локальной папки: двоеточие в названии игры вроде 'Hades: ...' недопустимо)."""
    parts = [_BAD_CHARS.sub('_', p.strip()).replace(' ', '_') for p in text.replace('\\', '/').split('/')]
    return '/'.join(p for p in parts if p and p not in ('.', '..'))


def _safe_remote_name(name: str) -> str:
    """Имя файла в облаке — всегда один сегмент, без путей и '..'.
    Иначе remote_name вроде '../ДругаяИгра/save.dat' записал бы сохранение
    в папку другой игры (особенно опасно для локальной синхронизируемой папки)."""
    name = os.path.basename((name or '').replace('\\', '/'))
    clean = _BAD_CHARS.sub('_', name).strip().replace(' ', '_').lstrip('.')
    return clean or 'save.dat'


def _remote_key(account, game: GameProfile, slot: SaveSlot) -> str:
    """Формирует путь внутри облака: <база (необязательно)>/<игра>/<файл>.
    Так один и тот же репозиторий/папка может использоваться сразу для
    всех игр — каждая автоматически получает свою подпапку."""
    parts = []
    base = (account.config.get('base_folder', '') or '').strip().strip('/')
    if base:
        parts.append(_clean_segment(base))
    prefix = (game.remote_prefix or game.name or game.id).strip('/')
    parts.append(_clean_segment(prefix) or game.id)
    return '/'.join(p for p in parts if p) + '/' + _safe_remote_name(slot.remote_name)


def preview_remote_path(account, remote_prefix: str, filename: str = 'файл_сохранения.dat') -> str:
    """То же, что _remote_key, но принимает значения напрямую — удобно для
    предпросмотра пути в диалогах, ещё до того как объекты игры/слота
    полностью собраны."""
    parts = []
    base = (account.config.get('base_folder', '') or '').strip().strip('/') if account else ''
    if base:
        parts.append(_clean_segment(base))
    prefix = (remote_prefix or 'Игра').strip('/')
    parts.append(_clean_segment(prefix) or 'Игра')
    return '/'.join(p for p in parts if p) + '/' + _safe_remote_name(filename)


def _save_slot_state(store: ConfigStore, game: GameProfile, slot: SaveSlot, **fields) -> None:
    """Записать отметки синхронизации, не перезаписывая всю игру целиком.
    Выгрузка может идти минуты — за это время пользователь успел изменить
    другие поля игры или удалить слот; store.update_game(game) с устаревшим
    объектом откатил бы эти правки и воскресил удалённый слот."""
    for key, value in fields.items():
        setattr(slot, key, value)
    fresh = store.get_game(game.id)
    if fresh is None:
        return
    target = next((s for s in fresh.slots if s.id == slot.id), None)
    if target is None:
        return
    for key, value in fields.items():
        setattr(target, key, value)
    store.update_game(fresh)


def _hash_file_into(path: str, hasher) -> None:
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            hasher.update(chunk)


_FP_CACHE: Dict[tuple, Tuple[tuple, str]] = {}
_FP_LOCK = threading.Lock()
_FRESH_SECONDS = 2.0  # только что изменённые файлы кэшем не считаем (грубая точность времён на некоторых ФС)


def _scan(path: str, excludes: tuple = ()):
    """Список (относительный путь, размер, mtime_ns) файлов папки — дёшево (только stat);
    файлы под маски excludes пропускаются."""
    out = []
    stack = [(path, '')]
    while stack:
        current, rel = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append((entry.path, rel + entry.name + '/'))
                        else:
                            if excludes and _excluded(rel + entry.name, excludes):
                                continue
                            st = entry.stat()
                            out.append((rel + entry.name, st.st_size, st.st_mtime_ns))
                    except OSError:
                        continue
        except OSError:
            continue
    out.sort()
    return out


def compute_fingerprint(path: str, is_directory: bool, excludes: tuple = ()) -> Optional[str]:
    """Считает контрольную сумму содержимого файла или папки (без учёта дат
    изменения и метаданных архива — только реальное содержимое).
    Результат кэшируется по (размер, время изменения) — повторные проверки
    неизменённых сохранений не перечитывают файлы с диска."""
    if not path or not os.path.exists(path):
        return None
    try:
        if is_directory:
            files = _scan(path, excludes)
            signature = tuple(files)
            newest = max((f[2] for f in files), default=0) / 1e9
        else:
            st = os.stat(path)
            signature = (st.st_size, st.st_mtime_ns)
            newest = st.st_mtime
    except OSError:
        return None
    key = (os.path.abspath(path), bool(is_directory), excludes)
    cacheable = (time.time() - newest) > _FRESH_SECONDS
    if cacheable:
        with _FP_LOCK:
            hit = _FP_CACHE.get(key)
        if hit and hit[0] == signature:
            return hit[1]
    hasher = hashlib.md5()
    if is_directory:
        for rel, _size, _mtime in files:
            hasher.update(rel.encode('utf-8', 'ignore'))
            try:
                _hash_file_into(os.path.join(path, rel), hasher)
            except OSError:
                continue
    else:
        _hash_file_into(path, hasher)
    digest = hasher.hexdigest()
    if cacheable:
        with _FP_LOCK:
            _FP_CACHE[key] = (signature, digest)
    return digest


def stat_signature(path: str, is_directory: bool, excludes: tuple = ()) -> Optional[Tuple[int, tuple]]:
    """Дешёвая «подпись» слота без чтения содержимого: (общий размер, ((путь, размер, mtime), ...)).
    Нужна, чтобы не хэшировать большие папки каждые N минут, пока ничего не менялось
    (для папки — только stat файлов); None, если пути нет."""
    if not path or not os.path.exists(path):
        return None
    try:
        if is_directory:
            files = _scan(path, excludes)
            return sum(f[1] for f in files), tuple(files)
        st = os.stat(path)
        return st.st_size, ((os.path.basename(path), st.st_size, st.st_mtime_ns),)
    except OSError:
        return None


def provider_for_account(store: ConfigStore, account):
    """Провайдер для аккаунта (секрет берётся из защищённого хранилища): (provider, error)."""
    account.secret = secrets_store.get_secret(account.id)
    try:
        return create_provider(account), None
    except ValueError as e:
        return None, str(e)


def catalog_key(account) -> str:
    """Путь файла-каталога игр в облаке: <база>/_catalog.json (общий для всех ПК)."""
    base = (account.config.get('base_folder', '') or '').strip().strip('/')
    return (_clean_segment(base) + '/' if base else '') + '_catalog.json'


def game_cloud_key(game: GameProfile) -> str:
    """Идентификатор игры в облаке (имя её папки) — по нему игры сопоставляются между ПК."""
    return (_clean_segment((game.remote_prefix or game.name or game.id).strip('/')) or game.id).lower()


def _get_provider(store: ConfigStore, game: GameProfile):
    """Возвращает (provider, account, error). Если error не пустой,
    provider и account — None."""
    if not game.account_id:
        return None, None, 'Для этой игры не выбран облачный аккаунт.'
    account = store.get_account(game.account_id)
    if not account:
        return None, None, 'Облачный аккаунт для этой игры не найден (возможно, был удалён).'
    account.secret = secrets_store.get_secret(account.id)
    try:
        provider = create_provider(account)
    except ValueError as e:
        return None, None, str(e)
    return provider, account, None


def _passphrase(account) -> Optional[str]:
    """Пароль шифрования, если для аккаунта включено шифрование; иначе None."""
    if not account or not account.config.get('encrypt'):
        return None
    return secrets_store.get_secret(account.id + ':enc') or ''


def _decrypt_if_needed(path: str, passphrase: Optional[str]) -> str:
    """Если скачанный файл зашифрован — расшифровывает (в тот же путь) и
    возвращает путь. Файлы, выгруженные до включения шифрования, читаются как есть."""
    if crypto_utils.is_encrypted(path):
        out = path + '.dec'
        crypto_utils.decrypt_file(path, out, passphrase or '')
        os.replace(out, path)
    return path


class Cancelled(Exception):
    """Операция отменена пользователем (бросается из callback прогресса)."""


PREV_SUFFIX = '.prev'  # предыдущая облачная версия лежит рядом с текущей


def parse_excludes(text: str) -> tuple:
    return tuple(p.strip().replace('\\', '/').lower() for p in (text or '').split(',') if p.strip())


def _excluded(rel: str, patterns: tuple) -> bool:
    """Подходит ли относительный путь под маску: по полному пути, имени файла или имени
    любой папки по пути (так 'cache' исключает всё внутри папки cache)."""
    if not patterns:
        return False
    rel = rel.replace('\\', '/').lower()
    parts = rel.split('/')
    return any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(parts[-1], p) or
               any(fnmatch.fnmatch(part, p) for part in parts[:-1]) for p in patterns)


def is_dangerous_target(path: str) -> bool:
    """Папки, которые нельзя целиком заменять загрузкой (корень диска, домашняя папка и
    её родители, AppData, Документы, Рабочий стол) — защита от опасного пути в слоте."""
    if not path:
        return True
    p = os.path.normcase(os.path.abspath(path))
    home = os.path.expanduser('~')
    protected = {home, os.path.join(home, 'AppData'), os.path.join(home, 'Documents'),
                 os.path.join(home, 'Desktop'), os.path.join(home, 'Downloads'),
                 os.environ.get('APPDATA', ''), os.environ.get('LOCALAPPDATA', ''),
                 os.environ.get('PROGRAMDATA', ''), os.environ.get('SYSTEMROOT', '')}
    protected = {os.path.normcase(os.path.abspath(x)) for x in protected if x}
    if p in protected or os.path.dirname(p) == p:  # корень диска
        return True
    home_n = os.path.normcase(os.path.abspath(home))
    return home_n.startswith(p + os.sep)  # предок домашней папки


Progress = Optional[Callable[[int, str], None]]  # progress(percent 0..100, text)


def _report(progress: Progress, percent: float, text: str):
    if progress:
        progress(max(0, min(100, int(percent))), text)


def _zip_directory(src_dir: str, dest_zip: str, progress: Progress, lo: int, hi: int,
                   excludes: tuple = ()):
    """Упаковывает папку в zip. Прогресс считается по байтам и отображается
    в диапазоне процентов lo..hi."""
    files = []
    total = 0
    for root, _dirs, names in os.walk(src_dir):
        for name in names:
            full = os.path.join(root, name)
            if excludes and _excluded(os.path.relpath(full, src_dir), excludes):
                continue
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            files.append((full, size))
            total += size
    done = 0
    with zipfile.ZipFile(dest_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        for full, size in files:
            zf.write(full, os.path.relpath(full, src_dir))
            done += size
            _report(progress, lo + (hi - lo) * (done / total if total else 1), 'Архивирование сохранения...')
    _report(progress, hi, 'Архивирование сохранения...')


def _safe_extract(zip_path: str, dest_dir: str, progress: Progress, lo: int, hi: int):
    """Распаковывает zip в dest_dir (с защитой от выхода за пределы папки).
    Реализация вынесена в zip_utils — ей же пользуется восстановление бэкапов."""
    from app.zip_utils import safe_extract
    safe_extract(zip_path, dest_dir,
                 (lambda pct, text: _report(progress, pct, text)) if progress else None,
                 lo, hi)


META_SUFFIX = '.meta.json'
MAX_PREV_COPY_BYTES = 100 * 1024 * 1024  # крупные облачные файлы не скачиваем ради копии


def _meta_key(remote_key: str) -> str:
    return remote_key + META_SUFFIX


def _read_cloud_meta(provider, remote_key: str) -> Optional[Dict[str, object]]:
    """Читает крошечный файл-метаданные рядом с сохранением (отпечаток, время,
    имя ПК). Позволяет проверять облако без скачивания самого сохранения."""
    tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False)
    tmp.close()
    try:
        ok, _ = provider.download_file(_meta_key(remote_key), tmp.name)
        if not ok:
            return None
        with open(tmp.name, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) and data.get('fingerprint') else None
    except (OSError, ValueError):
        return None
    finally:
        if os.path.exists(tmp.name):
            os.remove(tmp.name)


def _write_cloud_meta(provider, remote_key: str, fingerprint: str, size: int, is_directory: bool):
    tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w', encoding='utf-8')
    try:
        json.dump({'version': 1, 'fingerprint': fingerprint, 'size': size, 'is_directory': is_directory,
                   'uploaded_at': datetime.datetime.now().isoformat(timespec='seconds'),
                   'device': socket.gethostname()}, tmp)
        tmp.close()
        ok, msg = provider.upload_file(tmp.name, _meta_key(remote_key), message='meta')
        if not ok:
            log_action('upload_meta', 'fail', msg)
    except OSError as e:
        log_action('upload_meta', 'fail', str(e))
    finally:
        if os.path.exists(tmp.name):
            os.remove(tmp.name)


_INFO_CACHE: Dict[tuple, Tuple[float, Dict[str, object]]] = {}
_INFO_TTL = 3.0  # интерфейс перерисовывает карточки часто — не сканируем диск каждый раз


def local_info(slot: SaveSlot, use_cache: bool = True) -> Dict[str, object]:
    """Размер и время последнего изменения локального сохранения (для сравнения версий)."""
    path = slot.path
    if not path or not os.path.exists(path):
        return {}
    excludes = parse_excludes(slot.exclude_patterns)
    now = time.monotonic()
    if use_cache:
        hit = _INFO_CACHE.get((path, excludes))
        if hit and now - hit[0] < _INFO_TTL:
            return hit[1]
    try:
        if os.path.isfile(path):
            st = os.stat(path)
            info = {'size': st.st_size, 'mtime': st.st_mtime}
        else:
            files = _scan(path, excludes)
            info = {'size': sum(f[1] for f in files),
                    'mtime': max((f[2] for f in files), default=0) / 1e9}
    except OSError:
        return {}
    _INFO_CACHE[(path, excludes)] = (now, info)
    return info


def _keep_previous_cloud_version(provider, game: GameProfile, slot: SaveSlot, remote_key: str,
                                 meta: Optional[Dict[str, object]], new_fingerprint: str,
                                 passphrase: Optional[str] = None):
    """Перед перезаписью облака сохраняем прежнюю облачную версию в локальные
    резервные копии: ошибочная выгрузка не уничтожит последнюю хорошую версию."""
    if meta and (meta.get('fingerprint') == new_fingerprint or
                 int(meta.get('size') or 0) > MAX_PREV_COPY_BYTES):
        return
    tmp = tempfile.NamedTemporaryFile(suffix='.prev', delete=False)
    tmp.close()
    try:
        ok, _ = provider.download_file(remote_key, tmp.name)
        if ok:
            # одна предыдущая версия остаётся в облаке — откат возможен с любого ПК
            up_ok, up_msg = provider.upload_file(tmp.name, remote_key + PREV_SUFFIX, message='prev')
            if not up_ok:
                log_action('keep_previous', 'cloud_copy_fail', up_msg)
            _decrypt_if_needed(tmp.name, passphrase)  # в локальных копиях — расшифрованная версия
            store_cloud_copy(game.id, slot.id, tmp.name, slot.is_directory)
    except (OSError, CryptoError) as e:
        log_action('keep_previous', 'fail', str(e))
    finally:
        if os.path.exists(tmp.name):
            os.remove(tmp.name)


def upload_slot(store: ConfigStore, game: GameProfile, slot: SaveSlot, silent: bool = False,
                progress: Progress = None) -> Tuple[bool, str]:
    """Выгружает слот в облако. Папки перед выгрузкой архивируются в zip.
    progress(percent, text) — необязательный обратный вызов для индикатора."""
    if not slot.path or not os.path.exists(slot.path):
        msg = f'Файл/папка сохранения не найдены: {slot.path or "путь не указан"}'
        log_action('upload', 'fail', msg)
        return False, msg

    provider, account, err = _get_provider(store, game)
    if err:
        log_action('upload', 'fail', err)
        return False, err

    remote_key = _remote_key(account, game, slot)
    passphrase = _passphrase(account)
    if passphrase == '':
        return False, 'Включено шифрование, но не задан пароль — укажите его в настройках аккаунта.'
    tmp_zip = None
    tmp_enc = None
    try:
        excludes = parse_excludes(slot.exclude_patterns) if slot.is_directory else ()
        local_fingerprint = compute_fingerprint(slot.path, slot.is_directory, excludes)
        try:
            _keep_previous_cloud_version(provider, game, slot, remote_key,
                                         _read_cloud_meta(provider, remote_key), local_fingerprint,
                                         passphrase)
        except Exception as e:  # копия «на всякий случай» не должна блокировать выгрузку
            log_action('keep_previous', 'error', str(e))
        if slot.is_directory:
            tmp_zip = tempfile.NamedTemporaryFile(suffix='.zip', delete=False)
            tmp_zip.close()
            _zip_directory(slot.path, tmp_zip.name, progress, 0, 30, excludes)
            upload_path = tmp_zip.name
            lo, hi = 30, 100
        else:
            upload_path = slot.path
            lo, hi = 0, 100

        if passphrase:
            tmp_enc = tempfile.NamedTemporaryFile(suffix='.enc', delete=False)
            tmp_enc.close()
            crypto_utils.encrypt_file(upload_path, tmp_enc.name, passphrase)
            upload_path = tmp_enc.name

        def _net(done, total):
            _report(progress, lo + (hi - lo) * (done / total if total else 1), 'Отправка в облако...')

        _report(progress, lo, 'Отправка в облако...')
        message = f'{game.name}: {slot.label}' + (' [авто]' if silent else '')
        ok, result = provider.upload_file(upload_path, remote_key, message=message, progress=_net)
        if ok:
            _write_cloud_meta(provider, remote_key, local_fingerprint,
                              os.path.getsize(upload_path), slot.is_directory)
    except Cancelled:
        log_action('upload', 'cancelled', f'{game.name} / {slot.label}')
        return False, 'Отменено пользователем.'
    except (OSError, zipfile.BadZipFile, CryptoError) as e:
        log_action('upload', 'fail', f'{game.name} / {slot.label}: {e}')
        return False, f'Не удалось подготовить сохранение к выгрузке: {e}'
    finally:
        for tmp in (tmp_zip, tmp_enc):
            if tmp and os.path.exists(tmp.name):
                os.remove(tmp.name)

    if ok:
        _report(progress, 100, 'Готово')
        _save_slot_state(store, game, slot,
                         last_upload=datetime.datetime.now().isoformat(timespec='seconds'),
                         synced_fingerprint=local_fingerprint)
        log_action('upload', 'success', f'{game.name} / {slot.label} (auto={silent})')
    else:
        log_action('upload', 'fail', f'{game.name} / {slot.label}: {result}')
    return ok, result


def download_slot(store: ConfigStore, game: GameProfile, slot: SaveSlot,
                  progress: Progress = None, previous: bool = False) -> Tuple[bool, str]:
    """Скачивает слот из облака. Если слот — папка, архив распаковывается
    сначала во временную папку и только потом заменяет локальную — битый
    архив не уничтожит текущее сохранение. previous=True — откат к предыдущей
    облачной версии (отпечаток синхронизации при этом не меняется, поэтому
    дальше программа видит «локальная новее»)."""
    provider, account, err = _get_provider(store, game)
    if err:
        log_action('download', 'fail', err)
        return False, err
    if not slot.path:
        return False, 'Не указан путь, куда сохранять файл локально.'
    if slot.is_directory and is_dangerous_target(slot.path):
        return False, ('Опасный слишком общий путь — например, корень диска или «Документы». '
                       'Укажите конкретную папку именно с сохранением игры.')

    remote_key = _remote_key(account, game, slot) + (PREV_SUFFIX if previous else '')
    target = os.path.normpath(slot.path)  # без хвостового разделителя
    passphrase = _passphrase(account)
    tmp_download = tempfile.NamedTemporaryFile(suffix='.tmp', delete=False)
    tmp_download.close()
    extract_dir = None
    try:
        hi_net = 70 if slot.is_directory else 90

        def _net(done, total):
            _report(progress, hi_net * (done / total if total else 1), 'Скачивание из облака...')

        _report(progress, 0, 'Скачивание из облака...')
        ok, result = provider.download_file(remote_key, tmp_download.name, progress=_net)
        if not ok:
            if result == provider.NOT_FOUND:
                result = ('Предыдущей версии в облаке нет.' if previous else
                          'В облаке ещё нет сохранения для этого слота.')
            log_action('download', 'fail', f'{game.name} / {slot.label}: {result}')
            return False, result

        if crypto_utils.is_encrypted(tmp_download.name) and not passphrase:
            return False, 'Облачная копия зашифрована: включите шифрование и задайте пароль в аккаунте.'
        _decrypt_if_needed(tmp_download.name, passphrase)

        if slot.is_directory:
            extract_dir = tempfile.mkdtemp()
            _safe_extract(tmp_download.name, extract_dir, progress, 70, 95)

        # Резервная копия текущей локальной версии перед перезаписью
        make_local_backup(game.id, slot.id, target, slot.is_directory)

        if slot.is_directory:
            excludes = parse_excludes(slot.exclude_patterns)
            if os.path.isdir(target):
                if excludes:
                    _carry_excluded(target, extract_dir, excludes)  # исключённые файлы не теряем
                shutil.rmtree(target)
            os.makedirs(os.path.dirname(target) or '.', exist_ok=True)
            shutil.move(extract_dir, target)
            extract_dir = None
        else:
            os.makedirs(os.path.dirname(target) or '.', exist_ok=True)
            shutil.copy2(tmp_download.name, target)
    except Cancelled:
        log_action('download', 'cancelled', f'{game.name} / {slot.label}')
        return False, 'Отменено пользователем.'
    except (OSError, zipfile.BadZipFile, CryptoError) as e:
        log_action('download', 'fail', f'{game.name} / {slot.label}: {e}')
        return False, f'Не удалось применить загруженное сохранение: {e}'
    finally:
        if os.path.exists(tmp_download.name):
            os.remove(tmp_download.name)
        if extract_dir:
            shutil.rmtree(extract_dir, ignore_errors=True)

    _report(progress, 100, 'Готово')
    if not previous:
        _save_slot_state(store, game, slot,
                         last_download=datetime.datetime.now().isoformat(timespec='seconds'),
                         synced_fingerprint=compute_fingerprint(
                             slot.path, slot.is_directory,
                             parse_excludes(slot.exclude_patterns) if slot.is_directory else ()))
    log_action('download', 'success', f'{game.name} / {slot.label}' + (' (предыдущая версия)' if previous else ''))
    return True, ('Предыдущая облачная версия восстановлена локально. Чтобы сделать её основной, выгрузите её в облако.'
                  if previous else 'Сохранение успешно загружено из облака.')


def _carry_excluded(old_dir: str, new_dir: str, excludes: tuple) -> None:
    """Переносит из заменяемой папки файлы под исключения (кэш, логи) в новую."""
    for root, _dirs, names in os.walk(old_dir):
        for name in names:
            full = os.path.join(root, name)
            rel = os.path.relpath(full, old_dir)
            if _excluded(rel, excludes):
                dest = os.path.join(new_dir, rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(full, dest)


def prelaunch_sync(store: ConfigStore, game: GameProfile, progress: Progress = None) -> Dict[str, list]:
    """Перед запуском игры: если в облаке версия новее, а локальная с прошлой
    синхронизации не менялась (или локального файла нет) — безопасно скачиваем её.
    Конфликты и ошибки не решаем сами, а возвращаем вызывающему."""
    result = {'downloaded': [], 'conflicts': [], 'errors': [], 'ok': []}
    slots = [s for s in game.slots if s.path]
    for i, slot in enumerate(slots):
        _report(progress, 100 * i / max(1, len(slots)), f'Проверка облака: {slot.label}')
        status = check_slot_sync_status(store, game, slot)
        kind = status.get('status')
        if kind in ('cloud_newer', 'no_local_data'):
            ok, msg = download_slot(store, game, slot)
            (result['downloaded'] if ok else result['errors']).append((slot, msg))
        elif kind == 'conflict':
            result['conflicts'].append((slot, status))
        elif kind == 'error':
            result['errors'].append((slot, str(status.get('message') or 'облако недоступно')))
        else:
            result['ok'].append((slot, status))
    _report(progress, 100, 'Готово')
    return result


def auto_upload_slot(store: ConfigStore, game: GameProfile, slot: SaveSlot,
                     progress: Progress = None) -> Tuple[str, str, Dict[str, object]]:
    """Безопасная автовыгрузка после закрытия игры. Перед выгрузкой сверяется
    с облаком, чтобы НЕ затереть более новую версию (например, с другого ПК).

    Возвращает (результат, сообщение, статус), где результат — 'uploaded',
    'unchanged' (облако уже совпадает), 'skipped' (в облаке новее/конфликт —
    ничего не выгружено, нужно решение пользователя) или 'error'."""
    if not slot.path or not os.path.exists(slot.path):
        return 'error', f'Файл/папка сохранения не найдены: {slot.path or "путь не указан"}', {}
    info = local_info(slot, use_cache=False)
    if info and info.get('size') == 0:
        # пустой файл/папка почти наверняка результат сбоя игры — не затираем им облако
        log_action('auto_upload', 'skipped_empty', f'{game.name} / {slot.label}')
        return 'skipped', ('Локальное сохранение пустое — похоже на повреждённое, автовыгрузка '
                           'пропущена, чтобы не затереть хорошую копию в облаке.'), {'status': 'empty_local'}
    status = check_slot_sync_status(store, game, slot)
    kind = status.get('status')
    if kind == 'error':
        return 'error', str(status.get('message') or 'Не удалось проверить облако.'), status
    if kind == 'up_to_date':
        return 'unchanged', 'Облако уже содержит эту версию.', status
    if kind in ('cloud_newer', 'conflict'):
        log_action('auto_upload', 'skipped', f'{game.name} / {slot.label}: {kind}')
        return 'skipped', ('В облаке более новая версия или конфликт — автовыгрузка '
                           'пропущена, чтобы ничего не потерять.'), status
    # no_cloud_data / local_newer / no_local_data(невозможно тут) — выгружаем
    ok, message = upload_slot(store, game, slot, silent=True, progress=progress)
    return ('uploaded' if ok else 'error'), message, status


# ---------- проверка, нет ли в облаке более новой версии ----------

def _cloud_state(store: ConfigStore, game: GameProfile, slot: SaveSlot):
    """Возвращает (fingerprint, meta, error). Сначала читаются крошечные
    метаданные; если их нет (сохранение выгружено старой версией программы) —
    сохранение скачивается целиком и хешируется."""
    provider, account, err = _get_provider(store, game)
    if err:
        return None, None, err
    remote_key = _remote_key(account, game, slot)
    meta = _read_cloud_meta(provider, remote_key)
    if meta:
        return str(meta['fingerprint']), meta, None
    passphrase = _passphrase(account)
    tmp = tempfile.NamedTemporaryFile(suffix='.tmp', delete=False)
    tmp.close()
    try:
        ok, result = provider.download_file(remote_key, tmp.name)
        if not ok:
            return None, None, result
        _decrypt_if_needed(tmp.name, passphrase)
        if slot.is_directory:
            extract_dir = tempfile.mkdtemp()
            try:
                _safe_extract(tmp.name, extract_dir, None, 0, 0)
                # Старые архивы могли включать исключённые файлы — считаем
                # отпечаток по тем же маскам, что и локальный, иначе ложный conflict.
                excludes = parse_excludes(slot.exclude_patterns)
                return compute_fingerprint(extract_dir, True, excludes), None, None
            finally:
                shutil.rmtree(extract_dir, ignore_errors=True)
        return compute_fingerprint(tmp.name, False), None, None
    except (OSError, zipfile.BadZipFile, CryptoError) as e:
        return None, None, str(e)
    finally:
        if os.path.exists(tmp.name):
            os.remove(tmp.name)


def compute_cloud_fingerprint(store: ConfigStore, game: GameProfile, slot: SaveSlot) -> Tuple[Optional[str], Optional[str]]:
    """Отпечаток облачной версии слота: (fingerprint, None) либо (None, error);
    error может быть CloudProvider.NOT_FOUND, если в облаке ещё ничего нет."""
    fp, _meta, err = _cloud_state(store, game, slot)
    return fp, err


def check_slot_sync_status(store: ConfigStore, game: GameProfile, slot: SaveSlot) -> Dict[str, object]:
    """Сравнивает локальный файл, облако и отпечаток последней синхронизации,
    чтобы понять, можно ли безопасно предложить скачать более новую версию.

    Возможные статусы:
      no_account     — у игры не выбран облачный аккаунт;
      no_cloud_data  — в облаке ещё нет сохранения для этого слота;
      no_local_data  — локального файла нет (например, игра ни разу не запускалась);
      up_to_date     — локальная и облачная версии совпадают;
      cloud_newer    — в облаке есть более новая версия, локальный файл с прошлой
                        синхронизации не менялся — можно безопасно предложить скачать;
      local_newer    — локальный файл изменился, а облако — нет (типичная ситуация
                        сразу после игры, до автоматической выгрузки);
      conflict       — и локальный файл, и облако изменились независимо друг от
                        друга — нужно явно спросить пользователя;
      error          — не удалось проверить (сеть, неверные данные и т.д.).
    """
    if not game.account_id:
        return {'status': 'no_account'}

    cloud_fp, cloud_meta, err = _cloud_state(store, game, slot)
    if cloud_fp is None:
        if err == CloudProvider.NOT_FOUND:
            return {'status': 'no_cloud_data'}
        return {'status': 'error', 'message': err}

    local_fp = compute_fingerprint(slot.path, slot.is_directory,
                                   parse_excludes(slot.exclude_patterns) if slot.is_directory else ())
    if local_fp is None:
        return {'status': 'no_local_data', 'cloud_fp': cloud_fp, 'cloud_meta': cloud_meta}

    if local_fp == cloud_fp:
        return {'status': 'up_to_date', 'cloud_fp': cloud_fp, 'local_fp': local_fp, 'cloud_meta': cloud_meta}

    synced = slot.synced_fingerprint
    if synced and local_fp == synced and cloud_fp != synced:
        return {'status': 'cloud_newer', 'cloud_fp': cloud_fp, 'local_fp': local_fp, 'cloud_meta': cloud_meta}
    if synced and cloud_fp == synced and local_fp != synced:
        return {'status': 'local_newer', 'cloud_fp': cloud_fp, 'local_fp': local_fp, 'cloud_meta': cloud_meta}
    return {'status': 'conflict', 'cloud_fp': cloud_fp, 'local_fp': local_fp, 'cloud_meta': cloud_meta}


# ---------- отметка «сейчас играют на …» (защита от игры на двух ПК) ----------

PLAY_FRESH_SECONDS = 15 * 60   # отметка старше этого считается устаревшей (ПК мог выключиться)
PLAY_HEARTBEAT_SECONDS = 5 * 60


def _play_key(account, game: GameProfile) -> str:
    return _remote_key(account, game, SaveSlot(remote_name='_playing.json'))


def set_playing(store: ConfigStore, game: GameProfile, playing: bool) -> Tuple[bool, str]:
    """Пишет в облако отметку: этот ПК играет (или закончил). Маленький файл рядом с сохранениями."""
    provider, account, err = _get_provider(store, game)
    if err:
        return False, err
    tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w', encoding='utf-8')
    try:
        json.dump({'state': 'playing' if playing else 'idle', 'device': socket.gethostname(),
                   'at': datetime.datetime.now().isoformat(timespec='seconds')}, tmp)
        tmp.close()
        return provider.upload_file(tmp.name, _play_key(account, game), message='playing')
    except OSError as e:
        return False, str(e)
    finally:
        if os.path.exists(tmp.name):
            os.remove(tmp.name)


def playing_elsewhere(store: ConfigStore, game: GameProfile) -> Optional[Dict[str, str]]:
    """Если по отметке в облаке игра СЕЙЧАС идёт на другом ПК — {'device', 'since'}, иначе None."""
    provider, account, err = _get_provider(store, game)
    if err:
        return None
    tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False)
    tmp.close()
    try:
        ok, _ = provider.download_file(_play_key(account, game), tmp.name)
        if not ok:
            return None
        with open(tmp.name, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if data.get('state') != 'playing' or data.get('device') == socket.gethostname():
            return None
        age = (datetime.datetime.now() - datetime.datetime.fromisoformat(data.get('at'))).total_seconds()
        if age > PLAY_FRESH_SECONDS:
            return None
        return {'device': str(data.get('device', '?')), 'since': str(data.get('at', ''))}
    except (OSError, ValueError, TypeError):
        return None
    finally:
        if os.path.exists(tmp.name):
            os.remove(tmp.name)
