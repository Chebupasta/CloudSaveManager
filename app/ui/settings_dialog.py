"""
Диалог настроек приложения: поведение трея, автозапуск вместе с системой
и кнопка немедленной выгрузки всех сохранений (на всякий случай, вручную).
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from app import autostart, secrets_store, sync_manager
from app.store import ConfigStore
from app import manifest
from app.ui import motion
from app.ui.log_dialog import LogDialog
from app.ui import tokens as T
from app.ui.widgets import screen_fit
from app.ui.svg_icons import svg_icon
from app.ui.theme import WARNING
from app.ui.transfer_dialog import run_transfer


class _CheckRow(QWidget):
    """Чекбокс с многострочной подписью.

    У QCheckBox нет переноса текста: длинная подпись вылезала за границы
    диалога и обрезалась на узком окне / при масштабе 125–150 %. Здесь
    чекбокс и QLabel с wordWrap лежат в одной строке; клик по подписи
    переключает чекбокс."""

    def __init__(self, text: str, checked: bool = False, tip: str = ''):
        super().__init__()
        self.box = QCheckBox()
        self.box.setChecked(bool(checked))
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        if tip:
            self.setToolTip(tip)
            self.label.setToolTip(tip)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(self.box, 0, Qt.AlignTop)
        lay.addWidget(self.label, 1)
        self.label.mousePressEvent = lambda _event: self.box.toggle()
        # Сохраняем signals/методы чекбокса, чтобы код диалога не менялся.
        self.toggled = self.box.toggled

    def isChecked(self) -> bool:
        return self.box.isChecked()

    def setChecked(self, value: bool):
        self.box.setChecked(bool(value))

    def setEnabled(self, value: bool):
        self.box.setEnabled(bool(value))
        self.label.setEnabled(bool(value))


def _scrollable(page: QWidget) -> QScrollArea:
    """Вкладка с прокруткой: на низком логическом экране содержимое не сжимается."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    area.setWidget(page)
    return area


