"""
Диалог добавления/редактирования игры: имя, процесс(ы) для отслеживания,
облачный аккаунт и список слотов сохранения (файл или папка на диске
плюс имя, под которым сохранение хранится в облаке).
"""
import os

from PyQt5.QtCore import Qt, QThread, pyqtSignal

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QSpinBox, QCheckBox, QListWidget, QListWidgetItem,
    QMessageBox, QFileDialog, QDialogButtonBox, QInputDialog, QGroupBox, QScrollArea, QWidget,
)

from app import auto_detect, game_icons, learned_paths, presets
from app.models import GameProfile, SaveSlot
from app.store import ConfigStore
from app.sync_manager import preview_remote_path
from app.ui.auto_detect_dialogs import ProcessPickerDialog, SaveCandidatesDialog
from app.ui.widgets import screen_fit
from app.ui.svg_icons import svg_icon, svg_pixmap


class IconFetchWorker(QThread):
    """Ищет картинку игры в Steam в фоне, чтобы не подвешивать окно."""
    found = pyqtSignal(str)

    def __init__(self, game_id, name, exe_path, process_names, parent=None):
        super().__init__(parent)
        self._args = (game_id, name, exe_path, process_names)

    def run(self):
        try:
            self.found.emit(game_icons.find_icon_online(*self._args))
        except Exception:
            self.found.emit('')


class SlotEditDialog(QDialog):
    """Небольшой диалог добавления/редактирования одного слота сохранения."""

    def __init__(self, parent=None, slot: SaveSlot = None, other_slots=None):
        super().__init__(parent)
        self.setWindowTitle('Слот сохранения')
        self.setMinimumWidth(420)
        self.slot = slot or SaveSlot()
        self.other_slots = list(other_slots or [])

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.label_input = QLineEdit(self.slot.label)
        form.addRow('Название слота:', self.label_input)

        self.path_input = QLineEdit(self.slot.path)
        browse_file_btn = QPushButton('Файл...')
        browse_file_btn.clicked.connect(self._browse_file)
        browse_dir_btn = QPushButton('Папка...')
        browse_dir_btn.clicked.connect(self._browse_dir)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_input)
        path_row.addWidget(browse_file_btn)
        path_row.addWidget(browse_dir_btn)
        form.addRow('Путь на диске:', path_row)

        self.remote_name_input = QLineEdit(self.slot.remote_name)
        form.addRow('Имя в облаке:', self.remote_name_input)
        self.exclude_input = QLineEdit(self.slot.exclude_patterns)
        self.exclude_input.setPlaceholderText('например: *.log, cache, screenshots/*  (для папок)')
        self.exclude_input.setToolTip('Маски файлов и папок, которые НЕ выгружаются в облако и не '
                                      'затираются при загрузке. Через запятую.')
        form.addRow('Не выгружать:', self.exclude_input)

        layout.addLayout(form)

        hint = QLabel('Если сохранение — это целая папка (несколько файлов),\n'
                       'выберите её кнопкой "Папка..." — при выгрузке она будет\n'
                       'автоматически упакована в .zip, а имя в облаке должно\n'
                       'заканчиваться на .zip.')
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._is_directory = self.slot.is_directory

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Выберите файл сохранения')
        if path:
            self.path_input.setText(path)
            self._is_directory = False
            if not self.remote_name_input.text().strip():
                self.remote_name_input.setText(os.path.basename(path))

    def _browse_dir(self):
        path = QFileDialog.getExistingDirectory(self, 'Выберите папку сохранения')
        if path:
            self.path_input.setText(path)
            self._is_directory = True
            if not self.remote_name_input.text().strip():
                self.remote_name_input.setText('save.zip')

    def _on_accept(self):
        if not self.label_input.text().strip():
            QMessageBox.warning(self, 'Ошибка', 'Укажите название слота.')
            return
        if not self.remote_name_input.text().strip():
            QMessageBox.warning(self, 'Ошибка', 'Укажите имя файла в облаке.')
            return
        if any(s.label == self.label_input.text().strip() for s in self.other_slots):
            QMessageBox.warning(self, 'Ошибка', 'Слот с таким названием уже есть.')
            return
        remote = self.remote_name_input.text().strip().replace('\\', '/').split('/')[-1]
        if any(s.remote_name == remote for s in self.other_slots):
            QMessageBox.warning(
                self, 'Ошибка',
                'Другой слот уже использует это имя в облаке — сохранения перезаписывали бы '
                'друг друга. Укажите уникальное имя файла.')
            return
        self.slot.label = self.label_input.text().strip()
        self.slot.path = self.path_input.text().strip()
        self.slot.remote_name = self.remote_name_input.text().strip()
        self.slot.exclude_patterns = self.exclude_input.text().strip()
        # Путь могли ввести руками — тип определяем по реальному объекту на диске
        if os.path.isdir(self.slot.path):
            self._is_directory = True
        elif os.path.isfile(self.slot.path):
            self._is_directory = False
        if self._is_directory and not self.slot.remote_name.lower().endswith('.zip'):
            self.slot.remote_name = ('save.zip' if self.slot.remote_name == 'save.dat'
                                     else self.slot.remote_name + '.zip')  # папка хранится в облаке как архив
        self.slot.is_directory = self._is_directory
        self.accept()


