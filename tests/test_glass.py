import re

import pytest

pytest.importorskip('PyQt5')

from app.ui import glass, tokens  # noqa: E402


def test_blob_positions_stay_inside_window_and_move():
    for w, h in ((900, 600), (720, 480), (1, 1)):
        for t in (0.0, 13.7, 250.0, 10_000.0):
            blobs = glass.blob_positions(t, w, h)
            assert len(blobs) == 4
            for x, y, r in blobs:
                assert 0 <= x <= w and 0 <= y <= h and r > 0
    a = glass.blob_positions(0.0, 900, 600)
    b = glass.blob_positions(10.0, 900, 600)
    assert a != b                                   # капли действительно дрейфуют
    assert glass.blob_positions(5.0, 900, 600) == glass.blob_positions(5.0, 900, 600)


def test_parse_color_understands_hex_and_css_rgba():
    assert glass.parse_color('#102030') == (16, 32, 48, 255)
    assert glass.parse_color('rgba(255,255,255,0.5)') == (255, 255, 255, 128)
    assert glass.parse_color(' rgba( 10 , 20 , 30 , 1 ) ') == (10, 20, 30, 255)
    assert glass.parse_color('rgb(1,2,3)') == (1, 2, 3, 255)


def test_every_glass_token_is_parseable_and_translucent_where_expected():
    for name in ('glass', 'glass_dark'):
        p = tokens.PALETTES[name]
        assert p['IS_GLASS'] is True
        for key in ('GLASS_TOP', 'GLASS_BOTTOM', 'GLASS_HOVER', 'GLASS_INPUT', 'GLASS_SIDEBAR',
                    'RIM_LIGHT', 'RIM_DIM', 'SOFT', 'SOFT_HOVER'):
            a = glass.parse_color(p[key])[3]
            assert 0 < a < 255, (name, key)          # стекло: ни прозрачное целиком, ни глухое
        assert glass.parse_color(p['RIM_LIGHT'])[3] > glass.parse_color(p['RIM_DIM'])[3]
        assert len(p['BACKDROP']) == 6
        assert all(re.fullmatch(r'#[0-9A-Fa-f]{6}', c) for c in p['BACKDROP'])
        assert re.fullmatch(r'#[0-9A-Fa-f]{6}', p['POPUP'])   # меню и списки непрозрачны


def test_flat_themes_keep_glass_off():
    assert tokens.PALETTES['light']['IS_GLASS'] is False
    assert tokens.PALETTES['dark']['IS_GLASS'] is False
    assert tokens.DEFAULT_THEME == 'glass'


def test_stylesheet_is_balanced_and_glass_rules_follow_flat_ones():
    from app.ui import theme
    s = theme.STYLE_SHEET
    assert s.count('{') == s.count('}')
    if tokens.IS_GLASS:
        assert s.rindex('QWidget { background-color: transparent; }') > s.index('QPushButton {')
        assert 'QComboBoxPrivateContainer' in s
