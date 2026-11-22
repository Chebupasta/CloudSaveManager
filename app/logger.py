"""Простое файловое логирование действий приложения."""
import datetime
import os

from app.constants import get_log_path, MAX_LOG_SIZE


def log_action(action: str, status: str, details: str = ''):
    path = get_log_path()
    try:
        if os.path.isfile(path) and os.path.getsize(path) > MAX_LOG_SIZE:
            # Обрезаем лог, оставляя последнюю треть, чтобы файл не рос бесконечно
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            with open(path, 'w', encoding='utf-8') as f:
                f.writelines(lines[len(lines) // 3 * 2:])
        with open(path, 'a', encoding='utf-8') as f:
            f.write(f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {action} | {status} | {details}\n")
    except OSError:
        # Логирование не должно ронять приложение
        pass
