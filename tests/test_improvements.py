import os
import time

from app import backup, library_scan, sync_manager


def _exe(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'0' * size)
    return str(path)


def test_exe_prefers_name_match_over_size(tmp_path):
    root = tmp_path / 'Elden Ring'
    big_launcher = _exe(root / 'bigtool.exe', 5000)
    game = _exe(root / 'eldenring.exe', 100)
    _exe(root / 'unins000.exe', 99999)
    _exe(root / 'EasyAntiCheat' / 'eac_launcher.exe', 99999)
    cands = library_scan.exe_candidates(str(root), 'ELDEN RING')
    assert cands[0] == game
    assert big_launcher in cands
    assert all('unins' not in c and 'eac' not in c.lower() for c in cands)
    assert library_scan.guess_exe(str(root), game_name='ELDEN RING') == game


def test_exe_falls_back_to_largest_and_handles_missing(tmp_path):
    root = tmp_path / 'X'
    _exe(root / 'a.exe', 10)
    big = _exe(root / 'b.exe', 900)
    assert library_scan.guess_exe(str(root)) == big
    assert library_scan.exe_candidates(str(tmp_path / 'nope')) == []
    assert library_scan.guess_exe('') == ''


def test_stat_signature_changes_only_with_files(tmp_path):
    d = tmp_path / 'save'
    d.mkdir()
    (d / 'a.sav').write_text('one')
    (d / 'skip.log').write_text('log')
    sig = sync_manager.stat_signature(str(d), True, ('*.log',))
    assert sig[0] == 3
    assert sync_manager.stat_signature(str(d), True, ('*.log',)) == sig
    (d / 'skip.log').write_text('much longer log text')
    assert sync_manager.stat_signature(str(d), True, ('*.log',)) == sig      # исключённое не влияет
    time.sleep(0.01)
    (d / 'a.sav').write_text('changed!')
    assert sync_manager.stat_signature(str(d), True, ('*.log',)) != sig
    assert sync_manager.stat_signature(str(tmp_path / 'none'), True) is None
    f = tmp_path / 'one.sav'
    f.write_text('abc')
    assert sync_manager.stat_signature(str(f), False)[0] == 3


def test_backup_delta_and_bulk_delete(env):
    store, account, tmp, save_dir = env
    f = save_dir / 's.sav'
    paths = []
    for text in ('a', 'abcd', 'ab'):
        f.write_text(text)
        paths.append(backup.make_snapshot('g', 's', str(f), False, label='x'))
        time.sleep(0.01)
    items = backup.list_backups('g', 's')
    assert [i['size'] for i in items] == [2, 4, 1]          # новые сверху
    assert [i['delta_size'] for i in items] == [-2, 3, None]
    assert backup.delete_backups(paths[:2] + [str(tmp / 'missing')]) == 2
    assert len(backup.list_backups('g', 's')) == 1


def test_auto_snapshot_skips_unchanged_and_oversized(env):
    import pytest
    pytest.importorskip('PyQt5')
    from app.constants import RUNTIME
    from app.models import SaveSlot
    from app.process_monitor import ProcessMonitor
    from tests.conftest import make_game
    store, account, tmp, save_dir = env
    f = save_dir / 's.sav'
    f.write_text('v1')
    old = time.time() - 60
    os.utime(f, (old, old))
    game = make_game(store, account, SaveSlot(path=str(f), remote_name='s.sav'))
    game.snapshot_minutes = 1
    store.update_game(game)
    slot = game.slots[0]
    mon = ProcessMonitor(store)

    def tick():
        mon._last_snapshot[game.id] = time.time() - 120
        mon._maybe_snapshot(game)
        return len(backup.list_backups(game.id, slot.id))

    assert tick() == 1
    assert tick() == 1                                   # ничего не менялось — нового снимка нет
    f.write_text('v2-changed')
    os.utime(f, (old, old))
    assert tick() == 2
    RUNTIME['max_auto_snapshot_mb'] = 1                  # слот в 2 МБ — «слишком большой»
    try:
        f.write_bytes(b'x' * (2 * 1024 * 1024))
        os.utime(f, (old, old))
        assert tick() == 2
    finally:
        RUNTIME['max_auto_snapshot_mb'] = 300


def _lum(hex_color):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_palettes_are_complete_and_readable():
    from app.ui import tokens
    keys = [frozenset(p) for p in tokens.PALETTES.values()]
    assert len(set(keys)) == 1, 'во всех палитрах должен быть один и тот же набор ключей'
    assert {'glass', 'glass_dark', 'light', 'dark'} <= set(tokens.PALETTES)
    for name, p in tokens.PALETTES.items():
        assert _contrast(p['TEXT'], p['C_BG']) >= 7, name
        assert _contrast(p['TEXT_MUTED'], p['C_BG']) >= 4.5, name
        assert _contrast(p['TEXT_MUTED'], p['BG_SIDEBAR']) >= 4.5, name
        assert _contrast(p['TEXT_ON_SAGE'], p['SAGE']) >= 4.5, name
        assert _contrast(p['TEXT_ON_CARD_MUTED'], p['C_CARD']) >= 4.5, name
        assert _contrast(p['TEXT'], p['C_SURFACE']) >= 7, name


def test_theme_setting_defaults_and_clamps(env, monkeypatch):
    from app.constants import RUNTIME
    from app.models import AppSettings
    assert AppSettings().theme == 'glass'
    assert AppSettings.from_dict({'theme': 'neon'}).theme == 'glass'
    for name in ('glass', 'glass_dark', 'light', 'dark'):
        assert AppSettings.from_dict({'theme': name}).theme == name
    store = env[0]
    store.settings.max_auto_snapshot_mb = 42
    store.save_settings()
    assert RUNTIME['max_auto_snapshot_mb'] == 42
    RUNTIME['max_auto_snapshot_mb'] = 300
