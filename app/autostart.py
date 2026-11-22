"""
Включение/выключение автозапуска программы вместе с системой.

Windows: запись в реестр HKEY_CURRENT_USER\\...\\Run.
Linux: .desktop файл в ~/.config/autostart (стандарт XDG).
macOS: автоматический автозапуск не реализован — пользователю нужно
       добавить программу в "Объекты входа" вручную.
"""
import os
import sys
from typing import Tuple

APP_KEY = 'CloudSaveManager'


def is_supported() -> bool:
    return sys.platform.startswith('win') or sys.platform.startswith('linux')


def _launch_command(minimized: bool = True) -> str:
    """Команда для запуска приложения: если собрано в exe (PyInstaller) —
    путь к exe, иначе — python + путь к main.py."""
    arg = ' --minimized' if minimized else ''
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}"{arg}'
    main_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'main.py')
    python = sys.executable
    # На Windows используем pythonw, если он есть рядом, чтобы не открывалась консоль
    if sys.platform.startswith('win'):
        pythonw = os.path.join(os.path.dirname(python), 'pythonw.exe')
        if os.path.isfile(pythonw):
            python = pythonw
    return f'"{python}" "{main_py}"{arg}'


# ---------- Windows ----------
def _windows_run_key():
    import winreg  # доступен только на Windows
    return winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run'


def _is_enabled_windows() -> bool:
    import winreg
    hive, path = _windows_run_key()
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, APP_KEY)
            return True
    except OSError:
        return False


def _set_enabled_windows(enabled: bool, minimized: bool):
    import winreg
    hive, path = _windows_run_key()
    with winreg.OpenKey(hive, path, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_KEY, 0, winreg.REG_SZ, _launch_command(minimized))
        else:
            try:
                winreg.DeleteValue(key, APP_KEY)
            except FileNotFoundError:
                pass


# ---------- Linux ----------
def _linux_autostart_path() -> str:
    xdg_config = os.getenv('XDG_CONFIG_HOME') or os.path.join(os.path.expanduser('~'), '.config')
    return os.path.join(xdg_config, 'autostart', 'cloudsavemanager.desktop')


def _is_enabled_linux() -> bool:
    return os.path.isfile(_linux_autostart_path())


def _icon_path() -> str:
    """Путь к готовой иконке приложения (assets/icon.png), если она есть
    рядом со сборкой — используется только для красоты в .desktop файле."""
    if getattr(sys, 'frozen', False):
        base = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidate = os.path.join(base, 'assets', 'icon.png')
    return candidate if os.path.isfile(candidate) else ''


def _set_enabled_linux(enabled: bool, minimized: bool):
    path = _linux_autostart_path()
    if enabled:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        icon = _icon_path()
        content = (
            '[Desktop Entry]\n'
            'Type=Application\n'
            f'Name={APP_KEY}\n'
            f'Exec={_launch_command(minimized)}\n'
            + (f'Icon={icon}\n' if icon else '')
            + 'X-GNOME-Autostart-enabled=true\n'
        )
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
    else:
        if os.path.isfile(path):
            os.remove(path)


# ---------- общий интерфейс ----------
def is_enabled() -> bool:
    try:
        if sys.platform.startswith('win'):
            return _is_enabled_windows()
        if sys.platform.startswith('linux'):
            return _is_enabled_linux()
    except OSError:
        pass
    return False


def set_enabled(enabled: bool, minimized: bool = True) -> Tuple[bool, str]:
    """Включает/выключает автозапуск. Возвращает (ok: bool, message: str)."""
    try:
        if sys.platform.startswith('win'):
            _set_enabled_windows(enabled, minimized)
            return True, 'Автозапуск обновлён.'
        if sys.platform.startswith('linux'):
            _set_enabled_linux(enabled, minimized)
            return True, 'Автозапуск обновлён.'
        return False, 'Автоматический автозапуск на этой ОС не поддерживается. ' \
                       'Добавьте программу в автозагрузку вручную через настройки системы.'
    except OSError as e:
        return False, f'Не удалось изменить автозапуск: {e}'
