"""
Диалог просмотра локальных резервных копий слота сохранения и их
восстановления. Резервные копии создаются автоматически перед каждой
перезаписью (загрузкой из облака или восстановлением другой копии), так
что отменить неудачный выбор всегда можно.
"""
import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QInputDialog, QPushButton, QDialogButtonBox, QMessageBox,
)

from app import backup as backup_module
from app.models import GameProfile, SaveSlot
from app.store import ConfigStore
from app.ui import tokens as T
from app.ui.svg_icons import svg_icon
from app.ui.widgets import screen_fit


def _format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ('Б', 'КБ', 'МБ', 'ГБ'):
        if size < 1024 or unit == 'ГБ':
            return f'{size:.0f} {unit}' if unit == 'Б' else f'{size:.1f} {unit}'
        size /= 1024
    return f'{size:.1f} ГБ'


def _format_delta(delta) -> str:
    """Подпись «изменение размера относительно предыдущей копии»."""
    if delta is None:
        return ''
    if delta == 0:
        return 'размер как в предыдущей'
    sign = '+' if delta > 0 else '−'
    return f'{sign}{_format_size(abs(delta))} к предыдущей'


class BackupsDialog(QDialog):
    def __init__(self, parent, store: ConfigStore, game: GameProfile, slot: SaveSlot):
        super().__init__(parent)
        self.store = store
        self.game = game
        self.slot = slot
        self.setWindowTitle(f'Резервные копии — {game.name} / {slot.label}')
        self.setMinimumSize(*screen_fit(520, 380))

        layout = QVBoxLayout(self)
        hint = QLabel('Эти копии хранятся локально на вашем компьютере и создаются '
                       'автоматически перед каждой перезаписью файла сохранения '
                       '(загрузкой из облака или восстановлением). Берегите место на '
                       'диске — хранится не более 5 последних копий на слот.')
        hint.setWordWrap(True)
        hint.setProperty('muted', True)
        layout.addWidget(hint)

        self.list_widget = QListWidget()
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_widget.setTextElideMode(Qt.ElideRight)
        self.list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)   # Ctrl/Shift — несколько копий
        layout.addWidget(self.list_widget)
        self._refresh()

        btn_row = QHBoxLayout()
        self.restore_btn = QPushButton('Восстановить')
        self.restore_btn.setProperty('cls', 'primary')
        self.restore_btn.setIcon(svg_icon('history', 18, T.TEXT_ON_SAGE))
        self.restore_btn.setToolTip('Восстановить выбранную копию (перед этим текущее состояние '
                                    'тоже сохранится в бэкап)')
        self.restore_btn.clicked.connect(self._restore_selected)
        self.open_folder_btn = QPushButton('Папка копий')
        self.open_folder_btn.setIcon(svg_icon('folder'))
        self.open_folder_btn.setToolTip('Открыть папку с резервными копиями этого слота')
        self.open_folder_btn.clicked.connect(self._open_folder)
        self.snapshot_btn = QPushButton('Снимок...')
        self.snapshot_btn.setIcon(svg_icon('plus', 18, T.TEXT))
        self.snapshot_btn.setToolTip('Именной снимок текущего сохранения, например «перед боссом». '
                                     'Хранится, пока вы сами его не удалите.')
        self.snapshot_btn.clicked.connect(self._make_snapshot)
        self.delete_btn = QPushButton('Удалить')
        self.delete_btn.setIcon(svg_icon('trash', 18, T.TEXT))
        self.delete_btn.setToolTip('Удалить выбранные копии')
        self.delete_btn.clicked.connect(self._delete_selected)
        self.prev_cloud_btn = QPushButton('Предыдущая облачная версия')
        self.prev_cloud_btn.setIcon(svg_icon('cloud'))
        self.prev_cloud_btn.setToolTip('В облаке хранится одна предыдущая версия сохранения (до последней '
                                       'выгрузки). Она восстановится на этом компьютере.')
        self.prev_cloud_btn.clicked.connect(self._restore_prev_cloud)
        btn_row.addWidget(self.restore_btn)
        btn_row.addWidget(self.open_folder_btn)
        layout.addLayout(btn_row)
        extra = QHBoxLayout()
        extra.addWidget(self.snapshot_btn)
        extra.addWidget(self.delete_btn)
        layout.addLayout(extra)
        layout.addWidget(self.prev_cloud_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        buttons.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        layout.addWidget(buttons)

    def _make_snapshot(self):
        label, ok = QInputDialog.getText(self, 'Снимок сохранения', 'Подпись (например, «перед боссом»):')
        if not ok:
            return
        path = backup_module.make_snapshot(self.game.id, self.slot.id, self.slot.path,
                                           self.slot.is_directory, label or 'снимок')
        if not path:
            QMessageBox.warning(self, 'Нет сохранения', 'Локальное сохранение не найдено — снимок не создан.')
        self._refresh()

    def _selected_backups(self):
        return [it.data(Qt.UserRole) for it in self.list_widget.selectedItems() if it.data(Qt.UserRole)]

    def _delete_selected(self):
        chosen = self._selected_backups()
        if not chosen:
            return
        if len(chosen) == 1:
            question = 'Удалить выбранную копию безвозвратно?'
        else:
            question = f'Удалить выбранные копии ({len(chosen)} шт.) безвозвратно?'
        if any(b['kind'] == 'named' for b in chosen):
            question += '\n\nСреди них есть именные снимки.'
        reply = QMessageBox.question(self, 'Удалить копии', question,
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            backup_module.delete_backups([b['path'] for b in chosen])
            self._refresh()

    def _restore_prev_cloud(self):
        from app import sync_manager
        from app.ui.transfer_dialog import run_transfer
        reply = QMessageBox.question(
            self, 'Откат к предыдущей облачной версии',
            'Предыдущая версия из облака заменит локальное сохранение (его копия сохранится '
            'в резервных копиях). В облаке ничего не изменится, пока вы сами не выгрузите.\n\nПродолжить?',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        ok, message = run_transfer(
            self, 'Предыдущая облачная версия',
            lambda progress: sync_manager.download_slot(self.store, self.game, self.slot,
                                                         progress=progress, previous=True))
        if not ok:
            QMessageBox.warning(self, 'Не удалось', message)
        self._refresh()

    def _refresh(self):
        self.list_widget.clear()
        backups = backup_module.list_backups(self.game.id, self.slot.id)
        if not backups:
            placeholder = QListWidgetItem('Резервных копий для этого слота пока нет.')
            placeholder.setFlags(placeholder.flags() & ~Qt.ItemIsSelectable)
            self.list_widget.addItem(placeholder)
            return
        for b in backups:
            when = datetime.datetime.fromtimestamp(b['mtime']).strftime('%d.%m.%Y %H:%M:%S')
            size = _format_size(b['size'])
            kind = 'архив папки' if b['is_zip'] else 'файл'
            tag = {'named': f'Снимок: {b["label"]}', 'auto': 'Автоснимок'}.get(b['kind'], 'Копия перед заменой')
            delta = _format_delta(b.get('delta_size'))
            text = f'{when}   ·   {tag}   ·   {size}' + (f' ({delta})' if delta else '') + f'   ·   {kind}'
            item = QListWidgetItem(text)
            item.setToolTip(text)
            item.setData(Qt.UserRole, b)
            self.list_widget.addItem(item)

    def _restore_selected(self):
        chosen = self._selected_backups()
        if len(chosen) != 1:
            QMessageBox.information(self, 'Не выбрано', 'Выберите одну резервную копию в списке.')
            return
        data = chosen[0]
        reply = QMessageBox.question(
            self, 'Восстановить копию?',
            'Текущий файл/папка сохранения будут заменены выбранной резервной '
            'копией (текущее состояние перед этим тоже будет сохранено в '
            'резервную копию, так что это можно отменить). Продолжить?',
            QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        ok, message = backup_module.restore_backup(
            data['path'], self.slot.path, self.slot.is_directory, self.game.id, self.slot.id)
        (QMessageBox.information if ok else QMessageBox.warning)(self, 'Восстановление', message)
        if ok:
            self._refresh()

    def _open_folder(self):
        from app import os_utils
        folder = backup_module.backup_path_for(self.game.id, self.slot.id)
        if not os_utils.open_in_file_manager(folder):
            QMessageBox.warning(self, 'Не удалось открыть',
                                 f'Папка с копиями: {folder}')
