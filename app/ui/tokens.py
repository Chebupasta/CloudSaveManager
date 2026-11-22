"""
Дизайн-токены Cloud Save Manager. Темы: «жидкое стекло» (светлая и тёмная, по умолчанию) и прежние
плоские «светлая» / «тёмная лесная» (в настройках).
Все цвета, размеры, скругления и отступы живут здесь; стили (theme.py) и
виджеты берут значения только отсюда.
"""
import os
import sys

# ---------- палитры ----------
# Светлая — по умолчанию (воздушная, мягкие тени цвета вместо рамок); тёмная — прежняя лесная.
_LIGHT = {
    'C_TEXT_SECONDARY': '#6B7B77', 'C_MOSS': '#3E7F72', 'C_CARD': '#E6F0EC', 'C_SURFACE': '#FFFFFF', 'C_BG': '#F5F8F7',
    'TEXT': '#1B2B28', 'TEXT_MUTED': '#5C6C68', 'TEXT_ON_CARD_MUTED': '#4A5B57', 'TEXT_ON_ACCENT': '#FFFFFF',
    'BG_SIDEBAR': '#ECF2F0', 'CARD_TOP': '#FFFFFF', 'CARD_BOTTOM': '#E6F0EC',
    'ACCENT_HOVER': '#4A9082', 'ACCENT_PRESSED': '#336B60',
    'SAGE': '#2F7D6B', 'SAGE_HOVER': '#3A8F7B', 'SAGE_PRESSED': '#26695A', 'TEXT_ON_SAGE': '#FFFFFF',
    'SELECT_BAR': '#2F7D6B', 'BORDER': '#DCE6E3', 'BORDER_CARD': '#CBD9D4', 'BORDER_HOVER': '#B0C5BE',
    'FOCUS': '#2F7D6B', 'HOVER_BG': '#EAF1EE', 'SELECTED_BG': 'rgba(47,125,107,0.12)',
    'CARD_EDGE': '#E1EAE7', 'SOFT': 'rgba(60,90,82,0.07)', 'SOFT_HOVER': 'rgba(60,90,82,0.12)',
    'SOFT_PRESSED': 'rgba(60,90,82,0.19)', 'DANGER_HOVER': 'rgba(192,57,43,0.10)',
    'OK': '#2E8B62', 'WARN': '#A8680F', 'ERR': '#C0392B',
    'IS_GLASS': False,
    'GLASS_TOP': '#FFFFFF', 'GLASS_BOTTOM': '#FFFFFF', 'GLASS_HOVER': '#FFFFFF', 'GLASS_INPUT': '#FFFFFF',
    'GLASS_SIDEBAR': '#FFFFFF', 'RIM_LIGHT': 'rgba(255,255,255,0)', 'RIM_DIM': 'rgba(255,255,255,0)',
    'POPUP': '#FFFFFF', 'PRIMARY_TOP': '#3A8F7B',
    'BACKDROP': ('#F5F8F7', '#F5F8F7', '#F5F8F7', '#F5F8F7', '#F5F8F7', '#F5F8F7'),
}
_DARK = {
    'C_TEXT_SECONDARY': '#949DAA', 'C_MOSS': '#4A6864', 'C_CARD': '#1F3F3A', 'C_SURFACE': '#132523', 'C_BG': '#0B181F',
    'TEXT': '#E6EDEB', 'TEXT_MUTED': '#949DAA', 'TEXT_ON_CARD_MUTED': '#B4BCC4', 'TEXT_ON_ACCENT': '#F2F7F5',
    'BG_SIDEBAR': '#0F1F23', 'CARD_TOP': '#132523', 'CARD_BOTTOM': '#1F3F3A',
    'ACCENT_HOVER': '#58797A', 'ACCENT_PRESSED': '#3D5753',
    'SAGE': '#A9C1B4', 'SAGE_HOVER': '#B9CFC3', 'SAGE_PRESSED': '#97AFA2', 'TEXT_ON_SAGE': '#0B181F',
    'SELECT_BAR': '#7FA89B', 'BORDER': '#1F3A36', 'BORDER_CARD': '#2E5750', 'BORDER_HOVER': '#3F6E66',
    'FOCUS': '#8FB8AE', 'HOVER_BG': '#17302D', 'SELECTED_BG': 'rgba(31,63,58,0.7)',
    'CARD_EDGE': '#132523', 'SOFT': 'rgba(148,157,170,0.10)', 'SOFT_HOVER': 'rgba(148,157,170,0.17)',
    'SOFT_PRESSED': 'rgba(148,157,170,0.26)', 'DANGER_HOVER': 'rgba(232,141,141,0.12)',
    'OK': '#86C9A9', 'WARN': '#E2B96F', 'ERR': '#E88D8D',
    'IS_GLASS': False,
    'GLASS_TOP': '#FFFFFF', 'GLASS_BOTTOM': '#FFFFFF', 'GLASS_HOVER': '#FFFFFF', 'GLASS_INPUT': '#FFFFFF',
    'GLASS_SIDEBAR': '#FFFFFF', 'RIM_LIGHT': 'rgba(255,255,255,0)', 'RIM_DIM': 'rgba(255,255,255,0)',
    'POPUP': '#132523', 'PRIMARY_TOP': '#B9CFC3',
    'BACKDROP': ('#0B181F', '#0B181F', '#0B181F', '#0B181F', '#0B181F', '#0B181F'),
}

