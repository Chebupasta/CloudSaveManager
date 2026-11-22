"""
«Жидкое стекло»: живой цветной фон и стеклянные карточки с бликом на ребре.

* BackdropWidget — фон главного окна: плавно дрейфующие цветные «капли» света.
  Анимация идёт только пока окно видно (в трее таймер остановлен); в неактивном
  окне кадры реже; при выключенных анимациях в настройках фон статичен.
  В плоских темах виджет просто заливает окно цветом темы.
* GlassFrame — карточка: заливку и скругление рисует QSS, поверх добавляются
  яркая кромка с градиентом (свет сверху-слева) и мягкий верхний блик.

Положения капель считает чистая функция blob_positions — её можно проверить без Qt.
"""
import math
import re
import time
from typing import List, Tuple

from PyQt5.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PyQt5.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PyQt5.QtWidgets import QFrame, QWidget

from app.ui import motion, tokens as T

# Пятна света движутся очень медленно: 20 кадров/с выглядят так же плавно,
# а стоимость отрисовки фона падает на треть. В неактивном окне — 4 кадра/с.
FPS_ACTIVE = 20
FPS_IDLE = 4
# Фон состоит только из мягких градиентов — половинное разрешение визуально
# неотличимо, но требует в 4 раза меньше закрашиваемых пикселей.
RENDER_SCALE = 0.5
# (период по x, период по y в секундах, фаза, относительный радиус) — у каждой капли свой ритм
_BLOBS = (
    (47.0, 61.0, 0.0, 0.62),
    (59.0, 43.0, 1.7, 0.55),
    (71.0, 53.0, 3.1, 0.58),
    (41.0, 67.0, 4.6, 0.50),
)


def blob_positions(t: float, width: int, height: int) -> List[Tuple[float, float, float]]:
    """Центры и радиусы капель света в момент t (секунды). Центры всегда в пределах окна."""
    width, height = max(1, int(width)), max(1, int(height))
    big = max(width, height)
    result = []
    for px, py, phase, rel in _BLOBS:
        x = 0.5 + 0.42 * math.sin(2 * math.pi * t / px + phase)
        y = 0.5 + 0.42 * math.cos(2 * math.pi * t / py + phase * 1.3)
        result.append((x * width, y * height, rel * big))
    return result


_RGBA = re.compile(r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)')


def parse_color(value: str) -> Tuple[int, int, int, int]:
    """«#RRGGBB» или CSS-подобное «rgba(r,g,b,a)» (a от 0 до 1) -> (r, g, b, a 0..255).
    QColor сам rgba(...) не понимает, а токены стекла хранятся в формате QSS."""
    m = _RGBA.fullmatch(value.strip())
    if m:
        a = float(m.group(4)) if m.group(4) is not None else 1.0
        return int(m.group(1)), int(m.group(2)), int(m.group(3)), max(0, min(255, round(a * 255)))
    c = QColor(value)
    return c.red(), c.green(), c.blue(), c.alpha()


def _color(value: str, alpha: int = None) -> QColor:
    """QColor из токена; alpha (0..255), если задан, заменяет прозрачность токена."""
    r, g, b, a = parse_color(value)
    return QColor(r, g, b, a if alpha is None else alpha)


