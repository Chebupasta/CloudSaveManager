"""
Провайдер GitHub: хранит сохранения как файлы в приватном репозитории,
используя GitHub Contents API. Каждая выгрузка создаёт новый коммит,
поэтому при очень частом использовании GitHub может посчитать это
подозрительной активностью — приложение больше не делает автосохранение
по таймеру, а выгружает данные только вручную или один раз при закрытии
игры.
"""
import base64
import json
import re
from typing import Tuple

import requests

from app.cloud.base import CloudProvider, ProgressReader, stream_to_file

TIMEOUT = 20


class GitHubProvider(CloudProvider):
    """config: {'repo_url': 'https://github.com/user/repo.git' или 'user/repo'}
    secret: personal access token с правом 'repo'."""

    def _repo_path(self) -> str:
        repo = self.config.get('repo_url', '').strip()
        repo = re.sub(r'^(https?://)?(www\.)?github\.com[/:]', '', repo)
        repo = re.sub(r'^git@github\.com:', '', repo)
        if repo.endswith('.git'):
            repo = repo[:-4]
        return repo.strip('/')

    def _headers(self) -> dict:
        return {'Authorization': f'token {self.secret}', 'Accept': 'application/vnd.github+json'}

    def _default_branch(self, repo_path: str) -> str:
        try:
            r = requests.get(f'https://api.github.com/repos/{repo_path}',
                              headers=self._headers(), timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json().get('default_branch', 'main')
        except requests.RequestException:
            pass
        return 'main'

    def test_connection(self) -> Tuple[bool, str]:
        repo_path = self._repo_path()
        if not repo_path or not self.secret:
            return False, 'Укажите ссылку на репозиторий и токен доступа.'
        try:
            r = requests.get(f'https://api.github.com/repos/{repo_path}',
                              headers=self._headers(), timeout=TIMEOUT)
        except requests.RequestException as e:
            return False, f'Ошибка сети: {e}'
        if r.status_code == 200:
            return True, 'Доступ к репозиторию подтверждён.'
        if r.status_code == 404:
            return False, 'Репозиторий не найден. Проверьте ссылку и права токена.'
        if r.status_code == 401:
            return False, 'Неверный токен доступа.'
        return False, f'Ошибка GitHub API: {r.status_code} {r.text[:200]}'

    def upload_file(self, local_path: str, remote_key: str, message: str = '',
                    progress=None) -> Tuple[bool, str]:
        repo_path = self._repo_path()
        branch = self._default_branch(repo_path)
        api_url = f'https://api.github.com/repos/{repo_path}/contents/{remote_key}'
        try:
            with open(local_path, 'rb') as f:
                content = f.read()
        except OSError as e:
            return False, f'Не удалось прочитать файл: {e}'
        if not content:
            return False, 'Файл сохранения пустой.'
        b64_content = base64.b64encode(content).decode('utf-8')
        try:
            r = requests.get(api_url, headers=self._headers(), params={'ref': branch}, timeout=TIMEOUT)
        except requests.RequestException as e:
            return False, f'Ошибка сети: {e}'
        body = r.json() if r.status_code == 200 else None
        sha = body.get('sha') if isinstance(body, dict) else None
        data = {
            'message': message or f'Обновление сохранения ({remote_key})',
            'content': b64_content,
            'branch': branch,
        }
        if sha:
            data['sha'] = sha
        try:
            r = requests.put(api_url, headers=self._headers(),
                             data=ProgressReader(json.dumps(data).encode('utf-8'), progress), timeout=TIMEOUT)
        except requests.RequestException as e:
            return False, f'Ошибка сети: {e}'
        if r.status_code in (200, 201):
            return True, 'Сохранение успешно выгружено на GitHub.'
        return False, f'Ошибка загрузки: {r.status_code} {r.text[:300]}'

    def download_file(self, remote_key: str, local_path: str, progress=None) -> Tuple[bool, str]:
        repo_path = self._repo_path()
        branch = self._default_branch(repo_path)
        api_url = f'https://api.github.com/repos/{repo_path}/contents/{remote_key}'
        try:
            r = requests.get(api_url, headers=self._headers(), params={'ref': branch}, timeout=TIMEOUT)
        except requests.RequestException as e:
            return False, f'Ошибка сети: {e}'
        if r.status_code == 404:
            return False, self.NOT_FOUND
        if r.status_code != 200:
            return False, f'Ошибка GitHub API: {r.status_code} {r.text[:200]}'
        json_data = r.json()
        try:
            if json_data.get('download_url'):
                file_resp = requests.get(json_data['download_url'], timeout=TIMEOUT, stream=True)
                if file_resp.status_code != 200:
                    return False, f'Ошибка скачивания: {file_resp.status_code}'
                if not stream_to_file(file_resp, local_path, progress):
                    return False, 'Загруженный файл пустой.'
            else:
                content = base64.b64decode(json_data['content'])
                if not content:
                    return False, 'Загруженный файл пустой.'
                with open(local_path, 'wb') as f:
                    f.write(content)
                if progress:
                    progress(len(content), len(content))
        except (requests.RequestException, KeyError, ValueError) as e:
            return False, f'Ошибка получения содержимого файла: {e}'
        return True, 'Сохранение успешно загружено с GitHub.'