# «Жидкое стекло»: полупрозрачные поверхности поверх живого цветного фона. Цвета ключей C_* и BG*
# здесь — «эффективные» (как поверхность выглядит над фоном), на них считается контраст текста.
# Полупрозрачные значения (rgba) годятся только для QSS; в QColor идут одноцветные hex.
_GLASS_LIGHT = {
    'C_TEXT_SECONDARY': '#51627A', 'C_MOSS': '#2F6FD0', 'C_CARD': '#EEF4FD', 'C_SURFACE': '#F6F9FE', 'C_BG': '#DCE8FA',
    'TEXT': '#101C2C', 'TEXT_MUTED': '#43536B', 'TEXT_ON_CARD_MUTED': '#3B4B63', 'TEXT_ON_ACCENT': '#FFFFFF',
    'BG_SIDEBAR': '#E4EDFB', 'CARD_TOP': '#F8FBFF', 'CARD_BOTTOM': '#E9F1FC',
    'ACCENT_HOVER': '#3F82E6', 'ACCENT_PRESSED': '#1F58B0',
    'SAGE': '#1A62D6', 'SAGE_HOVER': '#2B74EA', 'SAGE_PRESSED': '#154FAE', 'TEXT_ON_SAGE': '#FFFFFF',
    'SELECT_BAR': '#2B74EA', 'BORDER': 'rgba(255,255,255,0.65)', 'BORDER_CARD': 'rgba(255,255,255,0.70)',
    'BORDER_HOVER': 'rgba(255,255,255,0.95)',
    'FOCUS': '#2B74EA', 'HOVER_BG': 'rgba(255,255,255,0.45)', 'SELECTED_BG': 'rgba(43,116,234,0.20)',
    'CARD_EDGE': 'rgba(255,255,255,0.80)', 'SOFT': 'rgba(255,255,255,0.62)', 'SOFT_HOVER': 'rgba(255,255,255,0.78)',
    'SOFT_PRESSED': 'rgba(255,255,255,0.90)', 'DANGER_HOVER': 'rgba(200,50,50,0.12)',
    'OK': '#1E7F57', 'WARN': '#9A5E0B', 'ERR': '#C23030',
    'IS_GLASS': True,
    # Поверхности достаточно плотные, чтобы текст не «светился» на фоне
    # движущихся цветных пятен — стекло остаётся стеклом, но читается уверенно.
    'GLASS_TOP': 'rgba(255,255,255,0.84)', 'GLASS_BOTTOM': 'rgba(255,255,255,0.68)',
    'GLASS_HOVER': 'rgba(255,255,255,0.92)', 'GLASS_INPUT': 'rgba(255,255,255,0.82)',
    'GLASS_SIDEBAR': 'rgba(255,255,255,0.64)',
    'RIM_LIGHT': 'rgba(255,255,255,0.95)', 'RIM_DIM': 'rgba(255,255,255,0.28)',
    'POPUP': '#F4F8FE', 'PRIMARY_TOP': '#4C8EF2',
    # фон: основа (2 цвета градиента) + 4 «капли» света
    'BACKDROP': ('#DCE8FA', '#EADFF7', '#9CC4FF', '#D9B8FF', '#9FE3D4', '#FFC9DE'),
}
_GLASS_DARK = {
    'C_TEXT_SECONDARY': '#9AA9C7', 'C_MOSS': '#6C9CF0', 'C_CARD': '#222B4F', 'C_SURFACE': '#1B2344', 'C_BG': '#0E1328',
    'TEXT': '#EEF3FF', 'TEXT_MUTED': '#A6B3D0', 'TEXT_ON_CARD_MUTED': '#B8C3DC', 'TEXT_ON_ACCENT': '#0A1226',
    'BG_SIDEBAR': '#131A36', 'CARD_TOP': '#222B4F', 'CARD_BOTTOM': '#1A2242',
    'ACCENT_HOVER': '#86AEF5', 'ACCENT_PRESSED': '#5B88DB',
    'SAGE': '#86B2FF', 'SAGE_HOVER': '#9CC2FF', 'SAGE_PRESSED': '#74A1F0', 'TEXT_ON_SAGE': '#0A1226',
    'SELECT_BAR': '#86B2FF', 'BORDER': 'rgba(255,255,255,0.14)', 'BORDER_CARD': 'rgba(255,255,255,0.20)',
    'BORDER_HOVER': 'rgba(255,255,255,0.34)',
    'FOCUS': '#9CC2FF', 'HOVER_BG': 'rgba(255,255,255,0.10)', 'SELECTED_BG': 'rgba(134,178,255,0.22)',
    'CARD_EDGE': 'rgba(255,255,255,0.28)', 'SOFT': 'rgba(255,255,255,0.17)', 'SOFT_HOVER': 'rgba(255,255,255,0.27)',
    'SOFT_PRESSED': 'rgba(255,255,255,0.36)', 'DANGER_HOVER': 'rgba(255,120,120,0.16)',
    'OK': '#7DD6AA', 'WARN': '#EBC278', 'ERR': '#FF9A9A',
    'IS_GLASS': True,
    # То же для тёмной темы: поверхность заметно плотнее фона, текст не тонет
    # в цветных пятнах, но остаётся ощущение прозрачного стекла.
    'GLASS_TOP': 'rgba(255,255,255,0.24)', 'GLASS_BOTTOM': 'rgba(255,255,255,0.14)',
    'GLASS_HOVER': 'rgba(255,255,255,0.32)', 'GLASS_INPUT': 'rgba(255,255,255,0.18)',
    'GLASS_SIDEBAR': 'rgba(255,255,255,0.13)',
    'RIM_LIGHT': 'rgba(255,255,255,0.55)', 'RIM_DIM': 'rgba(255,255,255,0.10)',
    'POPUP': '#1B2344', 'PRIMARY_TOP': '#A9C9FF',
    'BACKDROP': ('#0E1328', '#1A1038', '#2B52B8', '#7A3FC9', '#1E8F94', '#B03A7C'),
}
PALETTES = {'glass': _GLASS_LIGHT, 'glass_dark': _GLASS_DARK, 'light': _LIGHT, 'dark': _DARK}
THEME_NAMES = {'glass': 'Жидкое стекло (светлая)', 'glass_dark': 'Жидкое стекло (тёмная)',
               'light': 'Плоская светлая', 'dark': 'Плоская тёмная'}
