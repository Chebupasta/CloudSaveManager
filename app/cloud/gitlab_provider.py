"""
Провайдер GitLab: хранит сохранения как файлы в приватном репозитории
через GitLab Repository Files API. Поддерживает как gitlab.com, так и
собственные (self-hosted) инстансы GitLab.
"""
import base64
import json
from typing import Tuple
from urllib.parse import quote

import requests

from app.cloud.base import CloudProvider, ProgressReader

TIMEOUT = 20


class GitLabProvider(CloudProvider):
    """config: {'project': 'namespace/project' или числовой ID,
                'base_url': 'https://gitlab.com' (необязательно, для self-hosted)}
    secret: Personal Access Token с правом api или write_repository."""

    def _api_base(self) -> str:
        base_url = self.config.get('base_url', 'https://gitlab.com').strip().rstrip('/')
        return f'{base_url or "https://gitlab.com"}/api/v4'

    def _project(self) -> str:
        project = str(self.config.get('project', '')).strip()
        base = self.config.get('base_url', 'https://gitlab.com').strip().rstrip('/')
        if project.startswith(base + '/'):  # вставили полную ссылку на проект
            project = project[len(base) + 1:]
        if project.endswith('.git'):
            project = project[:-4]
        return quote(project.strip('/'), safe='')

    def _headers(self) -> dict:
        return {'PRIVATE-TOKEN': self.secret}

    def _default_branch(self) -> str:
        try:
            r = requests.get(f'{self._api_base()}/projects/{self._project()}',
                              headers=self._headers(), timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json().get('default_branch', 'main')
        except requests.RequestException:
            pass
        return 'main'

    def test_connection(self) -> Tuple[bool, str]:
        if not str(self.config.get('project', '')).strip() or not self.secret:
            return False, 'Укажите проект (namespace/project) и токен доступа.'
        try:
            r = requests.get(f'{self._api_base()}/projects/{self._project()}',
                              headers=self._headers(), timeout=TIMEOUT)
        except requests.RequestException as e:
            return False, f'Ошибка сети: {e}'
        if r.status_code == 200:
            return True, 'Доступ к проекту GitLab подтверждён.'
        if r.status_code == 404:
            return False, 'Проект не найден. Проверьте путь namespace/project.'
        if r.status_code == 401:
            return False, 'Неверный токен доступа.'
        return False, f'Ошибка GitLab API: {r.status_code} {r.text[:200]}'

    def upload_file(self, local_path: str, remote_key: str, message: str = '',
                    progress=None) -> Tuple[bool, str]:
        branch = self._default_branch()
        file_path = quote(remote_key, safe='')
        url = f'{self._api_base()}/projects/{self._project()}/repository/files/{file_path}'
        try:
            with open(local_path, 'rb') as f:
                content = f.read()
        except OSError as e:
            return False, f'Не удалось прочитать файл: {e}'
        if not content:
            return False, 'Файл сохранения пустой.'
        payload = {
            'branch': branch,
            'content': base64.b64encode(content).decode('utf-8'),
            'encoding': 'base64',
            'commit_message': message or f'Обновление сохранения ({remote_key})',
        }
        try:
            r = requests.get(url, headers=self._headers(), params={'ref': branch}, timeout=TIMEOUT)
            exists = r.status_code == 200
            method = requests.put if exists else requests.post
            headers = dict(self._headers(), **{'Content-Type': 'application/json'})
            r = method(url, headers=headers,
                       data=ProgressReader(json.dumps(payload).encode('utf-8'), progress), timeout=TIMEOUT)
        except requests.RequestException as e:
            return False, f'Ошибка сети: {e}'
        if r.status_code in (200, 201):
            return True, 'Сохранение успешно выгружено на GitLab.'
        return False, f'Ошибка загрузки: {r.status_code} {r.text[:300]}'

    def download_file(self, remote_key: str, local_path: str, progress=None) -> Tuple[bool, str]:
        branch = self._default_branch()
        file_path = quote(remote_key, safe='')
        url = f'{self._api_base()}/projects/{self._project()}/repository/files/{file_path}'
        try:
            r = requests.get(url, headers=self._headers(), params={'ref': branch}, timeout=TIMEOUT)
        except requests.RequestException as e:
            return False, f'Ошибка сети: {e}'
        if r.status_code == 404:
            return False, self.NOT_FOUND
        if r.status_code != 200:
            return False, f'Ошибка GitLab API: {r.status_code} {r.text[:200]}'
        data = r.json()
        try:
            content = base64.b64decode(data['content'])
        except (KeyError, ValueError) as e:
            return False, f'Ошибка декодирования файла: {e}'
        if not content:
            return False, 'Загруженный файл пустой.'
        with open(local_path, 'wb') as f:
            f.write(content)
        if progress:
            progress(len(content), len(content))
        return True, 'Сохранение успешно загружено с GitLab.'
