"""
Стили приложения: лёгкая светлая тема (или тёмная лесная — по настройке). Плоские поверхности,
тонкие кромки, один акцент для главного действия.
Все значения берутся из tokens.py.
"""
from app.ui import tokens as T

SOFT, SOFT_HOVER, SOFT_PRESSED = T.SOFT, T.SOFT_HOVER, T.SOFT_PRESSED   # фоны вторичных кнопок
# Явные реэкспорты для старого кода (раньше приходили через `import *`).
SUCCESS, WARNING, DANGER = T.SUCCESS, T.WARNING, T.DANGER

STYLE_SHEET = f"""
* {{ outline: none; }}
QWidget {{ background-color: {T.BG}; color: {T.TEXT}; font-size: {T.FS_BODY}px; }}
QMainWindow, QDialog {{ background-color: {T.BG}; }}
QLabel {{ background: transparent; color: {T.TEXT}; }}
/* Встроенные в главное окно диалоги — такие же скруглённые поверхности */
QDialog[embedded="true"] {{ border-radius: {T.R_CARD}px; border: 1px solid {T.BORDER}; }}
QLabel[muted="true"] {{ color: {T.TEXT_MUTED}; font-size: {T.FS_SMALL}px; }}
QLabel#sectionLabel {{ color: {T.TEXT_MUTED}; font-size: {T.FS_SECTION}px; font-weight: 600; }}

/* боковая панель: плоская, без границ */
QWidget#sidebar {{ background-color: {T.BG_SIDEBAR}; }}
QWidget#sidebar QLabel {{ background: transparent; }}
QFrame#sideSep {{ background: {T.BORDER}; border: none; }}

/* кнопки */
QPushButton {{
    background-color: {SOFT}; color: {T.TEXT}; border: 1px solid transparent;
    border-radius: {T.R_BUTTON}px; padding: 7px 14px; min-height: 18px;
}}
QPushButton:hover {{ background-color: {SOFT_HOVER}; }}
QPushButton:pressed {{ background-color: {SOFT_PRESSED}; }}
QPushButton:focus {{ border: 1px solid {T.FOCUS}; }}
QPushButton:disabled {{ color: {T.TEXT_MUTED}; background-color: {T.SOFT}; }}

QPushButton[cls="primary"], QPushButton[cls="success"] {{
    background-color: {T.SAGE}; color: {T.TEXT_ON_SAGE}; font-weight: 600;
}}
QPushButton[cls="primary"]:hover, QPushButton[cls="success"]:hover {{ background-color: {T.SAGE_HOVER}; }}
QPushButton[cls="primary"]:pressed, QPushButton[cls="success"]:pressed {{ background-color: {T.SAGE_PRESSED}; }}
QPushButton[cls="primary"]:focus, QPushButton[cls="success"]:focus {{ border: 2px solid {T.FOCUS}; }}
QPushButton[cls="primary"]:disabled, QPushButton[cls="success"]:disabled {{
    background-color: {SOFT}; color: {T.TEXT_MUTED};
}}
QPushButton[cls="danger"] {{ background-color: transparent; color: {T.ERR}; }}
QPushButton[cls="danger"]:hover {{ background-color: {T.DANGER_HOVER}; }}

QPushButton[cls="icon"], QPushButton[cls="square"] {{
    background-color: transparent; padding: 0; min-height: 0;
    min-width: 30px; max-width: 30px; max-height: 30px; border-radius: 8px;
}}
QPushButton[cls="icon"]:hover, QPushButton[cls="square"]:hover {{ background-color: {SOFT_HOVER}; }}
QPushButton[cls="icon"]:pressed, QPushButton[cls="square"]:pressed {{ background-color: {SOFT_PRESSED}; }}
QPushButton[cls="icon"]:disabled, QPushButton[cls="square"]:disabled {{ background: transparent; }}

QPushButton[cls="nav"] {{
    background-color: transparent; text-align: left; color: {T.TEXT_MUTED}; padding: 6px 8px;
}}
QPushButton[cls="nav"]:hover {{ background-color: {T.SOFT}; color: {T.TEXT}; }}

/* поля ввода */
QLineEdit, QComboBox, QSpinBox {{
    background-color: {T.BG_INPUT}; border: 1px solid {T.BORDER}; border-radius: {T.R_INPUT}px;
    padding: 6px 10px; color: {T.TEXT};
    selection-background-color: {T.ACCENT}; selection-color: {T.TEXT_ON_ACCENT};
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover {{ border-color: {T.BORDER_HOVER}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {T.FOCUS}; }}
QLineEdit:disabled, QComboBox:disabled {{ color: {T.TEXT_MUTED}; background-color: {T.BG}; }}
QSpinBox::up-button, QSpinBox::down-button {{ background: transparent; border: none; width: 20px; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {SOFT_HOVER}; border-radius: 4px; }}
QSpinBox::up-arrow {{ image: url({T.asset_url('chevron_up.svg')}); width: 10px; height: 10px; }}
QSpinBox::down-arrow {{ image: url({T.asset_url('chevron.svg')}); width: 10px; height: 10px; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url({T.asset_url('chevron.svg')}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background-color: {T.BG_INPUT}; border: 1px solid {T.BORDER};
    selection-background-color: {T.CARD}; selection-color: {T.TEXT}; color: {T.TEXT};
}}

/* список игр */
QListWidget {{ background-color: transparent; border: none; padding: 0; }}
QListWidget::item {{
    padding: 8px 10px; border-radius: 8px; margin: 1px 0; color: {T.TEXT_ON_CARD_MUTED};
    border: none; border-left: 2px solid transparent;
}}
QListWidget::item:hover:!selected {{ background-color: {T.HOVER_BG}; color: {T.TEXT}; }}
QListWidget::item:selected {{
    color: {T.TEXT}; background-color: {T.SELECTED_BG}; border-left: 2px solid {T.SELECT_BAR};
}}
QListWidget:focus {{ border: none; }}
QListWidget::item:focus:!selected {{ border-left: 2px solid {T.FOCUS}; }}
QDialog QListWidget {{
    background-color: {T.BG_PANEL}; border-radius: {T.R_INPUT}px; padding: 4px;
}}

/* карточки: плоская поверхность, без границ и градиентов */
QFrame#card, QGroupBox {{ background-color: {T.BG_PANEL}; border: 1px solid {T.CARD_EDGE}; border-radius: {T.R_CARD}px; }}
QFrame#card QLabel, QGroupBox QLabel {{ background: transparent; }}
QFrame#card QLabel[muted="true"], QGroupBox QLabel[muted="true"] {{ color: {T.TEXT_ON_CARD_MUTED}; }}
QGroupBox {{ margin-top: 14px; padding: 18px 14px 12px 14px; font-weight: 600; }}
QGroupBox::title {{
    subcontrol-origin: margin; left: 14px; top: 2px; padding: 0 6px;
    color: {T.TEXT_ON_CARD_MUTED}; background-color: transparent;
}}
QFrame[tag] {{ background: transparent; border: none; }}
QFrame[tag] QLabel {{ background: transparent; font-size: {T.FS_SMALL}px; }}

/* чекбоксы */
QCheckBox {{ background: transparent; spacing: 8px; color: {T.TEXT}; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 6px; border: 1px solid {T.BORDER_HOVER}; background-color: {T.BG_INPUT};
}}
QCheckBox::indicator:hover {{ border-color: {T.FOCUS}; }}
QCheckBox::indicator:checked {{
    background-color: {T.ACCENT}; border-color: {T.ACCENT}; image: url({T.asset_url('check.svg')});
}}
QCheckBox::indicator:focus {{ border: 1px solid {T.FOCUS}; }}

/* прочее */
QScrollArea {{ border: none; background-color: transparent; }}
QScrollArea > QWidget > QWidget {{ background-color: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {T.BORDER_HOVER}; border-radius: 4px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {T.TEXT_MUTED}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {T.BORDER_HOVER}; border-radius: 4px; min-width: 24px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QStatusBar {{ background-color: {T.BG}; color: {T.TEXT_MUTED}; font-size: {T.FS_SMALL}px; }}
QStatusBar::item {{ border: none; }}
QMenu {{ background-color: {T.BG_PANEL}; border: 1px solid {T.BORDER}; border-radius: {T.R_BUTTON}px; padding: 4px; }}
QMenu::separator {{ height: 1px; background: {T.BORDER}; margin: 4px 8px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background-color: {T.HOVER_BG}; }}
QMenu::item:disabled {{ color: {T.TEXT_MUTED}; }}
QProgressBar {{
    background-color: {T.BG_INPUT}; border: none; border-radius: 8px; text-align: center;
    color: {T.TEXT}; min-height: 16px;
}}
QProgressBar::chunk {{ background-color: {T.SAGE}; border-radius: 8px; }}
QToolTip {{ background-color: {T.BG_PANEL}; color: {T.TEXT}; border: 1px solid {T.BORDER}; padding: 4px 8px; }}

/* вкладки (окно настроек) и текстовое поле журнала */
QTabWidget::pane {{ border: 1px solid {T.BORDER}; border-radius: {T.R_INPUT}px; top: -1px; background-color: {T.BG}; }}
QTabBar::tab {{
    background: transparent; color: {T.TEXT_MUTED}; padding: 7px 14px; margin-right: 2px;
    border: none; border-bottom: 2px solid transparent;
}}
QTabBar::tab:hover {{ color: {T.TEXT}; }}
QTabBar::tab:selected {{ color: {T.TEXT}; font-weight: 600; border-bottom: 2px solid {T.SELECT_BAR}; }}
QPlainTextEdit {{
    background-color: {T.BG_INPUT}; border: 1px solid {T.BORDER}; border-radius: {T.R_INPUT}px;
    padding: 6px; color: {T.TEXT}; selection-background-color: {T.ACCENT}; selection-color: {T.TEXT_ON_ACCENT};
}}
"""