DEFAULT_THEME = 'glass'


def _saved_theme() -> str:
    """Тема из settings.json (применяется при запуске) или переменной CSM_THEME."""
    name = os.environ.get('CSM_THEME', '')
    if not name:
        try:
            import json
            from app.constants import get_app_dir, SETTINGS_FILE
            with open(os.path.join(get_app_dir(), SETTINGS_FILE), 'r', encoding='utf-8') as f:
                name = str(json.load(f).get('theme', ''))
        except (OSError, ValueError, AttributeError):
            name = ''
    return name if name in PALETTES else DEFAULT_THEME


THEME = _saved_theme()
_P = PALETTES[THEME]

# ---------- базовая палитра ----------
C_TEXT_SECONDARY = _P['C_TEXT_SECONDARY']   # вторичный текст, нейтральные иконки
C_MOSS = _P['C_MOSS']                       # приглушённый зелёный акцент
C_CARD = _P['C_CARD']                       # карточки и выделенные поверхности
C_SURFACE = _P['C_SURFACE']                 # поверхности
C_BG = _P['C_BG']                           # основной фон

# ---------- производные (для состояний и контраста) ----------
TEXT = _P['TEXT']
TEXT_MUTED = _P['TEXT_MUTED']
TEXT_ON_CARD_MUTED = _P['TEXT_ON_CARD_MUTED']
TEXT_ON_ACCENT = _P['TEXT_ON_ACCENT']

