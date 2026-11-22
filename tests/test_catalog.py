import os

from app import catalog, secrets_store, sync_manager
from app.models import CloudAccount, GameProfile, SaveSlot
from app.store import ConfigStore


def _second_pc(monkeypatch, tmp_path, cloud_dir):
    """Второй компьютер: другая папка настроек и другой «домашний» каталог, то же облако."""
    pc2 = tmp_path / 'pc2'
    for var in ('APPDATA', 'XDG_CONFIG_HOME', 'HOME', 'USERPROFILE', 'LOCALAPPDATA'):
        monkeypatch.setenv(var, str(pc2))
    store2 = ConfigStore()
    acc2 = CloudAccount(type='local', name='Облако (ПК 2)', config={'folder': cloud_dir})
    store2.add_account(acc2)
    return store2, acc2, pc2


def test_template_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv('APPDATA', str(tmp_path / 'u1' / 'AppData' / 'Roaming'))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'u1' / 'AppData' / 'Local'))
    monkeypatch.setenv('HOME', str(tmp_path / 'u1'))
    monkeypatch.setattr(os.path, 'expanduser', lambda p: str(tmp_path / 'u1') if p == '~' else p)
    p = tmp_path / 'u1' / 'AppData' / 'Roaming' / 'DarkSoulsIII' / '0110'
    t = catalog.to_template(str(p))
    assert t == '{APPDATA}/DarkSoulsIII/0110' and str(tmp_path) not in t
    # на другом ПК другое имя пользователя
    monkeypatch.setenv('APPDATA', str(tmp_path / 'u2' / 'AppData' / 'Roaming'))
    assert catalog.from_template(t) == os.path.normpath(str(tmp_path / 'u2' / 'AppData' / 'Roaming' / 'DarkSoulsIII' / '0110'))


def test_second_pc_discovers_games_and_downloads_saves(env, monkeypatch, tmp_path):
    store, account, tmp, save_dir = env
    appdata = tmp / 'pc1_appdata'
    monkeypatch.setenv('APPDATA', str(appdata))
    save = appdata / 'DarkSoulsIII' / '0110000100000000'
    save.mkdir(parents=True)
    (save / 'DS30000.sl2').write_text('progress-pc1')
    game = GameProfile(name='Dark Souls III', process_names=['DarkSoulsIII.exe'], account_id=account.id,
                       auto_upload_on_exit=True, check_cloud_on_start=False,
                       slots=[SaveSlot(label='Профиль', path=str(save), is_directory=True, remote_name='save.zip')])
    store.add_game(game)
    assert sync_manager.upload_slot(store, game, game.slots[0])[0]
    assert catalog.publish(store, account)[0]
    assert (tmp / 'cloud' / '_catalog.json').exists()
    assert 'pc1_appdata' not in (tmp / 'cloud' / '_catalog.json').read_text()  # путь переносимый

    # ----- второй ПК -----
    store2, acc2, pc2 = _second_pc(monkeypatch, tmp_path, str(tmp / 'cloud'))
    created, msg = catalog.sync_account(store2, acc2)
    assert [g.name for g in created] == ['Dark Souls III'] and 'Добавлено' in msg
    g2 = store2.get_game(created[0].id)
    assert g2.process_names == ['DarkSoulsIII.exe'] and g2.check_cloud_on_start is False
    slot2 = g2.slots[0]
    assert slot2.path.startswith(str(pc2)) and slot2.is_directory  # путь пересобран под новый ПК
    assert (pc2 / 'DarkSoulsIII' / '0110000100000000' / 'DS30000.sl2').read_text() == 'progress-pc1'
    # повторная синхронизация ничего не дублирует
    assert catalog.sync_account(store2, acc2)[0] == []
    assert len(store2.games) == 1


def test_removed_game_not_readded_until_forced(env, monkeypatch, tmp_path):
    store, account, tmp, save_dir = env
    f = save_dir / 'a.sav'
    f.write_text('x')
    game = GameProfile(name='Hades', account_id=account.id, slots=[SaveSlot(path=str(f), remote_name='a.sav')])
    store.add_game(game)
    assert catalog.publish(store, account)[0]
    store2, acc2, _ = _second_pc(monkeypatch, tmp_path, str(tmp / 'cloud'))
    created, _ = catalog.sync_account(store2, acc2)
    g = created[0]
    catalog.remember_removed(store2, g)
    store2.remove_game(g.id)
    assert catalog.sync_account(store2, acc2)[0] == []                      # не возвращается сама
    assert len(catalog.sync_account(store2, acc2, include_ignored=True)[0]) == 1   # но находится вручную


def test_catalog_with_encrypted_account(env):
    store, account, tmp, save_dir = env
    account.config['encrypt'] = True
    store.update_account(account)
    secrets_store.set_secret(account.id + ':enc', 'pw')
    f = save_dir / 'a.sav'
    f.write_text('x')
    store.add_game(GameProfile(name='Secret Game', account_id=account.id,
                               slots=[SaveSlot(path=str(f), remote_name='a.sav')]))
    assert catalog.publish(store, account)[0]
    raw = (tmp / 'cloud' / '_catalog.json').read_bytes()
    assert b'Secret Game' not in raw                     # имена игр тоже зашифрованы
    data, err = catalog.fetch(store, account)
    assert err is None
    assert [e['name'] for e in data['games'].values()] == ['Secret Game']
