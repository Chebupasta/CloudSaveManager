"""
Иконка приложения рисуется программно (QPainter), чтобы не тянуть внешние
файлы изображений: градиентный значок с облаком и стрелкой сохранения —
собственный узнаваемый стиль вместо стандартной системной иконки.
"""
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QPixmap, QPainter, QColor, QLinearGradient, QIcon, QPainterPath

ACCENT_START = '#111111'  # стрелка
ACCENT_END = '#000000'


def _draw_badge(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)

    # Фон: скруглённый квадрат с диагональным градиентом
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0, QColor('#1F3F3A'))
    grad.setColorAt(1, QColor('#0B181F'))
    bg_path = QPainterPath()
    radius = size * 0.24
    bg_path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    p.fillPath(bg_path, grad)

    # Облако (белое, слегка прозрачное)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 235))
    cx, cy = size * 0.5, size * 0.52
    p.drawEllipse(QPointF(cx - size * 0.17, cy + size * 0.01), size * 0.15, size * 0.12)
    p.drawEllipse(QPointF(cx + size * 0.03, cy - size * 0.06), size * 0.19, size * 0.15)
    p.drawEllipse(QPointF(cx + size * 0.21, cy + size * 0.02), size * 0.13, size * 0.10)
    p.drawRoundedRect(QRectF(cx - size * 0.32, cy, size * 0.62, size * 0.145),
                       size * 0.06, size * 0.06)

    # Стрелка "сохранения в облако" поверх, цвета фона
    p.setBrush(QColor('#0B181F'))
    arrow = QPainterPath()
    ax, ay = cx - size * 0.01, size * 0.24
    hw = size * 0.075   # половина ширины наконечника
    sw = size * 0.028   # половина ширины стержня
    arrow.moveTo(ax, ay)
    arrow.lineTo(ax + hw, ay + hw * 1.15)
    arrow.lineTo(ax + sw, ay + hw * 1.15)
    arrow.lineTo(ax + sw, ay + size * 0.16)
    arrow.lineTo(ax - sw, ay + size * 0.16)
    arrow.lineTo(ax - sw, ay + hw * 1.15)
    arrow.lineTo(ax - hw, ay + hw * 1.15)
    arrow.closeSubpath()
    p.drawPath(arrow)

    p.end()
    return pm


def make_app_icon() -> QIcon:
    """Иконка приложения/трея в нескольких разрешениях (для чёткости на HiDPI)."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_draw_badge(size))
    return icon
