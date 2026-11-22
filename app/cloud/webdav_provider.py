"""
Универсальный провайдер WebDAV. Подходит для любого сервиса с поддержкой
протокола WebDAV, в том числе:
  - Яндекс.Диск (https://webdav.yandex.ru, вход по логину и "паролю
    приложения" — обычный пароль от Яндекс ID не подходит из-за 2FA);
  - Nextcloud/ownCloud (обычно https://<сервер>/remote.php/dav/files/<логин>/);
  - mail.ru Облако, Box.com, Koofr и другие сервисы с WebDAV-доступом.

config: {
    'base_url': 'https://webdav.yandex.ru',
    'username': 'логин',
    'remote_folder': '/CloudSaveManager',
}
secret: пароль (или пароль приложения).
"""
import posixpath
from typing import Tuple

import requests
from requests.auth import HTTPBasicAuth

from app.cloud.base import CloudProvider, ProgressReader, stream_to_file

TIMEOUT = 30


class WebDAVProvider(CloudProvider):
    def _base_url(self) -> str:
        return self.config.get('base_url', '').strip().rstrip('/')

    def _auth(self) -> HTTPBasicAuth:
        return HTTPBasicAuth(self.config.get('username', ''), self.secret)

    def _remote_folder(self) -> str:
        folder = self.config.get('remote_folder', '/CloudSaveManager').strip()
        if not folder.startswith('/'):
            folder = '/' + folder
        return folder.rstrip('/') or '/CloudSaveManager'

    def _full_url(self, remote_key: str) -> str:
        path = posixpath.join(self._remote_folder(), remote_key.lstrip('/'))
        return self._base_url() + path

    def _ensure_folder(self, folder_path: str):
        """Рекурсивно создаёт папки на сервере (MKCOL), игнорируя ошибки,
        если папка уже существует."""
        parts = [p for p in folder_path.split('/') if p]
        current = ''
        for part in parts:
            current += '/' + part
            url = self._base_url() + current
            try:
                requests.request('MKCOL', url, auth=self._auth(), timeout=TIMEOUT)
            except requests.RequestException:
                pass  # некритично: если папка не создалась, PUT ниже вернёт понятную ошибку

    def test_connection(self) -> Tuple[bool, str]:
        if not self._base_url() or not self.config.get('username') or not self.secret:
            return False, 'Укажите адрес сервера, логин и пароль (пароль приложения).'
        try:
            self._ensure_folder(self._remote_folder())
            r = requests.request('PROPFIND', self._base_url() + self._remote_folder(),
                                  auth=self._auth(), headers={'Depth': '0'}, timeout=TIMEOUT)
        except requests.RequestException as e:
            return False, f'Ошибка сети: {e}'
        if r.status_code in (207, 200):
            return True, 'Подключение к WebDAV успешно установлено.'
        if r.status_code == 401:
            return False, 'Неверный логин или пароль (для Яндекс.Диска нужен пароль приложения).'
        return False, f'Ошибка WebDAV: {r.status_code} {r.text[:200]}'

    def upload_file(self, local_path: str, remote_key: str, message: str = '',
                    progress=None) -> Tuple[bool, str]:
        folder = posixpath.dirname(posixpath.join(self._remote_folder(), remote_key.lstrip('/')))
        self._ensure_folder(folder)
        try:
            with open(local_path, 'rb') as f:
                content = f.read()
        except OSError as e:
            return False, f'Не удалось прочитать файл: {e}'
        if not content:
            return False, 'Файл сохранения пустой.'
        try:
            r = requests.put(self._full_url(remote_key), data=ProgressReader(content, progress), auth=self._auth(), timeout=TIMEOUT)
        except requests.RequestException as e:
            return False, f'Ошибка сети: {e}'
        if r.status_code in (200, 201, 204):
            return True, 'Сохранение успешно выгружено по WebDAV.'
        if r.status_code == 401:
            return False, 'Неверный логин или пароль.'
        return False, f'Ошибка загрузки: {r.status_code} {r.text[:300]}'

    def download_file(self, remote_key: str, local_path: str, progress=None) -> Tuple[bool, str]:
        try:
            r = requests.get(self._full_url(remote_key), auth=self._auth(), timeout=TIMEOUT, stream=True)
            if r.status_code == 404:
                return False, self.NOT_FOUND
            if r.status_code != 200:
                return False, f'Ошибка WebDAV: {r.status_code} {r.text[:200]}'
            if not stream_to_file(r, local_path, progress):
                return False, 'Загруженный файл пустой.'
        except requests.RequestException as e:
            return False, f'Ошибка сети: {e}'
        return True, 'Сохранение успешно загружено по WebDAV.'
