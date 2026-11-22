"""
Диалог добавления/редактирования облачного аккаунта. Позволяет выбрать
тип провайдера (GitHub, GitLab, WebDAV, локальная папка) и заполнить
нужные поля, а также сразу проверить подключение.
"""
import webbrowser

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QGuiApplication
from PyQt5.QtWidgets import (
    QCheckBox, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QStackedWidget, QWidget, QMessageBox, QFileDialog,
    QDialogButtonBox, QScrollArea,
)

from app import secrets_store
from app.cloud import PROVIDER_REGISTRY, create_provider
from app.models import CloudAccount
from app.ui.theme import DANGER, SUCCESS
from app.ui.widgets import screen_fit

TYPE_ORDER = ['github', 'gitlab', 'webdav', 'dropbox', 'local']


def _preview_path(base_folder: str, prefix: str, filename: str) -> str:
    parts = []
    base = (base_folder or '').strip().strip('/')
    if base:
        parts.append(base.replace('\\', '/').replace(' ', '_'))
    parts.append((prefix or 'ИмяИгры').strip('/').replace('\\', '/').replace(' ', '_'))
    return '/'.join(parts) + '/' + filename


class AccountDialog(QDialog):
    def __init__(self, parent=None, account: CloudAccount = None, existing_secret: str = '',
                 preselect_type: str = ''):
        super().__init__(parent)
        self.setWindowTitle('Облачный аккаунт')
        self.setMinimumWidth(screen_fit(460, 0)[0])
        self.account = account
        self.result_account = None
        self.result_secret = None
        self.result_passphrase = ''  # '' — удалить пароль шифрования (если галочка снята)

        # Жёсткая минимальная высота 600 не влезала в 768p при масштабе 125 %.
        # Содержимое прокручивается, а диалог ограничен доступной высотой экрана.
        self.setMinimumWidth(screen_fit(560, 0)[0])
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.setMaximumHeight(screen_fit(0, 10000)[1])
        content = QWidget()
        layout = QVBoxLayout(content)

        top_form = QFormLayout()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText('Например: Мой GitHub')
        top_form.addRow('Название аккаунта:', self.name_input)

        self.type_combo = QComboBox()
        for key in TYPE_ORDER:
            self.type_combo.addItem(PROVIDER_REGISTRY[key][0], key)
        top_form.addRow('Тип хранилища:', self.type_combo)
        layout.addLayout(top_form)

        self.stack = QStackedWidget()
        self.pages = {}
        self._build_github_page()
        self._build_gitlab_page()
        self._build_webdav_page()
        self._build_dropbox_page()
        self._build_local_page()
        layout.addWidget(self.stack)

        if preselect_type and preselect_type in TYPE_ORDER:
            self.type_combo.setCurrentIndex(self.type_combo.findData(preselect_type))
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)

        # необязательное шифрование облачных копий
        self.enc_check = QCheckBox('Шифровать сохранения перед выгрузкой (AES-256)')
        layout.addWidget(self.enc_check)
        self.enc_pass = QLineEdit()
        self.enc_pass.setEchoMode(QLineEdit.Password)
        self.enc_pass.setPlaceholderText('Пароль шифрования (храните его — без него облачные копии не открыть)')
        self.enc_pass.setEnabled(False)
        self.enc_check.toggled.connect(self.enc_pass.setEnabled)
        layout.addWidget(self.enc_pass)

        self.preview_label = QLabel('')
        self.preview_label.setWordWrap(True)
        self.preview_label.setProperty('muted', True)
        layout.addWidget(self.preview_label)

        self.status_label = QLabel('')
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        btn_row = QHBoxLayout()
        self.test_btn = QPushButton('Проверить подключение')
        self.test_btn.clicked.connect(self._test_connection)
        btn_row.addWidget(self.test_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if account:
            self._load_account(account, existing_secret)
        if preselect_type and preselect_type in TYPE_ORDER:
            self._on_type_changed()  # все виджеты уже созданы — страница и превью
        else:
            self._update_preview()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.addWidget(scroll)
        self.resize(*screen_fit(640, 640))

    # ---------- страницы по типу провайдера ----------
    def _build_github_page(self):
        page = QWidget()
        form = QFormLayout(page)
        self.gh_repo = QLineEdit()
        self.gh_repo.setPlaceholderText('https://github.com/username/repo.git')
        self.gh_repo.textChanged.connect(self._update_preview)
        self.gh_token = QLineEdit()
        self.gh_token.setEchoMode(QLineEdit.Password)
        self.gh_base_folder = QLineEdit()
        self.gh_base_folder.setPlaceholderText('необязательно, например: Saves')
        self.gh_base_folder.textChanged.connect(self._update_preview)
        form.addRow('Ссылка на репозиторий:', self.gh_repo)
        form.addRow('Personal Access Token:', self.gh_token)
        form.addRow('Папка внутри репозитория:', self.gh_base_folder)
        row = QHBoxLayout()
        b1 = QPushButton('Создать репозиторий')
        b1.clicked.connect(lambda: webbrowser.open('https://github.com/new'))
        b2 = QPushButton('Получить токен')
        b2.clicked.connect(lambda: webbrowser.open(
            'https://github.com/settings/tokens/new?scopes=repo&description=CloudSaveManager'))
        row.addWidget(b1)
        row.addWidget(b2)
        form.addRow(row)
        hint = QLabel('Один и тот же репозиторий можно использовать сразу для всех ваших '
                       'игр — каждая игра автоматически получит свою подпапку, ничего '
                       'вручную создавать не нужно.')
        hint.setWordWrap(True)
        hint.setProperty('muted', True)
        form.addRow(hint)
        self.pages['github'] = page
        self.stack.addWidget(page)

    def _build_gitlab_page(self):
        page = QWidget()
        form = QFormLayout(page)
        self.gl_base_url = QLineEdit('https://gitlab.com')
        self.gl_project = QLineEdit()
        self.gl_project.setPlaceholderText('username/repo')
        self.gl_project.textChanged.connect(self._update_preview)
        self.gl_token = QLineEdit()
        self.gl_token.setEchoMode(QLineEdit.Password)
        self.gl_base_folder = QLineEdit()
        self.gl_base_folder.setPlaceholderText('необязательно, например: Saves')
        self.gl_base_folder.textChanged.connect(self._update_preview)
        form.addRow('Адрес GitLab:', self.gl_base_url)
        form.addRow('Проект (namespace/repo):', self.gl_project)
        form.addRow('Personal Access Token:', self.gl_token)
        form.addRow('Папка внутри репозитория:', self.gl_base_folder)
        row = QHBoxLayout()
        b1 = QPushButton('Создать проект')
        b1.clicked.connect(lambda: webbrowser.open('https://gitlab.com/projects/new'))
        b2 = QPushButton('Получить токен')
        b2.clicked.connect(lambda: webbrowser.open(
            'https://gitlab.com/-/user_settings/personal_access_tokens'))
        row.addWidget(b1)
        row.addWidget(b2)
        form.addRow(row)
        hint = QLabel('Один и тот же проект можно использовать сразу для всех ваших '
                       'игр — каждая игра автоматически получит свою подпапку.')
        hint.setWordWrap(True)
        hint.setProperty('muted', True)
        form.addRow(hint)
        self.pages['gitlab'] = page
        self.stack.addWidget(page)

    def _build_webdav_page(self):
        page = QWidget()
        form = QFormLayout(page)
        self.wd_base_url = QLineEdit()
        self.wd_base_url.setPlaceholderText('https://webdav.yandex.ru')
        self.wd_username = QLineEdit()
        self.wd_password = QLineEdit()
        self.wd_password.setEchoMode(QLineEdit.Password)
        self.wd_folder = QLineEdit('/CloudSaveManager')
        form.addRow('Адрес сервера:', self.wd_base_url)
        form.addRow('Логин:', self.wd_username)
        form.addRow('Пароль (приложения):', self.wd_password)
        form.addRow('Папка на сервере:', self.wd_folder)
        row = QHBoxLayout()
        yandex_btn = QPushButton('Заполнить для Яндекс.Диска')
        yandex_btn.clicked.connect(self._fill_yandex_defaults)
        pass_btn = QPushButton('Получить пароль приложения (Яндекс)')
        pass_btn.clicked.connect(lambda: webbrowser.open('https://id.yandex.ru/security/app-passwords'))
        row.addWidget(yandex_btn)
        row.addWidget(pass_btn)
        form.addRow(row)
        hint = QLabel('Для Яндекс.Диска обычный пароль от аккаунта не подойдёт — нужен\n'
                       '"пароль приложения" типа WebDAV. Также подходит любой другой\n'
                       'сервис с поддержкой WebDAV (Nextcloud, mail.ru и т.д.).')
        hint.setWordWrap(True)
        form.addRow(hint)
        self.pages['webdav'] = page
        self.stack.addWidget(page)

    def _build_dropbox_page(self):
        page = QWidget()
        form = QFormLayout(page)
        self.db_app_key = QLineEdit()
        self.db_app_key.setPlaceholderText('App key вашего приложения в Dropbox App Console')
        self.db_folder = QLineEdit('CloudSaveManager')
        self.db_code = QLineEdit()
        self.db_code.setPlaceholderText('Код авторизации из браузера')
        self.db_refresh = ''          # refresh token после успешного подключения
        self._db_verifier = ''
        form.addRow('App key:', self.db_app_key)
        form.addRow('Папка в Dropbox:', self.db_folder)
        row = QHBoxLayout()
        console_btn = QPushButton('Создать приложение (App Console)')
        console_btn.clicked.connect(lambda: webbrowser.open('https://www.dropbox.com/developers/apps/create'))
        auth_btn = QPushButton('1. Открыть авторизацию')
        auth_btn.clicked.connect(self._dropbox_open_auth)
        row.addWidget(console_btn)
        row.addWidget(auth_btn)
        form.addRow(row)
        form.addRow('Код:', self.db_code)
        connect_btn = QPushButton('2. Подключить по коду')
        connect_btn.clicked.connect(self._dropbox_connect)
        form.addRow(connect_btn)
        self.db_status = QLabel('')
        self.db_status.setWordWrap(True)
        form.addRow(self.db_status)
        hint = QLabel('Создайте приложение (Scoped access, права files.content.read/write и '
                      'account_info.read), вставьте его App key, нажмите «1», разрешите доступ '
                      'в браузере и вставьте показанный код, затем «2». Секрет приложения не нужен.')
        hint.setWordWrap(True)
        hint.setProperty('muted', True)
        hint.setMinimumHeight(84)
        form.addRow(hint)
        self.pages['dropbox'] = page
        self.stack.addWidget(page)

    def _dropbox_open_auth(self):
        from app.cloud import dropbox_provider
        key = self.db_app_key.text().strip()
        if not key:
            self.db_status.setText('Сначала введите App key.')
            return
        self._db_verifier = dropbox_provider.new_verifier()
        webbrowser.open(dropbox_provider.authorize_url(key, self._db_verifier))
        self.db_status.setText('Разрешите доступ в браузере, скопируйте код и вставьте его ниже.')

    def _dropbox_connect(self):
        from app.cloud import dropbox_provider
        if not self._db_verifier:
            self.db_status.setText('Сначала нажмите «1. Открыть авторизацию».')
            return
        ok, result = dropbox_provider.exchange_code(self.db_app_key.text(), self.db_code.text(), self._db_verifier)
        if ok:
            self.db_refresh = result
            self.db_status.setText('Dropbox подключён. Нажмите OK, чтобы сохранить аккаунт.')
        else:
            self.db_status.setText(result)

    def _build_local_page(self):
        page = QWidget()
        form = QFormLayout(page)
        self.local_folder = QLineEdit()
        browse_btn = QPushButton('Обзор...')
        browse_btn.clicked.connect(self._browse_local_folder)
        row = QHBoxLayout()
        row.addWidget(self.local_folder)
        row.addWidget(browse_btn)
        form.addRow('Синхронизируемая папка:', row)
        hint = QLabel('Укажите папку внутри Dropbox / Google Диска / OneDrive /\n'
                       'Яндекс.Диска, установленного на этом компьютере. Файлы будут\n'
                       'скопированы туда, а сам клиент сервиса выгрузит их в облако.\n'
                       'Токены и пароли для этого способа не нужны.')
        hint.setWordWrap(True)
        form.addRow(hint)
        self.pages['local'] = page
        self.stack.addWidget(page)

    def _fill_yandex_defaults(self):
        self.wd_base_url.setText('https://webdav.yandex.ru')

    def _browse_local_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Выберите синхронизируемую папку')
        if folder:
            self.local_folder.setText(folder)

    def _on_type_changed(self):
        key = self.type_combo.currentData()
        self.stack.setCurrentWidget(self.pages[key])
        self.status_label.setText('')
        self._update_preview()

    def _update_preview(self):
        key = self.type_combo.currentData()
        base_folder = ''
        if key == 'github':
            base_folder = self.gh_base_folder.text().strip()
        elif key == 'gitlab':
            base_folder = self.gl_base_folder.text().strip()
        if key in ('github', 'gitlab'):
            example = _preview_path(base_folder, 'DarkSoulsIII', 'DS30000.sl2')
            self.preview_label.setText(f'Пример пути в репозитории: {example}  '
                                        f'(для каждой игры — своя папка)')
        else:
            self.preview_label.setText('')

    # ---------- загрузка данных существующего аккаунта ----------
    def _load_account(self, account: CloudAccount, secret: str):
        self.name_input.setText(account.name)
        idx = TYPE_ORDER.index(account.type) if account.type in TYPE_ORDER else 0
        self.type_combo.setCurrentIndex(idx)
        self.stack.setCurrentWidget(self.pages[account.type])
        cfg = account.config
        if cfg.get('encrypt'):
            self.enc_check.setChecked(True)
            self.enc_pass.setText(secrets_store.get_secret(account.id + ':enc'))
        if account.type == 'github':
            self.gh_repo.setText(cfg.get('repo_url', ''))
            self.gh_token.setText(secret)
            self.gh_base_folder.setText(cfg.get('base_folder', ''))
        elif account.type == 'gitlab':
            self.gl_base_url.setText(cfg.get('base_url', 'https://gitlab.com'))
            self.gl_project.setText(cfg.get('project', ''))
            self.gl_token.setText(secret)
            self.gl_base_folder.setText(cfg.get('base_folder', ''))
        elif account.type == 'webdav':
            self.wd_base_url.setText(cfg.get('base_url', ''))
            self.wd_username.setText(cfg.get('username', ''))
            self.wd_password.setText(secret)
            self.wd_folder.setText(cfg.get('remote_folder', '/CloudSaveManager'))
        elif account.type == 'dropbox':
            self.db_app_key.setText(cfg.get('app_key', ''))
            self.db_folder.setText(cfg.get('base_folder', 'CloudSaveManager'))
            self.db_refresh = secret
        elif account.type == 'local':
            self.local_folder.setText(cfg.get('folder', ''))

    # ---------- сбор данных из формы ----------
    def _collect(self):
        key = self.type_combo.currentData()
        name = self.name_input.text().strip() or PROVIDER_REGISTRY[key][0]
        config = {}
        secret = ''
        if key == 'github':
            config = {
                'repo_url': self.gh_repo.text().strip(),
                'base_folder': self.gh_base_folder.text().strip(),
            }
            secret = self.gh_token.text().strip()
        elif key == 'gitlab':
            config = {
                'base_url': self.gl_base_url.text().strip() or 'https://gitlab.com',
                'project': self.gl_project.text().strip(),
                'base_folder': self.gl_base_folder.text().strip(),
            }
            secret = self.gl_token.text().strip()
        elif key == 'webdav':
            config = {
                'base_url': self.wd_base_url.text().strip(),
                'username': self.wd_username.text().strip(),
                'remote_folder': self.wd_folder.text().strip() or '/CloudSaveManager',
            }
            secret = self.wd_password.text().strip()
        elif key == 'dropbox':
            config = {'app_key': self.db_app_key.text().strip(),
                      'base_folder': self.db_folder.text().strip() or 'CloudSaveManager'}
            secret = self.db_refresh
        elif key == 'local':
            config = {'folder': self.local_folder.text().strip()}
            secret = ''
        if self.enc_check.isChecked():
            config['encrypt'] = True
        return key, name, config, secret

    def _test_connection(self):
        key, name, config, secret = self._collect()
        account = CloudAccount(type=key, name=name, config=config)
        account.secret = secret
        self.status_label.setText('Проверка подключения...')
        self.status_label.repaint()
        try:
            provider = create_provider(account)
            ok, message = provider.test_connection()
        except Exception as e:
            ok, message = False, f'Ошибка: {e}'
        color = SUCCESS if ok else DANGER
        self.status_label.setText(f'<span style="color:{color};">{message}</span>')

    def _on_accept(self):
        key, name, config, secret = self._collect()
        if key in ('github', 'gitlab', 'webdav', 'dropbox') and not secret and not (self.account and self.account.type == key):
            reply = QMessageBox.question(
                self, 'Нет токена/пароля',
                'Токен или пароль не указан. Сохранить аккаунт без него?\n'
                '(Вы сможете добавить его позже, отредактировав аккаунт.)',
                QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                return
        if self.enc_check.isChecked() and not self.enc_pass.text():
            QMessageBox.warning(self, 'Нет пароля', 'Включено шифрование — введите пароль шифрования.')
            return
        account = self.account or CloudAccount()
        account.type = key
        account.name = name
        account.config = config
        self.result_account = account
        self.result_secret = secret
        self.result_passphrase = self.enc_pass.text() if self.enc_check.isChecked() else ''
        self.accept()
