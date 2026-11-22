"""Автообновление: версии, разбор GitHub Releases и безопасная замена."""
from app import updater
from app.version import __version__, is_newer, parse_version


def test_version_parsing_and_comparison():
    assert parse_version('v1.2.3') == (1, 2, 3)
    assert parse_version('2.0-beta') == (2, 0)
    assert is_newer('v99.0.0', __version__)
    assert not is_newer('v0.0.1', __version__)
    assert not is_newer(__version__, __version__)


def test_repo_validation():
    assert updater.valid_repo('owner/repo')
    assert updater.valid_repo('User.Name/repo-name')
    assert not updater.valid_repo('')
    assert not updater.valid_repo('owner')
    assert not updater.valid_repo('https://github.com/owner/repo')


def test_check_for_update_parses_release(monkeypatch):
    class Response:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {
                'tag_name': 'v99.1.0',
                'body': 'Новое чудо',
                'html_url': 'https://github.com/owner/repo/releases/tag/v99.1.0',
                'assets': [
                    {'name': 'source.zip', 'browser_download_url': 'https://x/source.zip'},
                    {'name': 'CloudSaveManager.exe',
                     'browser_download_url': 'https://x/CloudSaveManager.exe'},
                ],
            }

    monkeypatch.setattr(updater.requests, 'get', lambda *a, **k: Response())
    info = updater.check_for_update('owner/repo')
    assert info is not None
    assert info.version == '99.1.0'
    assert info.asset_name == 'CloudSaveManager.exe'
    assert info.asset_url == 'https://x/CloudSaveManager.exe'
    assert info.notes == 'Новое чудо'


def test_check_for_update_no_newer_and_network_error(monkeypatch):
    class Response:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {'tag_name': 'v0.0.1', 'assets': []}

    monkeypatch.setattr(updater.requests, 'get', lambda *a, **k: Response())
    assert updater.check_for_update('owner/repo') is None

    def fail(*args, **kwargs):
        raise updater.requests.ConnectionError('нет сети')

    monkeypatch.setattr(updater.requests, 'get', fail)
    assert updater.check_for_update('owner/repo') is None


def test_schedule_replace_refuses_source_run(tmp_path):
    # При запуске из исходников автозамена недопустима — только страница релиза.
    exe = tmp_path / 'app.exe'
    exe.write_bytes(b'x')
    assert updater.schedule_replace(str(exe), str(exe), 1234) is False
