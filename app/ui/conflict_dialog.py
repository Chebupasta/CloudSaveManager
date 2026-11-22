"""Сравнение локальной и облачной версий сохранения при конфликте или когда
в облаке версия новее: пользователь видит обе версии и сам выбирает, какую оставить."""
import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QGridLayout, QLabel, QPushButton, QScrollArea,
                             QVBoxLayout, QWidget)

from app import sync_manager
from app.ui import fonts, motion, tokens as T
from app.ui.svg_icons import svg_icon
from app.ui.widgets import screen_fit


def _fmt_size(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return '—'
    for unit in ('Б', 'КБ', 'МБ', 'ГБ'):
        if n < 1024 or unit == 'ГБ':
            return f'{n:.0f} {unit}' if unit == 'Б' else f'{n:.1f} {unit}'
        n /= 1024
    return '—'


def _fmt_dt(value) -> str:
    try:
        if isinstance(value, (int, float)):
            return datetime.datetime.fromtimestamp(value).strftime('%d.%m.%Y, %H:%M')
        return datetime.datetime.fromisoformat(str(value)).strftime('%d.%m.%Y, %H:%M')
    except (TypeError, ValueError, OSError):
        return '—'


class ConflictDialog(QDialog):
    """result_choice: 'upload' (оставить локальную), 'download' (взять облачную) или None."""

    def __init__(self, parent, game, slot, status: dict):
        super().__init__(parent)
        self.setWindowTitle('Выберите версию сохранения')
        self.setMinimumWidth(screen_fit(500, 0)[0])
        self.result_choice = None
        conflict = status.get('status') == 'conflict'

        # На низком экране таблица версий сжималась до 1–2 px в строке —
        # содержимое должно прокручиваться, а не сплющиваться.
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setSpacing(T.S3)
        title = QLabel(f'{game.name} — {slot.label}')
        title.setFont(fonts.heading_font(title.text(), 16))
        title.setWordWrap(True)
        lay.addWidget(title)
        intro = QLabel(
            'Сохранение менялось и здесь, и в облаке — одну из версий придётся заменить.'
            if conflict else
            'В облаке лежит более новая версия, чем на этом компьютере.')
        intro.setWordWrap(True)
        intro.setProperty('muted', True)
        lay.addWidget(intro)

        local = sync_manager.local_info(slot)
        meta = status.get('cloud_meta') or {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(T.S5)
        grid.setVerticalSpacing(T.S2)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        for col, head in ((1, 'Этот компьютер'), (2, 'Облако')):
            h = QLabel(head)
            h.setObjectName('sectionLabel')
            h.setWordWrap(True)
            grid.addWidget(h, 0, col)
        rows = [
            ('Изменено', _fmt_dt(local.get('mtime')) if local else 'файла нет',
             _fmt_dt(meta.get('uploaded_at')) if meta else 'нет данных'),
            ('Размер', _fmt_size(local.get('size')) if local else '—',
             _fmt_size(meta.get('size')) if meta else '—'),
            ('Устройство', 'этот компьютер', str(meta.get('device') or 'неизвестно')),
        ]
        for i, (name, a, b) in enumerate(rows, start=1):
            cap = QLabel(name)
            cap.setProperty('muted', True)
            grid.addWidget(cap, i, 0)
            for col, value in ((1, a), (2, b)):
                cell = QLabel(value)
                cell.setWordWrap(True)
                cell.setToolTip(value)  # полное имя устройства/путь — по наведению
                grid.addWidget(cell, i, col)
        lay.addLayout(grid)

        note = QLabel('Заменяемая версия не пропадёт: перед заменой её копия сохраняется в резервных '
                      'копиях слота (кнопка с часами в карточке).')
        note.setWordWrap(True)
        note.setProperty('muted', True)
        lay.addWidget(note)

        keep_local = QPushButton('Оставить локальную')
        keep_local.setIcon(svg_icon('upload', 18, T.TEXT))
        keep_local.setToolTip('Оставить локальную версию (выгрузить её в облако)')
        take_cloud = QPushButton('Взять из облака')
        take_cloud.setProperty('cls', 'primary')
        take_cloud.setIcon(svg_icon('download', 18, T.TEXT_ON_SAGE))
        take_cloud.setToolTip('Взять версию из облака (загрузить её, локальная сохранится в бэкапе)')
        cancel = QPushButton('Отмена')
        for b in (keep_local, take_cloud, cancel):
            b.setFixedHeight(T.BTN_H)
        keep_local.clicked.connect(lambda: self._choose('upload'))
        take_cloud.clicked.connect(lambda: self._choose('download'))
        cancel.clicked.connect(self.reject)
        lay.addSpacing(T.S2)
        lay.addWidget(take_cloud)
        lay.addWidget(keep_local)
        lay.addWidget(cancel)
        cancel.setDefault(True)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.addWidget(scroll)

    def showEvent(self, event):
        super().showEvent(event)
        motion.fade_window(self, motion.DUR_FAST)

    def _choose(self, choice: str):
        self.result_choice = choice
        self.accept()

    @staticmethod
    def ask(parent, game, slot, status: dict):
        dlg = ConflictDialog(parent, game, slot, status)
        dlg.exec_()
        return dlg.result_choice
