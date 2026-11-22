"""Диалог «Найти установленные игры»: сканирует Steam/Epic/GOG в фоне и добавляет выбранные игры."""
from PyQt5.QtCore import Qt, QThread, pyqtSignal
import os

from PyQt5.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget,
                             QListWidgetItem, QPushButton, QVBoxLayout)

from app import library_scan, manifest
from app.ui import tokens as T


class _ScanWorker(QThread):
    progress = pyqtSignal(str)
    done = pyqtSignal(list)

    def run(self):
        try:
            self.done.emit(library_scan.scan_all(self.progress.emit))
        except Exception as e:  # диск/реестр могут преподнести сюрприз — окно не должно виснуть
            self.progress.emit(f'Ошибка поиска: {e}')
            self.done.emit([])


class _GameDetailsDialog(QDialog):
    """Уточнение найденной игры: какой .exe отслеживать и где лежит сохранение (если не нашлось)."""

    def __init__(self, parent, found):
        super().__init__(parent)
        self.found = found
        self.setWindowTitle(found.name)
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('Программа игры (по её запуску и закрытию выгружается сохранение):'))
        self.exe_combo = QComboBox()
        self.exe_combo.setEditable(True)
        paths = list(dict.fromkeys(([found.exe_path] if found.exe_path else []) + list(found.exe_candidates)))
        for path in paths:
            self.exe_combo.addItem(os.path.basename(path), path)
            self.exe_combo.setItemData(self.exe_combo.count() - 1, path, Qt.ToolTipRole)
        lay.addWidget(self.exe_combo)
        other_exe = QPushButton('Другой .exe...')
        other_exe.clicked.connect(self._pick_exe)
        lay.addWidget(other_exe)
        lay.addWidget(QLabel('Сохранения:'))
        self.saves_label = QLabel()
        self.saves_label.setWordWrap(True)
        self.saves_label.setProperty('muted', True)
        lay.addWidget(self.saves_label)
        row = QHBoxLayout()
        pick_file = QPushButton('Указать файл сохранения...')
        pick_file.clicked.connect(self._pick_save_file)
        pick_dir = QPushButton('Указать папку сохранения...')
        pick_dir.clicked.connect(self._pick_save_dir)
        row.addWidget(pick_file)
        row.addWidget(pick_dir)
        lay.addLayout(row)
        ok = QPushButton('Готово')
        ok.setProperty('cls', 'primary')
        ok.setFixedHeight(T.BTN_H)
        ok.clicked.connect(self._accept)
        lay.addWidget(ok)
        self._refresh_saves()

    def _refresh_saves(self):
        if self.found.saves:
            self.saves_label.setText('\n'.join(c['path'] for c in self.found.saves))
        else:
            self.saves_label.setText('Путь сохранения не найден — укажите вручную.')

    def _pick_exe(self):
        start = self.found.install_dir or ''
        path, _ = QFileDialog.getOpenFileName(self, 'Программа игры', start, 'Программы (*.exe);;Все файлы (*)')
        if path:
            self.exe_combo.addItem(os.path.basename(path), path)
            self.exe_combo.setCurrentIndex(self.exe_combo.count() - 1)

    def _add_save(self, path: str, is_dir: bool):
        if path and not any(c['path'] == path for c in self.found.saves):
            self.found.saves.append({'path': path, 'is_dir': is_dir})
            self._refresh_saves()

    def _pick_save_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Файл сохранения')
        self._add_save(path, False)

    def _pick_save_dir(self):
        self._add_save(QFileDialog.getExistingDirectory(self, 'Папка сохранения'), True)

    def _accept(self):
        idx = self.exe_combo.currentIndex()
        data = self.exe_combo.itemData(idx) if idx >= 0 else None
        if data and self.exe_combo.currentText() == self.exe_combo.itemText(idx):
            self.found.exe_path = data
        elif self.exe_combo.currentText().strip():
            self.found.exe_path = self.exe_combo.currentText().strip()
        self.accept()


class ScanDialog(QDialog):
    def __init__(self, parent, store):
        super().__init__(parent)
        self.store = store
        self.created = []
        self.setWindowTitle('Найти установленные игры')
        self.setMinimumSize(620, 520)
        lay = QVBoxLayout(self)
        self.status = QLabel('Поиск игр в Steam, Epic Games и GOG...')
        self.status.setProperty('muted', True)
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.list = QListWidget()
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.ElideRight)
        self.list.itemDoubleClicked.connect(self._edit_item)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel('Облачный аккаунт:'))
        self.account_combo = QComboBox()
        self.account_combo.addItem('Без облака (добавить позже)', '')
        for acc in store.accounts:
            self.account_combo.addItem(acc.name, acc.id)
        if store.accounts:
            self.account_combo.setCurrentIndex(1)
        row.addWidget(self.account_combo, 1)
        lay.addLayout(row)
        btns = QHBoxLayout()
        self.add_btn = QPushButton('Добавить выбранные')
        self.add_btn.setProperty('cls', 'primary')
        self.add_btn.setFixedHeight(T.BTN_H)
        self.add_btn.setEnabled(False)
        self.add_btn.clicked.connect(self._add)
        close = QPushButton('Закрыть')
        close.setFixedHeight(T.BTN_H)
        close.clicked.connect(self.reject)
        btns.addWidget(self.add_btn, 1)
        btns.addWidget(close)
        lay.addLayout(btns)
        self._found = []
        self.worker = _ScanWorker(self)
        self.worker.progress.connect(self.status.setText)
        self.worker.done.connect(self._on_done)
        self.worker.start()

    @staticmethod
    def _norm(name: str) -> str:
        return ''.join(c for c in name.lower() if c.isalnum())

    @staticmethod
    def _item_text(g) -> str:
        n = len(g.saves)
        return f'{g.name}   ·   {g.store}' + (f'   ·   сохранений: {n}' if n else '   ·   путь сохранения не найден')

    def _edit_item(self, item):
        found = item.data(Qt.UserRole)
        if found is None:
            return
        if _GameDetailsDialog(self, found).exec_() == QDialog.Accepted:
            item.setText(self._item_text(found))
            if found.saves:
                item.setCheckState(Qt.Checked)

    def _on_done(self, found: list):
        existing = {self._norm(g.name) for g in self.store.games}
        self._found = [g for g in found if self._norm(g.name) not in existing]
        index_ready = bool(manifest.load_index())
        for g in self._found:
            n = len(g.saves)
            item = QListWidgetItem(self._item_text(g))
            item.setToolTip(self._item_text(g) + '\n' + '\n'.join(
                s.path for s in g.saves if s.path))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if n else Qt.Unchecked)
            item.setData(Qt.UserRole, g)
            self.list.addItem(item)
        if not found:
            self.status.setText('Установленные игры не найдены (поддерживаются Steam, Epic Games, GOG).')
        elif not self._found:
            self.status.setText('Все найденные игры уже добавлены.')
        else:
            hint = '' if index_ready else '  База путей ещё не скачана — Настройки → «Обновить базу путей».'
            self.status.setText(f'Найдено новых игр: {len(self._found)}. Отмечены те, для которых нашлись сохранения. Двойной щелчок — выбрать .exe или указать сохранение вручную.{hint}')
        self.add_btn.setEnabled(bool(self._found))

    def _add(self):
        account_id = self.account_combo.currentData() or ''
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.checkState() == Qt.Checked:
                game = library_scan.to_profile(item.data(Qt.UserRole), account_id)
                self.store.add_game(game)
                self.created.append(game)
        self.accept()

    def done(self, result):
        if self.worker.isRunning():
            self.worker.wait(5000)
        super().done(result)
