"""Безопасная распаковка zip — защита от выхода за пределы папки (zip-slip).

Одна реализация используется и при загрузке сохранения из облака, и при
восстановлении локальной резервной копии: битый/подменённый архив не должен
писать файлы за пределами папки слота.
"""
import os
import zipfile
from typing import Callable, Optional


def safe_extract(zip_path: str, dest_dir: str, progress: Optional[Callable] = None,
                 lo: int = 0, hi: int = 100) -> None:
    dest_real = os.path.realpath(dest_dir)
    with zipfile.ZipFile(zip_path, 'r') as zf:
        infos = zf.infolist()
        total = sum(i.file_size for i in infos) or 1
        done = 0
        for info in infos:
            target = os.path.realpath(os.path.join(dest_dir, info.filename))
            if target != dest_real and not target.startswith(dest_real + os.sep):
                raise zipfile.BadZipFile(f'Небезопасный путь в архиве: {info.filename}')
            zf.extract(info, dest_dir)
            done += info.file_size
            if progress:
                progress(lo + (hi - lo) * done / total, 'Распаковка сохранения...')
    if progress:
        progress(hi, 'Распаковка сохранения...')
