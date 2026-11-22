import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Изолированные настройки приложения и локальная «облачная» папка."""
    for var in ('APPDATA', 'XDG_CONFIG_HOME', 'HOME'):
        monkeypatch.setenv(var, str(tmp_path / 'cfg'))
    from app.models import CloudAccount
    from app.store import ConfigStore
    store = ConfigStore()
    account = CloudAccount(type='local', name='L', config={'folder': str(tmp_path / 'cloud')})
    store.add_account(account)
    save_dir = tmp_path / 'saves'
    save_dir.mkdir()
    return store, account, tmp_path, save_dir


def make_game(store, account, slot):
    from app.models import GameProfile
    game = GameProfile(name='Hades: Test', account_id=account.id, slots=[slot])
    store.add_game(game)
    return game