class GameDialog(QDialog):
    def __init__(self, parent=None, store: ConfigStore = None, game: GameProfile = None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle('Игра')
        self.setMinimumWidth(screen_fit(680, 0)[0])
        self.game = GameProfile()
        if game:
            # Работаем с копией полей, чтобы отмена не портила исходный объект
            self.game.__dict__.update(game.__dict__)
            self.game.slots = [SaveSlot.from_dict(s.to_dict()) for s in game.slots]
        self.editing_existing = game is not None
        self.detected_exe_path = self.game.hint_exe_path or ''
        # Имя процесса и время его запуска (если игру только что выбрали из
        # списка запущенных) — используются, чтобы искать сохранение точнее
        # и чтобы запомнить найденный путь именно за этим процессом.
        self.detected_process_name = self.game.process_names[0] if self.game.process_names else ''
        self.detected_process_start_time = None

        # Форма длинная: без прокрутки нижние кнопки Ok/Отмена оказывались за
        # краем экрана на ноутбуке и при масштабе 125–150 %.
        content = QWidget()
        layout = QVBoxLayout(content)

        auto_box = QGroupBox('Автоматическая настройка (рекомендуется)')
        auto_layout = QVBoxLayout()
        auto_hint = QLabel('Не нужно ничего вводить вручную: запустите игру, выберите её '
                            'из списка и нажмите поиск сохранения — программа сама найдёт, '
                            'где лежит файл.')
        auto_hint.setWordWrap(True)
        auto_layout.addWidget(auto_hint)
        auto_btn_row = QVBoxLayout()
        pick_process_btn = QPushButton('1. Игра запущена — выбрать из списка')
        pick_process_btn.clicked.connect(self._pick_running_process)
        find_save_btn = QPushButton('2. Найти сохранение автоматически')
        find_save_btn.clicked.connect(self._run_save_finder)
        auto_btn_row.addWidget(pick_process_btn)
        auto_btn_row.addWidget(find_save_btn)
        auto_layout.addLayout(auto_btn_row)
        auto_box.setLayout(auto_layout)
        layout.addWidget(auto_box)

        icon_box = QGroupBox('Иконка игры')
        icon_layout = QHBoxLayout()
        self.icon_preview = QLabel()
        self.icon_preview.setFixedSize(64, 64)
        icon_layout.addWidget(self.icon_preview)
        icon_btns = QVBoxLayout()
        self.steam_icon_btn = QPushButton('Найти в Steam')
        self.steam_icon_btn.setIcon(svg_icon('search'))
        self.steam_icon_btn.setToolTip('Подставить обложку игры из Steam (по пресету, '
                                       'манифесту Steam или названию игры)')
        self.steam_icon_btn.clicked.connect(self._fetch_steam_icon)
        file_icon_btn = QPushButton('Выбрать с компьютера...')
        file_icon_btn.setIcon(svg_icon('image'))
        file_icon_btn.clicked.connect(self._pick_icon_file)
        exe_icon_btn = QPushButton('Взять из .exe')
        exe_icon_btn.setIcon(svg_icon('gamepad'))
        exe_icon_btn.clicked.connect(self._icon_from_exe)
        row = QHBoxLayout()
        row.addWidget(self.steam_icon_btn)
        row.addWidget(file_icon_btn)
        row.addWidget(exe_icon_btn)
        icon_btns.addLayout(row)
        self.icon_status = QLabel('')
        self.icon_status.setProperty('muted', True)
        icon_btns.addWidget(self.icon_status)
        icon_layout.addLayout(icon_btns, 1)
        icon_box.setLayout(icon_layout)
        layout.addWidget(icon_box)
        self._icon_worker = None
        self._refresh_icon_preview()

        layout.addWidget(QLabel('Или настройте вручную:'))
        form = QFormLayout()

        self.preset_combo = QComboBox()
        for key, preset in presets.PRESETS.items():
            self.preset_combo.addItem(preset.name, key)
        if self.game.preset_key:
            idx = self.preset_combo.findData(self.game.preset_key)
            if idx >= 0:
                self.preset_combo.setCurrentIndex(idx)
        form.addRow('Игра из списка:', self.preset_combo)

        apply_preset_btn = QPushButton('Заполнить поля по пресету')
        apply_preset_btn.clicked.connect(self._apply_preset)
        form.addRow('', apply_preset_btn)

        self.name_input = QLineEdit(self.game.name)
        self.name_input.textChanged.connect(self._update_cloud_path_preview)
        form.addRow('Название игры:', self.name_input)

        self.process_input = QLineEdit(', '.join(self.game.process_names))
        self.process_input.setPlaceholderText('DarkSoulsIII.exe, ещё_процесс.exe')
        form.addRow('Процесс(ы) игры (.exe):', self.process_input)

        launch_row = QHBoxLayout()
        self.launch_input = QLineEdit(self.game.launch_command)
        self.launch_input.setPlaceholderText('.exe игры или steam://rungameid/ID — для кнопки «Играть»')
        launch_browse = QPushButton('Обзор...')
        launch_browse.clicked.connect(self._browse_launch)
        launch_row.addWidget(self.launch_input, 1)
        launch_row.addWidget(launch_browse)
        form.addRow('Запуск игры:', launch_row)

        self.autoupload_check = QCheckBox('Автоматически выгружать в облако после закрытия игры')
        self.autoupload_check.setChecked(self.game.auto_upload_on_exit)
        form.addRow('', self.autoupload_check)

        self.periodic_spin = QSpinBox()
        self.periodic_spin.setRange(0, 240)
        self.periodic_spin.setSuffix(' мин')
        self.periodic_spin.setSpecialValueText('выключено')
        self.periodic_spin.setValue(int(getattr(self.game, 'periodic_upload_minutes', 0) or 0))
        self.periodic_spin.setToolTip('Страховка от вылета игры или отключения питания. Выгрузка идёт, '
                                      'только когда файл сохранения не менялся последние 20 секунд и '
                                      'в облаке нет более новой версии.')
        form.addRow('Выгружать во время игры:', self.periodic_spin)
        self.snapshot_spin = QSpinBox()
        self.snapshot_spin.setRange(0, 240)
        self.snapshot_spin.setSuffix(' мин')
        self.snapshot_spin.setSpecialValueText('выключено')
        self.snapshot_spin.setValue(int(getattr(self.game, 'snapshot_minutes', 0) or 0))
        self.snapshot_spin.setToolTip('Локальные автоснимки сохранения во время игры (хранятся последние 10): '
                                      'можно откатиться, если сохранение испортилось.')
        form.addRow('Автоснимки во время игры:', self.snapshot_spin)

        self.check_on_start_check = QCheckBox('При запуске игры проверять облако и '
                                               'предлагать скачать более новое сохранение')
        self.check_on_start_check.setChecked(self.game.check_cloud_on_start)
        form.addRow('', self.check_on_start_check)

        self.account_combo = QComboBox()
        self.account_combo.addItem('Не выбран', None)
        for acc in (self.store.accounts if self.store else []):
            self.account_combo.addItem(f'{acc.name} ({acc.type})', acc.id)
        if self.game.account_id:
            idx = self.account_combo.findData(self.game.account_id)
            if idx >= 0:
                self.account_combo.setCurrentIndex(idx)
        self.account_combo.currentIndexChanged.connect(self._update_cloud_path_preview)
        form.addRow('Облачный аккаунт:', self.account_combo)

        self.remote_prefix_input = QLineEdit(self.game.remote_prefix)
        self.remote_prefix_input.setPlaceholderText('папка в облаке, например: DarkSoulsIII')
        self.remote_prefix_input.textChanged.connect(self._update_cloud_path_preview)
        form.addRow('Папка в облаке:', self.remote_prefix_input)

        self.cloud_path_preview = QLabel('')
        self.cloud_path_preview.setWordWrap(True)
        self.cloud_path_preview.setProperty('muted', True)
        form.addRow('', self.cloud_path_preview)

        layout.addLayout(form)

        layout.addWidget(QLabel('Слоты сохранения:'))
        self.slots_list = QListWidget()
        self.slots_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.slots_list.setTextElideMode(Qt.ElideRight)
        self.slots_list.setWordWrap(False)
        self._refresh_slots_list()
        layout.addWidget(self.slots_list)

        slot_btn_row = QHBoxLayout()
        add_slot_btn = QPushButton('Добавить слот')
        add_slot_btn.clicked.connect(self._add_slot)
        edit_slot_btn = QPushButton('Изменить')
        edit_slot_btn.clicked.connect(self._edit_slot)
        remove_slot_btn = QPushButton('Удалить')
        remove_slot_btn.clicked.connect(self._remove_slot)
        detect_btn = QPushButton('Автоопределение путей')
        detect_btn.clicked.connect(self._auto_detect_paths)
        slot_btn_row.addWidget(add_slot_btn)
        slot_btn_row.addWidget(edit_slot_btn)
        slot_btn_row.addWidget(remove_slot_btn)
        slot_btn_row.addWidget(detect_btn)
        layout.addLayout(slot_btn_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.addWidget(scroll)
        self.resize(*screen_fit(780, 700))

    # ---------- иконка игры ----------
    def _refresh_icon_preview(self):
        pm = game_icons.load_square_pixmap(self.game.icon_path, 64)
        self.icon_preview.setPixmap(pm if pm is not None else svg_pixmap('gamepad', 48))

    def _set_icon(self, path: str, source: str):
        if not path:
            return False
        self.game.icon_path = path
        self._refresh_icon_preview()
        self.icon_status.setText(f'Иконка: {source}')
        return True

    def _current_exe_path(self) -> str:
        return self.detected_exe_path or self.game.hint_exe_path or ''

    def _process_list(self):
        return [p.strip() for p in self.process_input.text().split(',') if p.strip()]

    def _fetch_steam_icon(self, silent: bool = False):
        if self._icon_worker and self._icon_worker.isRunning():
            return
        self.steam_icon_btn.setEnabled(False)
        self.icon_status.setText('Ищем обложку в Steam...')
        self._icon_worker = IconFetchWorker(
            self.game.id, self.name_input.text().strip(), self._current_exe_path(),
            self._process_list(), self)
        self._icon_worker.found.connect(lambda path, s=silent: self._on_steam_icon(path, s))
        self._icon_worker.start()

    def _on_steam_icon(self, path: str, silent: bool):
        self.steam_icon_btn.setEnabled(True)
        if self._set_icon(path, 'обложка из Steam'):
            return
        # В Steam не нашлось — пробуем иконку самого .exe
        if self._set_icon(game_icons.extract_exe_icon(self._current_exe_path(), self.game.id),
                          'взята из .exe'):
            return
        self.icon_status.setText('Не удалось найти иконку автоматически — выберите файл вручную.')

    def _pick_icon_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Выберите картинку для игры', '',
            'Изображения (*.png *.jpg *.jpeg *.bmp *.webp *.ico *.svg);;Все файлы (*)')
        if not path:
            return
        if not self._set_icon(game_icons.import_custom_image(path, self.game.id), 'выбрана вами'):
            self.icon_status.setText('Не удалось использовать этот файл как иконку.')

    def _icon_from_exe(self):
        exe = self._current_exe_path()
        if not exe:
            exe, _ = QFileDialog.getOpenFileName(self, 'Выберите .exe игры', '',
                                                  'Программы (*.exe);;Все файлы (*)')
        if exe and not self._set_icon(game_icons.extract_exe_icon(exe, self.game.id), 'взята из .exe'):
            self.icon_status.setText('Не удалось достать иконку из этого файла.')

    # ---------- автоматическое определение ----------
    def _pick_running_process(self):
        dlg = ProcessPickerDialog(self)
        if dlg.exec_() != QDialog.Accepted or not dlg.selected:
            return
        proc = dlg.selected
        current = [p.strip() for p in self.process_input.text().split(',') if p.strip()]
        if proc['name'] not in current:
            current.append(proc['name'])
        self.process_input.setText(', '.join(current))
        self.detected_exe_path = proc['exe'] or ''
        if self.detected_exe_path and not self.launch_input.text().strip():
            self.launch_input.setText(self.detected_exe_path)  # разумное значение для «Играть»
        self.detected_process_name = proc['name']
        self.detected_process_start_time = proc.get('create_time')

        if not self.name_input.text().strip():
            pretty = auto_detect.guess_pretty_name(self.detected_exe_path)
            if pretty:
                self.name_input.setText(pretty)
                if not self.remote_prefix_input.text().strip():
                    self.remote_prefix_input.setText(pretty.replace(' ', ''))

        # Иконку определяем сами (Steam -> иконка .exe), если ещё не задана
        if not self.game.icon_path:
            self._fetch_steam_icon(silent=True)
        # Сразу предлагаем поискать сохранение — не нужно нажимать вторую кнопку отдельно
        self._run_save_finder()

    def _run_save_finder(self):
        candidate_text = self.name_input.text().strip() or self.process_input.text().strip()
        candidate_names = auto_detect.guess_candidate_names(self.detected_exe_path, candidate_text)
        if not candidate_names and not self.detected_exe_path:
            QMessageBox.information(
                self, 'Недостаточно данных',
                'Сначала укажите название игры или выберите запущенный процесс '
                'кнопкой "1. Игра запущена — выбрать из списка" — так поиск будет точнее.')
            return
        dlg = SaveCandidatesDialog(self, candidate_names=candidate_names, exe_path=self.detected_exe_path,
                                    process_name=self.detected_process_name,
                                    process_start_time=self.detected_process_start_time)
        if dlg.exec_() != QDialog.Accepted or not dlg.selected_path:
            return
        slot = SaveSlot()
        slot.path = dlg.selected_path
        slot.is_directory = dlg.selected_is_directory
        slot.remote_name = 'save.zip' if slot.is_directory else os.path.basename(dlg.selected_path)
        slot.label = 'Основное сохранение' if not self.game.slots else f'Слот {len(self.game.slots) + 1}'
        edit_dlg = SlotEditDialog(self, slot, other_slots=self.game.slots)
        if edit_dlg.exec_() == QDialog.Accepted:
            self.game.slots.append(edit_dlg.slot)
            self._refresh_slots_list()
            self._learn_from_slot(edit_dlg.slot)

    def _learn_from_slot(self, slot: SaveSlot):
        """Запоминает путь слота за именем процесса, чтобы в следующий раз
        (для этой же или даже другой переустановленной игры с тем же .exe)
        он находился мгновенно, без нового поиска по диску."""
        process_name = (self.detected_process_name or
                         (self.game.process_names[0] if self.game.process_names else '') or
                         self.process_input.text().split(',')[0].strip())
        if not process_name or not slot.path:
            return
        classification = auto_detect.classify_path(slot.path)
        if classification:
            root_key, relative = classification
            learned_paths.remember(process_name, root_key, relative, slot.is_directory,
                                   discriminator=slot.detect_key or slot.remote_name)

    # ---------- слоты ----------
    def _refresh_slots_list(self):
        self.slots_list.clear()
        for slot in self.game.slots:
            status = slot.path if slot.path else 'путь не указан'
            kind = 'папка' if slot.is_directory else 'файл'
            text = f'{slot.label} — {status} ({kind}) → облако: {slot.remote_name}'
            item = QListWidgetItem(text)
            item.setToolTip(text)  # путь не обрезается, а читается по наведению
            self.slots_list.addItem(item)
        self._update_cloud_path_preview()

    def _update_cloud_path_preview(self):
        account_id = self.account_combo.currentData()
        account = self.store.get_account(account_id) if (self.store and account_id) else None
        if not account:
            self.cloud_path_preview.setText('Путь в облаке появится здесь после выбора '
                                             'облачного аккаунта.')
            return
        filename = self.game.slots[0].remote_name if self.game.slots else 'файл_сохранения.dat'
        prefix = self.remote_prefix_input.text().strip() or self.name_input.text().strip()
        example = preview_remote_path(account, prefix, filename)
        self.cloud_path_preview.setText(f'Путь в облаке: {example}')

    def _selected_slot_index(self):
        row = self.slots_list.currentRow()
        if row < 0 or row >= len(self.game.slots):
            return -1
        return row

    def _add_slot(self):
        dlg = SlotEditDialog(self, other_slots=self.game.slots)
        if dlg.exec_() == QDialog.Accepted:
            self.game.slots.append(dlg.slot)
            self._refresh_slots_list()
            self._learn_from_slot(dlg.slot)

    def _edit_slot(self):
        idx = self._selected_slot_index()
        if idx < 0:
            QMessageBox.information(self, 'Слот не выбран', 'Выберите слот в списке.')
            return
        dlg = SlotEditDialog(self, self.game.slots[idx],
                             other_slots=[s for s in self.game.slots if s is not self.game.slots[idx]])
        if dlg.exec_() == QDialog.Accepted:
            self._refresh_slots_list()
            self._learn_from_slot(dlg.slot)

    def _remove_slot(self):
        idx = self._selected_slot_index()
        if idx < 0:
            QMessageBox.information(self, 'Слот не выбран', 'Выберите слот в списке.')
            return
        del self.game.slots[idx]
        self._refresh_slots_list()

    def _apply_preset(self):
        key = self.preset_combo.currentData()
        preset = presets.get_preset(key)
        if not preset:
            return
        if key == 'custom':
            QMessageBox.information(self, 'Другая игра',
                                     'Заполните название, процесс и добавьте слоты вручную '
                                     'кнопкой "Добавить слот".')
            return
        if self.game.slots:
            reply = QMessageBox.question(
                self, 'Заменить слоты?',
                'У игры уже есть настроенные слоты. Заменить их слотами из пресета?',
                QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                return
        self.game.preset_key = key
        self.name_input.setText(preset.name)
        self.process_input.setText(', '.join(preset.process_names))
        if not self.remote_prefix_input.text().strip():
            self.remote_prefix_input.setText(preset.name.replace(' ', ''))
        self.game.slots = []
        for sp in preset.slots:
            self.game.slots.append(SaveSlot(
                label=sp.label, remote_name=sp.remote_name,
                is_directory=sp.is_directory, detect_key=sp.key, path='',
            ))
        self._refresh_slots_list()
        QMessageBox.information(self, 'Готово',
                                 'Поля заполнены по пресету. Теперь нажмите '
                                 '"Автоопределение путей", чтобы найти файлы сохранений '
                                 '(игра должна быть хотя бы раз запущена).')

    def _auto_detect_paths(self):
        found_any = False
        not_found = []
        for slot in self.game.slots:
            if not slot.detect_key:
                continue
            slot_preset = presets.get_slot_preset(slot.detect_key)
            if not slot_preset:
                continue
            candidates = presets.detect_slot_paths(slot_preset)
            if not candidates:
                not_found.append(slot.label)
                continue
            if len(candidates) == 1:
                slot.path = candidates[0]
            else:
                choice, ok = QInputDialog.getItem(
                    self, 'Выбор слота сохранения',
                    f'Найдено несколько сохранений для "{slot.label}", выберите нужное:',
                    candidates, 0, False)
                if ok:
                    slot.path = choice
            found_any = True
        self._refresh_slots_list()
        if not_found:
            QMessageBox.warning(self, 'Не найдено',
                                 'Не удалось найти путь для: ' + ', '.join(not_found) +
                                 '.\nЗапустите игру хотя бы один раз, чтобы появился файл '
                                 'сохранения, или укажите путь вручную кнопкой "Изменить".')
        elif found_any:
            QMessageBox.information(self, 'Готово', 'Пути успешно найдены.')
        else:
            QMessageBox.information(self, 'Нечего искать',
                                     'Для слотов пользовательской игры автоопределение '
                                     'недоступно — укажите путь вручную.')

    # ---------- сохранение ----------
    def reject(self):
        if self._icon_worker and self._icon_worker.isRunning():
            self._icon_worker.wait(3000)
        super().reject()

    def _browse_launch(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Выберите программу для запуска игры', '',
                                              'Программы (*.exe *.bat *.lnk);;Все файлы (*)')
        if path:
            self.launch_input.setText(path)

    def _on_accept(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, 'Ошибка', 'Укажите название игры.')
            return
        if not self.game.slots:
            reply = QMessageBox.question(
                self, 'Нет слотов сохранения',
                'Вы не добавили ни одного слота сохранения. Продолжить всё равно?',
                QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                return
        if self._icon_worker and self._icon_worker.isRunning():
            self._icon_worker.wait(3000)
        self.game.name = name
        self.game.process_names = [p.strip() for p in self.process_input.text().split(',') if p.strip()]
        self.game.auto_upload_on_exit = self.autoupload_check.isChecked()
        self.game.periodic_upload_minutes = self.periodic_spin.value()
        self.game.snapshot_minutes = self.snapshot_spin.value()
        self.game.check_cloud_on_start = self.check_on_start_check.isChecked()
        self.game.account_id = self.account_combo.currentData()
        self.game.remote_prefix = self.remote_prefix_input.text().strip() or name.replace(' ', '')
        self.game.hint_exe_path = self.detected_exe_path
        self.game.launch_command = self.launch_input.text().strip()
        self.accept()
