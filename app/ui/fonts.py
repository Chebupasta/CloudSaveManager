"""
Шрифты: загрузка пользовательского шрифта заголовков (LPM PuffPuff / Shutters)
из assets/fonts и безопасные запасные варианты. Если файла нет или в нём нет
нужных символов (кириллица, цифры), текст рисуется системным шрифтом.
"""
import os

from PyQt5.QtGui import QFont, QFontDatabase, QFontMetrics

from app.ui.tokens import ASSETS_DIR

BODY_CANDIDATES = ['Segoe UI', 'Inter', 'Noto Sans', 'Ubuntu', 'Cantarell', 'DejaVu Sans', 'Arial']
MONO_CANDIDATES = ['Cascadia Mono', 'Consolas', 'DejaVu Sans Mono', 'Menlo', 'Courier New']
HEADING_KEYS = ('puffpuff', 'shutters')

_state = {'body': 'Sans Serif', 'mono': 'Monospace', 'heading': None}


def _px_to_pt(px: int) -> int:
    """Токены заданы в пикселях при 96 DPI; переводим в пункты для Qt."""
    return max(6, round(px * 72 / 96))


def _norm(name: str) -> str:
    return ''.join(ch for ch in name.lower() if ch.isalnum())


def _first_available(candidates, families):
    lower = {f.lower(): f for f in families}
    for c in candidates:
        if c.lower() in lower:
            return lower[c.lower()]
    return None


def setup(app) -> None:
    """Загружает шрифты и задаёт базовый шрифт приложения."""
    fonts_dir = os.path.join(ASSETS_DIR, 'fonts')
    if os.path.isdir(fonts_dir):
        for name in sorted(os.listdir(fonts_dir)):
            if name.lower().endswith(('.ttf', '.otf')):
                QFontDatabase.addApplicationFont(os.path.join(fonts_dir, name))
    families = QFontDatabase().families()
    _state['body'] = _first_available(BODY_CANDIDATES, families) or app.font().family()
    _state['mono'] = _first_available(MONO_CANDIDATES, families) or _state['body']
    for fam in families:
        if any(key in _norm(fam) for key in HEADING_KEYS):
            _state['heading'] = fam
            break
    base = QFont(_state['body'])
    # Размер в пунктах, а не в пикселях: при включённом HiDPI-масштабировании
    # Qt масштабирует point size, но НЕ pixel size — шрифт оставался бы мелким
    # относительно увеличенных кнопок и отступов.
    base.setPointSize(_px_to_pt(13))
    app.setFont(base)


def body_family() -> str:
    return _state['body']


def mono_font(px: int = 12) -> QFont:
    f = QFont(_state['mono'])
    f.setPointSize(_px_to_pt(px))
    return f


def _supports(family: str, text: str) -> bool:
    metrics = QFontMetrics(QFont(family))
    return all(ch.isspace() or metrics.inFontUcs4(ord(ch)) for ch in text)


def heading_font(text: str, px: int) -> QFont:
    """Шрифт заголовка. Декоративный — только если он умеет все символы текста
    (иначе кириллица/цифры превратились бы в «квадратики»)."""
    family = _state['heading']
    if family and _supports(family, text):
        font = QFont(family)
        font.setPointSize(_px_to_pt(px))
        return font
    font = QFont(_state['body'])
    font.setPointSize(_px_to_pt(px))
    font.setWeight(QFont.DemiBold)
    return font