# ---------- «жидкое стекло»: правила идут последними и перекрывают плоские ----------
# Главное окно рисует живой фон само (ui/glass.py: BackdropWidget), поэтому почти все виджеты
# прозрачны. Диалоги получают статичный градиент из цветов фона. Меню и выпадающие списки —
# непрозрачные (всплывающие окна не могут честно просвечивать).
_B0, _B1, _B2, _B3, _B4, _B5 = T.BACKDROP

GLASS_STYLE_SHEET = f"""
QWidget {{ background-color: transparent; }}
QMainWindow {{ background-color: {_B0}; }}
QDialog {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {_B0}, stop:0.55 {_B1}, stop:1 {_B2});
}}
QDialog[embedded="true"] {{
    border-radius: {T.R_CARD}px; border: 1px solid {T.RIM_DIM};
}}
QWidget#sidebar {{ background-color: {T.GLASS_SIDEBAR}; border-right: 1px solid {T.RIM_DIM}; }}

/* кнопки: матовое стекло с тонкой светлой кромкой */
QPushButton {{ background-color: {T.SOFT}; border: 1px solid {T.RIM_DIM}; border-radius: {T.R_BUTTON}px; }}
QPushButton:hover {{ background-color: {T.SOFT_HOVER}; border: 1px solid {T.RIM_LIGHT}; }}
QPushButton:pressed {{ background-color: {T.SOFT_PRESSED}; }}
QPushButton:focus {{ border: 1px solid {T.FOCUS}; }}
QPushButton:disabled {{ background-color: {T.SOFT}; border: 1px solid transparent; }}
QPushButton[cls="primary"], QPushButton[cls="success"] {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {T.PRIMARY_TOP}, stop:1 {T.SAGE});
    border: 1px solid {T.RIM_LIGHT};
}}
QPushButton[cls="primary"]:hover, QPushButton[cls="success"]:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {T.PRIMARY_TOP}, stop:1 {T.SAGE_HOVER});
}}
QPushButton[cls="primary"]:pressed, QPushButton[cls="success"]:pressed {{ background-color: {T.SAGE_PRESSED}; }}
QPushButton[cls="primary"]:disabled, QPushButton[cls="success"]:disabled {{
    background: {T.SOFT}; border: 1px solid transparent;
}}
QPushButton[cls="danger"], QPushButton[cls="icon"], QPushButton[cls="square"], QPushButton[cls="nav"] {{
    background-color: transparent; border: 1px solid transparent;
}}
QPushButton[cls="danger"]:hover {{ background-color: {T.DANGER_HOVER}; border: 1px solid transparent; }}
QPushButton[cls="icon"]:hover, QPushButton[cls="square"]:hover, QPushButton[cls="nav"]:hover {{
    background-color: {T.SOFT_HOVER}; border: 1px solid {T.RIM_DIM};
}}

/* поля ввода: «вдавленное» стекло */
QLineEdit, QComboBox, QSpinBox {{ background-color: {T.GLASS_INPUT}; border: 1px solid {T.BORDER_HOVER}; }}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover {{ border-color: {T.RIM_LIGHT}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {T.FOCUS}; }}
QLineEdit:disabled, QComboBox:disabled {{ background-color: {T.SOFT}; }}
QComboBox QAbstractItemView {{ background-color: {T.POPUP}; border: 1px solid {T.RIM_DIM}; }}
QComboBox QAbstractItemView, QCompleter QAbstractItemView {{ background-color: {T.POPUP}; }}
QComboBoxPrivateContainer {{ background-color: {T.POPUP}; border: 1px solid {T.RIM_DIM}; }}

/* список игр */
QListWidget::item:hover:!selected {{ background-color: {T.HOVER_BG}; }}
QListWidget::item:selected {{ background-color: {T.SELECTED_BG}; border-left: 2px solid {T.SELECT_BAR}; }}
QDialog QListWidget {{ background-color: {T.GLASS_INPUT}; border: 1px solid {T.RIM_DIM}; }}

/* карточки: стекло с градиентом прозрачности (кромку и блик дорисовывает GlassFrame) */
QFrame#card, QGroupBox {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {T.GLASS_TOP}, stop:1 {T.GLASS_BOTTOM});
    border: 1px solid {T.RIM_DIM};
}}

QCheckBox::indicator {{ background-color: {T.GLASS_INPUT}; border: 1px solid {T.BORDER_HOVER}; }}
QCheckBox::indicator:checked {{ background-color: {T.ACCENT}; border-color: {T.RIM_LIGHT}; }}

QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{ background: {T.TEXT_MUTED}; }}
QStatusBar {{ background-color: {T.GLASS_SIDEBAR}; }}
QMenu {{ background-color: {T.POPUP}; border: 1px solid {T.RIM_DIM}; }}
QMenu::item:selected {{ background-color: {T.SELECTED_BG}; }}
QProgressBar {{ background-color: {T.GLASS_INPUT}; border: 1px solid {T.RIM_DIM}; }}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {T.PRIMARY_TOP}, stop:1 {T.SAGE});
}}
QToolTip {{ background-color: {T.POPUP}; border: 1px solid {T.RIM_DIM}; }}

QTabWidget::pane {{ background-color: {T.GLASS_INPUT}; border: 1px solid {T.RIM_DIM}; }}
QPlainTextEdit {{ background-color: {T.GLASS_INPUT}; border: 1px solid {T.RIM_DIM}; }}
"""

if T.IS_GLASS:
    STYLE_SHEET = STYLE_SHEET + GLASS_STYLE_SHEET
