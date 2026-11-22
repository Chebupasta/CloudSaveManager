"""Автообновление из GitHub Releases: проверка версии, скачивание .exe
и замена запущенного файла после выхода программы (только Windows)."""
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Optional

import requests

from app.constants import get_app_dir
from app.version import __version__, is_newer, parse_version

_API = 'https://api.github.com/repos/{repo}/releases/latest'
_REPO_RE = re.compile(r'^[\w.-]+/[\w.-]+$')
UA = {'User-Agent': 'CloudSaveManager', 'Accept': 'application/vnd.github+json'}


@dataclass
class UpdateInfo:
    version: str
    notes: str
    page: str
    asset_url: str
    asset_name: str
    current: str = __version__


def valid_repo(repo: str) -> bool:
    return bool(_REPO_RE.fullmatch((repo or '').strip()))


def check_for_update(repo: str, timeout: int = 8) -> Optional[UpdateInfo]:
    """Вернуть информацию о новой версии или None, если обновлений нет/сеть недоступна."""
    repo = (repo or '').strip()
    if not valid_repo(repo):
        return None
    try:
        response = requests.get(_API.format(repo=repo), headers=UA, timeout=timeout)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return None

    tag = str(data.get('tag_name') or '')
    if not tag or not is_newer(tag, __version__):
        return None
    asset = ''
    asset_name = ''
    for item in data.get('assets') or []:
        name = str(item.get('name') or '')
        if name.lower().endswith('.exe'):
            asset = str(item.get('browser_download_url') or '')
            asset_name = name
            break
    return UpdateInfo(
        version='.'.join(str(v) for v in parse_version(tag)),
        notes=str(data.get('body') or '')[:1200],
        page=str(data.get('html_url') or f'https://github.com/{repo}/releases'),
        asset_url=asset,
        asset_name=asset_name,
    )


def updates_dir() -> str:
    path = os.path.join(get_app_dir(), 'updates')
    os.makedirs(path, exist_ok=True)
    return path


def download_update(url: str, destination: str, progress=None, timeout: int = 60) -> str:
    """Скачать .exe с прогрессом. progress(percent, text)."""
    response = requests.get(url, headers=UA, stream=True, timeout=timeout)
    response.raise_for_status()
    total = int(response.headers.get('Content-Length') or 0)
    done = 0
    with open(destination, 'wb') as handle:
        for chunk in response.iter_content(chunk_size=1024 * 256):
            if not chunk:
                continue
            handle.write(chunk)
            done += len(chunk)
            if progress:
                pct = min(99, int(100 * done / total)) if total else 0
                progress(pct, 'Скачивание обновления...')
    if progress:
        progress(100, 'Обновление скачано')
    return destination


def schedule_replace(new_exe: str, target_exe: str, pid: int) -> bool:
    """Подготовить замену .exe после выхода программы и запустить её заново.
    Возвращает False, если автоматическая замена невозможна (не Windows / source)."""
    if not sys.platform.startswith('win') or getattr(sys, 'frozen', False) is False:
        return False
    target = os.path.abspath(target_exe)
    source = os.path.abspath(new_exe)
    if not os.path.isfile(source) or not os.path.isfile(target):
        return False
    bat = os.path.join(tempfile.gettempdir(), 'csm_update.bat')
    script = (
        '@echo off\r\n'
        ':wait\r\n'
        f'tasklist /FI "PID eq {pid}" 2>NUL | find /I "{pid}" >NUL\r\n'
        'if %ERRORLEVEL%==0 (ping -n 2 127.0.0.1 >NUL & goto wait)\r\n'
        'ping -n 2 127.0.0.1 >NUL\r\n'
        'set N=0\r\n'
        ':move\r\n'
        f'move /Y "{source}" "{target}" >NUL\r\n'
        'if errorlevel 1 (\r\n'
        '  set /A N+=1\r\n'
        '  if %N% GEQ 15 goto fail\r\n'
        '  ping -n 2 127.0.0.1 >NUL\r\n'
        '  goto move\r\n'
        ')\r\n'
        f'start "" "{target}"\r\n'
        'goto done\r\n'
        ':fail\r\n'
        f'del /F /Q "{source}" >NUL 2>&1\r\n'
        ':done\r\n'
        'del /F /Q "%~f0" >NUL 2>&1\r\n'
    )
    with open(bat, 'w', encoding='cp866') as handle:
        handle.write(script)
    try:
        subprocess.Popen(['cmd', '/c', bat],
                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                         close_fds=True)
    except OSError:
        return False
    return True
