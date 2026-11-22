"""Регрессионные тесты исправлений: перемешивание данных и безопасность путей."""
import zipfile

from app import backup, learned_paths, sync_manager
from app.models import CloudAccount, GameProfile, SaveSlot


def test_remote_name_cannot_escape_game_folder(tmp_path, monkeypatch):
    monkeypatch.setenv('APPDATA', str(tmp_path / 'cfg'))
    account = CloudAccount(type='local', config={'folder': str(tmp_path / 'cloud')})
    slot = SaveSlot(remote_name='../ДругаяИгра/save.dat', path=str(tmp_path / 's.dat'))
    game = GameProfile(name='Game', slots=[slot])

    key = sync_manager._remote_key(account, game, slot)

    assert '..' not in key
    assert key.endswith('/save.dat')
    assert len(key.split('/')) == 2  # <игра>/<файл>, без вложенных папок


def test_upload_result_keyed_by_slot_id(env, monkeypatch):
    from app.process_monitor import ProcessMonitor

    store, account, tmp, save_dir = env
    f = save_dir / 'a.sav'
    f.write_text('v1')
    first = SaveSlot(label='Одинаковое имя', path=str(f), remote_name='a.sav')
    second = SaveSlot(label='Одинаковое имя', path=str(f), remote_name='b.sav')
    game = GameProfile(name='Game', account_id=account.id, slots=[first, second])
    store.add_game(game)
    monkeypatch.setattr(sync_manager, 'auto_upload_slot',
                        lambda *args, **kwargs: ('uploaded', 'ok', {}))

    monitor = ProcessMonitor(store)
    emitted = []
    monitor.upload_result.connect(lambda gid, results: emitted.append(results))
    monitor._auto_upload_after_exit(game)

    assert emitted
    assert {row[0] for row in emitted[0]} == {first.id, second.id}


def test_restore_backup_rejects_zip_slip(tmp_path):
    bad = tmp_path / 'bad.zip'
    with zipfile.ZipFile(bad, 'w') as zf:
        zf.writestr('../outside.txt', 'взлом')

    ok, _message = backup.restore_backup(
        str(bad), str(tmp_path / 'target' / 'save.dat'), True, 'g', 's')

    assert not ok
    assert not (tmp_path / 'outside.txt').exists()


def test_learned_paths_remembers_two_slots_of_same_process(tmp_path, monkeypatch):
    monkeypatch.setenv('APPDATA', str(tmp_path / 'cfg'))

    learned_paths.remember('game.exe', 'appdata', 'Game/save1.dat', False, 'slot1')
    learned_paths.remember('game.exe', 'appdata', 'Game/save2.dat', False, 'slot2')

    assert learned_paths.recall('game.exe', 'slot1')['relative'] == 'Game/save1.dat'
    assert learned_paths.recall('game.exe', 'slot2')['relative'] == 'Game/save2.dat'