class BackdropWidget(QWidget):
    """Фон окна. Кладите его центральным виджетом: всё остальное рисуется поверх."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._t0 = time.monotonic()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._surface = QPixmap()      # переиспользуем буфер, не выделяем каждый кадр
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    # --- анимация ---
    def _animated(self) -> bool:
        return T.IS_GLASS and motion.enabled()

    def showEvent(self, event):
        super().showEvent(event)
        if self._animated():
            self._timer.start(int(1000 / FPS_ACTIVE))

    def hideEvent(self, event):
        super().hideEvent(event)
        self._timer.stop()  # окно в трее / свёрнуто — ни одного кадра зря

    def _tick(self):
        win = self.window()
        if win is None or not win.isVisible() or win.isMinimized():
            self._timer.stop()
            return
        if not self._animated():
            self._timer.stop()
            self.update()
            return
        interval = int(1000 / (FPS_ACTIVE if win.isActiveWindow() else FPS_IDLE))
        if self._timer.interval() != interval:
            self._timer.setInterval(interval)
        self.update()

    # --- рисование ---
    def paintEvent(self, _event):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        p = QPainter(self)
        if not T.IS_GLASS:
            p.fillRect(self.rect(), QColor(T.BG))
            p.end()
            return

        # Градиенты рисуются в буфере половинного размера и одним махом
        # растягиваются на окно. Буфер живёт между кадрами и пересоздаётся
        # только при смене размера: в 4 раза меньше пикселей и аллокаций.
        sw, sh = max(1, int(w * RENDER_SCALE)), max(1, int(h * RENDER_SCALE))
        if self._surface.size() != QSize(sw, sh):
            self._surface = QPixmap(sw, sh)
        sp = QPainter(self._surface)
        # База непрозрачна (hex без альфы) и полностью перекрывает старый кадр;
        # пятна затем нормально смешиваются поверх неё режимом SourceOver.
        base0, base1, *blobs = T.BACKDROP
        grad = QLinearGradient(0, 0, sw, sh)
        grad.setColorAt(0.0, _color(base0))
        grad.setColorAt(1.0, _color(base1))
        sp.fillRect(self._surface.rect(), grad)
        t = (time.monotonic() - self._t0) if motion.enabled() else 0.0
        for (cx, cy, r), col in zip(blob_positions(t, w, h), blobs):
            # Пятна света остаются фоном, а не подсветкой текста: пониженная
            # прозрачность и плотные поверхности дают читаемый текст.
            cx, cy, r = cx * RENDER_SCALE, cy * RENDER_SCALE, r * RENDER_SCALE
            rg = QRadialGradient(QPointF(cx, cy), r)
            rg.setColorAt(0.0, _color(col, 110))
            rg.setColorAt(0.55, _color(col, 45))
            rg.setColorAt(1.0, _color(col, 0))
            sp.setPen(Qt.NoPen)
            sp.setBrush(rg)
            sp.drawEllipse(QPointF(cx, cy), r, r)
        sp.end()
        p.drawPixmap(self.rect(), self._surface)
        p.end()


class GlassFrame(QFrame):
    """Стеклянная карточка: QSS даёт полупрозрачную заливку, здесь — кромка света и блик."""

    def __init__(self, parent=None, radius: int = None):
        super().__init__(parent)
        self._radius = T.R_CARD if radius is None else radius

    def paintEvent(self, event):
        super().paintEvent(event)  # заливка и скругление из QSS
        if not T.IS_GLASS:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h, r = self.width(), self.height(), self._radius
        rect = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        # мягкий блик в верхней трети — как свет, скользящий по выпуклому стеклу
        clip = QPainterPath()
        clip.addRoundedRect(rect, r, r)
        p.setClipPath(clip)
        sheen = QLinearGradient(0, 0, 0, h * 0.42)
        # Блик очень слабый: он не должен высветлять заголовок и индикатор
        # слота, которые находятся именно в верхней части карточки.
        sheen.setColorAt(0.0, _color(T.RIM_LIGHT, 16))
        sheen.setColorAt(1.0, _color(T.RIM_LIGHT, 0))
        p.fillRect(QRectF(0, 0, w, h * 0.42), sheen)
        p.setClipping(False)
        # кромка: ярко сверху-слева, тускло по бокам, снова чуть ярче снизу-справа (преломление)
        rim = QLinearGradient(0, 0, w, h)
        rim.setColorAt(0.0, _color(T.RIM_LIGHT))
        rim.setColorAt(0.35, _color(T.RIM_DIM))
        rim.setColorAt(0.65, _color(T.RIM_DIM))
        rim.setColorAt(1.0, _color(T.RIM_LIGHT, 120))
        p.setPen(QPen(rim, 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, r, r)
        p.end()
