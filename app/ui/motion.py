"""
Лёгкая анимация интерфейса. Принципы: короткие (120–220 мс), одноразовые, без
постоянных таймеров и перерисовки в простое; эффект прозрачности снимается сразу
после анимации; ничего не анимируется, если окно скрыто (трей) или анимации
выключены в настройках.
"""
from PyQt5.QtCore import QEasingCurve, QPropertyAnimation, QTimer
from PyQt5.QtGui import QGuiApplication
from PyQt5.QtWidgets import QGraphicsOpacityEffect

DUR = 180
DUR_FAST = 120

_enabled = True


def set_enabled(value: bool) -> None:
    global _enabled
    _enabled = bool(value)


def enabled() -> bool:
    return _enabled


def _can_animate(widget) -> bool:
    return _enabled and widget is not None and widget.window() is not None and widget.window().isVisible()


def fade_in(widget, duration: int = DUR, delay: int = 0) -> None:
    """Плавное появление виджета; эффект удаляется по окончании (нулевая цена после)."""
    if not _can_animate(widget):
        return
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b'opacity', widget)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.OutCubic)

    def done():
        try:
            widget.setGraphicsEffect(None)
        except RuntimeError:  # виджет уже удалён
            pass

    anim.finished.connect(done)
    if delay > 0:
        timer = QTimer(widget)  # дочерний таймер умрёт вместе с виджетом
        timer.setSingleShot(True)
        timer.timeout.connect(anim.start)
        timer.start(delay)
    else:
        anim.start()


def fade_window(window, duration: int = DUR) -> None:
    """Появление окна/диалога через windowOpacity."""
    if not _enabled or QGuiApplication.platformName() in ('offscreen', 'wayland', 'minimal'):
        return  # платформа не умеет менять прозрачность окна
    window.setWindowOpacity(0.0)
    anim = QPropertyAnimation(window, b'windowOpacity', window)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    anim.finished.connect(lambda: window.setWindowOpacity(1.0))
    anim.start()


def animate_bar(bar, value: int, duration: int = DUR_FAST) -> None:
    """Плавное движение индикатора прогресса к новому значению."""
    if not _can_animate(bar):
        bar.setValue(value)
        return
    anim = getattr(bar, '_motion_anim', None)
    if anim is not None:
        anim.stop()
    anim = QPropertyAnimation(bar, b'value', bar)
    anim.setDuration(duration)
    anim.setStartValue(bar.value())
    anim.setEndValue(int(value))
    anim.setEasingCurve(QEasingCurve.OutQuad)
    bar._motion_anim = anim
    anim.start()
