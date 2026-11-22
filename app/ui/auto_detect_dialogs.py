"""
Диалоги автоматического определения:
  - ProcessPickerDialog — выбор игры из списка уже запущенных программ
    (чтобы не нужно было вручную вводить имя .exe);
  - SaveFinderWorker — фоновый поиск вероятных папок/файлов сохранения;
  - SaveCandidatesDialog — показывает найденные варианты пользователю.
"""
import datetime
import time

from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QDialogButtonBox, QProgressBar,
)

from app import auto_detect, learned_paths
from app.ui.svg_icons import svg_icon


class ProcessPickerDialog(QDialog):
    """Список запущенных сейчас программ — пользователь просто находит
    среди них свою игру, не вводя имя .exe вручную."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Выбор запущенной игры')
        self.setMinimumSize(460, 420)
        self.selected = None  # {'name': ..., 'exe': ...}

        layout = QVBoxLayout(self)
        hint = QLabel('Запустите игру, если ещё не сделали этого, затем найдите её '
                       'в списке ниже (можно ввести часть названия для поиска) и нажмите ОК.')
        hint.setWordWrap(True)
        layout.addWidget(hint)

        filter_row = QHBoxLayout()
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText('Начните вводить название...')
        self.filter_input.textChanged.connect(self._apply_filter)
        refresh_btn = QPushButton('Обновить список')
        refresh_btn.clicked.connect(self._reload)
        filter_row.addWidget(self.filter_input)
        filter_row.addWidget(refresh_btn)
        layout.addLayout(filter_row)

        self.list_widget = QListWidget()
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_widget.setTextElideMode(Qt.ElideRight)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._on_accept())
        layout.addWidget(self.list_widget)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._all_processes = []
        self._reload()

    def _reload(self):
        self._all_processes = auto_detect.list_running_processes()
        self._apply_filter()

    def _apply_filter(self):
        text = self.filter_input.text().strip().lower()
        self.list_widget.clear()
        for proc in self._all_processes:
            if text and text not in proc['name'].lower():
                continue
            label = proc['name']
            if proc['exe']:
                label += f'   —   {proc["exe"]}'
            item = QListWidgetItem(label)
            item.setToolTip(label)
            item.setData(Qt.UserRole, proc)
            self.list_widget.addItem(item)
        if self.list_widget.count() == 0:
            placeholder = QListWidgetItem('Ничего не найдено. Убедитесь, что игра запущена, '
                                           'и нажмите "Обновить список".')
            placeholder.setFlags(placeholder.flags() & ~Qt.ItemIsSelectable)
            self.list_widget.addItem(placeholder)

    def _on_accept(self):
        item = self.list_widget.currentItem()
        data = item.data(Qt.UserRole) if item else None
        if not data:
            return
        self.selected = data
        self.accept()


class SaveFinderWorker(QThread):
    """Ищет вероятные папки/файлы сохранения в фоновом потоке, чтобы
    не подвешивать интерфейс во время сканирования диска.

    Порядок приоритета результатов:
      1) уже когда-то запомненный путь для этого процесса (мгновенно,
         почти наверняка верно);
      2) совпадение по названию папки;
      3) недавно изменённые файлы — если известно время запуска процесса,
         ищем файлы, изменённые ПОСЛЕ старта игры (а не за произвольные
         последние несколько часов), что гораздо точнее для любой игры,
         для которой нет готового пресета."""
    finished_search = pyqtSignal(list)

    def __init__(self, candidate_names, exe_path='', process_name='',
                 process_start_time=None, parent=None):
        super().__init__(parent)
        self.candidate_names = candidate_names
        self.exe_path = exe_path
        self.process_name = process_name
        self.process_start_time = process_start_time

    def run(self):
        should_stop = self.isInterruptionRequested

        learned = []
        if self.process_name:
            found = learned_paths.try_resolve(self.process_name)
            if found:
                learned.append(found)

        all_roots = auto_detect.common_search_roots(self.exe_path)
        # Папка, где лежит сам exe (и её родитель), исключаются из поиска
        # ПО НАЗВАНИЮ: имя этой папки почти всегда само и есть источник
        # кандидата (мы же из него и получили "SuperGame"), так что
        # совпадение там гарантировано и ничего не говорит о том, где
        # реально лежит сохранение — только засоряет и перебивает настоящую
        # находку в AppData/Documents. Для поиска "по недавним изменениям"
        # эти папки по-прежнему проверяются — некоторые игры действительно
        # хранят сохранение рядом с собой.
        name_roots = [(k, p) for k, p in all_roots if k not in ('exe_dir', 'exe_parent')]

        since_minutes = 240
        if self.process_start_time:
            elapsed_min = max(1.0, (time.time() - self.process_start_time) / 60.0)
            since_minutes = min(elapsed_min + 5, 240)  # +5 мин запас, не больше 4 часов

        by_name = auto_detect.find_by_name(self.candidate_names, name_roots, max_depth=2,
                                            time_budget=4.0, should_stop=should_stop)
        recent = auto_detect.find_recent(all_roots, since_minutes=since_minutes, max_depth=3,
                                          time_budget=5.0, top_n=20, should_stop=should_stop)
        # пути из базы Ludusavi (если индекс уже скачан) — надёжнее эвристик
        try:
            from app import manifest
            from_manifest = manifest.find_candidates(self.candidate_names, self.exe_path)
        except Exception:
            from_manifest = []
        merged = auto_detect.merge_results(learned + from_manifest + by_name, recent, limit=25)
        self.finished_search.emit(merged)


class SaveCandidatesDialog(QDialog):
    """Показывает найденные варианты пути к сохранению; пользователь
    выбирает нужный (или отменяет и вводит путь вручную)."""

    def __init__(self, parent=None, candidate_names=None, exe_path='',
                 process_name='', process_start_time=None):
        super().__init__(parent)
        self.setWindowTitle('Поиск сохранения')
        self.setMinimumSize(560, 440)
        self.selected_path = None
        self.selected_is_directory = False
        self.selected_data = None
        self.candidate_names = candidate_names or set()
        self.exe_path = exe_path
        self.process_name = process_name
        self.process_start_time = process_start_time

        layout = QVBoxLayout(self)
        self.status_label = QLabel('Идёт поиск сохранения на диске, это может занять '
                                    'несколько секунд...')
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # индикатор без процентов (неопределённый)
        layout.addWidget(self.progress)

        self.list_widget = QListWidget()
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_widget.setTextElideMode(Qt.ElideRight)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._on_accept())
        layout.addWidget(self.list_widget)
        self.list_widget.hide()

        self.retry_btn = QPushButton('Искать ещё раз')
        self.retry_btn.setIcon(svg_icon('refresh'))
        self.retry_btn.setToolTip('Полезно, если вы только что сохранились в игре — '
                                   'запустите поиск заново, не закрывая это окно.')
        self.retry_btn.clicked.connect(self._start_search)
        layout.addWidget(self.retry_btn)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self._on_accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        layout.addWidget(self.buttons)

        self.worker = None
        self._start_search()

    def _start_search(self):
        if self.worker and self.worker.isRunning():
            return
        self.status_label.setText('Идёт поиск сохранения на диске, это может занять '
                                   'несколько секунд...')
        self.progress.show()
        self.list_widget.hide()
        self.list_widget.clear()
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self.retry_btn.setEnabled(False)
        self.worker = SaveFinderWorker(self.candidate_names, self.exe_path,
                                        self.process_name, self.process_start_time)
        self.worker.finished_search.connect(self._on_results)
        self.worker.start()

    def _on_results(self, results):
        self.progress.hide()
        self.list_widget.show()
        self.retry_btn.setEnabled(True)
        if not results:
            self.status_label.setText(
                'Автоматически ничего не нашлось. Это не страшно — можно указать путь '
                'вручную кнопкой "Файл..."/"Папка..." в окне слота, либо немного '
                'поиграть/сохраниться в игре и нажать "Искать ещё раз".')
            return

        self.status_label.setText(f'Найдено вариантов: {len(results)}. '
                                   f'Выберите наиболее подходящий и нажмите ОК.')
        for item_data in results:
            path = item_data['path']
            kind = 'папка' if item_data['is_dir'] else 'файл'
            reason = item_data['reason']
            mtime = item_data.get('mtime')
            when = ''
            if mtime:
                when = ' · изменено ' + datetime.datetime.fromtimestamp(mtime).strftime('%d.%m.%Y %H:%M')
            item = QListWidgetItem(f'{path}\n{kind}, {reason}{when}')
            item.setToolTip(path + '\n' + kind + ', ' + reason + when)
            item.setData(Qt.UserRole, item_data)
            self.list_widget.addItem(item)
        self.list_widget.setCurrentRow(0)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(True)

    def _on_accept(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        data = item.data(Qt.UserRole)
        self.selected_path = data['path']
        self.selected_is_directory = bool(data['is_dir'])
        self.selected_data = data
        self.accept()

    def reject(self):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait(1000)
        super().reject()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait(1000)
        event.accept()
