"""
Единое окно выгрузки/загрузки с индикатором в процентах. Заменяет цепочку
отдельных всплывающих сообщений: этап операции (архивирование, отправка,
скачивание, распаковка) и итог показываются в одном окне.
"""
from PyQt5.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton

from app.sync_manager import Cancelled
from app.ui import motion
from app.ui.svg_icons import svg_icon
from app.ui.theme import DANGER, SUCCESS


class _TransferWorker(QThread):
    progress = pyqtSignal(int, str)
    done = pyqtSignal(bool, str)

    def __init__(self, job, parent=None):
        super().__init__(parent)
        self._job = job
        self.cancel_requested = False

    def _progress(self, pct, text):
        # Отмена возможна, пока не начато применение результата к локальным файлам (≥90%)
        if self.cancel_requested and pct < 90:
            raise Cancelled()
        self.progress.emit(int(pct), text)

    def run(self):
        try:
            ok, message = self._job(self._progress)
        except Cancelled:
            ok, message = False, 'Отменено пользователем.'
        except Exception as e:  # любая непредвиденная ошибка показывается в окне
            ok, message = False, f'Непредвиденная ошибка: {e}'
        if self.cancel_requested and not ok:
            message = 'Отменено пользователем.'  # сетевая ошибка при отмене — это не сбой
        self.done.emit(bool(ok), message)


class TransferDialog(QDialog):
    """job(progress) -> (ok, message); progress(percent, text)."""

    def __init__(self, parent, title: str, job, auto_close_ms: int = 1200):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.ok = False
        self.message = ''
        self._auto_close_ms = auto_close_ms
        self._finished = False

        layout = QVBoxLayout(self)
        self.stage_label = QLabel('Подготовка...')
        self.stage_label.setWordWrap(True)
        layout.addWidget(self.stage_label)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setFormat('%p%')
        layout.addWidget(self.bar)
        self.result_label = QLabel('')
        self.result_label.setWordWrap(True)
        self.result_label.hide()
        layout.addWidget(self.result_label)
        self.close_btn = QPushButton('Закрыть')
        self.close_btn.setIcon(svg_icon('check'))
        self.close_btn.clicked.connect(self.accept)
        self.close_btn.hide()
        layout.addWidget(self.close_btn)
        self.cancel_btn = QPushButton('Отмена')
        self.cancel_btn.setToolTip('Остановить операцию. Локальные файлы не будут изменены, '
                                   'если отмена успела до применения.')
        self.cancel_btn.clicked.connect(self._request_cancel)
        layout.addWidget(self.cancel_btn)

        self.worker = _TransferWorker(job, self)
        self.worker.progress.connect(self._on_progress)
        self.worker.done.connect(self._on_done)
        self.worker.start()

    def showEvent(self, event):
        super().showEvent(event)
        motion.fade_window(self, motion.DUR_FAST)

    def _request_cancel(self):
        self.worker.cancel_requested = True
        self.cancel_btn.setEnabled(False)
        self.stage_label.setText('Отмена...')

    def _on_progress(self, percent: int, text: str):
        if percent >= 90:
            self.cancel_btn.setEnabled(False)  # идёт применение — уже не отменить
        if not self.worker.cancel_requested:
            motion.animate_bar(self.bar, percent)
        if text:
            self.stage_label.setText(text)

    def _on_done(self, ok: bool, message: str):
        self._finished = True
        self.cancel_btn.hide()
        self.ok, self.message = ok, message
        if ok:
            motion.animate_bar(self.bar, 100)
        color = SUCCESS if ok else DANGER
        self.stage_label.setText('Готово' if ok else 'Ошибка')
        self.result_label.setText(f'<span style="color:{color};">{message}</span>')
        self.result_label.show()
        motion.fade_in(self.result_label)
        if ok and self._auto_close_ms:
            # Диалог могли закрыть вручную за это время — не дёргаем accept()
            # повторно у уже скрытого окна.
            QTimer.singleShot(self._auto_close_ms,
                              lambda: self.isVisible() and self.accept())
        else:
            self.close_btn.show()

    def reject(self):
        if self._finished:
            super().reject()  # пока операция идёт, окно закрыть нельзя — нельзя прервать запись

    def closeEvent(self, event):
        if self._finished:
            event.accept()
        else:
            event.ignore()

    def done(self, result):
        if self._finished:
            super().done(result)


def run_transfer(parent, title: str, job, auto_close_ms: int = 1200):
    """Показывает окно и ждёт завершения. Возвращает (ok, message)."""
    dlg = TransferDialog(parent, title, job, auto_close_ms)
    dlg.exec_()
    return dlg.ok, dlg.message
