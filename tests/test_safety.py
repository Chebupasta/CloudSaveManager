import json
import os

from app import backup, catalog, sync_manager
from app.models import CloudAccount, SaveSlot
from tests.conftest import make_game


def _dir_slot(save_dir, excl=''):
    d = save_dir / 'profile'
    (d / 'cache').mkdir(parents=True)
    (d / 'keep.sl2').write_text('save1')
    (d / 'debug.log').write_text('log1')
    (d / 'cache' / 'tmp.bin').write_text('cache1')
    return d, SaveSlot(path=str(d), is_directory=True, remote_name='save.zip', exclude_patterns=excl)


def test_excludes_not_uploaded_and_not_lost_on_download(env):
    store, account, tmp, save_dir = env
    d, slot = _dir_slot(save_dir, '*.log, cache')
    game = make_game(store, account, slot)
    assert sync_manager.upload_slot(store, game, slot)[0]
    import zipfile
    with zipfile.ZipFile(tmp / 'cloud' / 'Hades__Test' / 'save.zip') as z:
        assert [n.replace('\\', '/') for n in z.namelist()] == ['keep.sl2']
    # изменение только исключённых файлов не делает слот «изменённым»
    (d / 'debug.log').write_text('log-changed-a-lot')
    assert sync_manager.check_slot_sync_status(store, game, slot)['status'] == 'up_to_date'
    (d / 'keep.sl2').write_text('save2')
    assert sync_manager.download_slot(store, game, slot)[0]
    assert (d / 'keep.sl2').read_text() == 'save1'
    assert (d / 'debug.log').read_text() == 'log-changed-a-lot'      # локальные исключения сохранены
    assert (d / 'cache' / 'tmp.bin').read_text() == 'cache1'


def test_dangerous_download_target_refused(env, monkeypatch):
    store, account, tmp, save_dir = env
    home = tmp / 'home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('USERPROFILE', str(home))
    for bad in (str(home), str(tmp), os.path.abspath(os.sep)):
        slot = SaveSlot(path=bad, is_directory=True, remote_name='save.zip')
        game = make_game(store, account, slot)
        ok, msg = sync_manager.download_slot(store, game, slot)
        assert not ok and 'опасн' in msg.lower(), bad
    assert home.exists()


def test_cancel_leaves_everything_intact(env):
    store, account, tmp, save_dir = env
    f = save_dir / 's.sav'
    f.write_text('v1')
    slot = SaveSlot(path=str(f), remote_name='s.sav')
    game = make_game(store, account, slot)
    assert sync_manager.upload_slot(store, game, slot)[0]
    f.write_text('v2')

    def cancel(_pct, _text):
        raise sync_manager.Cancelled()

    ok, msg = sync_manager.upload_slot(store, game, slot, progress=cancel)
    assert not ok and 'Отмен' in msg
    ok, msg = sync_manager.download_slot(store, game, slot, progress=cancel)
    assert not ok and 'Отмен' in msg and f.read_text() == 'v2'
    cloud_dir = tmp / 'cloud' / 'Hades__Test'
    assert not [p for p in os.listdir(cloud_dir) if p.endswith('.part')]


def test_previous_cloud_version_rollback_from_another_pc(env):
    store, account, tmp, save_dir = env
    f = save_dir / 's.sav'
    f.write_text('good')
    slot = SaveSlot(path=str(f), remote_name='s.sav')
    game = make_game(store, account, slot)
    assert sync_manager.upload_slot(store, game, slot)[0]
    f.write_text('bad')
    assert sync_manager.upload_slot(store, game, slot)[0]
    assert (tmp / 'cloud' / 'Hades__Test' / 's.sav.prev').read_text() == 'good'
    ok, msg = sync_manager.download_slot(store, game, slot, previous=True)
    assert ok and f.read_text() == 'good' and 'выгрузите' in msg
    # локальная откатная версия отличается от текущей облачной -> «локальная новее», можно выгрузить
    assert sync_manager.check_slot_sync_status(store, game, slot)['status'] == 'local_newer'
    assert any(open(b['path']).read() == 'bad' for b in backup.list_backups(game.id, slot.id))


def _tamper_cloud(tmp, text, device='LAPTOP'):
    cloud = tmp / 'cloud' / 'Hades__Test'
    other = tmp / 'o.tmp'
    other.write_text(text)
    (cloud / 's.sav').write_text(text)
    meta = json.loads((cloud / 's.sav.meta.json').read_text())
    meta['fingerprint'] = sync_manager.compute_fingerprint(str(other), False)
    meta['device'] = device
    (cloud / 's.sav.meta.json').write_text(json.dumps(meta))


def test_prelaunch_downloads_newer_cloud_and_reports_conflict(env):
    store, account, tmp, save_dir = env
    f = save_dir / 's.sav'
    f.write_text('v1')
    slot = SaveSlot(path=str(f), remote_name='s.sav')
    game = make_game(store, account, slot)
    assert sync_manager.upload_slot(store, game, slot)[0]
    _tamper_cloud(tmp, 'from-laptop')
    res = sync_manager.prelaunch_sync(store, game)
    assert len(res['downloaded']) == 1 and f.read_text() == 'from-laptop' and not res['conflicts']
    # теперь обе стороны меняются независимо -> конфликт, ничего не затирается
    f.write_text('local-edit')
    _tamper_cloud(tmp, 'laptop-again')
    res = sync_manager.prelaunch_sync(store, game)
    assert len(res['conflicts']) == 1 and f.read_text() == 'local-edit'


def test_prelaunch_missing_local_is_downloaded(env):
    store, account, tmp, save_dir = env
    f = save_dir / 's.sav'
    f.write_text('v1')
    slot = SaveSlot(path=str(f), remote_name='s.sav')
    game = make_game(store, account, slot)
    assert sync_manager.upload_slot(store, game, slot)[0]
    f.unlink()
    res = sync_manager.prelaunch_sync(store, game)
    assert len(res['downloaded']) == 1 and f.read_text() == 'v1'


def test_catalog_unsafe_path_not_applied(env, monkeypatch, tmp_path):
    store, account, tmp, save_dir = env
    # злонамеренный каталог: слот указывает вне профиля пользователя
    evil = {'version': 1, 'games': {'evil': {'name': 'Evil', 'prefix': 'Evil', 'process_names': [],
            'slots': [{'label': 'x', 'remote_name': 'save.zip', 'is_directory': True,
                       'path': '{APPDATA}/../../../../Windows/System32'},
                      {'label': 'y', 'remote_name': 'a.sav', 'is_directory': False, 'path': '/etc/passwd'}]}}}
    (tmp / 'cloud').mkdir(exist_ok=True)
    (tmp / 'cloud' / '_catalog.json').write_text(json.dumps(evil))
    from app.store import ConfigStore
    for var in ('APPDATA', 'XDG_CONFIG_HOME', 'HOME', 'USERPROFILE', 'LOCALAPPDATA'):
        monkeypatch.setenv(var, str(tmp_path / 'pc2'))
    store2 = ConfigStore()
    acc2 = CloudAccount(type='local', name='L2', config={'folder': str(tmp / 'cloud')})
    store2.add_account(acc2)
    created, msg = catalog.sync_account(store2, acc2)
    assert [g.name for g in created] == ['Evil'] and all(s.path == '' for s in created[0].slots)
    assert 'вне безопасных' in msg
