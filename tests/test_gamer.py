import json
import os

from app import backup, library_scan, manifest, sync_manager
from app.models import GameProfile, SaveSlot
from tests.conftest import make_game


def test_named_snapshots_survive_trimming_and_auto_are_limited(env):
    store, account, tmp, save_dir = env
    f = save_dir / 's.sav'
    f.write_text('before-boss')
    p = backup.make_snapshot('g', 's', str(f), False, 'перед боссом')
    assert p.endswith('.sav') and '__s_' in p
    for i in range(14):                                   # автоснимки: хранятся последние 10
        f.write_text(f'auto{i}')
        backup.make_snapshot('g', 's', str(f), False, auto=True)
    for i in range(9):                                    # обычные копии: по настройке (5)
        f.write_text(f'reg{i}')
        backup.make_local_backup('g', 's', str(f), False)
    items = backup.list_backups('g', 's')
    kinds = [i['kind'] for i in items]
    assert kinds.count('named') == 1 and kinds.count('auto') == 10 and kinds.count('regular') == 5
    named = [i for i in items if i['kind'] == 'named'][0]
    assert named['label'] == 'перед боссом' and open(named['path']).read() == 'before-boss'
    assert backup.delete_backup(named['path'])


def test_empty_save_is_not_auto_uploaded(env):
    store, account, tmp, save_dir = env
    f = save_dir / 's.sav'
    f.write_text('good')
    slot = SaveSlot(path=str(f), remote_name='s.sav')
    game = make_game(store, account, slot)
    assert sync_manager.upload_slot(store, game, slot)[0]
    f.write_text('')                                       # игра «обнулила» сохранение
    outcome, msg, status = sync_manager.auto_upload_slot(store, game, slot)
    assert outcome == 'skipped' and status['status'] == 'empty_local' and 'пуст' in msg
    assert (tmp / 'cloud' / 'Hades__Test' / 's.sav').read_text() == 'good'


def test_play_marker_detects_other_pc(env, monkeypatch):
    store, account, tmp, save_dir = env
    f = save_dir / 's.sav'
    f.write_text('x')
    slot = SaveSlot(path=str(f), remote_name='s.sav')
    game = make_game(store, account, slot)
    monkeypatch.setattr(sync_manager.socket, 'gethostname', lambda: 'DESKTOP')
    assert sync_manager.set_playing(store, game, True)[0]
    assert sync_manager.playing_elsewhere(store, game) is None            # это тот же ПК
    monkeypatch.setattr(sync_manager.socket, 'gethostname', lambda: 'LAPTOP')
    other = sync_manager.playing_elsewhere(store, game)
    assert other and other['device'] == 'DESKTOP'
    monkeypatch.setattr(sync_manager.socket, 'gethostname', lambda: 'DESKTOP')
    assert sync_manager.set_playing(store, game, False)[0]               # закончил играть
    monkeypatch.setattr(sync_manager.socket, 'gethostname', lambda: 'LAPTOP')
    assert sync_manager.playing_elsewhere(store, game) is None
    # устаревшая отметка (ПК мог выключиться) игнорируется
    marker = tmp / 'cloud' / 'Hades__Test' / '_playing.json'
    marker.write_text(json.dumps({'state': 'playing', 'device': 'DESKTOP', 'at': '2020-01-01T10:00:00'}))
    assert sync_manager.playing_elsewhere(store, game) is None


def test_playtime_and_launch_count(env):
    store, account, tmp, save_dir = env
    from app.process_monitor import ProcessMonitor
    game = GameProfile(name='G', process_names=['g.exe'])
    store.add_game(game)
    mon = ProcessMonitor(store)
    seq = [{'g.exe'}, {'g.exe'}, set(), set(), set()]
    mon._current_process_names = lambda: seq.pop(0)
    mon._poll_once(); mon._poll_once()
    mon._started_at[game.id] -= 3700                                      # «играли» 1 ч с лишним
    for _ in range(3):
        mon._poll_once()
    g = store.get_game(game.id)
    assert g.launch_count == 1 and g.last_played and 3700 <= g.playtime_seconds < 3720


def test_library_scan_steam_epic_and_saves(tmp_path, monkeypatch):
    steam = tmp_path / 'Steam'
    lib2 = tmp_path / 'Lib2'
    (steam / 'steamapps').mkdir(parents=True)
    (lib2 / 'steamapps' / 'common' / 'DARK SOULS III' / 'Game').mkdir(parents=True)
    (steam / 'steamapps' / 'libraryfolders.vdf').write_text('"libraryfolders" { "1" { "path" "%s" } }' % str(lib2).replace('\\', '\\\\'))
    (lib2 / 'steamapps' / 'appmanifest_374320.acf').write_text('"AppState" { "appid" "374320" "name" "DARK SOULS III" "installdir" "DARK SOULS III" }')
    (lib2 / 'steamapps' / 'appmanifest_228980.acf').write_text('"AppState" { "appid" "228980" "name" "Steamworks Common Redistributables" "installdir" "Steamworks Shared" }')
    game_dir = lib2 / 'steamapps' / 'common' / 'DARK SOULS III'
    (game_dir / 'Game' / 'DarkSoulsIII.exe').write_bytes(b'0' * 5000)
    (game_dir / 'Game' / 'unins000.exe').write_bytes(b'0' * 9000)         # больше, но это деинсталлятор
    found = library_scan.scan_steam([str(steam)])
    assert [g.name for g in found] == ['DARK SOULS III'] and found[0].launch == 'steam://rungameid/374320'
    assert os.path.basename(found[0].exe_path) == 'DarkSoulsIII.exe'
    # Epic
    epic = tmp_path / 'epic'
    epic.mkdir()
    inst = tmp_path / 'EpicGame'
    inst.mkdir()
    (inst / 'Run.exe').write_bytes(b'0' * 100)
    (epic / 'a.item').write_text(json.dumps({'DisplayName': 'Hades', 'InstallLocation': str(inst), 'LaunchExecutable': 'Run.exe',
                                             'CatalogNamespace': 'ns', 'CatalogItemId': 'cat', 'AppName': 'app'}))
    eg = library_scan.scan_epic(str(epic))
    assert eg[0].name == 'Hades' and 'ns%3Acat%3Aapp' in eg[0].launch
    # пути сохранений из базы
    monkeypatch.setenv('APPDATA', str(tmp_path / 'AppData'))
    save = tmp_path / 'AppData' / 'DarkSoulsIII' / '0110'
    save.mkdir(parents=True)
    (save / 'DS30000.sl2').write_text('x')
    idx = {'Dark Souls III': {'p': ['<winAppData>/DarkSoulsIII/<storeUserId>'], 's': 374320, 'i': ['DARK SOULS III']}}
    (tmp_path / 'idx.json').write_text(json.dumps(idx))
    monkeypatch.setattr(manifest, 'index_path', lambda: str(tmp_path / 'idx.json'))
    manifest._index_cache.clear(); manifest._norm_cache.clear()
    found[0].saves = library_scan.match_saves(found[0])
    prof = library_scan.to_profile(found[0], 'acc1')
    assert prof.process_names == ['DarkSoulsIII.exe'] and prof.account_id == 'acc1'
    assert [s.path for s in prof.slots] == [os.path.normpath(str(save))] and prof.slots[0].is_directory
    assert prof.slots[0].remote_name == 'slot1.zip'
