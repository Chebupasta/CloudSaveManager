import os
import zipfile

from app import backup, sync_manager
from app.models import SaveSlot
from tests.conftest import make_game


def _file_slot(save_dir, text='v1'):
    f = save_dir / 'save.sl2'
    f.write_text(text)
    return SaveSlot(path=str(f), remote_name='save.sl2')


def test_file_roundtrip_and_meta(env):
    store, account, tmp, save_dir = env
    slot = _file_slot(save_dir)
    game = make_game(store, account, slot)
    ok, _ = sync_manager.upload_slot(store, game, slot)
    assert ok
    cloud = tmp / 'cloud' / 'Hades__Test'  # двоеточие заменено — путь валиден на Windows
    assert (cloud / 'save.sl2').exists()
    assert (cloud / 'save.sl2.meta.json').exists()
    assert sync_manager.check_slot_sync_status(store, game, slot)['status'] == 'up_to_date'
    open(slot.path, 'w').write('v2')
    assert sync_manager.check_slot_sync_status(store, game, slot)['status'] == 'local_newer'
    ok, _ = sync_manager.download_slot(store, game, slot)
    assert ok and open(slot.path).read() == 'v1'
    assert backup.list_backups(game.id, slot.id)  # локальная версия сохранена перед заменой


def test_directory_zipped_and_restored(env):
    store, account, tmp, save_dir = env
    d = save_dir / 'profile'
    (d / 'sub').mkdir(parents=True)
    (d / 'a.dat').write_text('A')
    (d / 'sub' / 'b.dat').write_text('B')
    slot = SaveSlot(path=str(d) + os.sep, is_directory=True, remote_name='save.zip')  # слеш в конце
    game = make_game(store, account, slot)
    assert sync_manager.upload_slot(store, game, slot)[0]
    with zipfile.ZipFile(tmp / 'cloud' / 'Hades__Test' / 'save.zip') as z:
        assert sorted(n.replace('\\', '/') for n in z.namelist()) == ['a.dat', 'sub/b.dat']
    (d / 'a.dat').write_text('changed')
    assert sync_manager.download_slot(store, game, slot)[0]
    assert (d / 'a.dat').read_text() == 'A'
    assert not (d / 'profile').exists()  # папка не вложилась сама в себя


def test_auto_upload_does_not_overwrite_newer_cloud(env):
    store, account, tmp, save_dir = env
    slot = _file_slot(save_dir)
    game = make_game(store, account, slot)
    assert sync_manager.upload_slot(store, game, slot)[0]
    # «другой ПК» выгрузил новую версию: подменяем облако и метаданные
    other = tmp / 'other.sl2'
    other.write_text('from-other-pc')
    cloud_file = tmp / 'cloud' / 'Hades__Test' / 'save.sl2'
    cloud_file.write_text('from-other-pc')
    meta = tmp / 'cloud' / 'Hades__Test' / 'save.sl2.meta.json'
    import json
    data = json.loads(meta.read_text())
    data['fingerprint'] = sync_manager.compute_fingerprint(str(other), False)
    data['device'] = 'LAPTOP'
    meta.write_text(json.dumps(data))
    # на этом ПК файл не менялся -> облако новее; автовыгрузка пропускается
    outcome, _msg, status = sync_manager.auto_upload_slot(store, game, slot)
    assert outcome == 'skipped' and status['status'] == 'cloud_newer'
    assert status['cloud_meta']['device'] == 'LAPTOP'
    assert cloud_file.read_text() == 'from-other-pc'
    # и локально менялось -> конфликт, тоже пропуск
    open(slot.path, 'w').write('local-change')
    assert sync_manager.auto_upload_slot(store, game, slot)[0] == 'skipped'
    assert cloud_file.read_text() == 'from-other-pc'


def test_previous_cloud_version_is_kept(env):
    store, account, tmp, save_dir = env
    slot = _file_slot(save_dir, 'good')
    game = make_game(store, account, slot)
    assert sync_manager.upload_slot(store, game, slot)[0]
    open(slot.path, 'w').write('broken')
    assert sync_manager.upload_slot(store, game, slot)[0]
    copies = backup.list_backups(game.id, slot.id)
    assert any(open(c['path']).read() == 'good' for c in copies)


def test_old_cloud_without_meta_still_checked(env):
    store, account, tmp, save_dir = env
    slot = _file_slot(save_dir)
    game = make_game(store, account, slot)
    assert sync_manager.upload_slot(store, game, slot)[0]
    (tmp / 'cloud' / 'Hades__Test' / 'save.sl2.meta.json').unlink()
    assert sync_manager.check_slot_sync_status(store, game, slot)['status'] == 'up_to_date'


def test_zip_slip_rejected(tmp_path):
    bad = tmp_path / 'bad.zip'
    with zipfile.ZipFile(bad, 'w') as z:
        z.writestr('../evil.txt', 'x')
    try:
        sync_manager._safe_extract(str(bad), str(tmp_path / 'out'), None, 0, 0)
    except zipfile.BadZipFile:
        pass
    else:
        raise AssertionError('zip-slip не отклонён')
    assert not (tmp_path / 'evil.txt').exists()


def test_backups_keep_newest(env):
    store, account, tmp, save_dir = env
    from app.constants import MAX_BACKUPS_PER_SLOT
    f = save_dir / 'x.sav'
    for i in range(MAX_BACKUPS_PER_SLOT + 3):
        f.write_text(str(i))
        backup.make_local_backup('g', 's', str(f), False)
    items = backup.list_backups('g', 's')
    assert len(items) == MAX_BACKUPS_PER_SLOT
    assert open(items[0]['path']).read() == str(MAX_BACKUPS_PER_SLOT + 2)


def test_failed_auto_upload_is_retried(env, monkeypatch):
    store, account, tmp, save_dir = env
    from app.process_monitor import ProcessMonitor
    slot = _file_slot(save_dir)
    game = make_game(store, account, slot)
    mon = ProcessMonitor(store)
    emitted = []
    mon.upload_result.connect(lambda gid, res: emitted.append(res))
    calls = {'n': 0}

    def fake(store_, game_, slot_, progress=None):
        calls['n'] += 1
        return ('error', 'нет сети', {}) if calls['n'] < 3 else ('uploaded', 'ok', {})

    monkeypatch.setattr(sync_manager, 'auto_upload_slot', fake)
    mon._auto_upload_after_exit(game)
    assert game.id in mon._retries and emitted  # первая неудача: уведомление + повтор
    mon._retries[game.id]['due'] = 0
    mon._process_retries()                      # вторая неудача: без спама уведомлений
    assert game.id in mon._retries and len(emitted) == 1
    mon._retries[game.id]['due'] = 0
    mon._process_retries()                      # успех: итоговое уведомление
    assert game.id not in mon._retries and emitted[-1][0][1] is True
