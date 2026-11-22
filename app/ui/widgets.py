"""Переиспользуемые виджеты интерфейса: пилюли-теги, обрезка длинных путей,
обложка игры и «текучий» (flow) layout для тегов."""
from PyQt5.QtCore import Qt, QRect, QSize, QPoint
from PyQt5.QtGui import QGuiApplication, QPainter, QColor, QPainterPath
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLayout, QSizePolicy)

from app import game_icons
from app.ui import fonts, tokens as T
from app.ui.svg_icons import svg_pixmap

_TAG_COLORS = {'neutral': T.TEXT_ON_CARD_MUTED, 'ok': T.OK, 'info': T.SAGE, 'warn': T.WARN, 'error': T.ERR}


def screen_fit(width: int, height: int, margin_x: int = 40, margin_y: int = 60) -> tuple:
    """Ограничить размер окна доступной областью экрана.

    При масштабе 125–150 % логический экран заметно меньше физического, и
    жёсткие минимальные размеры диалогов вылезают за его границы — кнопки
    Ok/Отмена становятся недоступны."""
    screen = QGuiApplication.primaryScreen()
    if screen is not None:
        geo = screen.availableGeometry()
        width = min(width, max(320, geo.width() - margin_x))
        height = min(height, max(240, geo.height() - margin_y))
    return width, height


class ElidedLabel(QLabel):
    """Однострочная подпись: длинный текст обрезается многоточием, полный
    текст доступен во всплывающей подсказке. Не растягивает компоновку."""

    def __init__(self, text: str = '', mode=Qt.ElideMiddle, mono: bool = False, parent=None):
        super().__init__(parent)
        self._full = ''
        self._mode = mode
        if mono:
            self.setFont(fonts.mono_font(T.FS_SMALL))
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setText(text)

    def setText(self, text: str):
        self._full = text
        self.setToolTip(text)
        super().setText('')
        self.update()

    def fullText(self) -> str:
        return self._full

    def minimumSizeHint(self):
        return QSize(24, self.fontMetrics().height() + 4)

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self._full) + 4, self.fontMetrics().height() + 4)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setFont(self.font())
        p.setPen(self.palette().color(self.foregroundRole()))
        text = self.fontMetrics().elidedText(self._full, self._mode, self.width())
        p.drawText(self.rect(), Qt.AlignVCenter | Qt.AlignLeft, text)


class Tag(QFrame):
    """Минималистичный индикатор состояния: цветная точка + текст (статус
    передаётся и текстом, не только цветом). Параметр icon оставлен для
    совместимости и не используется."""

    def __init__(self, text: str, kind: str = 'neutral', icon: str = None, tooltip: str = '',
                 max_text_width: int = 0, parent=None):
        super().__init__(parent)
        self.setProperty('tag', kind)
        self.text_value = text  # чтобы заметить смену состояния и плавно показать новое
        color = _TAG_COLORS.get(kind, T.TEXT_MUTED)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        dot = QLabel()
        dot.setFixedSize(7, 7)
        dot.setStyleSheet(f'background: {color}; border-radius: 3px;')
        self._dot = dot
        lay.addWidget(dot, 0, Qt.AlignVCenter)
        # ElidedLabel: длинный статус обрезается многоточием, а не растягивает
        # карточку и не наезжает на соседние виджеты.
        self._label = ElidedLabel(text, Qt.ElideRight)
        self._label.setStyleSheet(f'color: {color}; background: transparent;')
        lay.addWidget(self._label)
        self.setToolTip(tooltip or text)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        if max_text_width:
            self.set_max_width(max_text_width)

    def set_max_width(self, width: int):
        """Ограничить ширину индикатора, чтобы он не вытеснял соседей."""
        self.setMaximumWidth(width)
        self._label.setMaximumWidth(max(24, width - 14))

    def set_status(self, text: str, kind: str, tooltip: str = ''):
        """Изменить состояние на месте, не пересоздавая виджет."""
        self.text_value = text
        color = _TAG_COLORS.get(kind, T.TEXT_MUTED)
        self._label.setText(text)
        self._label.setStyleSheet(f'color: {color}; background: transparent;')
        self._dot.setStyleSheet(f'background: {color}; border-radius: 3px;')
        self.setToolTip(tooltip or text)


class GameCover(QLabel):
    """Обложка/иконка игры в заголовке: размер адаптивный (44–56 px по высоте),
    пропорции сохраняются, без растягивания и обрезки; без обложки — нейтральная
    заглушка."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path = ''
        self._size = T.COVER_MAX
        self.setAlignment(Qt.AlignCenter)

    def set_cover(self, path: str, size: int):
        self._path = path
        self._size = size
        self._render()

    def set_size(self, size: int):
        if size != self._size:
            self._size = size
            self._render()

    def _render(self):
        s = self._size
        pm = game_icons.load_fit_pixmap(self._path, s, int(s * 2.1), T.R_COVER if s >= 52 else 12)
        if pm is not None:
            self.setPixmap(pm)
            self.setFixedSize(int(pm.width() / pm.devicePixelRatio()), int(pm.height() / pm.devicePixelRatio()))
            return
        # нейтральная заглушка: скруглённый квадрат + векторный геймпад
        from PyQt5.QtGui import QPixmap
        dpr = 2
        ph = QPixmap(s * dpr, s * dpr)
        ph.fill(Qt.transparent)
        p = QPainter(ph)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, s * dpr, s * dpr, 12 * dpr, 12 * dpr)
        p.fillPath(path, QColor(T.CARD))
        iw = int(s * dpr * 0.5)
        icon = svg_pixmap('gamepad', iw // dpr, T.C_TEXT_SECONDARY)
        off = (s * dpr - iw) // 2
        p.drawPixmap(QRect(off, off, iw, iw), icon)
        p.end()
        ph.setDevicePixelRatio(dpr)
        self.setPixmap(ph)
        self.setFixedSize(s, s)


class FlowLayout(QLayout):
    """Раскладывает виджеты в строки с переносом — теги не вылезают за окно."""

    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _layout(self, rect, test_only):
        x, y, line_h = rect.x(), rect.y(), 0
        for item in self._items:
            w = item.sizeHint().width()
            h = item.sizeHint().height()
            if x + w > rect.right() + 1 and line_h > 0:
                x = rect.x()
                y += line_h + self._spacing
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x += w + self._spacing
            line_h = max(line_h, h)
        return y + line_h - rect.y()