class SettingsDialog(QDialog):
    def __init__(self, parent, store: ConfigStore):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle('Настройки')
        self.setMinimumSize(*screen_fit(560, 520))
        self.resize(*screen_fit(620, 600))

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        st = store.settings

        def check(text, value, tip=''):
            return _CheckRow(text, value, tip)

        def spin(lo, hi, value, suffix='', tip=''):
            sp = QSpinBox()
            sp.setRange(lo, hi)
            sp.setValue(int(value))
            sp.setSuffix(suffix)
            sp.setMinimumWidth(110)
            if tip:
                sp.setToolTip(tip)
            return sp

        # ---------- Общие ----------
        general = QWidget()
        g = QVBoxLayout(general)
        g.addWidget(QLabel('<b>Трей</b>'))
        self.minimize_check = check('Сворачивать в трей при закрытии окна (программа продолжит '
                                    'следить за играми в фоне)', st.minimize_to_tray)
        self.notifications_check = check('Показывать уведомления трея (о выгрузке и найденных '
                                         'обновлениях)', st.tray_notifications)
        self.confirm_download_check = check('Спрашивать подтверждение перед быстрой загрузкой из трея '
                                            '(резервная копия создаётся в любом случае)', st.confirm_tray_download)
        for w in (self.minimize_check, self.notifications_check, self.confirm_download_check):
            g.addWidget(w)
        g.addWidget(QLabel('<b>Игры</b>'))
        self.play_lock_check = check('Предупреждать, если игра уже запущена на другом компьютере '
                                     '(отметка в облаке)', st.play_lock_enabled)
        self.sort_recent_check = check('Сортировать список: недавно запущенные сверху', st.sort_recent)
        g.addWidget(self.play_lock_check)
        g.addWidget(self.sort_recent_check)
        g.addWidget(QLabel('<b>Вид и ресурсы</b>'))
        theme_row = QFormLayout()
        self.theme_combo = QComboBox()
        from app.ui.tokens import THEME_NAMES
        for key, title in THEME_NAMES.items():
            self.theme_combo.addItem(title, key)
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(st.theme)))
        theme_row.addRow('Оформление (после перезапуска):', self.theme_combo)
        theme_item = theme_row.itemAt(0, QFormLayout.LabelRole)
        if theme_item is not None and theme_item.widget() is not None:
            theme_item.widget().setWordWrap(True)
        g.addLayout(theme_row)
        self.animations_check = check('Плавные анимации интерфейса (короткие, только при открытом окне)',
                                      st.animations)
        self.eco_check = check('Экономичный режим: когда окно скрыто в трее — режим эффективности '
                               'Windows и возврат памяти системе', st.eco_mode_in_tray)
        g.addWidget(self.animations_check)
        g.addWidget(self.eco_check)
        g.addWidget(QLabel('<b>Автозапуск</b>'))
        self.autostart_check = check('Запускать программу вместе с системой', autostart.is_enabled())
        self.autostart_check.setEnabled(autostart.is_supported())
        self.start_minimized_check = check('При автозапуске сразу сворачивать в трей (не показывать окно)',
                                           st.start_minimized)
        g.addWidget(self.autostart_check)
        g.addWidget(self.start_minimized_check)
        if not autostart.is_supported():
            note = QLabel('Автозапуск на этой ОС настраивается вручную через настройки системы.')
            note.setWordWrap(True)
            note.setProperty('muted', True)
            g.addWidget(note)
        g.addWidget(QLabel('<b>Безопасность</b>'))
        if secrets_store.is_secure_backend_available():
            sec_note = QLabel('Токены и пароли хранятся в защищённом системном хранилище '
                              '(Credential Manager / Keychain / Secret Service).')
        else:
            sec_note = QLabel(f'<span style="color:{WARNING};">Системное защищённое хранилище паролей '
                              f'недоступно — токены и пароли сохраняются в обычном файле на диске '
                              f'(доступ к нему равен доступу к вашим облачным аккаунтам).</span>')
        sec_note.setWordWrap(True)
        g.addWidget(sec_note)
        g.addStretch()
        tabs.addTab(_scrollable(general), 'Общие')

        # ---------- Слежение и выгрузка ----------
        sync = QWidget()
        s_lay = QVBoxLayout(sync)
        self.pause_check = check('Приостановить отслеживание всех игр (временно)', st.monitoring_paused)
        s_lay.addWidget(self.pause_check)
        self.retry_check = check('Повторять неудачную автовыгрузку (через 30 с, 2, 10 и 30 минут)',
                                 st.retry_failed_uploads)
        s_lay.addWidget(self.retry_check)
        form = QFormLayout()
        self.poll_spin = spin(2, 60, st.poll_interval_sec, ' с', 'Как часто проверять, запущена ли игра. '
                              'Меньше — быстрее реакция, чуть больше нагрузки.')
        self.confirm_polls_spin = spin(1, 10, st.exit_confirm_polls, '', 'Сколько проверок подряд процесса '
                                       'не должно быть, чтобы игра считалась закрытой.')
        self.exit_delay_spin = spin(0, 60, st.exit_upload_delay_sec, ' с', 'Пауза после закрытия игры перед '
                                    'выгрузкой — чтобы игра дописала файл на диск.')
        self.stable_spin = spin(5, 300, st.periodic_stable_sec, ' с', 'Для выгрузки во время игры: файл '
                                'должен не меняться столько секунд.')
        self.backups_spin = spin(1, 100, st.max_backups_per_slot, '', 'Сколько локальных резервных копий '
                                 'хранить на каждый слот сохранения.')
        form.addRow('Проверять процессы раз в:', self.poll_spin)
        form.addRow('Проверок подряд до «игра закрыта»:', self.confirm_polls_spin)
        form.addRow('Пауза перед выгрузкой после закрытия:', self.exit_delay_spin)
        form.addRow('Файл «успокоился» через (выгрузка во время игры):', self.stable_spin)
        self.snap_limit_spin = spin(0, 100000, st.max_auto_snapshot_mb, ' МБ', 'Для слотов больше этого размера '
                                    'автоснимки во время игры не делаются. 0 — без ограничения.')
        form.addRow('Резервных копий на слот:', self.backups_spin)
        form.addRow('Автоснимки только для слотов до:', self.snap_limit_spin)
        # Длинные подписи должны переноситься, а не вытеснять поля ввода за
        # границы диалога на узком окне / при крупном масштабе.
        for row in range(form.rowCount()):
            item = form.itemAt(row, QFormLayout.LabelRole)
            if item is not None and item.widget() is not None:
                item.widget().setWordWrap(True)
        s_lay.addLayout(form)
        s_lay.addStretch()
        tabs.addTab(_scrollable(sync), 'Слежение и выгрузка')

        # ---------- Облако и каталог игр ----------
        cloud = QWidget()
        c_lay = QVBoxLayout(cloud)
        self.catalog_check = check('Синхронизировать список игр через облако (второй компьютер сам '
                                   'подхватит игры первого)', st.catalog_sync,
                                   'В облаке хранится маленький файл _catalog.json со списком игр, '
                                   'процессами и путями сохранений (без имени пользователя).')
        self.auto_download_check = check('Сразу скачивать сохранения подхваченных игр, если на этом '
                                         'компьютере их ещё нет', st.auto_download_imported,
                                         'Перезаписывать нечего, поэтому это безопасно.')
        c_lay.addWidget(self.catalog_check)
        c_lay.addWidget(self.auto_download_check)
        self.catalog_check.toggled.connect(self.auto_download_check.setEnabled)
        self.auto_download_check.setEnabled(self.catalog_check.isChecked())
        hint = QLabel('Удалённые вручную игры повторно не добавляются; вернуть их можно кнопкой '
                      '«Найти игры в облаке» в окне облачных аккаунтов.')
        hint.setWordWrap(True)
        hint.setProperty('muted', True)
        c_lay.addWidget(hint)
        c_lay.addSpacing(8)
        manifest_btn = QPushButton('Обновить базу путей сохранений игр (Ludusavi)')
        manifest_btn.setIcon(svg_icon('refresh', 18, T.TEXT))
        manifest_btn.setToolTip('Открытая база путей сохранений для автопоиска; сама обновляется раз в 30 дней.')
        manifest_btn.clicked.connect(lambda: run_transfer(self, 'База путей сохранений',
                                                          lambda progress: manifest.update_index(progress)))
        c_lay.addWidget(manifest_btn)
        sync_all_btn = QPushButton('Выгрузить все сохранения сейчас')
        sync_all_btn.setProperty('cls', 'success')
        sync_all_btn.setIcon(svg_icon('upload', 18, T.TEXT_ON_SAGE))
        sync_all_btn.clicked.connect(self._sync_all_now)
        c_lay.addWidget(sync_all_btn)
        log_btn = QPushButton('Открыть журнал')
        log_btn.setIcon(svg_icon('history', 18, T.TEXT))
        log_btn.clicked.connect(lambda: LogDialog(self).exec_())
        c_lay.addWidget(log_btn)
        c_lay.addStretch()
        tabs.addTab(_scrollable(cloud), 'Облако и данные')

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _sync_all_now(self):
        jobs = [(g, sl) for g in self.store.games if g.account_id for sl in g.slots if sl.path]
        if not jobs:
            QMessageBox.information(self, 'Нечего выгружать',
                                     'Нет игр с настроенным облачным аккаунтом и указанным '
                                     'путём к сохранению.')
            return

        def job(progress):
            lines = []
            total = len(jobs)
            for i, (game, slot) in enumerate(jobs):
                base = 100 * i / total

                def sub(pct, text, g=game, sl=slot, base=base):
                    progress(base + pct / total, f'{g.name} / {sl.label}: {text}')

                ok, message = sync_manager.upload_slot(self.store, game, slot, silent=False, progress=sub)
                lines.append(f'{game.name} / {slot.label}: ' + ('ок' if ok else f'ошибка — {message}'))
                if message.startswith('Отменено'):
                    break
            progress(100, 'Готово')
            return all('ошибка' not in l for l in lines), '<br>'.join(lines)

        run_transfer(self, 'Выгрузка всех сохранений', job)

    def _on_accept(self):
        self.store.settings.minimize_to_tray = self.minimize_check.isChecked()
        self.store.settings.tray_notifications = self.notifications_check.isChecked()
        self.store.settings.confirm_tray_download = self.confirm_download_check.isChecked()
        self.store.settings.monitoring_paused = self.pause_check.isChecked()
        st = self.store.settings
        st.start_minimized = self.start_minimized_check.isChecked()
        st.animations = self.animations_check.isChecked()
        st.play_lock_enabled = self.play_lock_check.isChecked()
        st.sort_recent = self.sort_recent_check.isChecked()
        st.eco_mode_in_tray = self.eco_check.isChecked()
        motion.set_enabled(st.animations)
        st.retry_failed_uploads = self.retry_check.isChecked()
        st.poll_interval_sec = self.poll_spin.value()
        st.exit_confirm_polls = self.confirm_polls_spin.value()
        st.exit_upload_delay_sec = self.exit_delay_spin.value()
        st.periodic_stable_sec = self.stable_spin.value()
        st.max_backups_per_slot = self.backups_spin.value()
        st.max_auto_snapshot_mb = self.snap_limit_spin.value()
        theme_changed = self.theme_combo.currentData() != st.theme
        st.theme = self.theme_combo.currentData() or 'glass'
        st.catalog_sync = self.catalog_check.isChecked()
        st.auto_download_imported = self.auto_download_check.isChecked()
        self.store.save_settings()

        if autostart.is_supported():
            wanted = self.autostart_check.isChecked()
            if wanted != autostart.is_enabled():
                ok, message = autostart.set_enabled(wanted, minimized=self.start_minimized_check.isChecked())
                if not ok:
                    QMessageBox.warning(self, 'Автозапуск', message)
        if theme_changed:
            QMessageBox.information(self, 'Оформление', 'Новое оформление применится после перезапуска программы.')
        self.accept()
