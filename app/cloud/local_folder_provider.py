"""
"Облачный" провайдер, который на самом деле просто копирует файл в
указанную локальную папку. Полезен, если на компьютере уже установлен
десктопный клиент Dropbox / Google Диск / OneDrive / Яндекс.Диск —
достаточно указать путь к папке внутри синхронизируемого каталога,
и сам клиент сервиса выгрузит файл в облако. Не требует токенов и
API-ключей вообще.

config: {'folder': 'C:/Users/me/Dropbox/CloudSaveManager'}
"""
import os
from typing import Tuple

from app.cloud.base import CloudProvider


def _copy_with_progress(src: str, dst: str, progress=None):
    total = os.path.getsize(src)
    done = 0
    # Пишем во временный файл и переименовываем: клиент Dropbox/Яндекс.Диска
    # не успеет засинхронизировать наполовину записанный файл.
    part = dst + '.part'
    try:
        with open(src, 'rb') as fi, open(part, 'wb') as fo:
            while True:
                chunk = fi.read(1024 * 1024)
                if not chunk:
                    break
                fo.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        os.replace(part, dst)
    finally:
        if os.path.exists(part):  # ошибка или отмена — недописанный файл не оставляем
            os.remove(part)
    if progress and total == 0:
        progress(1, 1)


class LocalFolderProvider(CloudProvider):
    def _folder(self) -> str:
        return os.path.expanduser(os.path.expandvars(self.config.get('folder', '').strip()))

    def _full_path(self, remote_key: str) -> str:
        # remote_key может содержать '/', приводим к системному разделителю
        parts = remote_key.split('/')
        return os.path.join(self._folder(), *parts)

    def test_connection(self) -> Tuple[bool, str]:
        folder = self._folder()
        if not folder:
            return False, 'Укажите путь к синхронизируемой папке.'
        try:
            os.makedirs(folder, exist_ok=True)
            test_file = os.path.join(folder, '.cloudsave_test')
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write('ok')
            os.remove(test_file)
        except OSError as e:
            return False, f'Нет доступа для записи в папку: {e}'
        return True, 'Папка доступна для записи.'

    def upload_file(self, local_path: str, remote_key: str, message: str = '',
                    progress=None) -> Tuple[bool, str]:
        dest = self._full_path(remote_key)
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            _copy_with_progress(local_path, dest, progress)
        except OSError as e:
            return False, f'Ошибка копирования: {e}'
        return True, 'Сохранение скопировано в синхронизируемую папку.'

    def download_file(self, remote_key: str, local_path: str, progress=None) -> Tuple[bool, str]:
        src = self._full_path(remote_key)
        if not os.path.isfile(src):
            return False, self.NOT_FOUND
        try:
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            _copy_with_progress(src, local_path, progress)
        except OSError as e:
            return False, f'Ошибка копирования: {e}'
        return True, 'Сохранение скопировано из синхронизируемой папки.'
