"""
Главное окно приложения: список игр слева, управление сохранениями
выбранной игры справа, отслеживание процессов игр в фоне, автоматическая
выгрузка сохранения в облако после закрытия игры и проверка облака при
запуске игры. Умеет сворачиваться в трей и запускаться вместе с системой.
"""
import glob
import os

from PyQt5.QtCore import QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (QFrame,
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
    QListWidgetItem, QPushButton, QLabel, QMessageBox, QLineEdit, QComboBox,
    QSpinBox, QShortcut,
    QDialog, QDialogButtonBox, QSystemTrayIcon, QMenu, QScrollArea, QTextBrowser,
)

from app import backup, os_utils, secrets_store, sync_manager
from app.logger import log_action
from app.models import GameProfile
from app.process_monitor import ProcessMonitor
from app.store import ConfigStore
from app.ui.account_dialog import AccountDialog
from app.ui.backups_dialog import BackupsDialog
from app.ui.game_dialog import GameDialog
from app.ui.icons import make_app_icon
from app.ui.svg_icons import svg_icon, svg_pixmap
from app import catalog, power
from app.ui import motion
from app.ui.conflict_dialog import ConflictDialog
from app.ui.scan_dialog import ScanDialog
from app.ui.transfer_dialog import run_transfer
from app import game_icons
from app.ui.settings_dialog import SettingsDialog
from app.ui import fonts, tokens as T
from app.ui.glass import BackdropWidget, GlassFrame
from app.ui.widgets import ElidedLabel, GameCover, Tag, screen_fit

STATUS_TEXT = {
    'cloud_newer': 'В облаке есть более новая версия — рекомендуется скачать.',
    'conflict': 'Сохранение менялось и локально, и в облаке — выберите, что оставить.',
}


def _icon_button(icon: str, tooltip: str, color: str = T.TEXT_MUTED, size: int = 18) -> QPushButton:
    """Компактная кнопка только с иконкой: подсказка и accessible name обязательны."""
    btn = QPushButton()
    btn.setProperty('cls', 'icon')
    btn.setIcon(svg_icon(icon, size, color))
    btn.setIconSize(QSize(size, size))
    btn.setToolTip(tooltip)
    btn.setAccessibleName(tooltip)
    btn.setCursor(Qt.PointingHandCursor)
    return btn


def _square_button(icon: str, tooltip: str, color: str = T.TEXT_MUTED) -> QPushButton:
    """Квадратная кнопка 30x30 для панели списка игр (одинаковые размеры и стиль)."""
    btn = QPushButton()
    btn.setProperty('cls', 'square')
    btn.setIcon(svg_icon(icon, 18, color))
    btn.setIconSize(QSize(18, 18))
    btn.setToolTip(tooltip)
    btn.setAccessibleName(tooltip)
    btn.setCursor(Qt.PointingHandCursor)
    return btn


