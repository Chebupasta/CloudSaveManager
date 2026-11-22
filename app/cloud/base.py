"""
Базовый интерфейс облачного провайдера. Любой провайдер (GitHub, GitLab,
WebDAV, локальная папка и т.д.) реализует эти три метода.

Все методы возвращают кортеж (ok: bool, message: str), что удобно
показывать пользователю без дополнительной обработки исключений на
стороне вызывающего кода. download() дополнительно возвращает,
существует ли вообще запрошенный файл (not_found), чтобы UI мог
отличить реальную ошибку от "в облаке ещё нет сохранения".
"""
from abc import ABC, abstractmethod
from typing import Callable, Optional, Tuple

# progress(done_bytes, total_bytes) — необязательный обратный вызов для отображения процентов
ProgressCb = Optional[Callable[[int, int], None]]


class ProgressReader:
    """Обёртка над bytes для requests: читает по кусочкам и сообщает прогресс
    отправки. Знает свою длину, поэтому requests шлёт обычный Content-Length."""

    def __init__(self, data: bytes, progress: ProgressCb = None, chunk: int = 65536):
        self._data = data
        self._pos = 0
        self._progress = progress
        self._chunk = chunk

    def __len__(self):
        return len(self._data)

    def read(self, size=-1):
        if self._pos >= len(self._data):
            return b''
        size = self._chunk if size is None or size < 0 else min(size, self._chunk)
        part = self._data[self._pos:self._pos + size]
        self._pos += len(part)
        if self._progress:
            self._progress(self._pos, len(self._data))
        return part


def stream_to_file(response, local_path: str, progress: ProgressCb = None) -> bool:
    """Скачивает тело ответа requests (stream=True) в файл, сообщая прогресс.
    Возвращает False, если файл получился пустым."""
    total = int(response.headers.get('Content-Length') or 0)
    done = 0
    with open(local_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            f.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total or done)
    return done > 0


class CloudProvider(ABC):
    def __init__(self, config: dict, secret: str = ''):
        self.config = config or {}
        self.secret = secret or ''

    @abstractmethod
    def test_connection(self) -> Tuple[bool, str]:
        """Проверяет, что учётные данные верны и доступ к хранилищу есть."""
        raise NotImplementedError

    @abstractmethod
    def upload_file(self, local_path: str, remote_key: str, message: str = '',
                    progress: ProgressCb = None) -> Tuple[bool, str]:
        """Загружает локальный файл local_path в облако под ключом remote_key."""
        raise NotImplementedError

    @abstractmethod
    def download_file(self, remote_key: str, local_path: str,
                      progress: ProgressCb = None) -> Tuple[bool, str]:
        """Скачивает файл remote_key из облака и сохраняет в local_path.
        Если файла в облаке нет, возвращает (False, 'not_found')."""
        raise NotImplementedError

    NOT_FOUND = 'not_found'
