"""
Загрузка и сохранение списка игр и облачных аккаунтов в JSON-файлы
внутри папки настроек приложения.
"""
import json
import os
import threading
from typing import List

from app.constants import RUNTIME, get_app_dir, GAMES_FILE, ACCOUNTS_FILE, SETTINGS_FILE
from app.models import GameProfile, CloudAccount, AppSettings
from app import secrets_store


class ConfigStore:
    def __init__(self):
        self._lock = threading.RLock()
        self.games: List[GameProfile] = []
        self.accounts: List[CloudAccount] = []
        self.settings: AppSettings = AppSettings()
        self.load()

    # ---------- games ----------
    def _games_path(self) -> str:
        return os.path.join(get_app_dir(), GAMES_FILE)

    def _accounts_path(self) -> str:
        return os.path.join(get_app_dir(), ACCOUNTS_FILE)

    def _settings_path(self) -> str:
        return os.path.join(get_app_dir(), SETTINGS_FILE)

    def load(self):
        self.games = []
        path = self._games_path()
        if os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    raw = json.load(f)
                self.games = [GameProfile.from_dict(g) for g in raw]
            except (json.JSONDecodeError, OSError):
                self.games = []

        self.accounts = []
        path = self._accounts_path()
        if os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    raw = json.load(f)
                self.accounts = [CloudAccount.from_dict(a) for a in raw]
            except (json.JSONDecodeError, OSError):
                self.accounts = []

        self.settings = AppSettings()
        path = self._settings_path()
        if os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    raw = json.load(f)
                self.settings = AppSettings.from_dict(raw)
            except (json.JSONDecodeError, OSError):
                self.settings = AppSettings()
        self._apply_runtime()

    def _apply_runtime(self):
        st = self.settings.clamp()
        RUNTIME['max_backups'] = st.max_backups_per_slot
        RUNTIME['max_auto_snapshot_mb'] = st.max_auto_snapshot_mb

    @staticmethod
    def _write_json(path: str, data):
        # запись через временный файл: сбой посреди записи не повредит конфиг
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def save_settings(self):
        with self._lock:
            self._apply_runtime()
            self._write_json(self._settings_path(), self.settings.to_dict())

    def save_games(self):
        with self._lock:
            self._write_json(self._games_path(), [g.to_dict() for g in self.games])

    def save_accounts(self):
        with self._lock:
            self._write_json(self._accounts_path(), [a.to_dict() for a in self.accounts])

    # ---------- helpers ----------
    # Все методы ниже защищены общей блокировкой: process_monitor работает в
    # отдельном потоке (проверяет облако и выгружает сохранения при выходе
    # из игры) и может обращаться к store одновременно с интерфейсом.
    def get_game(self, game_id: str):
        with self._lock:
            return next((g for g in self.games if g.id == game_id), None)

    def get_account(self, account_id: str):
        with self._lock:
            return next((a for a in self.accounts if a.id == account_id), None)

    def add_game(self, game: GameProfile):
        with self._lock:
            self.games.append(game)
            self.save_games()

    def update_game(self, game: GameProfile):
        with self._lock:
            for i, g in enumerate(self.games):
                if g.id == game.id:
                    self.games[i] = game
                    break
            self.save_games()

    def remove_game(self, game_id: str):
        with self._lock:
            self.games = [g for g in self.games if g.id != game_id]
            self.save_games()

    def add_account(self, account: CloudAccount, secret: str = ''):
        with self._lock:
            self.accounts.append(account)
            self.save_accounts()
        if secret:
            secrets_store.set_secret(account.id, secret)

    def update_account(self, account: CloudAccount, secret: str = None):
        with self._lock:
            for i, a in enumerate(self.accounts):
                if a.id == account.id:
                    self.accounts[i] = account
                    break
            self.save_accounts()
        # None — не трогать секрет; '' — пользователь очистил токен/пароль,
        # старое значение должно быть удалено, а не оставаться в хранилище.
        if secret == '':
            secrets_store.delete_secret(account.id)
        elif secret is not None:
            secrets_store.set_secret(account.id, secret)

    def remove_account(self, account_id: str):
        with self._lock:
            self.accounts = [a for a in self.accounts if a.id != account_id]
            self.save_accounts()
            secrets_store.delete_secret(account_id)
            secrets_store.delete_secret(account_id + ':enc')
            # Отвязываем аккаунт от игр, которые его использовали
            changed = False
            for g in self.games:
                if g.account_id == account_id:
                    g.account_id = None
                    changed = True
            if changed:
                self.save_games()
