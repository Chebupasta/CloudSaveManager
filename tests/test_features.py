import json
import os
import time

import pytest

from app import backup, crypto_utils, manifest, secrets_store, sync_manager
from app.models import SaveSlot
from tests.conftest import make_game


def test_crypto_roundtrip_and_wrong_password(tmp_path):
    src = tmp_path / 'a.bin'
    src.write_bytes(b'secret save data' * 100)
    enc = tmp_path / 'a.enc'
    crypto_utils.encrypt_file(str(src), str(enc), 'pw1')
    assert crypto_utils.is_encrypted(str(enc)) and b'secret' not in enc.read_bytes()
    out = tmp_path / 'a.out'
    crypto_utils.decrypt_file(str(enc), str(out), 'pw1')
    assert out.read_bytes() == src.read_bytes()
    with pytest.raises(crypto_utils.CryptoError):
        crypto_utils.decrypt_file(str(enc), str(tmp_path / 'x'), 'wrong')


def test_encrypted_account_sync(env):
    store, account, tmp, save_dir = env
    account.config['encrypt'] = True
    store.update_account(account)
    secrets_store.set_secret(account.id + ':enc', 'pw')
    f = save_dir / 's.sav'
    f.write_text('hello')
    slot = SaveSlot(path=str(f), remote_name='s.sav')
    game = make_game(store, account, slot)
    assert sync_manager.upload_slot(store, game, slot)[0]
    cloud = tmp / 'cloud' / 'Hades__Test' / 's.sav'
    assert crypto_utils.is_encrypted(str(cloud)) and b'hello' not in cloud.read_bytes()
    assert sync_manager.check_slot_sync_status(store, game, slot)['status'] == 'up_to_date'
    f.write_text('changed')
    assert sync_manager.download_slot(store, game, slot)[0] and f.read_text() == 'hello'
    # без пароля облачная копия не открывается
    secrets_store.set_secret(account.id + ':enc', '')
    ok, msg = sync_manager.download_slot(store, game, slot)
    assert not ok and ('пароль' in msg.lower() or 'зашифрован' in msg.lower())
    assert f.read_text() == 'hello'  # локальный файл не тронут


def test_previous_cloud_copy_is_decrypted(env):
    store, account, tmp, save_dir = env
    account.config['encrypt'] = True
    store.update_account(account)
    secrets_store.set_secret(account.id + ':enc', 'pw')
    f = save_dir / 's.sav'
    f.write_text('good')
    slot = SaveSlot(path=str(f), remote_name='s.sav')
    game = make_game(store, account, slot)
    assert sync_manager.upload_slot(store, game, slot)[0]
    f.write_text('bad')
    assert sync_manager.upload_slot(store, game, slot)[0]
    assert any(open(c['path']).read() == 'good' for c in backup.list_backups(game.id, slot.id))


def test_manifest_index_lookup_and_expand(tmp_path, monkeypatch):
    raw = {
        'Dark Souls III': {'files': {'<winAppData>/DarkSoulsIII/<storeUserId>': {'tags': ['save'], 'when': [{'os': 'windows'}, {'os': 'linux'}]},
                                     '<winAppData>/DarkSoulsIII/GraphicsConfig.xml': {'tags': ['config']}},
                           'installDir': {'DARK SOULS III': {}}, 'steam': {'id': 374320}},
        'Other': {'steam': {'id': 1}},
        'Mac only': {'files': {'<home>/x': {'tags': ['save'], 'when': [{'os': 'mac'}]}}},
    }
    idx = manifest.build_index(raw)
    assert idx['Dark Souls III']['p'] == ['<winAppData>/DarkSoulsIII/<storeUserId>']  # конфиг отброшен
    assert 'Mac only' not in idx and idx['Dark Souls III']['s'] == 374320
    monkeypatch.setenv('APPDATA', str(tmp_path))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'cfg'))
    monkeypatch.setattr(manifest, 'index_path', lambda: str(tmp_path / 'idx.json'))
    (tmp_path / 'idx.json').write_text(json.dumps(idx))
    manifest._index_cache.clear(); manifest._norm_cache.clear()
    save = tmp_path / 'DarkSoulsIII' / '0110000100000000'
    save.mkdir(parents=True)
    (save / 'DS30000.sl2').write_text('x')
    found = manifest.find_candidates({'DarkSoulsIII.exe', 'darksoulsiii', 'Dark Souls III'})
    assert [os.path.normpath(c['path']) for c in found] == [os.path.normpath(str(save))] and found[0]['is_dir']
    assert manifest.steam_id_for({'Dark Souls III'}) == '374320'


def test_dropbox_provider_with_mocked_http(tmp_path, monkeypatch):
    from app.cloud import dropbox_provider as dp
    calls = []

    class Resp:
        def __init__(self, code=200, body=None, text='', content=b''):
            self.status_code, self._body, self.text, self._content = code, body or {}, text, content
            self.headers = {'Content-Length': str(len(content))}

        def json(self):
            return self._body

        def iter_content(self, chunk_size=0):
            yield self._content

    def fake_post(url, **kw):
        calls.append((url, kw))
        if url == dp.TOKEN_URL:
            return Resp(body={'access_token': 'AT', 'expires_in': 3600, 'refresh_token': 'RT'})
        if url.endswith('/files/upload'):
            return Resp(body={})
        if url.endswith('/files/download'):
            return Resp(content=b'data') if 'good' in kw['headers']['Dropbox-API-Arg'] else Resp(409, text='path/not_found')
        return Resp(body={'email': 'a@b.c'})

    monkeypatch.setattr(dp.requests, 'post', fake_post)
    ok, token = dp.exchange_code('KEY', 'CODE', 'VER')
    assert ok and token == 'RT'
    p = dp.DropboxProvider({'app_key': 'KEY', 'base_folder': 'Saves'}, 'RT')
    assert p.test_connection()[0]
    f = tmp_path / 'f.bin'
    f.write_bytes(b'data')
    assert p.upload_file(str(f), 'Игра/good.sav')[0]
    arg = json.loads([c for c in calls if c[0].endswith('/files/upload')][0][1]['headers']['Dropbox-API-Arg'])
    assert arg['path'] == '/Saves/Игра/good.sav' and arg['mode'] == 'overwrite'
    out = tmp_path / 'o.bin'
    assert p.download_file('good.sav', str(out))[0] and out.read_bytes() == b'data'
    assert p.download_file('missing.sav', str(out)) == (False, p.NOT_FOUND)
    assert sum(1 for c in calls if c[0] == dp.TOKEN_URL) == 2  # exchange + один refresh (токен кэшируется)


def test_periodic_upload_only_stable_files(env, monkeypatch):
    store, account, tmp, save_dir = env
    from app.process_monitor import ProcessMonitor
    f = save_dir / 's.sav'
    f.write_text('v1')
    slot = SaveSlot(path=str(f), remote_name='s.sav')
    game = make_game(store, account, slot)
    game.periodic_upload_minutes = 1
    store.update_game(game)
    mon = ProcessMonitor(store)
    got = []
    mon.periodic_result.connect(lambda gid, res: got.append(res))
    mon._last_periodic[game.id] = time.time() - 120
    mon._maybe_periodic_upload(game)            # файл только что записан — не трогаем
    assert not got and not (tmp / 'cloud').exists()
    old = time.time() - 60
    os.utime(f, (old, old))
    mon._last_periodic[game.id] = time.time() - 120
    mon._maybe_periodic_upload(game)
    assert got and got[0][0][1] is True
    assert (tmp / 'cloud' / 'Hades__Test' / 's.sav').exists()