def _nav_button(icon: str, text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setProperty('cls', 'nav')
    btn.setIcon(svg_icon(icon, 18, T.TEXT_MUTED))
    btn.setIconSize(QSize(18, 18))
    return btn


def _fmt_ts(value: str) -> str:
    """ISO-время -> «14.10.2026 18:30» (или «никогда»)."""
    if not value:
        return 'никогда'
    try:
        import datetime as _dt
        return _dt.datetime.fromisoformat(value).strftime('%d.%m.%Y, %H:%M')
    except ValueError:
        return value


def _fmt_ago(value: str) -> str:
    """Короткая дата для карточки: «сегодня, 14:30», «вчера», «12.03, 09:10».
    Полная дата остаётся в подсказке."""
    if not value:
        return 'никогда'
    try:
        import datetime as _dt
        when = _dt.datetime.fromisoformat(value)
        now = _dt.datetime.now()
    except ValueError:
        return value
    if when.date() == now.date():
        return 'сегодня, ' + when.strftime('%H:%M')
    if (now.date() - when.date()).days == 1:
        return 'вчера, ' + when.strftime('%H:%M')
    if when.year == now.year:
        return when.strftime('%d.%m, %H:%M')
    return when.strftime('%d.%m.%Y, %H:%M')


def _fmt_size(num) -> str:
    """Размер сохранения в понятном виде: 820 Б / 1,4 МБ / 2,1 ГБ."""
    try:
        value = float(num)
    except (TypeError, ValueError):
        return ''
    for unit in ('Б', 'КБ', 'МБ', 'ГБ'):
        if value < 1024 or unit == 'ГБ':
            return (f'{int(value)} {unit}' if unit == 'Б' else f'{value:.1f} {unit}').replace('.', ',')
        value /= 1024
    return ''


def _modified_since_sync(slot) -> bool:
    """Менялся ли локальный файл после последней выгрузки/загрузки — по времени
    изменения, без чтения содержимого."""
    import datetime as _dt
    stamps = []
    for v in (slot.last_upload, slot.last_download):
        try:
            stamps.append(_dt.datetime.fromisoformat(v).timestamp())
        except (TypeError, ValueError):
            pass
    if not stamps:
        return False
    info = sync_manager.local_info(slot)
    return bool(info) and info['mtime'] > max(stamps) + 2


def _restyle(button: QPushButton, cls: str) -> QPushButton:
    button.setProperty('cls', cls)
    # Заставляем Qt немедленно пересчитать стиль для нового значения
    # свойства — иначе кнопки, созданные уже после первого показа окна,
    # не подхватят цветной вариант из QSS.
    button.style().unpolish(button)
    button.style().polish(button)
    return button


def _primary(button: QPushButton) -> QPushButton:
    return _restyle(button, 'primary')


def _success(button: QPushButton) -> QPushButton:
    return _restyle(button, 'success')


def _danger(button: QPushButton) -> QPushButton:
    return _restyle(button, 'danger')


class AccountManagerDialog(QDialog):
    """Список облачных аккаунтов с возможностью добавить/изменить/удалить."""

    def __init__(self, parent, store: ConfigStore):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle('Облачные аккаунты')
        self.setMinimumSize(*screen_fit(420, 320))
        layout = QVBoxLayout(self)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)
        self._refresh()

        btn_row = QHBoxLayout()
        add_btn = _primary(QPushButton('Добавить'))
        add_btn.clicked.connect(self._add)
        edit_btn = QPushButton('Изменить')
        edit_btn.clicked.connect(self._edit)
        remove_btn = _danger(QPushButton('Удалить'))
        remove_btn.clicked.connect(self._remove)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(edit_btn)
        btn_row.addWidget(remove_btn)
        layout.addLayout(btn_row)

        find_btn = QPushButton('Найти игры в облаке')
        find_btn.setToolTip('Найти игры в облаке для выбранного аккаунта. Читает каталог игр '
                            'в облаке и добавляет игры, которых нет на этом компьютере '
                            '(включая удалённые вручную раньше).')
        find_btn.clicked.connect(self._find_games)
        layout.addWidget(find_btn)

        close_buttons = QDialogButtonBox(QDialogButtonBox.Close)
        close_buttons.rejected.connect(self.reject)
        close_buttons.accepted.connect(self.accept)
        close_buttons.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        layout.addWidget(close_buttons)

    def _refresh(self):
        self.list_widget.clear()
        for acc in self.store.accounts:
            self.list_widget.addItem(QListWidgetItem(f'{acc.name} — {acc.type}'))

    def _find_games(self):
        acc = self._selected_account()
        if not acc:
            QMessageBox.information(self, 'Не выбрано', 'Выберите аккаунт в списке.')
            return
        result = {}

        def job(progress):
            created, msg = catalog.sync_account(self.store, acc, include_ignored=True, progress=progress)
            result['created'] = created
            return not msg.startswith(('Не удалось', 'Ошибка')), msg

        run_transfer(self, f'Поиск игр в облаке — {acc.name}', job)

    def _selected_account(self):
        row = self.list_widget.currentRow()
        if row < 0 or row >= len(self.store.accounts):
            return None
        return self.store.accounts[row]

    def _add(self):
        dlg = AccountDialog(self)
        if dlg.exec_() == QDialog.Accepted and dlg.result_account:
            self.store.add_account(dlg.result_account, secret=dlg.result_secret or '')
            self._apply_enc_secret(dlg.result_account.id, dlg.result_passphrase)
            self._refresh()

    @staticmethod
    def _apply_enc_secret(account_id: str, passphrase: str):
        """Пустой пароль шифрования означает, что шифрование выключено."""
        if passphrase:
            secrets_store.set_secret(account_id + ':enc', passphrase)
        else:
            secrets_store.delete_secret(account_id + ':enc')

    def _edit(self):
        acc = self._selected_account()
        if not acc:
            QMessageBox.information(self, 'Не выбрано', 'Выберите аккаунт в списке.')
            return
        secret = secrets_store.get_secret(acc.id)
        dlg = AccountDialog(self, account=acc, existing_secret=secret)
        if dlg.exec_() == QDialog.Accepted and dlg.result_account:
            self.store.update_account(dlg.result_account, secret=dlg.result_secret)
            self._apply_enc_secret(dlg.result_account.id, dlg.result_passphrase)
            self._refresh()

    def _remove(self):
        acc = self._selected_account()
        if not acc:
            QMessageBox.information(self, 'Не выбрано', 'Выберите аккаунт в списке.')
            return
        reply = QMessageBox.question(
            self, 'Удалить аккаунт?',
            f'Удалить аккаунт "{acc.name}"? Игры, использующие его, останутся без '
            f'привязанного облака.',
            QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.store.remove_account(acc.id)
            self._refresh()


class CatalogWorker(QThread):
    """Фоновая синхронизация каталога игр: подхватывает игры с других ПК, докачивает
    их сохранения и публикует игры этого ПК (по всем аккаунтам подряд)."""
    finished_sync = pyqtSignal(list, list)  # [имена добавленных игр], [сообщения об ошибках]

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store

    def run(self):
        added, errors = [], []
        for account in list(self.store.accounts):
            try:
                created, msg = catalog.sync_account(self.store, account)
            except Exception as e:  # сеть/облако не должны ронять поток
                created, msg = [], f'{account.name}: {e}'
                log_action('catalog', 'exception', msg)
            added.extend(g.name for g in created)
            if msg.startswith(('Не удалось', 'Ошибка')) or 'не обновлён' in msg:
                errors.append(f'{account.name}: {msg}')
        self.finished_sync.emit(added, errors)


class MainWindow(QMainWindow):
    # Фоновая подкачка обложек не имеет права трогать store/виджеты из потока.
    icon_ready = pyqtSignal(str, str)  # game_id, path

    def __init__(self, start_hidden: bool = False):
        super().__init__()
        self.store = ConfigStore()
        self.setWindowTitle('Cloud Save Manager — облачные сохранения для любых игр')
        self.setMinimumSize(*screen_fit(720, 480))
        self.resize(*screen_fit(860, 540))
        self._force_quit = False
        # (game_id, slot_id) -> статус синхронизации, обнаруженный при запуске игры
        self.pending_sync = {}
        # id игр, которые сейчас запущены (по данным ProcessMonitor) — нужно
        # для быстрого меню в трее
        self.running_game_ids = set()
        self._order = []  # игры в том порядке, в каком показаны в списке

        icon = make_app_icon()
        self.setWindowIcon(icon)

        self._build_ui()
        self._refresh_games_list()
        # При пустом списке currentRowChanged не срабатывает — рисуем стартовый
        # экран с подсказкой, что делать дальше, явно.
        self._render_game_details()
        self._init_tray(icon)

        self.monitor = ProcessMonitor(self.store)
        self.monitor.status_changed.connect(self._on_status_changed)
        self.monitor.game_started.connect(self._on_game_started)
        self.monitor.game_exited.connect(self._on_game_exited)
        self.monitor.upload_result.connect(self._on_upload_result)
        self.monitor.periodic_result.connect(self._on_periodic_result)
        self.monitor.play_conflict.connect(self._on_play_conflict)
        QTimer.singleShot(45000, self._refresh_manifest_in_background)  # не мешаем запуску
        self._catalog_worker = None
        self._pending_status = ''
        self._eco_active = False
        self._last_rendered_game = None
        self._last_tags = {}  # slot_id -> текст индикатора состояния
        motion.set_enabled(self.store.settings.animations)
        power.lower_priority()  # фоновая утилита не должна конкурировать с игрой
        self._catalog_rerun = False
        QTimer.singleShot(1500, self._sync_catalogs)  # после показа окна
        self.monitor.sync_check_result.connect(self._on_sync_check_result)
        self.icon_ready.connect(self._on_icon_ready)
        self.monitor.start()

        if start_hidden and self.tray:
            if self.store.settings.tray_notifications:
                self.tray.showMessage('Cloud Save Manager', 'Запущен в трее и следит за играми.',
                                       QSystemTrayIcon.Information, 4000)
        else:
            self.show()

    # ---------- построение интерфейса ----------
    def _build_ui(self):
        central = BackdropWidget()  # живой фон «жидкого стекла» (в плоских темах — просто заливка)
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ----- боковая панель -----
        left = QVBoxLayout()
        left.setContentsMargins(T.S3, T.S4, T.S3, T.S3)
        left.setSpacing(T.S2)

        header_row = QHBoxLayout()
        header_row.setSpacing(T.S2)
        logo = QLabel()
        logo.setPixmap(svg_pixmap('cloud', 22, T.FOCUS))
        header_row.addWidget(logo)
        title = ElidedLabel('Cloud Save Manager', Qt.ElideRight)
        title.setFont(fonts.heading_font('Cloud Save Manager', T.FS_APP_TITLE))
        header_row.addWidget(title, 1)
        left.addLayout(header_row)
        left.addSpacing(T.S2)

        list_header = QHBoxLayout()
        list_header.setSpacing(T.S1 + 2)
        section = QLabel('ИГРЫ')
        section.setObjectName('sectionLabel')
        list_header.addWidget(section)
        list_header.addStretch()
        add_btn = _square_button('plus', 'Добавить игру (Ctrl+N)', T.TEXT)
        add_btn.clicked.connect(self._add_game)
        scan_btn = _square_button('search', 'Найти установленные игры (Steam, Epic, GOG)')
        scan_btn.clicked.connect(self._scan_games)
        edit_btn = _square_button('edit', 'Изменить выбранную игру (F2)')
        edit_btn.clicked.connect(self._edit_game)
        remove_btn = _square_button('trash', 'Удалить выбранную игру (Delete)')
        remove_btn.clicked.connect(self._remove_game)
        for b in (add_btn, scan_btn, edit_btn, remove_btn):
            list_header.addWidget(b)
        left.addLayout(list_header)

        # Поиск по названию игры и имени процесса — в библиотеке из десятков
        # игр искать прокруткой неудобно.
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('Поиск по играм...')
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setAccessibleName('Поиск по играм')
        self.search_input.textChanged.connect(self._on_search_changed)
        left.addWidget(self.search_input)

        self.games_list = QListWidget()
        self.games_list.currentRowChanged.connect(self._on_game_selected)
        self.games_list.setAccessibleName('Список игр')
        self.games_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.games_list.setTextElideMode(Qt.ElideRight)
        self.games_list.setWordWrap(False)
        left.addWidget(self.games_list, 1)

        sep = QFrame()
        sep.setObjectName('sideSep')
        sep.setFixedHeight(1)
        left.addWidget(sep)

        # состояние слежения: заметно, но компактно (точка + текст + кнопка паузы)
        monitor_row = QHBoxLayout()
        monitor_row.setSpacing(T.S2)
        self.monitor_dot = QLabel()
        self.monitor_dot.setFixedSize(10, 10)
        monitor_row.addWidget(self.monitor_dot)
        # Обычный QLabel не умеет обрезать текст: на узкой боковой панели
        # длинная надпись вылезала за край. ElidedLabel оставляет многоточие.
        self.monitor_state_label = ElidedLabel('', Qt.ElideRight)
        monitor_row.addWidget(self.monitor_state_label, 1)
        self.pause_btn = _square_button('pause', '')
        self.pause_btn.clicked.connect(self._toggle_pause)
        monitor_row.addWidget(self.pause_btn)
        left.addLayout(monitor_row)
        self._update_pause_button()

        accounts_btn = _nav_button('cloud', 'Аккаунты')
        accounts_btn.setToolTip('Облачные аккаунты (Ctrl+Shift+A) — GitHub, GitLab, WebDAV, локальная папка')
        accounts_btn.setAccessibleName(accounts_btn.toolTip())
        accounts_btn.clicked.connect(self._open_accounts)
        left.addWidget(accounts_btn)
        settings_btn = _nav_button('settings', 'Настройки')
        settings_btn.setToolTip('Настройки (Ctrl+,)')
        settings_btn.clicked.connect(self._open_settings)
        left.addWidget(settings_btn)
        help_btn = _nav_button('help', 'Инструкция')
        help_btn.clicked.connect(self._show_help)
        left.addWidget(help_btn)

        self.sidebar = QWidget()
        self.sidebar.setObjectName('sidebar')
        self.sidebar.setLayout(left)
        self.sidebar.setFixedWidth(T.SIDEBAR_WIDTH)
        root.addWidget(self.sidebar)

        # ----- рабочая область -----
        self.right = QVBoxLayout()
        self.right.setSpacing(T.S3)
        title_row = QHBoxLayout()
        title_row.setSpacing(T.S3)
        self.game_cover = GameCover()
        self.game_cover.hide()
        title_row.addWidget(self.game_cover, 0, Qt.AlignTop)
        head_col = QVBoxLayout()
        head_col.setSpacing(2)
        self.game_title_label = ElidedLabel('', Qt.ElideRight)
        head_col.addWidget(self.game_title_label)
        self.meta_primary = ElidedLabel('', Qt.ElideRight)   # аккаунт · слежение
        head_col.addWidget(self.meta_primary)
        # Спокойный «индикатор спокойствия»: обычному пользователю важны не
        # технические подробности, а ответ: «мои сохранения в безопасности?»
        self.sync_badge = Tag('', 'neutral', 'check', '')
        self.sync_badge.setMaximumWidth(340)
        head_col.addWidget(self.sync_badge)
        title_row.addLayout(head_col, 1)
        self.play_btn = QPushButton('Играть')
        self.play_btn.setProperty('cls', 'primary')
        self.play_btn.setIcon(svg_icon('play', 18, T.TEXT_ON_SAGE))
        self.play_btn.setIconSize(QSize(18, 18))
        self.play_btn.setFixedHeight(T.BTN_H - 4)
        self.play_btn.setMinimumWidth(110)
        self.play_btn.setCursor(Qt.PointingHandCursor)
        self.play_btn.clicked.connect(self._play_game)
        self.play_btn.hide()
        title_row.addWidget(self.play_btn, 0, Qt.AlignTop)

        # Геймеру, который сел за другой ПК, достаточно одной кнопки: скачать
        # облачную версию и сразу запустить игру.
        self.play_cloud_btn = _icon_button('download', 'Играть с облачной копии — скачать '
                                          'сохранение из облака и запустить игру')
        self.play_cloud_btn.setFixedSize(T.BTN_H - 4, T.BTN_H - 4)
        self.play_cloud_btn.clicked.connect(self._play_from_cloud)
        self.play_cloud_btn.hide()
        title_row.addWidget(self.play_cloud_btn, 0, Qt.AlignTop)
        self.right.addLayout(title_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.slots_container = QWidget()
        self.slots_layout = QVBoxLayout(self.slots_container)
        self.slots_layout.setContentsMargins(0, 0, T.S1, 0)
        self.slots_layout.setSpacing(T.S3)
        self.slots_layout.addStretch()
        scroll.setWidget(self.slots_container)
        self.right.addWidget(scroll, 1)

        root.addLayout(self.right, 1)
        self._install_shortcuts()
        self._apply_density()
        self.statusBar().showMessage('Инициализация отслеживания процессов...')

    def _install_shortcuts(self):
        """Горячие клавиши для частых действий. Не срабатывают, когда пользователь
        печатает в поле ввода (иначе Delete в поиске удалил бы игру)."""
        def safe(fn):
            def call():
                focus = QApplication.focusWidget()
                if isinstance(focus, (QLineEdit, QComboBox, QSpinBox)):
                    return
                fn()
            return call

        combos = (
            ('Ctrl+N', self._add_game),
            ('Ctrl+Shift+A', self._open_accounts),
            ('Ctrl+,', self._open_settings),
            ('F2', self._edit_game),
            ('Delete', self._remove_game),
        )
        self._shortcuts = [QShortcut(QKeySequence(seq), self, safe(fn)) for seq, fn in combos]
        self._search_shortcut = QShortcut(QKeySequence('Ctrl+F'), self,
                                          lambda: self.search_input.setFocus())

    def _apply_density(self):
        """Компактный режим на узких окнах: меньше отступы и обложка."""
        w = self.width()
        compact = w < T.COMPACT_WIDTH
        m = T.S3 if compact else T.S5
        self.right.setContentsMargins(m, T.S3 if compact else T.S4, m, T.S2)
        if hasattr(self, 'game_cover'):
            self.game_cover.set_size(T.COVER_MIN if w < 780 else T.COVER_MAX)
        # На узком окне панель уже — рабочей области остаётся больше места.
        if hasattr(self, 'sidebar'):
            self.sidebar.setFixedWidth(196 if w < 820 else T.SIDEBAR_WIDTH)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_density()

    def _init_tray(self, icon):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = None
            return
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(icon)
        self.tray.setToolTip('Cloud Save Manager — следит за играми')
        # Меню трея строится заново прямо перед показом (aboutToShow) —
        # так пункты "Запущенные игры" всегда отражают текущее состояние,
        # даже если игры запустились/закрылись, пока окно было скрыто.
        self.tray_menu = QMenu()
        self.tray_menu.aboutToShow.connect(self._rebuild_tray_menu)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _rebuild_tray_menu(self):
        menu = getattr(self, 'tray_menu', None)
        if menu is None:  # системный трей недоступен — меню не строим
            return
        menu.clear()

        running_games = [g for g in self.store.games if g.id in self.running_game_ids]
        if running_games:
            header = menu.addAction('ЗАПУЩЕННЫЕ ИГРЫ')
            header.setEnabled(False)
            for game in running_games:
                self._add_game_submenu(menu, game)
            menu.addSeparator()

        recent = [g for g in self.store.games if g.last_played and self._launch_target(g)]
        if recent:
            last = max(recent, key=lambda g: g.last_played)
            cont = menu.addAction(svg_icon('play'), f'Продолжить: {last.name}')
            cont.triggered.connect(lambda _=False, g=last: (self._restore_from_tray(), self._select_game(g.id), self._play_game(g)))
            menu.addSeparator()

        show_action = menu.addAction('Открыть окно')
        show_action.triggered.connect(self._restore_from_tray)
        paused = self.store.settings.monitoring_paused
        pause_action = menu.addAction(svg_icon('play' if paused else 'pause'),
                                      'Возобновить слежение' if paused else 'Приостановить слежение')
        pause_action.triggered.connect(self._toggle_pause)
        settings_action = menu.addAction(svg_icon('settings'), 'Настройки...')
        settings_action.triggered.connect(self._open_settings)
        menu.addSeparator()
        quit_action = menu.addAction('Выход')
        quit_action.triggered.connect(self._quit_from_tray)

    def _add_game_submenu(self, parent_menu: QMenu, game: GameProfile):
        submenu = parent_menu.addMenu(game.name)
        if not game.slots:
            act = submenu.addAction('Нет настроенных слотов сохранения')
            act.setEnabled(False)
        else:
            # Если слот один — действия кладём прямо в меню игры, чтобы не
            # заставлять открывать лишний уровень подменю. Если слотов
            # несколько (например, обычная игра + Seamless Co-op) — у
            # каждого своё подменю.
            single = len(game.slots) == 1
            for slot in game.slots:
                target_menu = submenu if single else submenu.addMenu(slot.label)
                status = self.pending_sync.get((game.id, slot.id))
                is_newer = bool(status and status.get('status') in ('cloud_newer', 'conflict'))

                up_act = target_menu.addAction(svg_icon('upload'), 'Выгрузить в облако')
                up_act.triggered.connect(lambda _, g=game, s=slot: self._tray_upload(g, s))

                down_label = 'Загрузить из облака'
                if is_newer:
                    down_label += '  (есть новая версия!)'
                down_act = target_menu.addAction(svg_icon('download'), down_label)
                down_act.triggered.connect(lambda _, g=game, s=slot: self._tray_download(g, s))

                snap_act = target_menu.addAction(svg_icon('bookmark'), 'Быстрый снимок')
                snap_act.triggered.connect(lambda _, g=game, s=slot: self._quick_snapshot(g, s))

        submenu.addSeparator()
        open_act = submenu.addAction(svg_icon('folder'), 'Открыть папку сохранения')
        open_act.triggered.connect(lambda _, g=game: self._tray_open_folder(g))
        show_act = submenu.addAction('Показать в окне программы')
        show_act.triggered.connect(lambda _, g=game: self._tray_show_game(g))

    def _tray_upload(self, game: GameProfile, slot):
        if (game.id, slot.id) in self.pending_sync:
            self._restore_from_tray()
        if not self._confirm_overwrite_cloud(game, slot):
            return
        ok, message = sync_manager.upload_slot(self.store, game, slot, silent=False)
        self.pending_sync[(game.id, slot.id)] = ({'status': 'up_to_date'} if ok else
                                                 {'status': 'error', 'message': message})
        if self.tray and self.store.settings.tray_notifications:
            icon = QSystemTrayIcon.Information if ok else QSystemTrayIcon.Warning
            self.tray.showMessage(f'{game.name}: {slot.label}', message, icon, 4000)
        if self._current_game() and self._current_game().id == game.id:
            self._render_game_details()

    def _tray_download(self, game: GameProfile, slot):
        # Резервная копия текущей локальной версии создаётся автоматически
        # внутри download_slot, так что даже без подтверждения исходный файл
        # всегда можно вернуть. Если включено в настройках — подтверждаем.
        if self.store.settings.confirm_tray_download:
            self._restore_from_tray()
            reply = QMessageBox.question(
                self, 'Подтверждение',
                f'Загрузить сохранение "{slot.label}" ({game.name}) из облака? '
                f'Текущий локальный файл будет заменён (резервная копия создастся '
                f'автоматически).',
                QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        ok, message = sync_manager.download_slot(self.store, game, slot)
        if ok:
            self.pending_sync[(game.id, slot.id)] = {'status': 'up_to_date'}
        if self.tray and self.store.settings.tray_notifications:
            icon = QSystemTrayIcon.Information if ok else QSystemTrayIcon.Warning
            self.tray.showMessage(f'{game.name}: {slot.label}', message, icon, 4000)
        if self._current_game() and self._current_game().id == game.id:
            self._render_game_details()

    def _tray_open_folder(self, game: GameProfile):
        for slot in game.slots:
            if slot.path and os_utils.open_in_file_manager(slot.path):
                return
        if self.tray:
            self.tray.showMessage(game.name, 'Не удалось найти папку сохранения.',
                                   QSystemTrayIcon.Warning, 3000)

    def _tray_show_game(self, game: GameProfile):
        self._restore_from_tray()
        self._select_game(game.id)

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._restore_from_tray()

    def _restore_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_from_tray(self):
        self._force_quit = True
        self.close()

    # ---------- список игр ----------
    def _ordered_games(self):
        games = list(self.store.games)
        if self.store.settings.sort_recent:  # недавно запускавшиеся — выше
            games.sort(key=lambda g: g.last_played or '', reverse=True)
        query = self.search_input.text().strip().lower() if hasattr(self, 'search_input') else ''
        if query:
            games = [g for g in games
                     if query in g.name.lower() or any(query in p.lower() for p in g.process_names)]
        return games

    def _on_search_changed(self, _text: str):
        self._refresh_games_list()

    def _refresh_games_list(self, select_id: str = None):
        """Перестраивает список, сохраняя выбранную игру (или выбирая select_id)."""
        previous = self._current_game()
        keep_id = select_id or (previous.id if previous else None)
        self._order = self._ordered_games()
        self.games_list.blockSignals(True)
        self.games_list.clear()
        for game in self._order:
            self.games_list.addItem(QListWidgetItem(game.name))
        if not self._order and self.search_input.text().strip():
            nothing = QListWidgetItem('Ничего не найдено')
            nothing.setFlags(nothing.flags() & ~Qt.ItemIsSelectable)
            self.games_list.addItem(nothing)
        row = next((i for i, g in enumerate(self._order) if g.id == keep_id), -1)
        if row >= 0:
            self.games_list.setCurrentRow(row)
        self.games_list.blockSignals(False)
        if (self._order[row].id if row >= 0 else None) != (previous.id if previous else None):
            self._render_game_details()

    def _select_game(self, game_id: str):
        row = next((i for i, g in enumerate(self._order) if g.id == game_id), -1)
        if row < 0 and self.search_input.text() and any(g.id == game_id for g in self.store.games):
            # Например, «Показать в окне программы» из трея: сбрасываем фильтр,
            # чтобы игра точно стала видна.
            self.search_input.blockSignals(True)
            self.search_input.clear()
            self.search_input.blockSignals(False)
            self._refresh_games_list(select_id=game_id)
            row = next((i for i, g in enumerate(self._order) if g.id == game_id), -1)
        if row >= 0:
            self.games_list.setCurrentRow(row)

    def _current_game(self) -> GameProfile:
        row = self.games_list.currentRow()
        if row < 0 or row >= len(self._order):
            return None
        return self._order[row]

    def _on_game_selected(self, row):
        self._render_game_details()

    def _add_game(self):
        dlg = GameDialog(self, store=self.store)
        if dlg.exec_() == QDialog.Accepted:
            self.store.add_game(dlg.game)
            self._refresh_games_list(select_id=dlg.game.id)
            self._select_game(dlg.game.id)
            self._sync_catalogs()

    def _edit_game(self):
        game = self._current_game()
        if not game:
            QMessageBox.information(self, 'Не выбрано', 'Выберите игру в списке.')
            return
        dlg = GameDialog(self, store=self.store, game=game)
        if dlg.exec_() == QDialog.Accepted:
            self.store.update_game(dlg.game)
            self._refresh_games_list()
            self._render_game_details()
            self._sync_catalogs()

    def _scan_games(self):
        """Массовое добавление: сканируем установленные игры и добавляем выбранные."""
        dlg = ScanDialog(self, self.store)
        dlg.exec_()
        if dlg.created:
            self._refresh_games_list(select_id=dlg.created[0].id)
            self.statusBar().showMessage(f'Добавлено игр: {len(dlg.created)}', 8000)
            self._sync_catalogs()
            self._fetch_icons_in_background(list(dlg.created))

    def _fetch_icons_in_background(self, games):
        """Обложки для добавленных игр (Steam-арт по App ID/названию) — в фоне, без блокировки окна."""
        import threading

        def work():
            for g in games:
                try:
                    path = game_icons.find_icon_online(g.id, g.name, g.hint_exe_path, g.process_names)
                except Exception:
                    path = ''
                if path:
                    self.icon_ready.emit(g.id, path)
        threading.Thread(target=work, daemon=True).start()

    def _on_icon_ready(self, game_id: str, path: str):
        """Обложка пришла из фонового потока — сохраняем и перерисовываем в GUI-потоке."""
        fresh = self.store.get_game(game_id)
        if not fresh or fresh.icon_path == path:
            return
        fresh.icon_path = path
        self.store.update_game(fresh)
        current = self._current_game()
        if current and current.id == game_id:
            self._render_game_details()

    def _remove_game(self):
        game = self._current_game()
        if not game:
            QMessageBox.information(self, 'Не выбрано', 'Выберите игру в списке.')
            return
        reply = QMessageBox.question(self, 'Удалить игру?',
                                      f'Удалить игру "{game.name}" из списка? '
                                      f'Сохранения в облаке и на диске не удаляются.',
                                      QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            catalog.remember_removed(self.store, game)  # не возвращать её из облачного каталога
            self.store.remove_game(game.id)
            for old in glob.glob(os.path.join(game_icons.icons_dir(), f'{game.id}.*')):
                try:
                    os.remove(old)
                except OSError:
                    pass
            self._refresh_games_list()
            self._render_game_details()

    def _open_accounts(self):
        dlg = AccountManagerDialog(self, self.store)
        dlg.exec_()
        # названия аккаунтов/список игр могли измениться (в т.ч. «Найти игры в облаке»)
        self._refresh_games_list()
        self._render_game_details()
        self._sync_catalogs()  # новый/изменённый аккаунт: подхватить игры и опубликовать свои

    def _open_settings(self):
        dlg = SettingsDialog(self, self.store)
        dlg.exec_()
        self._update_pause_button()

    def _toggle_pause(self):
        self.store.settings.monitoring_paused = not self.store.settings.monitoring_paused
        self.store.save_settings()
        self._update_pause_button()
        self._update_tray_tooltip()
        self._render_game_details()

    def _update_tray_tooltip(self):
        """Подсказка значка в трее говорит человеческим языком, что происходит."""
        if not self.tray:
            return
        running = [g.name for g in self.store.games if g.id in self.running_game_ids]
        if running:
            text = 'Cloud Save Manager — ' + ', '.join(running[:2]) + ' запущена'
            if len(running) > 2:
                text += f' и ещё {len(running) - 2}'
        elif self.store.settings.monitoring_paused:
            text = 'Cloud Save Manager — слежение на паузе'
        else:
            text = 'Cloud Save Manager — следит за играми'
        self.tray.setToolTip(text)

    def _update_pause_button(self):
        paused = self.store.settings.monitoring_paused
        self.pause_btn.setIcon(svg_icon('play' if paused else 'pause', 16, T.TEXT))
        self.pause_btn.setToolTip('Возобновить слежение за играми' if paused else
                                  'Приостановить слежение за играми')
        self.pause_btn.setAccessibleName(self.pause_btn.toolTip())
        if hasattr(self, 'monitor_state_label'):
            self.monitor_state_label.setText('Слежение приостановлено' if paused else 'Слежение активно')
            color = T.WARN if paused else T.OK
            self.monitor_dot.setStyleSheet(f'background: {color}; border-radius: 5px;')

    # ---------- детали игры / слоты ----------
    def _clear_slots_layout(self):
        while self.slots_layout.count():
            item = self.slots_layout.takeAt(0)
            widget = item.widget()
            if widget:
                # setParent(None) отсоединяет виджет немедленно (он сразу
                # перестаёт отображаться); deleteLater() только освобождает
                # память позже. Без setParent(None) виджет ещё виден поверх
                # новых карточек, если _render_game_details() вызывается
                # повторно до того, как отработает цикл событий Qt.
                widget.setParent(None)
                widget.deleteLater()

    def _update_sync_badge(self, game):
        """Один спокойный статус вместо набора технических индикаторов."""
        if not game:
            self.sync_badge.hide()
            return
        self.sync_badge.show()
        account = self.store.get_account(game.account_id) if game.account_id else None
        if not account:
            self.sync_badge.set_status(
                'Без облака — сохранения только на этом компьютере', 'warn',
                'Добавьте облачный аккаунт: тогда сохранение не пропадёт, если сломается компьютер.')
            return
        if self.store.settings.monitoring_paused:
            self.sync_badge.set_status(
                'Слежение на паузе', 'warn',
                'Пока слежение выключено, игра не отслеживается и автосохранение не работает.')
            return
        statuses = [value for (game_id, _slot_id), value in self.pending_sync.items()
                    if game_id == game.id]
        if any(s.get('status') == 'conflict' for s in statuses):
            self.sync_badge.set_status(
                'Нужно выбрать, какую версию оставить', 'error',
                'Сохранение менялось и здесь, и в облаке. Откройте карточку слота и выберите версию.')
        elif any(s.get('status') == 'cloud_newer' for s in statuses):
            self.sync_badge.set_status(
                'В облаке есть более свежее сохранение', 'warn',
                'Нажмите «Загрузить» в карточке слота, чтобы продолжить с облачной версии.')
        elif any(s.get('status') == 'error' for s in statuses):
            self.sync_badge.set_status(
                'Облако пока недоступно — повторим позже', 'warn',
                'Проверьте интернет и настройки аккаунта. Локальное сохранение не тронуто.')
        else:
            self.sync_badge.set_status(
                'Сохранения под контролем', 'ok',
                'Когда игра закроется, программа сама сохранит прогресс в облако.')

    def _details_signature(self, game):
        """Всё, что реально влияет на рабочую область. Если ничего не изменилось,
        пересоздавать карточки и заново пересчитывать стили не нужно."""
        if game is None:
            return ('empty', bool(self.store.games), len(self.store.accounts),
                    self.search_input.text())
        account = self.store.get_account(game.account_id) if game.account_id else None
        sync_state = tuple(sorted(
            (key[1], str(value.get('status')), str(value.get('message')))
            for key, value in self.pending_sync.items() if key[0] == game.id))
        return (
            game.id, game.name, game.icon_path, game.launch_command,
            game.auto_upload_on_exit, game.check_cloud_on_start,
            tuple(game.process_names), game.playtime_seconds, game.last_played,
            self.store.settings.monitoring_paused,
            account.name if account else '',
            tuple((s.id, s.label, s.path, s.is_directory, s.remote_name,
                   s.last_upload, s.last_download, s.exclude_patterns) for s in game.slots),
            sync_state,
        )

    def _render_game_details(self, force: bool = False):
        game = self._current_game()
        signature = self._details_signature(game)
        if not force and signature == getattr(self, '_details_signature_cache', None):
            return  # состояние не менялось — сохраняем CPU и не дёргаем QSS
        self._details_signature_cache = signature
        self._clear_slots_layout()
        if not game:
            def add_local():
                dlg = AccountDialog(self, preselect_type='local')
                if dlg.exec_() == QDialog.Accepted and dlg.result_account:
                    self.store.add_account(dlg.result_account, secret=dlg.result_secret or '')
                    self._refresh_games_list()
                    self._render_game_details(force=True)

            if not self.store.games:
                heading = 'Добавьте первую игру'
                hint = ('Программа сама найдёт запущенную игру и путь к сохранению. '
                        'Также можно выбрать готовый пресет Dark Souls III / Elden Ring.')
                actions = [('Добавить игру (Ctrl+N)', self._add_game)]
            elif not self.store.accounts:
                heading = 'Подключите облачный аккаунт'
                hint = ('Проще всего — папка в Dropbox, Google Диске или OneDrive: '
                        'никаких токенов и паролей вводить не нужно.')
                actions = [
                    ('Использовать папку на диске (без пароля)', add_local),
                    ('Другие варианты — GitHub, Яндекс.Диск (Ctrl+Shift+A)', self._open_accounts),
                ]
            elif self.search_input.text().strip():
                heading = 'Игра не найдена'
                hint = 'Измените запрос в поле поиска слева или очистите его.'
                actions = [('Очистить поиск', lambda: self.search_input.clear())]
            else:
                heading = 'Выберите игру слева'
                hint = 'Выберите игру в списке, чтобы увидеть слоты сохранения и кнопки синхронизации.'
                actions = [('Добавить игру (Ctrl+N)', self._add_game)]

            self.game_title_label.setText(heading)
            self.game_title_label.setFont(fonts.heading_font(heading, T.FS_GAME_TITLE))
            self.game_cover.hide()
            self.play_btn.hide()
            self.play_cloud_btn.hide()
            self.sync_badge.hide()
            self.meta_primary.setText('')

            card = GlassFrame()
            card.setObjectName('card')
            inner = QVBoxLayout(card)
            inner.setContentsMargins(T.S5, T.S5, T.S5, T.S5)
            inner.setSpacing(T.S3)
            hint_label = QLabel(hint)
            hint_label.setWordWrap(True)
            hint_label.setProperty('muted', True)
            inner.addWidget(hint_label)
            for index, (action_text, action) in enumerate(actions):
                action_btn = QPushButton(action_text)
                if index == 0:
                    _primary(action_btn)
                action_btn.setFixedHeight(T.BTN_H)
                action_btn.setCursor(Qt.PointingHandCursor)
                action_btn.clicked.connect(action)
                inner.addWidget(action_btn, 0, Qt.AlignLeft)
            self.slots_layout.addWidget(card)
            self.slots_layout.addStretch()
            self._last_rendered_game = None
            return

        self.game_title_label.setText(game.name)
        self.game_title_label.setFont(fonts.heading_font(game.name, T.FS_GAME_TITLE))
        self.game_cover.set_cover(getattr(game, 'icon_path', ''), self.game_cover._size)
        self.game_cover.show()
        target = self._launch_target(game)
        self.play_btn.show()
        self.play_btn.setEnabled(bool(target))
        self.play_btn.setToolTip(
            'Проверить облако и запустить игру (если там версия новее — она скачается до запуска)'
            if target else 'Укажите запуск игры: «Изменить» → поле «Запуск игры»')
        self.play_cloud_btn.setVisible(bool(game.account_id and any(s.path for s in game.slots)))
        self.play_cloud_btn.setEnabled(bool(target))

        account = self.store.get_account(game.account_id) if game.account_id else None
        paused = self.store.settings.monitoring_paused
        attention = (account is None) or paused
        parts = [account.name if account else 'Аккаунт не выбран',
                 'Авто-выгрузка ' + ('вкл' if game.auto_upload_on_exit else 'выкл')]
        if game.process_names:
            parts.append(', '.join(game.process_names))
        if game.playtime_seconds >= 60:
            hours, minutes = divmod(game.playtime_seconds // 60, 60)
            parts.append(f'играл {hours} ч {minutes:02d} мин' if hours else f'играл {minutes} мин')
        if game.last_played:
            parts.append('последний запуск ' + _fmt_ts(game.last_played).split(',')[0])
        if paused:
            parts.append('слежение приостановлено')
        self.meta_primary.setStyleSheet(
            f'color: {T.WARN if attention else T.TEXT_MUTED}; font-size: {T.FS_SMALL}px; background: transparent;')
        self.meta_primary.setText('  ·  '.join(parts))
        self.meta_primary.setToolTip(
            'Проверка при запуске: ' + ('вкл' if game.check_cloud_on_start else 'выкл') +
            '\nПроцесс: ' + (', '.join(game.process_names) or 'не указан'))
        self._update_sync_badge(game)

        if not game.slots:
            empty = QLabel('У этой игры пока нет слотов сохранения. Нажмите «Изменить», чтобы добавить.')
            empty.setProperty('muted', True)
            empty.setWordWrap(True)
            self.slots_layout.addWidget(empty)
        animate = self._last_rendered_game != game.id
        self._last_rendered_game = game.id
        for i, slot in enumerate(game.slots):
            card = self._build_slot_card(game, slot)
            self.slots_layout.addWidget(card)
            if animate:
                motion.fade_in(card, delay=min(i, 4) * 40)
        if animate:
            motion.fade_in(self.game_cover)
            motion.fade_in(self.game_title_label, motion.DUR_FAST)
        # Не копим состояния удалённых слотов и игр между перерисовками.
        alive = {s.id for s in game.slots}
        self._last_tags = {k: v for k, v in self._last_tags.items() if k in alive}
        self.slots_layout.addStretch()

    def _slot_status_tag(self, game: GameProfile, slot):
        """Компактный индикатор реального состояния слота. Статус облака
        известен только после проверки (при запуске игры, после операций или по
        кнопке «Проверить облако»), иначе показываем только локальные факты."""
        if not slot.path:
            return Tag('Путь не указан', 'warn', 'warning', 'Укажите путь к сохранению в настройках игры')
        if not os.path.exists(slot.path):
            return Tag('Нет локального файла', 'warn', 'file_x', 'Файл или папка не найдены:\n' + slot.path)
        status = self.pending_sync.get((game.id, slot.id)) or {}
        kind = status.get('status')
        if kind == 'cloud_newer':
            return Tag('Облако новее', 'warn', 'download', STATUS_TEXT['cloud_newer'])
        if kind == 'conflict':
            return Tag('Конфликт версий', 'error', 'warning', STATUS_TEXT['conflict'])
        if kind == 'error':
            return Tag('Облако недоступно', 'error', 'cloud_off', str(status.get('message') or 'Ошибка облака'))
        if kind == 'empty_local':
            return Tag('Сохранение пустое', 'warn', 'warning', 'Локальное сохранение пустое — автовыгрузка пропущена, чтобы не затереть облако')
        if kind == 'no_account':
            return Tag('Нет аккаунта', 'warn', 'user', 'Выберите облачный аккаунт в настройках игры')
        if kind == 'no_cloud_data':
            return Tag('В облаке пусто', 'neutral', 'cloud', 'В облаке пока нет сохранения для этого слота')
        if _modified_since_sync(slot):
            return Tag('Изменено после выгрузки', 'info', 'edit', 'Локальный файл менялся после последней синхронизации')
        if kind == 'local_newer':
            return Tag('Локальная новее', 'info', 'upload', 'Локальная версия новее облачной')
        if kind == 'up_to_date':
            return Tag('Синхронизировано', 'ok', 'check', 'Локальная и облачная версии совпадают')
        if not slot.last_upload and not slot.last_download:
            return Tag('Ещё не выгружалось', 'neutral', 'cloud', '')
        return None

    def _check_cloud_status(self, game: GameProfile, slot):
        """Реальная проверка актуальности: сравнение локальной и облачной версий."""
        result = {}

        def job(progress):
            progress(10, 'Проверка облака...')
            result['status'] = sync_manager.check_slot_sync_status(self.store, game, slot)
            progress(100, 'Готово')
            st = result['status']
            return st.get('status') != 'error', str(st.get('message') or 'Проверка завершена.')

        run_transfer(self, f'Проверка — {game.name}: {slot.label}', job)
        if result.get('status'):
            self.pending_sync[(game.id, slot.id)] = result['status']
        self._render_game_details()

    def _build_slot_card(self, game: GameProfile, slot) -> QFrame:
        card = GlassFrame()
        card.setObjectName('card')
        lay = QVBoxLayout(card)
        lay.setContentsMargins(T.S5, T.S4, T.S5, T.S5 - 2)
        lay.setSpacing(T.S2 + 2)

        status = self.pending_sync.get((game.id, slot.id)) or {}
        recommended_download = status.get('status') in ('cloud_newer', 'conflict')

        # 1: название + индикатор состояния
        top = QHBoxLayout()
        top.setSpacing(T.S2)
        title = ElidedLabel(slot.label, Qt.ElideRight)
        title.setFont(fonts.heading_font(slot.label, 14))
        top.addWidget(title, 1)
        tag = self._slot_status_tag(game, slot)
        if tag:
            # Длинный статус («Изменено после выгрузки») не должен вытеснять
            # название слота и кнопки за пределы карточки.
            tag.set_max_width(max(140, min(260, self.width() // 4)))
            top.addWidget(tag)
            # состояние слота изменилось после операции — индикатор появляется плавно
            if self._last_tags.get(slot.id) not in (None, tag.text_value):
                motion.fade_in(tag, motion.DUR_FAST)
        self._last_tags[slot.id] = tag.text_value if tag else None
        lay.addLayout(top)

        # 2: путь (клик — копировать) + действия
        path_row = QHBoxLayout()
        path_row.setSpacing(0)
        path_label = ElidedLabel(slot.path or 'Путь не указан', Qt.ElideMiddle, mono=True)
        path_label.setProperty('muted', True)
        if slot.path:
            path_label.setToolTip(slot.path + '\n\nНажмите, чтобы скопировать путь')
            path_label.setCursor(Qt.PointingHandCursor)
            path_label.mousePressEvent = lambda _e, p=slot.path: self._copy_path(p)
        path_row.addWidget(path_label, 1)
        if slot.path:
            folder_btn = _icon_button('folder', 'Открыть папку сохранения')
            folder_btn.clicked.connect(lambda _, s=slot: os_utils.open_in_file_manager(s.path))
            path_row.addWidget(folder_btn)
        check_btn = _icon_button('refresh', 'Проверить состояние в облаке')
        check_btn.clicked.connect(lambda _, g=game, s=slot: self._check_cloud_status(g, s))
        path_row.addWidget(check_btn)
        snapshot_btn = _icon_button('bookmark', 'Быстрый снимок прямо сейчас (перед боссом)')
        snapshot_btn.clicked.connect(lambda _, g=game, s=slot: self._quick_snapshot(g, s))
        path_row.addWidget(snapshot_btn)
        backups_btn = _icon_button('history', 'Резервные копии и восстановление')
        backups_btn.clicked.connect(lambda _, g=game, s=slot: self._open_backups(g, s))
        path_row.addWidget(backups_btn)
        lay.addLayout(path_row)

        # 3: время выгрузки / загрузки — одной спокойной строкой
        info = sync_manager.local_info(slot) if slot.path else None
        size_part = (f' &nbsp;·&nbsp; {_fmt_size(info["size"])}'
                     if info and info.get('size') is not None else '')
        times = QLabel(
            f'<span style="color:{T.TEXT_ON_CARD_MUTED};">Выгружено</span> {_fmt_ago(slot.last_upload)}'
            f' &nbsp;·&nbsp; '
            f'<span style="color:{T.TEXT_ON_CARD_MUTED};">Загружено</span> {_fmt_ago(slot.last_download)}'
            f'{size_part}')
        times.setTextFormat(Qt.RichText)
        times.setWordWrap(True)
        times.setStyleSheet(f'font-size: {T.FS_SMALL}px;')
        times.setToolTip(f'Выгружено: {_fmt_ts(slot.last_upload)}\n'
                         f'Загружено: {_fmt_ts(slot.last_download)}')
        lay.addSpacing(2)
        lay.addWidget(times)
        lay.addSpacing(T.S2)

        # 4: две равные по размеру кнопки. Подписи короче, чем действия в
        # подсказках: длинный текст не помещался в карточку на узком окне и
        # при масштабе 125–150 %, а иконка и так показывает направление.
        btn_row = QHBoxLayout()
        btn_row.setSpacing(T.S2 + 2)
        upload_btn = QPushButton('Выгрузить')
        download_btn = QPushButton('Загрузить')
        upload_btn.setProperty('cls', 'secondary' if recommended_download else 'primary')
        download_btn.setProperty('cls', 'primary' if recommended_download else 'secondary')
        upload_btn.setIcon(svg_icon('upload', 18, T.TEXT if recommended_download else T.TEXT_ON_SAGE))
        download_btn.setIcon(svg_icon('download', 18, T.TEXT_ON_SAGE if recommended_download else T.TEXT))
        for b in (upload_btn, download_btn):
            b.setIconSize(QSize(18, 18))
            b.setFixedHeight(T.BTN_H)
            b.setCursor(Qt.PointingHandCursor)
        upload_btn.setToolTip('Выгрузить в облако — отправить локальное сохранение в облако')
        download_btn.setToolTip('Загрузить из облака — заменить локальное сохранение версией '
                                'из облака (с резервной копией)')
        upload_btn.clicked.connect(lambda _, g=game, s=slot: self._manual_upload(g, s))
        download_btn.clicked.connect(lambda _, g=game, s=slot: self._manual_download(g, s))
        can_upload = bool(slot.path) and os.path.exists(slot.path)
        upload_btn.setEnabled(can_upload)
        if not can_upload:
            upload_btn.setToolTip('Нечего выгружать: локальное сохранение не найдено')
        btn_row.addWidget(upload_btn, 1)
        btn_row.addWidget(download_btn, 1)
        lay.addLayout(btn_row)
        return card

    @staticmethod
    def _launch_target(game: GameProfile) -> str:
        if game.launch_command:
            return game.launch_command
        return game.hint_exe_path if game.hint_exe_path and os.path.isfile(game.hint_exe_path) else ''

    def _play_game(self, game: GameProfile = None):
        """Запуск игры: сначала сверка с облаком (безопасно скачиваем более новую версию
        ДО старта игры), конфликты решает пользователь, потом запускаем."""
        game = game if isinstance(game, GameProfile) else self._current_game()
        if not game:
            return
        target = self._launch_target(game)
        if not target:
            return
        if game.account_id and any(s.path for s in game.slots):
            result = {}

            def job(progress):
                if self.store.settings.play_lock_enabled:
                    result['other'] = sync_manager.playing_elsewhere(self.store, game)
                result['r'] = sync_manager.prelaunch_sync(self.store, game, progress)
                return True, 'Готово'

            # 300 мс — меньше времени отображения самого окна: результат проверки
            # облака был нечитаем, а сразу открывался диалог конфликта.
            ok, message = run_transfer(self, f'Подготовка к запуску — {game.name}', job, auto_close_ms=2000)
            res = result.get('r')
            if res is None:
                return  # отменено — игру не запускаем
            other = result.get('other')
            if other:
                since = other['since'][11:16] if len(other['since']) >= 16 else ''
                reply = QMessageBox.warning(
                    self, 'Игра запущена на другом ПК',
                    f'Игра уже идёт на компьютере «{other["device"]}»' + (f' (с {since})' if since else '') +
                    '.\n\nЕсли играть и здесь, сохранения на двух ПК разойдутся и появится конфликт. '
                    'Запустить всё равно?', QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if reply != QMessageBox.Yes:
                    return
            for slot, _msg in res['downloaded']:
                self.pending_sync[(game.id, slot.id)] = {'status': 'up_to_date'}
            for slot, status in res['conflicts']:
                choice = ConflictDialog.ask(self, game, slot, status)
                if choice == 'download':
                    self._manual_download(game, slot, confirmed=True)
                elif choice == 'upload':
                    ok2, msg2 = run_transfer(
                        self, f'Выгрузка — {game.name}: {slot.label}',
                        lambda progress, s=slot: sync_manager.upload_slot(self.store, game, s, progress=progress))
                    self._after_transfer(game, slot, ok2, msg2, 'выгружено в облако')
                else:
                    return  # пользователь отказался выбирать — не запускаем
            if res['errors']:
                details = '\n'.join(f'• {s.label}: {m}' for s, m in res['errors'][:4])
                reply = QMessageBox.question(
                    self, 'Облако не проверено',
                    f'Не удалось сверить сохранения с облаком:\n{details}\n\nЗапустить игру всё равно? '
                    f'(Более новое облачное сохранение при этом не будет затёрто: автовыгрузка '
                    f'после игры снова сверится с облаком.)',
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
                if reply != QMessageBox.Yes:
                    return
            self._render_game_details()
            if res['downloaded']:
                self.statusBar().showMessage(f'{game.name}: загружена более новая версия из облака', 6000)
        ok, message = os_utils.launch_target(target)
        if ok:
            self.statusBar().showMessage(f'{game.name}: {message}', 5000)
        else:
            QMessageBox.warning(self, 'Не удалось запустить игру', message)

    def _play_from_cloud(self):
        """«Продолжить на этом ПК»: скачать облачные сохранения (с резервной
        копией локальных) и сразу запустить игру — без ручного обхода слотов."""
        game = self._current_game()
        if not game or not self._launch_target(game):
            return
        slots = [s for s in game.slots if s.path]
        if not game.account_id or not slots:
            QMessageBox.information(self, 'Нет облачной копии',
                                    'У игры не выбран облачный аккаунт или не указан путь к сохранению.')
            return
        reply = QMessageBox.question(
            self, 'Играть с облачной копии',
            'Локальные сохранения будут заменены версиями из облака (копии обязательно '
            'останутся в резервных). После загрузки игра запустится.\n\nПродолжить?',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        for slot in slots:
            ok, message = run_transfer(
                self, f'Загрузка — {game.name}: {slot.label}',
                lambda progress, s=slot: sync_manager.download_slot(
                    self.store, game, s, progress=progress))
            if not ok:
                QMessageBox.warning(self, 'Не удалось загрузить сохранение',
                                    f'{slot.label}: {message}\n\nИгра не запущена — локальные файлы '
                                    f'могут остаться частично заменёнными, проверьте резервные копии.')
                self._render_game_details()
                return
            self.pending_sync[(game.id, slot.id)] = {'status': 'up_to_date'}
        self._render_game_details()
        self.statusBar().showMessage(f'{game.name}: облачная версия загружена, запускаем игру', 6000)
        self._play_game(game)

    def _copy_path(self, path: str):
        QApplication.clipboard().setText(path)
        self.statusBar().showMessage('Путь скопирован в буфер обмена', 3000)

    # ---------- ручная синхронизация ----------
    def _confirm_overwrite_cloud(self, game: GameProfile, slot) -> bool:
        """Если облако новее/конфликт — показываем сравнение версий. True — можно
        выгружать (выбрано «оставить локальную»). Если выбрана облачная версия,
        загрузка запускается здесь же, а выгрузка отменяется."""
        status = self.pending_sync.get((game.id, slot.id))
        if not status or status.get('status') not in ('cloud_newer', 'conflict'):
            return True
        choice = ConflictDialog.ask(self, game, slot, status)
        if choice == 'download':
            self._manual_download(game, slot, confirmed=True)
        return choice == 'upload'

    def _manual_upload(self, game: GameProfile, slot):
        info = sync_manager.local_info(slot, use_cache=False)
        if info and info.get('size') == 0:
            reply = QMessageBox.warning(
                self, 'Сохранение пустое',
                'Локальное сохранение пустое — возможно, игра его повредила. Выгрузка затрёт им '
                'облачную копию (предыдущая версия сохранится в облаке рядом).\n\nВыгрузить всё равно?',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        if not self._confirm_overwrite_cloud(game, slot):
            return
        ok, message = run_transfer(
            self, f'Выгрузка — {game.name}: {slot.label}',
            lambda progress: sync_manager.upload_slot(self.store, game, slot, silent=False,
                                                      progress=progress))
        self._after_transfer(game, slot, ok, message, 'выгружено в облако')

    def _manual_download(self, game: GameProfile, slot, confirmed: bool = False):
        status = self.pending_sync.get((game.id, slot.id)) or {}
        if not confirmed and status.get('status') == 'conflict':
            choice = ConflictDialog.ask(self, game, slot, status)
            if choice == 'upload':
                ok, message = run_transfer(
                    self, f'Выгрузка — {game.name}: {slot.label}',
                    lambda progress: sync_manager.upload_slot(self.store, game, slot, silent=False,
                                                              progress=progress))
                self._after_transfer(game, slot, ok, message, 'выгружено в облако')
                return
            if choice != 'download':
                return
        elif not confirmed and slot.path and os.path.exists(slot.path):
            reply = QMessageBox.question(
                self, 'Подтверждение',
                f'Загрузка ЗАМЕНИТ локальное сохранение «{slot.label}» версией из облака.\n\n'
                f'Всё, что вы сыграли после последней синхронизации, из игры пропадёт. '
                f'Копия текущего файла сохранится в резервных копиях (кнопка с часами '
                f'в карточке), оттуда её можно вернуть.\n\nПродолжить?',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No:
                return
        ok, message = run_transfer(
            self, f'Загрузка — {game.name}: {slot.label}',
            lambda progress: sync_manager.download_slot(self.store, game, slot, progress=progress))
        self._after_transfer(game, slot, ok, message, 'загружено из облака')

    def _after_transfer(self, game: GameProfile, slot, ok: bool, message: str, done_text: str):
        if ok:
            self.pending_sync[(game.id, slot.id)] = {'status': 'up_to_date'}
            self.statusBar().showMessage(f'{game.name}: {slot.label} — {done_text}')
        else:
            self.pending_sync[(game.id, slot.id)] = {'status': 'error', 'message': message}
        self._render_game_details()

    def _quick_snapshot(self, game: GameProfile, slot):
        """Снимок в один клик: «сохранился перед боссом» — без диалога и без
        переключения из игры. Доступен и в карточке слота, и в меню трея."""
        if not slot.path or not os.path.exists(slot.path):
            QMessageBox.information(self, 'Нет сохранения',
                                    'Локальный файл или папка сохранения не найдены.')
            return
        import datetime as _dt
        label = 'Быстрый ' + _dt.datetime.now().strftime('%d.%m %H:%M')
        try:
            path = backup.make_snapshot(game.id, slot.id, slot.path, slot.is_directory, label=label)
        except OSError as e:
            QMessageBox.warning(self, 'Не удалось сохранить снимок', str(e))
            return
        if path:
            self.statusBar().showMessage(f'{game.name}: снимок «{slot.label}» сохранён '
                                         f'({label}) — найдите его в резервных копиях слота', 5000)
        else:
            QMessageBox.warning(self, 'Не удалось сохранить снимок',
                                'Проверьте путь к сохранению и права доступа к папке приложения.')

    def _open_backups(self, game: GameProfile, slot):
        dlg = BackupsDialog(self, self.store, game, slot)
        dlg.exec_()
        self._render_game_details()

    # ---------- отслеживание процессов ----------
    def _on_status_changed(self, text: str):
        # скрытое окно (трей) не перерисовываем ради строки статуса — покажем при открытии
        if self.isVisible():
            self.statusBar().showMessage(text)
        else:
            self._pending_status = text

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, '_shown_once', False):
            self._shown_once = True
            motion.fade_window(self)
        if self._eco_active:
            self._eco_active = False
            power.leave_background()
        if self._pending_status:
            self.statusBar().showMessage(self._pending_status)
            self._pending_status = ''

    def hideEvent(self, event):
        super().hideEvent(event)
        if self.store.settings.eco_mode_in_tray:
            QTimer.singleShot(1500, self._enter_eco)

    def _enter_eco(self):
        """Окно скрыто в трее: режим эффективности + возврат памяти системе."""
        if not self.isVisible() and not self._eco_active:
            self._eco_active = True
            power.enter_background()

    def _on_game_started(self, game_id: str):
        self.running_game_ids.add(game_id)
        self._update_tray_tooltip()
        game = self.store.get_game(game_id)
        if game:
            self.statusBar().showMessage(f'{game.name} запущена — отслеживание активно')

    def _on_sync_check_result(self, game_id: str, slot_id: str, status: dict):
        self.pending_sync[(game_id, slot_id)] = status
        game = self.store.get_game(game_id)
        current = self._current_game()
        if current and current.id == game_id:
            self._render_game_details()
        if game and self.tray and self.store.settings.tray_notifications:
            if status.get('status') == 'cloud_newer':
                self.tray.showMessage(
                    f'{game.name}: доступно новое сохранение',
                    'В облаке найдена более новая версия сохранения. Откройте '
                    'программу, чтобы скачать её.', QSystemTrayIcon.Information, 6000)
            elif status.get('status') == 'conflict':
                self.tray.showMessage(
                    f'{game.name}: конфликт сохранений',
                    'Сохранение изменилось и локально, и в облаке — откройте '
                    'программу, чтобы выбрать, какую версию оставить.',
                    QSystemTrayIcon.Warning, 8000)

    def _on_game_exited(self, game_id: str):
        self.running_game_ids.discard(game_id)
        self._update_tray_tooltip()
        game = self.store.get_game(game_id)
        if game:
            self.statusBar().showMessage(f'{game.name} закрыта.')

    def _sync_catalogs(self):
        """Каталог игр в облаке: подхватить игры других ПК и опубликовать свои."""
        if not self.store.settings.catalog_sync or not self.store.accounts:
            return
        if self._catalog_worker and self._catalog_worker.isRunning():
            self._catalog_rerun = True  # после текущего прогона повторим — данные уже изменились
            return
        self._catalog_worker = CatalogWorker(self.store, self)
        self._catalog_worker.finished_sync.connect(self._on_catalog_synced)
        self._catalog_worker.start()

    def _on_catalog_synced(self, added: list, errors: list):
        if added:
            self._refresh_games_list()
            if self._current_game() is None and self._order:
                self.games_list.setCurrentRow(0)
            text = 'Из облака добавлены игры: ' + ', '.join(added[:5]) + (f' и ещё {len(added) - 5}' if len(added) > 5 else '')
            self.statusBar().showMessage(text, 10000)
            if self.tray and self.store.settings.tray_notifications:
                self.tray.showMessage('Cloud Save Manager', text, QSystemTrayIcon.Information, 6000)
        if errors:
            self.statusBar().showMessage('Каталог игр: ' + errors[0], 8000)
        if self._catalog_rerun:
            self._catalog_rerun = False
            self._sync_catalogs()

    def _refresh_manifest_in_background(self):
        """Раз в 30 дней тихо обновляет базу путей сохранений (поток-демон: при выходе
        из программы не мешает, индекс записывается атомарно)."""
        import threading
        from app import manifest
        if manifest.index_is_fresh():
            return
        if any(self.monitor._running_state.values()):  # идёт игра — не отнимаем у неё процессор
            QTimer.singleShot(600000, self._refresh_manifest_in_background)
            return
        threading.Thread(target=manifest.update_index, daemon=True).start()

    def _on_play_conflict(self, game_id: str, device: str, since: str):
        game = self.store.get_game(game_id)
        if not game:
            return
        text = f'{game.name}: игра уже запущена на компьютере «{device}»' + (f' (с {since[11:16]})' if len(since) >= 16 else '') + \
               ' — сохранения могут разойтись. Закройте игру на одном из ПК.'
        self.statusBar().showMessage(text, 15000)
        if self.tray:
            self.tray.showMessage('Игра запущена на двух ПК', text, QSystemTrayIcon.Warning, 10000)

    def _on_periodic_result(self, game_id: str, results: list):
        """Выгрузка во время игры: без всплывающих уведомлений, только состояние
        карточек и строка статуса (ошибки видны в индикаторе слота)."""
        game = self.store.get_game(game_id)
        if not game:
            return
        # Ключ — id слота: одинаковые названия слотов не должны перемешивать
        # результаты выгрузки между собой.
        by_id = {slot_id: (ok, msg) for slot_id, ok, msg in results}
        for slot in game.slots:
            status = self.pending_sync.get((game.id, slot.id))
            if status and status.get('status') in ('cloud_newer', 'conflict'):
                continue
            res = by_id.get(slot.id)
            if res:
                self.pending_sync[(game.id, slot.id)] = ({'status': 'up_to_date'} if res[0] else
                                                         {'status': 'error', 'message': res[1]})
        current = self._current_game()
        if current and current.id == game_id:
            self._render_game_details()
        if all(ok for ok, _ in by_id.values()):
            self.statusBar().showMessage(f'{game.name}: сохранение выгружено во время игры', 5000)
        else:
            self.statusBar().showMessage(f'{game.name}: выгрузка во время игры не удалась — см. индикатор слота', 8000)

    def _on_upload_result(self, game_id: str, results: list):
        game = self.store.get_game(game_id)
        if not game:
            return
        log_action('auto_upload', 'trigger', game.name)
        by_id = {slot_id: (ok, msg) for slot_id, ok, msg in results}
        for slot in game.slots:
            # Предупреждение о новой версии в облаке остаётся, пока слот не
            # синхронизирован; ошибка выгрузки показывается в карточке.
            status = self.pending_sync.get((game.id, slot.id))
            if status and status.get('status') in ('cloud_newer', 'conflict'):
                continue
            res = by_id.get(slot.id)
            if res and not res[0]:
                self.pending_sync[(game.id, slot.id)] = {'status': 'error', 'message': res[1]}
            elif res and res[0]:
                self.pending_sync[(game.id, slot.id)] = {'status': 'up_to_date'}
            else:
                self.pending_sync.pop((game.id, slot.id), None)
        current = self._current_game()
        if current and current.id == game_id:
            self._render_game_details()
        all_ok = all(ok for _slot_id, ok, _msg in results)
        labels = {s.id: s.label for s in game.slots}
        summary = '; '.join(f'{labels.get(slot_id, slot_id)}: {"ок" if ok else msg}'
                            for slot_id, ok, msg in results)
        if self.tray and self.store.settings.tray_notifications:
            self.tray.showMessage(
                f'{game.name}: ' + ('сохранение выгружено' if all_ok else 'автовыгрузка не выполнена'),
                summary, QSystemTrayIcon.Information if all_ok else QSystemTrayIcon.Warning, 6000)
        self.statusBar().showMessage(f'{game.name}: автовыгрузка — {summary}')

    # ---------- справка ----------
    def _show_help(self):
        text = (
            'КАК ПОЛЬЗОВАТЬСЯ — КОРОТКО\n'
            '═══════════════════════════\n\n'
            '1. Куда будем сохранять?\n'
            '   Нажмите «Аккаунты». Самый простой вариант — «Папка на диске»:\n'
            '   укажите папку внутри Dropbox, Google Диска или OneDrive.\n'
            '   Никаких токенов и паролей вводить не нужно.\n\n'
            '2. Какая игра?\n'
            '   Нажмите «+», запустите игру и выберите её из списка.\n'
            '   Программа сама найдёт файл сохранения. Если не нашла —\n'
            '   нажмите «Найти сохранение автоматически» ещё раз или укажите путь руками.\n\n'
            '3. Просто играйте.\n'
            '   После закрытия игры сохранение само появится в облаке.\n'
            '   Если вы играли на другом компьютере, при запуске программа\n'
            '   предложит скачать свежую версию. Кнопка «Играть с облачной копии»\n'
            '   делает это одной командой.\n\n'
            '4. Если что-то не так.\n'
            '   Кнопка с часами в карточке — резервные копии и быстрые снимки.\n'
            '   Оттуда можно вернуть любую версию за пару кликов.\n\n'
            'ЧАСТЫЕ ВОПРОСЫ\n'
            '═══════════════════════════\n\n'
            '• Я закрыл окно, а программа осталась в трее. Это нормально?\n'
            '  Да — она продолжает следить за играми. Щёлкните значок в трее,\n'
            '  чтобы открыть окно, или выберите «Выход» в его меню.\n\n'
            '• Что значит «нужно выбрать версию»?\n'
            '  Сохранение менялось и здесь, и в облаке. Программа не угадывает:\n'
            '  она покажет дату, размер и устройство каждой версии — вы решаете.\n'
            '  Старая версия всё равно останется в резервных копиях.\n\n'
            '• Можно ли сохраниться прямо во время игры, не открывая окно?\n'
            '  Да: правой кнопкой по значку в трее → название игры → «Выгрузить».\n'
            '  Там же есть «Быстрый снимок» — удобно перед боссом.\n\n'
            '• Почему нет автосохранения по таймеру?\n'
            '  Частые выгрузки могут привести к ограничениям облачных сервисов.\n'
            '  Мы сохраняем один раз — когда игра закрылась, и по вашей команде.\n'
        )
        # Обычный QMessageBox с таким объёмом текста не помещается на экран
        # ноутбука: у него нет прокрутки, и кнопка OK оказывается вне экрана.
        dlg = QDialog(self)
        dlg.setWindowTitle('Инструкция')
        dlg.setMinimumSize(560, 420)
        view = QTextBrowser()
        view.setPlainText(text)
        view.setOpenExternalLinks(True)
        lay = QVBoxLayout(dlg)
        lay.addWidget(view, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dlg.reject)
        buttons.button(QDialogButtonBox.Close).clicked.connect(dlg.accept)
        lay.addWidget(buttons)
        dlg.exec_()

    def closeEvent(self, event):
        if self.tray and self.store.settings.minimize_to_tray and not self._force_quit:
            event.ignore()
            self.hide()
            if self.store.settings.tray_notifications:
                self.tray.showMessage('Cloud Save Manager',
                                       'Свёрнуто в трей. Программа продолжает следить за играми.',
                                       QSystemTrayIcon.Information, 3000)
            return
        self.monitor.stop()
        # Если идёт выгрузка после закрытия игры — даём ей закончиться, иначе
        # поток будет убит посреди записи.
        self.monitor.wait(20000)
        # Фоновая синхронизация каталога тоже поток: без ожидания Qt роняет процесс
        # («QThread: Destroyed while thread is still running»), если выйти во время неё.
        worker = self._catalog_worker
        if worker is not None and worker.isRunning():
            worker.wait(20000)
        event.accept()
        # setQuitOnLastWindowClosed(False) — без явного quit() процесс остался бы жить в трее
        QApplication.quit()
