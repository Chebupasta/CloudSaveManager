import os

from app import emulators


def _setup(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('USERPROFILE', str(home))
    monkeypatch.setenv('APPDATA', str(home / 'AppData' / 'Roaming'))
    monkeypatch.delenv('XDG_DATA_HOME', raising=False)
    monkeypatch.delenv('XDG_CONFIG_HOME', raising=False)
    return home


def test_unknown_emulator_returns_empty(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert emulators.find_emulator_saves('nope') == []


def test_finds_existing_dirs_only(tmp_path, monkeypatch):
    home = _setup(tmp_path, monkeypatch)
    assert emulators.find_emulator_saves('pcsx2') == []
    memcards = home / 'Documents' / 'PCSX2' / 'memcards'
    memcards.mkdir(parents=True)
    assert emulators.find_emulator_saves('pcsx2') == [str(memcards)]
    assert emulators.find_all_emulator_saves() == {'pcsx2': [str(memcards)]}


def test_portable_install_via_extra_roots(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    portable = tmp_path / 'Emu' / 'rpcs3'
    save = portable / 'dev_hdd0' / 'home' / '00000001' / 'savedata'
    save.mkdir(parents=True)
    found = emulators.find_emulator_saves('rpcs3', extra_roots=[str(portable)])
    assert [os.path.realpath(p) for p in found] == [os.path.realpath(str(save))]


def test_no_duplicates_through_symlink(tmp_path, monkeypatch):
    home = _setup(tmp_path, monkeypatch)
    real = home / 'Documents' / 'Dolphin Emulator' / 'GC'
    real.mkdir(parents=True)
    appdata_gc = home / 'AppData' / 'Roaming' / 'Dolphin Emulator'
    appdata_gc.mkdir(parents=True)
    try:
        os.symlink(real, appdata_gc / 'GC')
    except (OSError, NotImplementedError):
        return  # символические ссылки недоступны на этой платформе
    assert len(emulators.find_emulator_saves('dolphin')) == 1


def test_all_presets_are_well_formed():
    for key, p in emulators.EMULATORS.items():
        assert p.key == key and p.name and p.process_names and p.save_dirs
        for root_name, rel in p.save_dirs:
            assert root_name in {'appdata', 'documents', 'home', 'xdg_data', 'xdg_config'}
            assert rel and not rel.startswith('/') and '\\' not in rel
