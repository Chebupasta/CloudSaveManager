#!/usr/bin/env python3
"""
Cloud Save Manager — универсальный менеджер облачных сохранений для игр
без встроенной поддержки облака (Dark Souls III и другие).

Запуск: python main.py
Запуск сразу свёрнутым в трей (используется автозапуском): python main.py --minimized
"""
import sys
import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtNetwork import QLocalServer, QLocalSocket
from PyQt5.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from app.ui.one_window import install as install_single_window
from app.ui.icons import make_app_icon
from app.ui import fonts
from app.ui.theme import STYLE_SHEET

# Уникальный ключ канала между копиями программы. Второй запуск не создаёт
# новое окно, а просит уже работающий экземпляр показать своё окно.
_SINGLE_INSTANCE_KEY = 'CloudSaveManager_single_instance_v1'


class _SingleInstance:
    """Одна копия приложения: повторный запуск активирует существующее окно."""

    def __init__(self, key: str):
        self.key = key
        self.server = None
        self.on_activate = None

    def try_acquire(self) -> bool:
        """ True — мы первый экземпляр; False — уже есть другой, нужно выйти."""
        probe = QLocalSocket()
        probe.connectToServer(self.key)
        if probe.waitForConnected(200):
            # waitForBytesWritten без работающего цикла событий часто возвращает
            # False и данные остаются в буфере — крутим события сами.
            probe.write(b'SHOW')
            probe.flush()
            deadline = time.monotonic() + 0.5
            while probe.bytesToWrite() and time.monotonic() < deadline:
                QApplication.processEvents()
            probe.disconnectFromServer()
            return False
        # После аварийного выхода сервер мог остаться «висеть» — чистим его.
        QLocalServer.removeServer(self.key)
        self.server = QLocalServer()
        if not self.server.listen(self.key):
            # Не удалось занять канал (например, ограничения ОС) — лучше
            # работать без защиты, чем не запуститься вообще.
            self.server = None
            return True
        self.server.newConnection.connect(self._on_connection)
        return True

    def _on_connection(self):
        while self.server.hasPendingConnections():
            conn = self.server.nextPendingConnection()
            if conn is None:
                return
            conn.readyRead.connect(lambda c=conn: self._read(c))
            # Второй процесс пишет и сразу отключается: readyRead не гарантирован
            # (данные могут прийти до подключения обработчика). Дополнительное
            # чтение на следующем проходе цикла событий надёжнее; повторное чтение
            # пустого буфера ничего не делает.
            QTimer.singleShot(100, lambda c=conn: self._read(c))
            QTimer.singleShot(2000, conn.deleteLater)

    def _read(self, conn):
        try:
            data = bytes(conn.readAll())
        except RuntimeError:  # сокет уже удалён — повторного сообщения не будет
            return
        if b'SHOW' in data and self.on_activate:
            self.on_activate()
        try:
            conn.disconnectFromServer()
        except RuntimeError:
            pass


def main():
    start_hidden = '--minimized' in sys.argv[1:]

    # Корректный масштаб 125/150 % в Windows: без этих атрибутов Qt5
    # просто растягивает картинку системой, и элементы «слипаются».
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    # Файловые диалоги тоже должны быть частью нашего окна, а не системными.
    QApplication.setAttribute(Qt.AA_DontUseNativeDialogs, True)
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except AttributeError:
        pass  # старый Qt5 — масштабирование всё равно включено атрибутами
    # QApplication должен существовать ДО проверки второй копии: иначе
    # QLocalSocket не может отправить сообщение в работающий процесс.
    app = QApplication(sys.argv)
    install_single_window()  # все диалоги встроены в главное окно

    single = _SingleInstance(_SINGLE_INSTANCE_KEY)
    if not single.try_acquire():
        return 0

    app.setApplicationName('Cloud Save Manager')
    # Fusion — единственный встроенный стиль Qt, который полностью
    # подчиняется QSS на всех платформах; на нём строится дизайн
    # (Material 3, тёмная лесная тема) из app/ui/tokens.py и theme.py.
    app.setStyle('Fusion')
    fonts.setup(app)  # шрифты до применения стилей
    app.setStyleSheet(STYLE_SHEET)
    app.setWindowIcon(make_app_icon())
    # Окно может быть скрыто (свёрнуто в трей), поэтому не выходим из
    # программы автоматически при закрытии последнего окна — выход
    # происходит только через пункт "Выход" в трее или при явном закрытии,
    # когда сворачивание в трей отключено в настройках.
    app.setQuitOnLastWindowClosed(False)

    window = MainWindow(start_hidden=start_hidden)
    single.on_activate = window._restore_from_tray
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
