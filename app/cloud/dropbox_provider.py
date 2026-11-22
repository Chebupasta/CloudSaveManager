"""
Провайдер Dropbox (HTTP API). Авторизация — OAuth2 PKCE без «секрета приложения»:
вы создаёте своё приложение в Dropbox App Console (тип Scoped access, App folder
или Full Dropbox, права files.content.read / files.content.write / account_info.read),
вводите App key, получаете код в браузере и вставляете его в программу — она
обменивает его на долгоживущий refresh token (он хранится как секрет аккаунта).

config: {'app_key': '...', 'base_folder': 'CloudSaveManager'}
secret: refresh token.
"""
import base64
import hashlib
import json
import secrets as _secrets
import time
from typing import Tuple
from urllib.parse import urlencode

import requests

from app.cloud.base import CloudProvider, ProgressReader, stream_to_file

TIMEOUT = 30
API = 'https://api.dropboxapi.com'
CONTENT = 'https://content.dropboxapi.com'
TOKEN_URL = API + '/oauth2/token'
AUTH_URL = 'https://www.dropbox.com/oauth2/authorize'


def new_verifier() -> str:
    return base64.urlsafe_b64encode(_secrets.token_bytes(48)).decode().rstrip('=')


def authorize_url(app_key: str, verifier: str) -> str:
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    return AUTH_URL + '?' + urlencode({
        'client_id': app_key, 'response_type': 'code', 'code_challenge': challenge,
        'code_challenge_method': 'S256', 'token_access_type': 'offline'})


def exchange_code(app_key: str, code: str, verifier: str) -> Tuple[bool, str]:
    """Меняет код авторизации на refresh token. Возвращает (ok, token или текст ошибки)."""
    try:
        r = requests.post(TOKEN_URL, data={'code': code.strip(), 'grant_type': 'authorization_code',
                                           'code_verifier': verifier, 'client_id': app_key.strip()},
                          timeout=TIMEOUT)
    except requests.RequestException as e:
        return False, f'Ошибка сети: {e}'
    if r.status_code != 200:
        return False, f'Dropbox отклонил код: {r.status_code} {r.text[:200]}'
    token = r.json().get('refresh_token')
    return (True, token) if token else (False, 'Dropbox не вернул refresh token (нужен token_access_type=offline).')


class DropboxProvider(CloudProvider):
    def __init__(self, config: dict, secret: str = ''):
        super().__init__(config, secret)
        self._access = ''
        self._expires = 0.0

    def _token(self) -> Tuple[str, str]:
        """(access_token, ошибка). Обновляется по refresh token за минуту до истечения."""
        if self._access and time.time() < self._expires - 60:
            return self._access, ''
        app_key = self.config.get('app_key', '').strip()
        if not app_key or not self.secret:
            return '', 'Укажите App key и подключите Dropbox (получите код авторизации).'
        try:
            r = requests.post(TOKEN_URL, data={'grant_type': 'refresh_token', 'refresh_token': self.secret,
                                               'client_id': app_key}, timeout=TIMEOUT)
        except requests.RequestException as e:
            return '', f'Ошибка сети: {e}'
        if r.status_code != 200:
            return '', f'Не удалось обновить доступ к Dropbox: {r.status_code} {r.text[:200]}'
        data = r.json()
        self._access = data['access_token']
        self._expires = time.time() + int(data.get('expires_in', 14400))
        return self._access, ''

    def _path(self, remote_key: str) -> str:
        base = self.config.get('base_folder', 'CloudSaveManager').strip().strip('/')
        return '/' + '/'.join(p for p in (base, remote_key.strip('/')) if p)

    @staticmethod
    def _arg(**kwargs) -> str:
        return json.dumps(kwargs, ensure_ascii=True)  # заголовок Dropbox-API-Arg должен быть ASCII

    def test_connection(self) -> Tuple[bool, str]:
        token, err = self._token()
        if err:
            return False, err
        try:
            r = requests.post(API + '/2/users/get_current_account',
                              headers={'Authorization': f'Bearer {token}'}, timeout=TIMEOUT)
        except requests.RequestException as e:
            return False, f'Ошибка сети: {e}'
        if r.status_code != 200:
            return False, f'Dropbox вернул ошибку: {r.status_code} {r.text[:200]}'
        return True, 'Подключение к Dropbox успешно: ' + r.json().get('email', 'аккаунт найден')

    def upload_file(self, local_path: str, remote_key: str, message: str = '',
                    progress=None) -> Tuple[bool, str]:
        token, err = self._token()
        if err:
            return False, err
        try:
            with open(local_path, 'rb') as f:
                content = f.read()
        except OSError as e:
            return False, f'Не удалось прочитать файл: {e}'
        if len(content) > 140 * 1024 * 1024:
            return False, 'Файл больше 140 МБ — слишком велик для простой загрузки в Dropbox.'
        try:
            r = requests.post(CONTENT + '/2/files/upload', timeout=TIMEOUT * 4,
                              headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/octet-stream',
                                       'Dropbox-API-Arg': self._arg(path=self._path(remote_key), mode='overwrite',
                                                                    mute=True)},
                              data=ProgressReader(content, progress))
        except requests.RequestException as e:
            return False, f'Ошибка сети: {e}'
        if r.status_code != 200:
            return False, f'Ошибка Dropbox при выгрузке: {r.status_code} {r.text[:200]}'
        return True, 'Сохранение выгружено в Dropbox.'

    def download_file(self, remote_key: str, local_path: str, progress=None) -> Tuple[bool, str]:
        token, err = self._token()
        if err:
            return False, err
        try:
            r = requests.post(CONTENT + '/2/files/download', timeout=TIMEOUT * 4, stream=True,
                              headers={'Authorization': f'Bearer {token}',
                                       'Dropbox-API-Arg': self._arg(path=self._path(remote_key))})
            if r.status_code == 409 and 'not_found' in r.text:
                return False, self.NOT_FOUND
            if r.status_code != 200:
                return False, f'Ошибка Dropbox при загрузке: {r.status_code} {r.text[:200]}'
            if not stream_to_file(r, local_path, progress):
                return False, 'Загруженный файл пустой.'
        except requests.RequestException as e:
            return False, f'Ошибка сети: {e}'
        return True, 'Сохранение загружено из Dropbox.'