BG = C_BG
BG_SIDEBAR = _P['BG_SIDEBAR']
BG_PANEL = C_SURFACE
BG_INPUT = C_SURFACE
CARD = C_CARD
CARD_TOP = _P['CARD_TOP']
CARD_BOTTOM = _P['CARD_BOTTOM']
ACCENT = C_MOSS                # ограниченный акцент: границы, индикаторы, чекбоксы
ACCENT_HOVER = _P['ACCENT_HOVER']
ACCENT_PRESSED = _P['ACCENT_PRESSED']
SAGE = _P['SAGE']              # основная кнопка
SAGE_HOVER = _P['SAGE_HOVER']
SAGE_PRESSED = _P['SAGE_PRESSED']
TEXT_ON_SAGE = _P['TEXT_ON_SAGE']
SELECT_BAR = _P['SELECT_BAR']  # индикатор активной игры
BORDER = _P['BORDER']
BORDER_CARD = _P['BORDER_CARD']
BORDER_HOVER = _P['BORDER_HOVER']
FOCUS = _P['FOCUS']            # кольцо фокуса (клавиатурная навигация)
HOVER_BG = _P['HOVER_BG']
SELECTED_BG = _P['SELECTED_BG']
CARD_EDGE = _P['CARD_EDGE']    # тонкая кромка карточек (на тёмной теме сливается с поверхностью)
SOFT = _P['SOFT']              # фон вторичных кнопок
SOFT_HOVER = _P['SOFT_HOVER']
SOFT_PRESSED = _P['SOFT_PRESSED']
DANGER_HOVER = _P['DANGER_HOVER']

# ---------- жидкое стекло ----------
IS_GLASS = bool(_P['IS_GLASS'])
GLASS_TOP = _P['GLASS_TOP']          # заливка стеклянной карточки сверху (rgba)
GLASS_BOTTOM = _P['GLASS_BOTTOM']    # и снизу
GLASS_HOVER = _P['GLASS_HOVER']
GLASS_INPUT = _P['GLASS_INPUT']
GLASS_SIDEBAR = _P['GLASS_SIDEBAR']
RIM_LIGHT = _P['RIM_LIGHT']          # яркая кромка (блик света на ребре стекла)
RIM_DIM = _P['RIM_DIM']
POPUP = _P['POPUP']                  # непрозрачный фон меню и выпадающих списков
PRIMARY_TOP = _P['PRIMARY_TOP']      # верх градиента главной кнопки
BACKDROP = _P['BACKDROP']            # основа фона (2 цвета) + 4 цвета «капель» света

# ---------- семантика (только когда нужна) ----------
OK = _P['OK']
WARN = _P['WARN']
ERR = _P['ERR']
SUCCESS, WARNING, DANGER = OK, WARN, ERR

# ---------- скругления ----------
R_CARD = 18
R_BUTTON = 12
R_INPUT = 12
R_TAG = 10          # компактный индикатор высотой 20 px
R_COVER = 14

# ---------- отступы (сетка 4 px) ----------
S1, S2, S3, S4, S5, S6 = 4, 8, 12, 16, 20, 24

# ---------- типографика ----------
FS_BODY = 13
FS_SMALL = 12
FS_APP_TITLE = 16
FS_GAME_TITLE = 20
FS_SECTION = 11

# ---------- размеры ----------
SIDEBAR_WIDTH = 236
COVER_MAX = 52
COVER_MIN = 44
BTN_H = 40
COMPACT_WIDTH = 900          # окно уже этого — компактный режим
ICON_BTN = 34

if getattr(sys, 'frozen', False):  # собранный PyInstaller-ом .exe: ресурсы лежат в _MEIPASS
    ASSETS_DIR = os.path.join(getattr(sys, '_MEIPASS', os.path.dirname(sys.executable)), 'assets')
else:
    ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'assets')


def asset_url(name: str) -> str:
    return os.path.join(ASSETS_DIR, name).replace('\\', '/')
