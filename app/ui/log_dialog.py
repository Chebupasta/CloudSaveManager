"""Просмотр журнала действий приложения (последние записи) — чтобы понимать,
почему выгрузка не сработала, без поиска файла на диске."""
import os

from PyQt5.QtWidgets import (QApplication, QDialog, QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout)

from app import os_utils
from app.constants import get_log_path
from app.ui import fonts, tokens as T
from app.ui.svg_icons import svg_icon
from app.ui.widgets import screen_fit

MAX_LINES = 400


class LogDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Журнал')
        self.setMinimumSize(*screen_fit(640, 420))
        self.resize(*screen_fit(760, 480))
        lay = QVBoxLayout(self)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        # Длинные пути, URL и traceback должны переноситься, а не требовать
        # горизонтальной прокрутки на узком окне.
        self.view.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.view.setFont(fonts.mono_font(12))
        lay.addWidget(self.view, 1)
        # Два ряда кнопок: на узком окне (масштаб 125 %) четыре кнопки в одной
        # строке не помещались и их подписи обрезались.
        refresh = QPushButton('Обновить')
        refresh.setIcon(svg_icon('refresh', 18, T.TEXT))
        refresh.clicked.connect(self._load)
        copy = QPushButton('Копировать')
        copy.setIcon(svg_icon('copy', 18, T.TEXT))
        copy.setToolTip('Копировать весь журнал в буфер обмена')
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.view.toPlainText()))
        folder = QPushButton('Папка')
        folder.setIcon(svg_icon('folder', 18, T.TEXT))
        folder.setToolTip('Открыть папку с файлом журнала')
        folder.clicked.connect(lambda: os_utils.open_in_file_manager(get_log_path()))
        close = QPushButton('Закрыть')
        close.clicked.connect(self.accept)
        row1 = QHBoxLayout()
        row1.addWidget(refresh)
        row1.addWidget(copy)
        row1.addStretch()
        row2 = QHBoxLayout()
        row2.addWidget(folder)
        row2.addStretch()
        row2.addWidget(close)
        lay.addLayout(row1)
        lay.addLayout(row2)
        self._load()

    def _load(self):
        path = get_log_path()
        text = 'Журнал пока пуст.'
        if os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    text = ''.join(f.readlines()[-MAX_LINES:]) or text
            except OSError as e:
                text = f'Не удалось прочитать журнал: {e}'
        self.view.setPlainText(text)
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())
