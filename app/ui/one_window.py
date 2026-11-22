"""Одно окно приложения.

Все диалоги (настройки, аккаунты, игра, прогресс, подтверждения) показываются
внутри главного окна встроенными панелями, а не отдельными системными окнами.

Обычный код ``dlg.exec_()`` продолжает работать как раньше — результат тот же.
Исключение — QMessageBox: его статические методы заменяются собственной
лёгкой панелью, потому что нативный QMessageBox некорректно ведёт себя,
будучи дочерним виджетом.
"""
from PyQt5.QtCore import QSize, Qt
from PyQt5.QtWidgets import (QApplication, QDialog, QFileDialog, QHBoxLayout, QInputDialog,
                             QLabel, QMainWindow, QMessageBox, QPushButton, QVBoxLayout, QWidget)

_installed = False
_original_exec = None


def _main_window():
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, QMainWindow) and widget.isVisible():
            return widget
    return None


def _host_for(widget):
    if widget is not None:
        parent = widget.parentWidget()
        while parent is not None:
            if isinstance(parent, QMainWindow):
                return parent
            parent = parent.parentWidget()
        if isinstance(widget, QMainWindow):
            return widget
    return _main_window()


def _embed_widget(dialog, host):
    """Сделать диалог дочерней панелью главного окна и закрыть фон подложкой."""
    dialog.setWindowFlags(Qt.Widget)
    dialog.setProperty('embedded', True)
    dialog.setParent(host)
    # Свойство появилось после показа — заставляем Qt пересчитать QSS.
    dialog.style().unpolish(dialog)
    dialog.style().polish(dialog)
    available = host.size() - QSize(32, 32)
    size = dialog.size().boundedTo(available)
    size = size.expandedTo(dialog.minimumSizeHint().boundedTo(available))
    dialog.resize(size)
    dialog.move(max(0, (host.width() - dialog.width()) // 2),
                max(0, (host.height() - dialog.height()) // 2))
    shade = QWidget(host)
    shade.setGeometry(host.rect())
    shade.setStyleSheet('background: rgba(8, 16, 24, 90);')
    shade.show()
    shade.raise_()
    dialog.raise_()
    return shade


def _embedded_exec_impl(original_exec):
    """Фабрика перехватчиков: у QFileDialog и QInputDialog свой exec(), отличный
    от QDialog.exec_(), поэтому их нужно перехватывать отдельно."""

    def patched(self):
        shade = None
        if self.windowFlags() & Qt.Dialog and not isinstance(self, QMessageBox):
            host = _host_for(self)
            if host is not None:
                try:
                    shade = _embed_widget(self, host)
                except Exception:
                    shade = None
        try:
            return original_exec(self)
        finally:
            if shade is not None:
                shade.deleteLater()

    return patched


class _EmbeddedMessage(QDialog):
    """Простая панель с текстом и кнопками вместо системного message box."""

    _BUTTONS = (
        (QMessageBox.Ok, 'OK'),
        (QMessageBox.Yes, 'Да'),
        (QMessageBox.No, 'Нет'),
        (QMessageBox.Cancel, 'Отмена'),
        (QMessageBox.Close, 'Закрыть'),
    )

    def __init__(self, parent, title: str, text: str, buttons: int, default: int):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.Widget)
        self.result_code = QMessageBox.Cancel
        self.setMinimumWidth(360)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(16)
        label = QLabel(text)
        label.setWordWrap(True)
        lay.addWidget(label)
        row = QHBoxLayout()
        row.addStretch()
        for flag, caption in self._BUTTONS:
            if not buttons & flag:
                continue
            btn = QPushButton(caption)
            btn.setFixedHeight(34)
            if flag == default:
                btn.setProperty('cls', 'primary')
            btn.clicked.connect(lambda _checked=False, code=flag: self.done(code))
            row.addWidget(btn)
        lay.addLayout(row)

    def done(self, result):
        self.result_code = result
        super().done(result)


def _ask(parent, title: str, text: str, buttons: int, default: int = QMessageBox.NoButton):
    host = _host_for(parent)
    if host is None:
        return default or QMessageBox.Ok
    box = _EmbeddedMessage(host, title, text, buttons, default)
    shade = _embed_widget(box, host)
    try:
        box.exec_()  # уже Qt.Widget — перехват ничего не меняет
    finally:
        shade.deleteLater()
    return box.result_code


def _information(parent, title, text, *args, **kwargs):
    return _ask(parent, title, text, QMessageBox.Ok, QMessageBox.Ok)


def _warning(parent, title, text, buttons=QMessageBox.Ok, default=QMessageBox.NoButton, **kwargs):
    return _ask(parent, title, text, buttons, default)


def _critical(parent, title, text, buttons=QMessageBox.Ok, default=QMessageBox.NoButton, **kwargs):
    return _ask(parent, title, text, buttons, default)


def _question(parent, title, text, buttons=QMessageBox.Yes | QMessageBox.No,
              default=QMessageBox.NoButton, **kwargs):
    return _ask(parent, title, text, buttons, default)


def _file_dialog(parent, caption, directory='', filter_text='', mode=QFileDialog.ExistingFile):
    """Собственный статический файловый диалог: его exec_ вызывается из Python
    и попадает под встраивание (C++-реализация вызывает exec напрямую)."""
    dialog = QFileDialog(parent, caption, directory or '', filter_text or '')
    dialog.setFileMode(mode)
    dialog.setAcceptMode(QFileDialog.AcceptOpen)
    if mode == QFileDialog.Directory:
        dialog.setOption(QFileDialog.ShowDirsOnly, True)
    if dialog.exec_() != QDialog.Accepted:
        return ('', '') if mode != QFileDialog.Directory else ''
    selected = dialog.selectedFiles()
    path = selected[0] if selected else ''
    if mode == QFileDialog.Directory:
        return path
    return path, dialog.selectedNameFilter()


def _get_open_file_name(parent, caption='', directory='', filter_text='', *args, **kwargs):
    return _file_dialog(parent, caption, directory, filter_text, QFileDialog.ExistingFile)


def _get_save_file_name(parent, caption='', directory='', filter_text='', *args, **kwargs):
    dialog = QFileDialog(parent, caption, directory or '', filter_text or '')
    dialog.setFileMode(QFileDialog.AnyFile)
    dialog.setAcceptMode(QFileDialog.AcceptSave)
    if dialog.exec_() != QDialog.Accepted:
        return '', ''
    selected = dialog.selectedFiles()
    return (selected[0] if selected else ''), dialog.selectedNameFilter()


def _get_existing_directory(parent, caption='', directory='', *args, **kwargs):
    return _file_dialog(parent, caption, directory, '', QFileDialog.Directory)


def install():
    """Включить режим «одно окно». Вызывается один раз при старте приложения."""
    global _installed
    if _installed:
        return
    originals = {}
    for name in ('exec', 'exec_'):
        func = getattr(QDialog, name, None)
        if func is not None:
            originals[name] = func
            setattr(QDialog, name, _embedded_exec_impl(func))
    # QFileDialog и QInputDialog переопределяют exec/exec_ — перехватываем
    # и их собственные реализации, иначе они остаются отдельными окнами.
    for cls in (QFileDialog, QInputDialog):
        for name, base in originals.items():
            own = cls.__dict__.get(name)
            if own is not None and own is not base:
                setattr(cls, name, _embedded_exec_impl(own))
    QMessageBox.information = staticmethod(_information)
    QMessageBox.warning = staticmethod(_warning)
    QMessageBox.critical = staticmethod(_critical)
    QMessageBox.question = staticmethod(_question)
    QFileDialog.getOpenFileName = staticmethod(_get_open_file_name)
    QFileDialog.getSaveFileName = staticmethod(_get_save_file_name)
    QFileDialog.getExistingDirectory = staticmethod(_get_existing_directory)
    # Нативные файловые диалоги — отдельные системные окна; используем Qt-диалог.
    QApplication.setAttribute(Qt.AA_DontUseNativeDialogs, True)
    _installed = True
