"""Небольшие кроссплатформенные вспомогательные функции для работы с ОС."""
import os
import subprocess
import sys


def open_in_file_manager(path: str) -> bool:
    """Открывает файл или папку в проводнике/файловом менеджере системы."""
    if not path or not os.path.exists(path):
        return False
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    try:
        if sys.platform.startswith('win'):
            os.startfile(folder)  # noqa: E501 - доступно только на Windows
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', folder])
        else:
            subprocess.Popen(['xdg-open', folder])
        return True
    except OSError:
        return False


def launch_target(target: str):
    """Запускает игру: .exe/.bat/.lnk или ссылку (steam://rungameid/…). Возвращает (ok, сообщение)."""
    import subprocess
    import sys
    try:
        if '://' in target:
            if sys.platform.startswith('win'):
                os.startfile(target)  # noqa: S606  (ссылка протокола Steam/Epic и т.п.)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', target])
            else:
                subprocess.Popen(['xdg-open', target])
            return True, 'Запуск через ссылку.'
        if not os.path.isfile(target):
            return False, f'Файл запуска не найден: {target}'
        if sys.platform.startswith('win') and target.lower().endswith('.lnk'):
            os.startfile(target)
        else:
            # рабочая папка = папка программы: многие игры ищут ресурсы рядом
            subprocess.Popen([target], cwd=os.path.dirname(target) or None, close_fds=True)
        return True, 'Игра запущена.'
    except OSError as e:
        return False, f'Не удалось запустить: {e}'
