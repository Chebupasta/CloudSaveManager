"""
Экономия ресурсов: пониженный приоритет процесса (программа никогда не мешает игре),
«режим эффективности» Windows (EcoQoS) и сброс рабочего набора, когда окно скрыто в трее.
Все вызовы безопасны: при ошибке или на другой ОС ничего не происходит.
"""
import gc
import sys

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

IS_WIN = sys.platform.startswith('win')


def lower_priority() -> None:
    """Пониженный приоритет: фоновая утилита не должна конкурировать с игрой за процессор."""
    if psutil is None:
        return
    try:
        proc = psutil.Process()
        if IS_WIN:
            proc.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        else:
            proc.nice(5)
    except (psutil.Error, OSError, AttributeError, ValueError):
        pass


def set_efficiency_mode(enabled: bool) -> None:
    """Windows 11/10: «режим эффективности» (EcoQoS) — система переводит процесс на
    энергоэффективные ядра и снижает частоты."""
    if not IS_WIN:
        return
    try:
        import ctypes
        from ctypes import wintypes

        class PowerThrottling(ctypes.Structure):
            _fields_ = [('Version', wintypes.ULONG), ('ControlMask', wintypes.ULONG),
                        ('StateMask', wintypes.ULONG)]

        state = PowerThrottling(1, 1, 1 if enabled else 0)  # PROCESS_POWER_THROTTLING_EXECUTION_SPEED
        kernel32 = ctypes.windll.kernel32
        kernel32.SetProcessInformation(kernel32.GetCurrentProcess(), 4,  # ProcessPowerThrottling
                                       ctypes.byref(state), ctypes.sizeof(state))
    except (AttributeError, OSError, ImportError):
        pass


def trim_memory() -> None:
    """Возвращает системе неиспользуемую память (когда окно скрыто)."""
    gc.collect()
    if not IS_WIN:
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.K32EmptyWorkingSet(kernel32.GetCurrentProcess())
    except (AttributeError, OSError):
        pass


def enter_background() -> None:
    set_efficiency_mode(True)
    trim_memory()


def leave_background() -> None:
    set_efficiency_mode(False)
